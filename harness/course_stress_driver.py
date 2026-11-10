"""Declared offline input/dependency stress study for the accepted workflow.

All provider surfaces are the existing in-memory SDK double. Candidate JSON
is replayed from retained trials; synthetic usage is not a provider measure.
The real offline collector, controller, checker and renderer execute in a copy.
"""

import copy
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest import mock



def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit("internal usage: source-copy evidence-directory")
    root, evidence = map(Path, argv)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    from harness import course_workflow as workflow
    assert workflow.ROOT.resolve() == root.resolve(), "workflow must load from the isolated source copy"
    from harness.model_budget import TokenLedger
    from test_budgeted_course_workflow import SDKDouble

    inputs = evidence / "inputs"
    cases = evidence / "cases"
    cases.mkdir()
    protocol = json.loads((evidence / "protocol.json").read_text())
    rows = []


    def read(name):
        return json.loads((inputs / name).read_text())


    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()


    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


    class TracedSDK(SDKDouble):
        def __init__(self, trace, output, **kwargs):
            super().__init__([output] * 3, **kwargs)
            self.trace = trace

        def count(self, **kwargs):
            self.trace.append({"stage": "synthetic_input_count", "number": self.count_calls + 1})
            return super().count(**kwargs)

        def create(self, **kwargs):
            self.trace.append({"stage": "synthetic_generation", "number": self.create_calls + 1})
            try:
                return super().create(**kwargs)
            except Exception as error:
                self.trace.append({"stage": "synthetic_generation_error", "type": type(error).__name__})
                raise

        def close(self):
            pass


    def new_ledger(directory, calls=3):
        directory.mkdir()
        return TokenLedger(ledger_path=directory / "ledger.json", run_token_limit=1000,
                           max_output_tokens=100, max_model_calls=calls)


    def sdk_counts(sdk):
        return {"simulated_count_dispatches": sdk.count_calls,
                "simulated_generation_dispatches": sdk.create_calls, "live_provider_requests": 0}


    real_subprocess_run = subprocess.run


    def observed_components(trace):
        def run(command, *args, **kwargs):
            if len(command) > 1 and Path(command[1]).suffix == ".py":
                component = str(Path(command[1]).relative_to(root))
                assert "OPENAI_API_KEY" not in kwargs.get("env", {}), "child received a credential variable"
                result = real_subprocess_run(command, *args, **kwargs)
                trace.append({"stage": "component", "component": component, "exit_code": result.returncode})
                return result
            return real_subprocess_run(command, *args, **kwargs)
        return run


    def record(case_id, trace, result, ledger, sdk, *, later=None, note=""):
        row = {"case_id": case_id, "result": asdict(result), "ledger": ledger.state,
               "trace": trace, "note": note, **sdk_counts(sdk), "expectations_met": True}
        if later is not None:
            row["later_case_result"] = asdict(later)
        save(evidence / "scenario-results" / (case_id + ".json"), row)
        rows.append(row)
        print(case_id + ": " + result.status + "; declared expectations met", flush=True)


    def component_seen(trace, filename):
        return any(event.get("component", "").endswith(filename) for event in trace)


    def direct(case_id, source, output, *, expected, legacy=False, calls=3, create_error=None,
               omit_usage=False, later_blocked=False, call_cap=False, note=""):
        trace = []
        directory = cases / case_id
        ledger = new_ledger(directory, calls)
        sdk = TracedSDK(trace, output, create_error=create_error, omit_usage=omit_usage)
        checker = root / "historical-control/check_courses.py" if legacy else root / "eval/check_courses.py"
        with mock.patch.object(workflow, "CHECKER", checker), \
                mock.patch.object(workflow.subprocess, "run", side_effect=observed_components(trace)):
            result = workflow.run_course_workflow(copy.deepcopy(source), ledger, sdk, directory / "first")
        assert result.status == expected, (case_id, result)
        if expected == "source_rejected":
            assert (sdk.count_calls, sdk.create_calls) == (0, 0)
            assert ledger.state["reservations"] == [] and not ledger.state["blocked"]
        elif expected == "accepted":
            assert (sdk.count_calls, sdk.create_calls) == (1, 1)
            assert component_seen(trace, "render_courses.py")
            assert Path(result.rendered_json_path).is_file() and Path(result.rendered_markdown_path).is_file()
        elif expected == "candidate_rejected":
            assert result.attempts == 3 and (sdk.count_calls, sdk.create_calls) == (3, 3)
            assert not component_seen(trace, "render_courses.py")
            feedback = (directory / "first/candidate-check-1.json").read_text()
            assert "role is ambiguous" in feedback and "application_deadline" in feedback and "start_date" in feedback
        elif expected == "provider_abort":
            assert (sdk.count_calls, sdk.create_calls) == (1, 1)
            assert ledger.state["blocked"]
            assert not component_seen(trace, "check_courses.py") and not component_seen(trace, "render_courses.py")
            assert ledger.state["reservations"] and ledger.state["reservations"][0]["status"] != "settled"
        later = None
        if later_blocked or call_cap:
            before = (sdk.count_calls, sdk.create_calls)
            later = workflow.run_course_workflow(read("source-base.json"), ledger, sdk, directory / "later")
            assert later.status != "accepted" and (sdk.count_calls, sdk.create_calls) == before
            if call_cap:
                assert later.status == "budget_exhausted" and ledger.state["model_calls"] == 1
            else:
                assert ledger.state["blocked"]
        record(case_id, trace, result, ledger, sdk, later=later, note=note)


    def normal_cli(case_id, output, *, fail=False):
        trace = []
        sdk = TracedSDK(trace, output, create_error=TimeoutError("simulated provider timeout") if fail else None)
        directory = cases / case_id
        directory.mkdir()
        published = (root / "out/training/courses.json", root / "out/training/comparison.md")
        prior = {str(p.relative_to(root)): digest(p) for p in published} if fail else {}
        out = io.StringIO()
        with mock.patch.object(workflow, "create_live_client", return_value=sdk), \
                mock.patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-offline-contract-only"}), \
                mock.patch.object(workflow.subprocess, "run", side_effect=observed_components(trace)), \
                redirect_stdout(out), redirect_stderr(out):
            code = workflow.main(["--offline", "--run-token-limit", "1000", "--max-output-tokens", "100",
                                  "--max-model-calls", "3"])
        (directory / "cli.log").write_text(out.getvalue())
        assert code == (7 if fail else 0), (case_id, code, out.getvalue())
        assert (sdk.count_calls, sdk.create_calls) == (1, 1)
        assert component_seen(trace, "course_sources.py"), "real offline collection did not execute"
        if fail:
            assert not component_seen(trace, "check_courses.py") and not component_seen(trace, "render_courses.py")
            assert prior == {str(p.relative_to(root)): digest(p) for p in published}
        else:
            assert all(p.is_file() for p in published)
            assert component_seen(trace, "check_courses.py") and component_seen(trace, "render_courses.py")
        run_line = next(line for line in out.getvalue().splitlines() if line.startswith("Run evidence: "))
        run_directory = root / run_line.split(": ", 1)[1]
        ledger = json.loads((run_directory / "ledger.json").read_text())
        if fail:
            assert ledger["blocked"]
        row = {"case_id": case_id, "cli_exit_code": code, "trace": trace,
               "ledger": ledger, "normal_run_directory": str(run_directory.relative_to(root)),
               "prior_publication_sha256": prior, "expectations_met": True, **sdk_counts(sdk)}
        save(evidence / "scenario-results" / (case_id + ".json"), row)
        rows.append(row)
        print(case_id + ": CLI exit " + str(code) + "; declared expectations met", flush=True)


    base = read("source-base.json")
    base_output = (inputs / "candidate-base.json").read_text()
    bad_output = (inputs / "candidate-conflict-bad.json").read_text()
    abstain_output = (inputs / "candidate-conflict-abstain.json").read_text()

    try:
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")), \
                mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network forbidden")), \
                mock.patch.object(workflow, "create_live_client", side_effect=AssertionError("live client forbidden")):
            normal_cli("N00-normal-cli", base_output)
            direct("I01-identical-rows", read("source-duplicate.json"), base_output, expected="accepted",
                   note="Harmless source perturbation absorbed; no distinct offering is inferred.")
            direct("I02-unapproved-url", read("source-unapproved.json"), base_output, expected="source_rejected",
                   note="The approved-source boundary absorbs the out-of-scope URL before counting or extraction.")
            direct("I03-conflict-historical-checker", read("source-conflict.json"), bad_output,
                   expected="accepted", legacy=True,
                   note="Negative historical control: Compulsory 2 checker accepts a source-present but unselected offering. Only the checker component is historical.")
            direct("I04-conflict-current-checker", read("source-conflict.json"), bad_output,
                   expected="candidate_rejected",
                   note="Same source and replayed candidate; current date-role guard blocks all three attempts before rendering. This measures enforcement, not model improvement.")
            direct("I05-conflict-abstention", read("source-conflict.json"), abstain_output, expected="accepted",
                   note="Positive control: retained baseline attempt 2 abstains on the conflicting dates. Trusted metadata assembly restores its source URL.")
            direct("D01-generation-timeout", base, base_output, expected="provider_abort",
                   create_error=TimeoutError("simulated provider timeout"), later_blocked=True,
                   note="Injected dependency failure is absorbed by reservation retention and permanent blocking of this invocation's ledger.")
            direct("D02-missing-usage", base, base_output, expected="provider_abort", omit_usage=True,
                   later_blocked=True,
                   note="A complete-looking body with missing usage cannot settle its reservation or authorize later dispatch.")
            normal_cli("D03-cli-timeout-publication", base_output, fail=True)
            direct("S01-call-cap", base, base_output, expected="accepted", calls=1, call_cap=True,
                   note="Safety control: one accepted response consumes the only call slot; a later case stops before counting.")
        expected_ids = [case["id"] for case in protocol["cases"]]
        assert [row["case_id"] for row in rows] == expected_ids
        before = cases / "I03-conflict-historical-checker/first"
        after = cases / "I04-conflict-current-checker/first"
        comparison = {}
        for name in ("source.json", "raw-response-1.txt", "candidate-1.json"):
            assert (before / name).read_bytes() == (after / name).read_bytes(), name
            comparison[name] = {"before_sha256": digest(before / name), "after_sha256": digest(after / name)}
        summary = {"status": "all_declared_controls_met", "case_count": len(rows),
                   "live_provider_requests": 0, "source_collection": "saved fixture only",
                   "provider_surface": "existing in-memory SDK double with synthetic usage",
                   "not_model_accuracy": True, "not_live_outage_measurement": True,
                   "not_general_injection_resistance": True,
                   "historical_current_identical_input_comparison": comparison, "rows": rows}
        save(evidence / "study-results.json", summary)
    except BaseException as error:
        save(evidence / "study-results.json", {"status": "study_incomplete", "case_count": len(rows),
             "live_provider_requests": 0, "failure_type": type(error).__name__, "rows": rows})
        raise


if __name__ == "__main__":
    main()
