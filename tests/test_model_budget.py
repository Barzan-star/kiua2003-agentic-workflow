"""Offline tests for durable token reservations (all limits are synthetic)."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.model_budget import (
    BudgetBlocked,
    BudgetExhausted,
    InvalidLimit,
    LedgerAlreadyExists,
    LedgerPersistenceError,
    ReservationError,
    TokenLedger,
    UsageValidationError,
)


TEST_RUN_LIMIT = 100
TEST_MAX_OUTPUT = 40
TEST_MAX_CALLS = 3


class TokenLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "run-evidence"
        self.directory.mkdir()
        self.path = self.directory / "token-ledger.json"

    def tearDown(self):
        self.temp.cleanup()

    def make_ledger(self, *, run_limit=TEST_RUN_LIMIT, output=TEST_MAX_OUTPUT,
                    calls=TEST_MAX_CALLS, path=None):
        return TokenLedger(
            ledger_path=self.path if path is None else path,
            run_token_limit=run_limit,
            max_output_tokens=output,
            max_model_calls=calls,
        )

    def reserve_and_dispatch(self, ledger, input_tokens=20):
        handle = ledger.reserve(input_tokens)
        ledger.dispatch(handle)
        return handle

    def test_limits_require_positive_exact_integers(self):
        for field in ("run_token_limit", "max_output_tokens", "max_model_calls"):
            for value in (None, True, False, "10", 0, -1, 1.5):
                kwargs = {
                    "ledger_path": self.path,
                    "run_token_limit": TEST_RUN_LIMIT,
                    "max_output_tokens": TEST_MAX_OUTPUT,
                    "max_model_calls": TEST_MAX_CALLS,
                }
                kwargs[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(InvalidLimit):
                        TokenLedger(**kwargs)

    def test_run_limits_cannot_be_reassigned_after_creation(self):
        ledger = self.make_ledger()
        for field in ("run_token_limit", "max_output_tokens", "max_model_calls"):
            with self.subTest(field=field), self.assertRaises(AttributeError):
                setattr(ledger, field, 10_000)
        self.assertEqual(ledger.state["run_token_limit"], TEST_RUN_LIMIT)
        self.assertEqual(ledger.max_output_tokens, TEST_MAX_OUTPUT)

    def test_reservation_records_its_own_output_ceiling(self):
        ledger = self.make_ledger()
        handle = self.reserve_and_dispatch(ledger)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["reservations"][0]["max_output_tokens"], TEST_MAX_OUTPUT)
        with self.assertRaises(UsageValidationError):
            ledger.settle(handle, input_tokens=20, output_tokens=41, total_tokens=61)
        self.assertEqual(ledger.pending_tokens, 60)

    def test_interrupted_persistence_blocks_before_and_after_dispatch(self):
        for after_dispatch in (False, True):
            ledger = self.make_ledger(path=self.directory / f"interrupt-{after_dispatch}.json")
            handle = self.reserve_and_dispatch(ledger) if after_dispatch else None
            with self.subTest(after_dispatch=after_dispatch):
                with patch.object(ledger, "_persist_state", side_effect=KeyboardInterrupt()):
                    with self.assertRaises(KeyboardInterrupt):
                        if after_dispatch:
                            ledger.settle(handle, input_tokens=20, output_tokens=1, total_tokens=21)
                        else:
                            ledger.reserve(20)
                self.assertTrue(ledger.state["blocked"])
                self.assertEqual(ledger.pending_tokens, 60 if after_dispatch else 0)
                with self.assertRaises(BudgetBlocked):
                    ledger.assert_can_count()

    def test_persistence_exception_text_is_not_exposed(self):
        ledger = self.make_ledger()
        with patch.object(ledger, "_persist_state", side_effect=LedgerPersistenceError("SYNTHETIC-SECRET")):
            with self.assertRaises(LedgerPersistenceError) as caught:
                ledger.reserve(20)
        self.assertNotIn("SYNTHETIC-SECRET", str(caught.exception))

    def test_ledger_requires_caller_supplied_existing_directory(self):
        with self.assertRaises(TypeError):
            TokenLedger(ledger_path=self.path, run_token_limit=1, max_output_tokens=1)
        with self.assertRaises(LedgerPersistenceError):
            self.make_ledger(path=self.directory / "missing" / "ledger.json")

    def test_exact_boundary_is_admitted_and_over_boundary_refused(self):
        ledger = self.make_ledger(run_limit=60, output=40)
        handle = ledger.reserve(20)
        self.assertEqual(ledger.pending_tokens, 60)
        ledger.dispatch(handle)
        self.assertEqual(ledger.settle(
            handle, input_tokens=20, output_tokens=40, total_tokens=60,
        ), 60)
        self.assertEqual(ledger.state["confirmed_tokens"], 60)
        self.assertEqual(ledger.remaining_tokens, 0)
        with self.assertRaises(BudgetExhausted):
            ledger.assert_can_count()

        other = self.make_ledger(run_limit=60, output=40, path=self.directory / "other.json")
        with self.assertRaises(BudgetExhausted):
            other.reserve(21)
        self.assertEqual(other.state["model_calls"], 0)

    def test_reservation_is_durable_before_dispatch_and_old_ledger_is_never_reset(self):
        ledger = self.make_ledger()
        handle = ledger.reserve(21)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["reservations"][0]["handle"], handle)
        self.assertEqual(saved["reservations"][0]["status"], "reserved")
        self.assertEqual(saved["model_calls"], 0)
        before = self.path.read_bytes()
        with self.assertRaises(LedgerAlreadyExists):
            self.make_ledger()
        self.assertEqual(self.path.read_bytes(), before)

    def test_settlement_releases_unused_reservation_for_another_attempt(self):
        ledger = self.make_ledger(run_limit=100, output=40, calls=2)
        first = self.reserve_and_dispatch(ledger, 20)
        ledger.settle(first, input_tokens=20, output_tokens=10, total_tokens=30)
        self.assertEqual(ledger.state["confirmed_tokens"], 30)
        self.assertEqual(ledger.pending_tokens, 0)

        # Retry attempts use the same in-memory ledger and remaining allowance.
        second = self.reserve_and_dispatch(ledger, 20)
        self.assertNotEqual(first, second)
        ledger.settle(second, input_tokens=20, output_tokens=15, total_tokens=35)
        self.assertEqual(ledger.state["model_calls"], 2)
        self.assertEqual(ledger.state["confirmed_tokens"], 65)
        self.assertEqual(ledger.remaining_model_calls, 0)
        with self.assertRaises(BudgetExhausted):
            ledger.assert_can_count()
        with self.assertRaises(LedgerAlreadyExists):
            self.make_ledger()

    def test_uncertain_dispatch_retains_reservation_and_permanently_blocks(self):
        ledger = self.make_ledger()
        handle = self.reserve_and_dispatch(ledger, 20)
        ledger.mark_uncertain(handle)
        self.assertTrue(ledger.state["blocked"])
        self.assertEqual(ledger.state["reservations"][0]["status"], "uncertain")
        self.assertEqual(ledger.pending_tokens, 60)
        self.assertEqual(ledger.state["model_calls"], 1)
        with self.assertRaises(BudgetBlocked):
            ledger.assert_can_count()
        with self.assertRaises(BudgetBlocked):
            ledger.reserve(1)
        with self.assertRaises(LedgerAlreadyExists):
            self.make_ledger()

    def test_call_limit_counts_dispatches_not_reservations(self):
        ledger = self.make_ledger(run_limit=200, output=20, calls=1)
        handle = ledger.reserve(10)
        self.assertEqual(ledger.state["model_calls"], 0)
        ledger.dispatch(handle)
        self.assertEqual(ledger.state["model_calls"], 1)
        ledger.settle(handle, input_tokens=10, output_tokens=1, total_tokens=11)
        with self.assertRaises(BudgetExhausted):
            ledger.assert_can_count()

    def test_duplicate_settlement_is_rejected(self):
        ledger = self.make_ledger()
        handle = self.reserve_and_dispatch(ledger)
        ledger.settle(handle, input_tokens=20, output_tokens=1, total_tokens=21)
        with self.assertRaises(ReservationError):
            ledger.settle(handle, input_tokens=20, output_tokens=1, total_tokens=21)
        self.assertEqual(ledger.state["confirmed_tokens"], 21)

    def test_cached_input_and_reasoning_are_details_not_extra_charges(self):
        ledger = self.make_ledger()
        handle = self.reserve_and_dispatch(ledger, 30)
        ledger.settle(
            handle, input_tokens=30, output_tokens=12, total_tokens=42,
            cached_input_tokens=18, reasoning_tokens=7,
        )
        item = ledger.state["reservations"][0]
        self.assertEqual(item["actual_tokens"], 42)
        self.assertEqual(item["cached_input_tokens"], 18)
        self.assertEqual(item["reasoning_tokens"], 7)
        self.assertEqual(ledger.state["confirmed_tokens"], 42)

    def test_malformed_usage_blocks_and_retains_the_full_reservation(self):
        invalid_usages = (
            {"input_tokens": True, "output_tokens": 1, "total_tokens": 21},
            {"input_tokens": 20, "output_tokens": "1", "total_tokens": 21},
            {"input_tokens": 20, "output_tokens": 1, "total_tokens": None},
            {"input_tokens": 20, "output_tokens": -1, "total_tokens": 19},
            {"input_tokens": 20, "output_tokens": 1, "total_tokens": 22},
            {"input_tokens": 20, "output_tokens": 1, "total_tokens": 21, "cached_input_tokens": 21},
            {"input_tokens": 20, "output_tokens": 1, "total_tokens": 21, "reasoning_tokens": 2},
        )
        for index, usage in enumerate(invalid_usages):
            path = self.directory / f"invalid-{index}.json"
            ledger = self.make_ledger(path=path)
            handle = self.reserve_and_dispatch(ledger)
            with self.subTest(usage=usage):
                with self.assertRaises(UsageValidationError):
                    ledger.settle(
                        handle,
                        input_tokens=usage["input_tokens"],
                        output_tokens=usage["output_tokens"],
                        total_tokens=usage["total_tokens"],
                        cached_input_tokens=usage.get("cached_input_tokens", 0),
                        reasoning_tokens=usage.get("reasoning_tokens", 0),
                    )
                self.assertTrue(ledger.state["blocked"])
                self.assertEqual(ledger.pending_tokens, 60)
                self.assertEqual(ledger.state["confirmed_tokens"], 0)

    def test_input_mismatch_and_output_over_cap_are_recorded_as_contradictions(self):
        cases = (
            {"input_tokens": 19, "output_tokens": 2, "total_tokens": 21},
            {"input_tokens": 20, "output_tokens": 41, "total_tokens": 61},
        )
        for index, usage in enumerate(cases):
            ledger = self.make_ledger(path=self.directory / f"contradiction-{index}.json")
            handle = self.reserve_and_dispatch(ledger)
            with self.subTest(usage=usage), self.assertRaises(UsageValidationError):
                ledger.settle(handle, **usage)
            item = ledger.state["reservations"][0]
            self.assertEqual(item["status"], "contradiction")
            self.assertEqual(item["failure_code"], "usage_bound_contradiction")
            self.assertTrue(ledger.state["blocked"])
            self.assertEqual(ledger.pending_tokens, 60)

    def test_persistence_failure_before_dispatch_stops_and_blocks_memory_ledger(self):
        ledger = self.make_ledger()
        with patch.object(ledger, "_persist_state", side_effect=LedgerPersistenceError("SYNTHETIC-SECRET")):
            with self.assertRaises(LedgerPersistenceError):
                ledger.reserve(20)
        self.assertTrue(ledger.state["blocked"])
        self.assertEqual(ledger.state["model_calls"], 0)
        self.assertEqual(ledger.state["reservations"], [])

    def test_persistence_failure_after_generation_keeps_existing_reservation(self):
        ledger = self.make_ledger()
        handle = self.reserve_and_dispatch(ledger)
        with patch.object(ledger, "_persist_state", side_effect=LedgerPersistenceError("SYNTHETIC-SECRET")):
            with self.assertRaises(LedgerPersistenceError):
                ledger.settle(handle, input_tokens=20, output_tokens=1, total_tokens=21)
        self.assertTrue(ledger.state["blocked"])
        self.assertEqual(ledger.state["reservations"][0]["status"], "dispatched")
        self.assertEqual(ledger.pending_tokens, 60)

    def test_audit_metadata_is_allowlisted_and_secret_markers_are_dropped(self):
        ledger = self.make_ledger()
        handle = ledger.reserve(20, audit={
            "requested_model": "gpt-6-luna",
            "count_input_sha256": "a" * 64,
            "unknown": "SYNTHETIC-SECRET",
        })
        self.assertEqual(set(ledger.state["reservations"][0]["audit"]), {
            "requested_model", "count_input_sha256",
        })
        self.assertNotIn("SYNTHETIC-SECRET", self.path.read_text(encoding="utf-8"))
        self.assertEqual(ledger.state["reservations"][0]["handle"], handle)

    def test_credential_shaped_values_are_not_audit_identifiers(self):
        ledger = self.make_ledger()
        marker = "sk-SYNTHETIC-SECRET"
        ledger.reserve(20, audit={key: marker for key in (
            "count_request_id", "request_id", "response_id", "requested_model", "returned_model")})
        self.assertNotIn(marker, self.path.read_text(encoding="utf-8"))
        self.assertEqual(ledger.state["reservations"][0]["audit"], {})


if __name__ == "__main__":
    unittest.main()
