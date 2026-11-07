"""Offline SDK contract tests using OpenAI's real methods and HTTPX2 transport.

Every request is handled in memory by ``MockTransport``. The synthetic key
and ``.invalid`` API origin are test-only values; this module never reads a
runtime credential or sends a network request.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import tempfile
import unittest

try:
    import httpx2
    from openai import OpenAI
    from openai.resources.responses import Responses
    from openai.resources.responses.input_tokens import InputTokens
    from openai.types.responses import InputTokenCountResponse, Response
except ImportError as error:  # fail test discovery with an actionable message
    raise RuntimeError(
        "test_openai_course_sdk requires openai==3.46.0 and its HTTPX2 dependencies"
    ) from error


EXPECTED_SDK_VERSION = "3.46.0"
try:
    ACTUAL_SDK_VERSION = importlib.metadata.version("openai")
except importlib.metadata.PackageNotFoundError as error:
    raise RuntimeError("test_openai_course_sdk requires openai==3.46.0") from error
if ACTUAL_SDK_VERSION != EXPECTED_SDK_VERSION:
    raise RuntimeError(
        "test_openai_course_sdk requires openai==3.46.0; "
        f"found {ACTUAL_SDK_VERSION}"
    )


def _require_parameters(callable_object, expected, label):
    import inspect

    actual = set(inspect.signature(callable_object).parameters)
    missing = sorted(set(expected) - actual)
    if missing:
        raise RuntimeError(
            f"test_openai_course_sdk found an incompatible {label}; "
            f"missing parameters: {', '.join(missing)}"
        )


_require_parameters(
    OpenAI,
    ("api_key", "base_url", "timeout", "max_retries", "http_client"),
    "OpenAI constructor",
)
_require_parameters(
    InputTokens.count,
    ("input", "instructions", "model", "reasoning", "text"),
    "Responses input-token count method",
)
_require_parameters(
    Responses.create,
    (
        "input", "instructions", "model", "reasoning", "text",
        "max_output_tokens", "service_tier", "store", "stream", "background",
    ),
    "Responses create method",
)
if not callable(getattr(httpx2, "MockTransport", None)):
    raise RuntimeError("test_openai_course_sdk requires HTTPX2 MockTransport")
if not hasattr(Response, "model_validate") or not hasattr(InputTokenCountResponse, "model_validate"):
    raise RuntimeError("test_openai_course_sdk requires SDK response parsing models")


from harness import course_sources
from harness.model_budget import BudgetBlocked, BudgetExhausted, TokenLedger
from harness.openai_course_client import (
    MODEL,
    CourseClientError,
    CourseProtocolError,
    OpenAICourseClient,
)


TEST_API_KEY = "sk-test-offline-contract-only"
TEST_API_ORIGIN = "https://responses-contract.invalid/v1"
COUNT_PATH = "/v1/responses/input_tokens"
CREATE_PATH = "/v1/responses"
TEST_OUTPUT_CAP = 80
TEST_COUNTED_INPUT = 50
TEST_USAGE = {
    "input_tokens": 50,
    "input_tokens_details": {"cached_tokens": 9, "cache_write_tokens": 0},
    "output_tokens": 12,
    "output_tokens_details": {"reasoning_tokens": 4},
    "total_tokens": 62,
}
_MISSING = object()


def response_body(*, usage=_MISSING, status="completed", model=MODEL, output=_MISSING):
    """Return a synthetic Responses API body accepted by the pinned SDK."""
    if output is _MISSING:
        output = [
            {
                "id": "msg_test_123",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"schema_version":1,"courses":[]}',
                        "annotations": [],
                    }
                ],
            }
        ]
    body = {
        "id": "resp_test_123",
        "created_at": 1_794_000_000,
        "model": model,
        "object": "response",
        "output": output,
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "status": status,
    }
    if usage is not _MISSING:
        body["usage"] = usage
    if status == "incomplete":
        body["incomplete_details"] = {"reason": "max_output_tokens"}
    return body


class InMemoryResponsesTransport:
    """HTTPX2 handler that stores sanitized paths and synthetic JSON bodies."""

    def __init__(
        self,
        *,
        count_tokens=TEST_COUNTED_INPUT,
        count_status=200,
        create_status=200,
        generated_response=None,
        create_timeout=False,
        on_create=None,
        count_content=None,
        create_content=None,
    ):
        self.count_tokens = count_tokens
        self.count_status = count_status
        self.create_status = create_status
        self.generated_response = generated_response or response_body(usage=TEST_USAGE)
        self.create_timeout = create_timeout
        self.on_create = on_create
        self.count_content = count_content
        self.create_content = create_content
        self.paths = []
        self.origins = []
        self.request_bodies = {COUNT_PATH: [], CREATE_PATH: []}

    def __call__(self, request):
        # Deliberately do not read, store, or print request headers. In
        # particular, Authorization is never retained in test evidence.
        path = request.url.path
        self.paths.append((request.method, path))
        self.origins.append((request.url.scheme, request.url.host))
        try:
            body = json.loads(request.content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            body = None
        if path in self.request_bodies:
            self.request_bodies[path].append(copy.deepcopy(body))

        if path == COUNT_PATH:
            if self.count_status != 200:
                return self._error_response(request, self.count_status)
            if self.count_content is not None:
                return httpx2.Response(200, content=self.count_content,
                    headers={"content-type": "application/json"}, request=request)
            return httpx2.Response(
                200,
                headers={"x-request-id": "req_sdk_count"},
                json={
                    "input_tokens": self.count_tokens,
                    "object": "response.input_tokens",
                },
                request=request,
            )

        if path == CREATE_PATH:
            if self.on_create is not None:
                self.on_create()
            if self.create_timeout:
                raise httpx2.ReadTimeout("synthetic in-memory timeout", request=request)
            if self.create_status != 200:
                return self._error_response(request, self.create_status)
            if self.create_content is not None:
                return httpx2.Response(200, content=self.create_content,
                    headers={"content-type": "application/json"}, request=request)
            return httpx2.Response(200, json=self.generated_response,
                                  headers={"x-request-id": "req_sdk_create"}, request=request)

        return self._error_response(request, 404)

    @staticmethod
    def _error_response(request, status):
        return httpx2.Response(
            status,
            json={
                "error": {
                    "message": "synthetic offline contract failure",
                    "type": "server_error",
                    "code": None,
                }
            },
            request=request,
        )


class OpenAISDKContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.evidence = Path(self.temp.name)
        self.source = json.loads(course_sources.FIXTURE.read_text(encoding="utf-8"))
        self._ledger_number = 0

    def new_ledger(self, *, run_limit=300, output=TEST_OUTPUT_CAP, calls=3):
        self._ledger_number += 1
        evidence = self.evidence / f"ledger-{self._ledger_number}"
        evidence.mkdir()
        return TokenLedger(
            ledger_path=evidence / "token-ledger.json",
            run_token_limit=run_limit,
            max_output_tokens=output,
            max_model_calls=calls,
        )

    def attach(self, transport, *, ledger=None):
        ledger = self.new_ledger() if ledger is None else ledger
        http_client = httpx2.Client(
            transport=httpx2.MockTransport(transport),
            trust_env=False,
        )
        sdk_client = OpenAI(
            api_key=TEST_API_KEY,
            base_url=TEST_API_ORIGIN,
            timeout=0.25,
            max_retries=0,
            http_client=http_client,
        )
        self.addCleanup(sdk_client.close)
        return OpenAICourseClient(client=sdk_client, ledger=ledger), ledger, sdk_client

    def assert_test_origin_only(self, transport):
        self.assertTrue(transport.origins)
        self.assertEqual(
            transport.origins,
            [("https", "responses-contract.invalid")] * len(transport.origins),
        )

    def test_pinned_sdk_and_native_transport_are_the_inspected_interfaces(self):
        self.assertEqual(ACTUAL_SDK_VERSION, EXPECTED_SDK_VERSION)
        self.assertTrue(callable(httpx2.MockTransport))
        self.assertTrue(callable(InputTokens.count))
        self.assertTrue(callable(Responses.create))

    def test_real_count_and_create_serialize_the_same_full_input_contract(self):
        transport = InMemoryResponsesTransport()
        adapter, ledger, sdk_client = self.attach(transport)

        result = adapter.generate(self.source)

        self.assertEqual(sdk_client.max_retries, 0)
        self.assertEqual(transport.paths, [("POST", COUNT_PATH), ("POST", CREATE_PATH)])
        self.assert_test_origin_only(transport)
        counted = transport.request_bodies[COUNT_PATH][0]
        created = transport.request_bodies[CREATE_PATH][0]
        shared_fields = {"input", "instructions", "model", "reasoning", "text"}
        self.assertEqual(set(counted), shared_fields)
        self.assertEqual({key: counted[key] for key in shared_fields},
                         {key: created[key] for key in shared_fields})
        self.assertEqual(counted["model"], MODEL)
        self.assertEqual(counted["reasoning"], {"effort": "low"})
        self.assertEqual(counted["text"]["format"]["type"], "json_schema")
        self.assertIn("schema", counted["text"]["format"])
        self.assertTrue(counted["instructions"])
        self.assertEqual(created["max_output_tokens"], TEST_OUTPUT_CAP)
        self.assertEqual(created["service_tier"], "default")
        self.assertIs(created["store"], False)
        self.assertIs(created["stream"], False)
        self.assertIs(created["background"], False)
        self.assertNotIn("tools", created)
        self.assertEqual(result.payload_sha256, ledger.state["reservations"][0]["audit"]["count_input_sha256"])
        serialized_shared = {key: counted[key] for key in shared_fields}
        wire_input_hash = hashlib.sha256(json.dumps(serialized_shared, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(wire_input_hash, result.payload_sha256)
        self.assertEqual(result.count_request_id, "req_sdk_count")
        self.assertEqual(result.request_id, "req_sdk_create")

    def test_reservation_is_durable_and_dispatched_before_create_transport(self):
        ledger = self.new_ledger()
        snapshots = []

        def inspect_durable_ledger():
            snapshots.append(json.loads(ledger.path.read_text(encoding="utf-8")))

        transport = InMemoryResponsesTransport(on_create=inspect_durable_ledger)
        adapter, same_ledger, _ = self.attach(transport, ledger=ledger)
        adapter.generate(self.source)

        self.assertIs(same_ledger, ledger)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["model_calls"], 1)
        self.assertEqual(snapshots[0]["reservations"][0]["status"], "dispatched")
        self.assertEqual(snapshots[0]["reservations"][0]["reserved_tokens"], 130)
        self.assertEqual(snapshots[0]["reservations"][0]["actual_tokens"], None)

    def test_real_usage_parsing_charges_cached_and_reasoning_details_once(self):
        transport = InMemoryResponsesTransport()
        adapter, ledger, _ = self.attach(transport)

        generated = adapter.generate(self.source)

        reservation = ledger.state["reservations"][0]
        self.assertTrue(generated.text.startswith("{"))
        self.assertEqual(ledger.state["confirmed_tokens"], 62)
        self.assertEqual(reservation["actual_tokens"], 62)
        self.assertEqual(reservation["cached_input_tokens"], 9)
        self.assertEqual(reservation["reasoning_tokens"], 4)
        self.assertEqual(ledger.pending_tokens, 0)
        self.assertEqual(reservation["status"], "settled")

    def test_one_ledger_is_reused_and_refuses_an_unaffordable_next_generation(self):
        transport = InMemoryResponsesTransport()
        ledger = self.new_ledger(run_limit=190)
        adapter, same_ledger, _ = self.attach(transport, ledger=ledger)

        adapter.generate(self.source)
        with self.assertRaises(BudgetExhausted):
            adapter.generate(self.source)

        self.assertIs(same_ledger, ledger)
        self.assertEqual(transport.paths, [("POST", COUNT_PATH), ("POST", CREATE_PATH),
                                           ("POST", COUNT_PATH)])
        self.assertEqual(ledger.state["confirmed_tokens"], 62)
        self.assertEqual(ledger.state["model_calls"], 1)
        self.assertEqual(len(ledger.state["reservations"]), 1)

    def test_http_failures_have_exact_request_counts_with_sdk_retries_disabled(self):
        count_transport = InMemoryResponsesTransport(count_status=500)
        count_adapter, count_ledger, count_sdk = self.attach(count_transport)
        with self.assertRaises(CourseClientError):
            count_adapter.generate(self.source)
        self.assertEqual(count_sdk.max_retries, 0)
        self.assertEqual(count_transport.paths, [("POST", COUNT_PATH)])
        self.assertEqual(count_ledger.state["model_calls"], 0)
        self.assertEqual(count_ledger.state["reservations"], [])

        create_transport = InMemoryResponsesTransport(create_status=500)
        create_adapter, create_ledger, create_sdk = self.attach(create_transport)
        with self.assertRaises(CourseClientError):
            create_adapter.generate(self.source)
        self.assertEqual(create_sdk.max_retries, 0)
        self.assertEqual(create_transport.paths, [("POST", COUNT_PATH), ("POST", CREATE_PATH)])
        self.assertEqual(create_ledger.state["model_calls"], 1)
        self.assertTrue(create_ledger.state["blocked"])
        self.assertEqual(create_ledger.pending_tokens, 130)

    def test_real_httpx_timeout_retains_reservation_and_blocks_later_calls(self):
        transport = InMemoryResponsesTransport(create_timeout=True)
        adapter, ledger, _ = self.attach(transport)

        with self.assertRaises(CourseClientError):
            adapter.generate(self.source)
        with self.assertRaises(BudgetBlocked):
            adapter.generate(self.source)

        self.assertEqual(transport.paths, [("POST", COUNT_PATH), ("POST", CREATE_PATH)])
        self.assertTrue(ledger.state["blocked"])
        self.assertEqual(ledger.state["reservations"][0]["status"], "uncertain")
        self.assertEqual(ledger.pending_tokens, 130)

    def test_malformed_and_contradictory_real_sdk_usage_is_rejected(self):
        cases = [
            ("missing usage", TEST_COUNTED_INPUT, _MISSING),
            ("input mismatch", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "input_tokens": 49, "total_tokens": 61}),
            ("total mismatch", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "total_tokens": 63}),
            ("output above cap", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "output_tokens": 81, "total_tokens": 131}),
            # These exact raw JSON values must be rejected before accounting.
            # The SDK's Pydantic response parser may coerce them; if so, these
            # assertions intentionally preserve a failing regression.
            ("boolean input", 1,
             {**TEST_USAGE, "input_tokens": True, "input_tokens_details": {
                 "cached_tokens": 0, "cache_write_tokens": 0,
             }, "output_tokens": 12, "total_tokens": 13}),
            ("string input", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "input_tokens": "50"}),
            ("float input", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "input_tokens": 50.0}),
            ("boolean output", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "output_tokens": True, "total_tokens": 51,
              "output_tokens_details": {"reasoning_tokens": 0}}),
            ("string output", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "output_tokens": "12"}),
            ("string total", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "total_tokens": "62"}),
            ("boolean cached input", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "input_tokens_details": {"cached_tokens": True}}),
            ("string reasoning", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "output_tokens_details": {"reasoning_tokens": "4"}}),
            ("malformed usage detail", TEST_COUNTED_INPUT,
             {**TEST_USAGE, "input_tokens_details": "not an object"}),
        ]
        for index, (label, count_tokens, usage) in enumerate(cases):
            with self.subTest(usage_case=label):
                transport = InMemoryResponsesTransport(
                    count_tokens=count_tokens,
                    generated_response=(response_body() if usage is _MISSING
                                        else response_body(usage=usage)),
                )
                ledger = self.new_ledger()
                adapter, _, _ = self.attach(transport, ledger=ledger)
                try:
                    adapter.generate(self.source)
                except CourseClientError:
                    pass
                else:
                    self.assertEqual(ledger.state["reservations"][0]["status"], "settled")
                    self.fail(f"adapter accepted malformed {label} usage after settling it")
                self.assertTrue(ledger.state["blocked"])
                self.assertEqual(ledger.pending_tokens, TEST_COUNTED_INPUT + TEST_OUTPUT_CAP
                                 if count_tokens == TEST_COUNTED_INPUT else 1 + TEST_OUTPUT_CAP)

    def test_raw_count_types_stop_before_any_generation_request(self):
        for value in (True, "50", 50.0):
            with self.subTest(count=value):
                transport = InMemoryResponsesTransport(count_tokens=value)
                adapter, ledger, _ = self.attach(transport)
                with self.assertRaises(CourseClientError):
                    adapter.generate(self.source)
                self.assertEqual(transport.paths, [("POST", COUNT_PATH)])
                self.assertTrue(ledger.state["blocked"])
                self.assertEqual(ledger.state["model_calls"], 0)
                self.assertEqual(ledger.pending_tokens, 0)

    def test_raw_count_json_shapes_and_duplicates_are_rejected(self):
        bodies = (b"not JSON", b"[]", b'{"object":"response","input_tokens":50}',
                  b'{"object":"response.input_tokens","input_tokens":50,"input_tokens":50}')
        for body in bodies:
            with self.subTest(body=body):
                transport = InMemoryResponsesTransport(count_content=body)
                adapter, ledger, _ = self.attach(transport)
                with self.assertRaises(CourseClientError):
                    adapter.generate(self.source)
                self.assertEqual(transport.paths, [("POST", COUNT_PATH)])
                self.assertTrue(ledger.state["blocked"])
                self.assertEqual(ledger.pending_tokens, 0)

    def test_raw_generation_json_errors_retain_reservation_and_block(self):
        bodies = (b"not JSON", b"[]", b'{"object":"response.input_tokens"}',
                  b'{"object":"response","object":"response"}')
        for body in bodies:
            with self.subTest(body=body):
                transport = InMemoryResponsesTransport(create_content=body)
                adapter, ledger, _ = self.attach(transport)
                with self.assertRaises(CourseClientError):
                    adapter.generate(self.source)
                with self.assertRaises(BudgetBlocked):
                    adapter.generate(self.source)
                self.assertEqual(transport.paths, [("POST", COUNT_PATH), ("POST", CREATE_PATH)])
                self.assertEqual(ledger.pending_tokens, 130)
                self.assertEqual(ledger.state["confirmed_tokens"], 0)

    def test_incomplete_model_mismatch_tool_and_refusal_outputs_are_rejected(self):
        function_call = [{
            "id": "fc_test_123",
            "type": "function_call",
            "status": "completed",
            "call_id": "call_test_123",
            "name": "synthetic_tool",
            "arguments": "{}",
        }]
        refusal = [{
            "id": "msg_test_123",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "refusal", "refusal": "synthetic refusal fixture"}],
        }]
        cases = (
            ("incomplete", response_body(usage=TEST_USAGE, status="incomplete"), CourseProtocolError),
            ("unexpected model", response_body(usage=TEST_USAGE, model="gpt-6-luna-unexpected"), CourseProtocolError),
            ("tool call", response_body(usage=TEST_USAGE, output=function_call), CourseProtocolError),
            ("refusal", response_body(usage=TEST_USAGE, output=refusal), CourseProtocolError),
        )
        for label, body, error_type in cases:
            with self.subTest(output_case=label):
                transport = InMemoryResponsesTransport(generated_response=body)
                ledger = self.new_ledger()
                adapter, _, _ = self.attach(transport, ledger=ledger)
                with self.assertRaises(error_type):
                    adapter.generate(self.source)
                self.assertTrue(ledger.state["blocked"])
                self.assertEqual(ledger.pending_tokens, 130 if label == "incomplete" else 0)


if __name__ == "__main__":
    unittest.main()
