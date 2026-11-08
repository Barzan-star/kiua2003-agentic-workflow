"""Budgeted, serial course extraction shared by normal and evaluation callers.

The caller owns the ledger, SDK client, source acquisition, and publication
policy. This module only creates case evidence, checks candidates, retries
completed checker rejections, and renders accepted records into that evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import course_sources
from harness.model_budget import BudgetBlocked, BudgetExhausted, TokenLedger
from harness.openai_course_client import (
    CourseClientError,
    CourseGeneration,
    CourseProtocolError,
    OpenAICourseClient,
    RequestShapeError,
    build_extraction_request,
    create_live_client,
    _validated_source_view,
)


MAX_ATTEMPTS = 3
MODEL_TIMEOUT_SECONDS = 90
COMPONENT_TIMEOUT_SECONDS = 30
CHECKER = ROOT / "eval" / "check_courses.py"
RENDERER = ROOT / "harness" / "render_courses.py"
PUBLISHED_JSON = ROOT / "out" / "training" / "courses.json"
PUBLISHED_MARKDOWN = ROOT / "out" / "training" / "comparison.md"


@dataclass(frozen=True)
class CourseWorkflowResult:
    """Safe outcome and evidence paths for one source case."""

    status: str
    attempts: int
    evidence_dir: str
    source_path: str | None = None
    candidate_path: str | None = None
    checker_path: str | None = None
    rendered_json_path: str | None = None
    rendered_markdown_path: str | None = None
    failure_code: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value) -> None:
    path.write_bytes(_json_bytes(value))


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    return environment


def _safe_block(ledger: TokenLedger, reason: str) -> None:
    try:
        ledger.block(reason=reason)
    except Exception:
        pass


def _result(status, attempts, evidence_dir, **kwargs) -> CourseWorkflowResult:
    return CourseWorkflowResult(
        status=status,
        attempts=attempts,
        evidence_dir=str(evidence_dir),
        **kwargs,
    )


def _record_result(evidence_dir: Path, result: CourseWorkflowResult, ledger: TokenLedger) -> None:
    _write_json(evidence_dir / "result.json", asdict(result))
    _write_json(evidence_dir / "budget-final.json", ledger.state)


def _abandon_case(case_dir: Path, ledger: TokenLedger, progress: dict, *,
                  interrupted: bool = False) -> CourseWorkflowResult:
    """Block first; failure receipts are best effort when storage has failed."""
    _safe_block(ledger, "request_interrupted" if interrupted else "protocol_failure")

    def existing(name):
        path = case_dir / name
        try:
            return str(path) if path.is_file() and not path.is_symlink() else None
        except OSError:
            return None

    result = _result(
        "infrastructure_abort", progress["attempts"], case_dir,
        source_path=existing("source.json"),
        candidate_path=existing("candidate.json"),
        checker_path=existing("candidate-check.json"),
        failure_code="interrupted" if interrupted else progress["stage"] + "_failure",
    )
    # A failed result write must not prevent a separate budget receipt attempt.
    # Never log the underlying exception or resume work after either failure.
    for name, value in (("result.json", asdict(result)), ("budget-final.json", ledger.state)):
        try:
            _write_json(case_dir / name, value)
        except (Exception, KeyboardInterrupt, SystemExit):
            pass
    return result


def run_course_workflow(source_bundle, ledger: TokenLedger, sdk_client,
                        evidence_dir) -> CourseWorkflowResult:
    """Run one approved source case using caller-owned budget and SDK objects.

    ``evidence_dir`` must be a new directory. The ledger is never constructed,
    replaced, reset, or resumed here. ``sdk_client`` is the raw injected SDK
    client consumed by the existing ``OpenAICourseClient`` adapter.
    """
    if not isinstance(ledger, TokenLedger):
        raise TypeError("ledger must be a caller-owned TokenLedger")
    case_dir = Path(evidence_dir)
    progress = {"attempts": 0, "stage": "evidence_directory"}
    try:
        case_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        # Existing evidence is never reused or overwritten.
        _safe_block(ledger, "protocol_failure")
        raise
    except (KeyboardInterrupt, SystemExit):
        return _abandon_case(case_dir, ledger, progress, interrupted=True)
    except OSError:
        return _abandon_case(case_dir, ledger, progress)
    try:
        return _run_case(source_bundle, ledger, sdk_client, case_dir, progress)
    except (KeyboardInterrupt, SystemExit):
        return _abandon_case(case_dir, ledger, progress, interrupted=True)
    except Exception:
        return _abandon_case(case_dir, ledger, progress)


def _run_case(source_bundle, ledger, sdk_client, case_dir, progress):
    attempts = 0
    stable_candidate = case_dir / "candidate.json"
    case_source = case_dir / "source.json"
    checker_evidence = case_dir / "candidate-check.json"

    try:
        # Validate source data independently of prompt/schema and storage. A
        # missing context file or failed write is an infrastructure failure,
        # not an expected rejection of the source.
        progress["stage"] = "source_validation"
        source_snapshot = json.loads(json.dumps(source_bundle, ensure_ascii=False, allow_nan=False))
        _validated_source_view(source_snapshot)
    except RequestShapeError:
        result = _result("source_rejected", 0, case_dir, failure_code="source_contract_rejected")
        _record_result(case_dir, result, ledger)
        return result
    except (TypeError, ValueError):
        result = _result("source_rejected", 0, case_dir, failure_code="source_snapshot_invalid")
        _record_result(case_dir, result, ledger)
        return result

    progress["stage"] = "source_request_context"
    request = build_extraction_request(source_snapshot)
    progress["stage"] = "source_snapshot"
    source_bytes = _json_bytes(source_snapshot)
    case_source.write_bytes(source_bytes)
    case_source.chmod(0o444)
    source_hash = _sha256(source_bytes)
    progress["stage"] = "source_provenance"
    _write_json(case_dir / "source-provenance.json", {
        "source_sha256": source_hash,
        "approved_request_sha256": request.sha256,
        "source_course_count": len(source_snapshot["courses"]),
    })

    adapter = OpenAICourseClient(client=sdk_client, ledger=ledger)
    previous_candidate = None
    feedback = None
    checker_path = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        progress["attempts"] = attempt
        progress["stage"] = "repair_request"
        try:
            attempt_request = build_extraction_request(
                source_snapshot,
                previous_candidate_json=previous_candidate,
                production_checker_feedback=feedback,
            )
        except RequestShapeError:
            _safe_block(ledger, "protocol_failure")
            result = _result(
                "provider_abort", attempt - 1, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="repair_protocol_error",
            )
            _record_result(case_dir, result, ledger)
            return result

        request_evidence = case_dir / f"request-attempt-{attempt}.json"
        progress["stage"] = "request_evidence"
        try:
            _write_json(request_evidence, {
                "attempt": attempt,
                "count_create_payload_sha256": attempt_request.sha256,
                "source_sha256": source_hash,
                "repair_candidate_sha256": _sha256(previous_candidate.encode("utf-8")) if previous_candidate is not None else None,
                "checker_feedback_sha256": _sha256(feedback.encode("utf-8")) if feedback is not None else None,
                "dispatch_status": "not_started",
            })
        except Exception:
            _safe_block(ledger, "ledger_persistence_failure")
            result = _result(
                "infrastructure_abort", attempt - 1, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="request_evidence_write_failure",
            )
            _record_result(case_dir, result, ledger)
            return result

        progress["stage"] = "generation"
        try:
            generation: CourseGeneration = adapter.generate(
                source_snapshot,
                previous_candidate_json=previous_candidate,
                production_checker_feedback=feedback,
            )
        except BudgetExhausted:
            _write_json(request_evidence, {
                **json.loads(request_evidence.read_text(encoding="utf-8")),
                "dispatch_status": "blocked_by_budget",
            })
            _write_json(case_dir / f"model-attempt-{attempt}.json", {
                "attempt": attempt,
                "dispatch_status": "not_dispatched",
                "failure_code": "budget_exhausted",
                "budget": ledger.state,
            })
            result = _result(
                "budget_exhausted", attempt - 1, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="budget_exhausted",
            )
            _record_result(case_dir, result, ledger)
            return result
        except BudgetBlocked:
            _write_json(request_evidence, {
                **json.loads(request_evidence.read_text(encoding="utf-8")),
                "dispatch_status": "blocked_by_ledger",
            })
            _write_json(case_dir / f"model-attempt-{attempt}.json", {
                "attempt": attempt,
                "dispatch_status": "not_dispatched",
                "failure_code": "budget_blocked",
                "budget": ledger.state,
            })
            result = _result(
                "provider_abort", attempt - 1, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="budget_blocked",
            )
            _record_result(case_dir, result, ledger)
            return result
        except (CourseClientError, CourseProtocolError):
            _write_json(request_evidence, {
                **json.loads(request_evidence.read_text(encoding="utf-8")),
                "dispatch_status": "aborted; inspect budget reservation state",
            })
            _write_json(case_dir / f"model-attempt-{attempt}.json", {
                "attempt": attempt,
                "dispatch_status": "see_ledger_reservation_state",
                "failure_code": "provider_or_protocol_failure",
                "budget": ledger.state,
            })
            result = _result(
                "provider_abort", attempt, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="provider_or_protocol_failure",
            )
            _record_result(case_dir, result, ledger)
            return result
        except KeyboardInterrupt:
            _safe_block(ledger, "request_interrupted")
            _write_json(request_evidence, {
                **json.loads(request_evidence.read_text(encoding="utf-8")),
                "dispatch_status": "interrupted",
            })
            _write_json(case_dir / f"model-attempt-{attempt}.json", {
                "attempt": attempt,
                "dispatch_status": "interrupted",
                "failure_code": "interrupted",
                "budget": ledger.state,
            })
            result = _result(
                "provider_abort", attempt, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="interrupted",
            )
            _record_result(case_dir, result, ledger)
            return result
        except Exception:
            _safe_block(ledger, "protocol_failure")
            _write_json(request_evidence, {
                **json.loads(request_evidence.read_text(encoding="utf-8")),
                "dispatch_status": "unknown",
            })
            _write_json(case_dir / f"model-attempt-{attempt}.json", {
                "attempt": attempt,
                "dispatch_status": "unknown",
                "failure_code": "controller_failure",
                "budget": ledger.state,
            })
            result = _result(
                "infrastructure_abort", attempt, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                checker_path=str(checker_evidence) if checker_evidence.exists() else None,
                failure_code="controller_failure",
            )
            _record_result(case_dir, result, ledger)
            return result

        candidate_path = case_dir / f"candidate-{attempt}.json"
        progress["stage"] = "candidate_evidence"
        try:
            candidate_bytes = generation.text.encode("utf-8")
            _write_json(request_evidence, {
                **json.loads(request_evidence.read_text(encoding="utf-8")),
                "dispatch_status": "completed",
            })
            candidate_path.write_bytes(candidate_bytes)
            shutil.copyfile(candidate_path, stable_candidate)
            _write_json(case_dir / f"attempt-{attempt}.json", {
                "attempt": attempt,
                "candidate_path": candidate_path.name,
                "candidate_sha256": _sha256(candidate_bytes),
                "source_sha256": source_hash,
                "count_create_payload_sha256": generation.payload_sha256,
                "requested_model": generation.requested_model,
                "returned_model": generation.returned_model,
                "response_id": generation.response_id,
                "request_id": generation.request_id,
                "count_request_id": generation.count_request_id,
                "generation_status": "completed",
                "checker_status": "not_dispatched",
            })
            _write_json(case_dir / f"budget-after-attempt-{attempt}.json", ledger.state)
        except Exception:
            _safe_block(ledger, "ledger_persistence_failure")
            result = _result(
                "infrastructure_abort", attempt, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate) if stable_candidate.exists() else None,
                failure_code="evidence_write_failure",
            )
            _record_result(case_dir, result, ledger)
            return result

        progress["stage"] = "checker"
        try:
            checked = subprocess.run(
                [sys.executable, str(CHECKER), "--source", str(case_source), "--candidate", str(candidate_path)],
                cwd=ROOT,
                env=_child_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=COMPONENT_TIMEOUT_SECONDS,
                check=False,
            )
            checker_status = checked.returncode
            stdout = checked.stdout
            stderr = checked.stderr
            timed_out = False
            dispatch_status = "completed"
        except subprocess.TimeoutExpired as error:
            checker_status = None
            stdout = _as_text(error.stdout)
            stderr = _as_text(error.stderr)
            timed_out = True
            dispatch_status = "dispatched_timeout"
        except OSError:
            checker_status = None
            stdout = ""
            stderr = ""
            timed_out = False
            dispatch_status = "not_dispatched"

        checker_feedback = stdout + stderr
        checker_record = {
            "attempt": attempt,
            "status": checker_status,
            "timed_out": timed_out,
            "dispatch_status": dispatch_status,
            "stdout": stdout,
            "stderr": stderr,
            "feedback_sha256": _sha256(checker_feedback.encode("utf-8")),
            "source_sha256": source_hash,
            "candidate_sha256": _sha256(candidate_path.read_bytes()),
        }
        progress["stage"] = "checker_evidence"
        try:
            attempt_checker_evidence = case_dir / f"candidate-check-{attempt}.json"
            _write_json(attempt_checker_evidence, checker_record)
            _write_json(checker_evidence, checker_record)
            attempt_record_path = case_dir / f"attempt-{attempt}.json"
            attempt_record = json.loads(attempt_record_path.read_text(encoding="utf-8"))
            attempt_record["checker_status"] = checker_status
            attempt_record["checker_dispatch_status"] = dispatch_status
            attempt_record["checker_timed_out"] = timed_out
            _write_json(attempt_record_path, attempt_record)
            checker_path = checker_evidence
        except Exception:
            _safe_block(ledger, "ledger_persistence_failure")
            result = _result(
                "infrastructure_abort", attempt, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate),
                failure_code="checker_evidence_write_failure",
            )
            _record_result(case_dir, result, ledger)
            return result

        if checker_status == 0 and not timed_out:
            rendered_json = case_dir / "rendered-courses.json"
            rendered_markdown = case_dir / "comparison.md"
            progress["stage"] = "renderer"
            try:
                rendered = subprocess.run(
                    [sys.executable, str(RENDERER), "--input", str(candidate_path),
                     "--json-output", str(rendered_json), "--markdown-output", str(rendered_markdown)],
                    cwd=ROOT,
                    env=_child_environment(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=COMPONENT_TIMEOUT_SECONDS,
                    check=False,
                )
                render_status = rendered.returncode
                render_stdout = rendered.stdout
                render_stderr = rendered.stderr
                render_timed_out = False
                render_dispatch = "completed"
            except subprocess.TimeoutExpired as error:
                render_status = None
                render_stdout = _as_text(error.stdout)
                render_stderr = _as_text(error.stderr)
                render_timed_out = True
                render_dispatch = "dispatched_timeout"
            except OSError:
                render_status = None
                render_stdout = ""
                render_stderr = ""
                render_timed_out = False
                render_dispatch = "not_dispatched"
            progress["stage"] = "renderer_evidence"
            _write_json(case_dir / "render.json", {
                "status": render_status,
                "timed_out": render_timed_out,
                "dispatch_status": render_dispatch,
                "stdout": render_stdout,
                "stderr": render_stderr,
                "json_sha256": _sha256(rendered_json.read_bytes()) if rendered_json.is_file() else None,
                "markdown_sha256": _sha256(rendered_markdown.read_bytes()) if rendered_markdown.is_file() else None,
            })
            if render_status == 0 and not render_timed_out and rendered_json.is_file() and rendered_markdown.is_file():
                result = _result(
                    "accepted", attempt, case_dir,
                    source_path=str(case_source), candidate_path=str(stable_candidate),
                    checker_path=str(checker_evidence),
                    rendered_json_path=str(rendered_json),
                    rendered_markdown_path=str(rendered_markdown),
                )
                _record_result(case_dir, result, ledger)
                return result
            _safe_block(ledger, "protocol_failure")
            result = _result(
                "infrastructure_abort", attempt, case_dir,
                source_path=str(case_source), candidate_path=str(stable_candidate),
                checker_path=str(checker_evidence), failure_code="renderer_failure",
            )
            _record_result(case_dir, result, ledger)
            return result

        if checker_status == 1 and not timed_out:
            if attempt == MAX_ATTEMPTS:
                result = _result(
                    "candidate_rejected", attempt, case_dir,
                    source_path=str(case_source), candidate_path=str(stable_candidate),
                    checker_path=str(checker_evidence), failure_code="three_candidates_rejected",
                )
                _record_result(case_dir, result, ledger)
                return result
            previous_candidate = generation.text
            feedback = checker_feedback
            continue

        _safe_block(ledger, "protocol_failure")
        result = _result(
            "infrastructure_abort", attempt, case_dir,
            source_path=str(case_source), candidate_path=str(stable_candidate),
            checker_path=str(checker_evidence),
            failure_code="checker_timeout" if timed_out else "checker_failure",
        )
        _record_result(case_dir, result, ledger)
        return result

    # The loop has explicit terminal outcomes above.
    _safe_block(ledger, "protocol_failure")
    result = _result("infrastructure_abort", attempts, case_dir, failure_code="controller_state_invalid")
    _record_result(case_dir, result, ledger)
    return result


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if parsed <= 0 or str(parsed) != value:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="use the checked-in course source fixture")
    parser.add_argument("--dry-run", action="store_true", help="show real stages without creating files or a client")
    parser.add_argument("--run-token-limit", type=_positive_integer)
    parser.add_argument("--max-output-tokens", type=_positive_integer)
    parser.add_argument("--max-model-calls", type=_positive_integer)
    return parser


def _dry_run(offline: bool) -> int:
    source_stage = "checked-in fixture" if offline else "approved course pages and robots.txt"
    print("DRY RUN: no collection, provider, checker, renderer, client construction, or file creation.")
    print(f"1. Collect sources: {source_stage} (OPENAI_API_KEY removed from collector subprocess).")
    print("2. Create a read-only per-run source snapshot under out/training/run-*/.")
    print("3. Count input and make up to 3 serial Responses API generation attempts using gpt-6-luna, reasoning low.")
    print("4. Enforce caller-supplied --run-token-limit, --max-output-tokens, and --max-model-calls with one run ledger.")
    print("5. Run eval/check_courses.py with OPENAI_API_KEY removed; retry only completed candidate rejections.")
    print("6. Render accepted output inside the run evidence directory, then publish courses.json and comparison.md.")
    print("Evidence paths: out/training/run-*/course-sources.json, ledger.json, and case/candidate.json, candidate-check.json, rendered-courses.json, comparison.md.")
    print("Example limits are required caller choices; dry-run selects no values.")
    return 0


def _collect_sources(offline: bool, evidence_dir: Path) -> tuple[dict | None, int]:
    collector = ROOT / "harness" / "course_sources.py"
    source_output = ROOT / "out" / "training" / "course-sources.json"
    try:
        previous_stat = source_output.lstat()
        if not stat.S_ISREG(previous_stat.st_mode):
            return None, 4
        previous_identity = (previous_stat.st_dev, previous_stat.st_ino)
    except FileNotFoundError:
        previous_identity = None
    except OSError:
        return None, 4
    command = [sys.executable, str(collector)]
    if offline:
        command.append("--offline")
    try:
        completed = subprocess.run(
            command, cwd=ROOT, env=_child_environment(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
        )
    except subprocess.TimeoutExpired as error:
        (evidence_dir / "collector.stdout.log").write_text(_as_text(error.stdout), encoding="utf-8")
        (evidence_dir / "collector.stderr.log").write_text(_as_text(error.stderr), encoding="utf-8")
        return None, 4
    except OSError:
        (evidence_dir / "collector.stdout.log").write_text("", encoding="utf-8")
        (evidence_dir / "collector.stderr.log").write_text("collector dispatch failed\n", encoding="utf-8")
        return None, 4
    (evidence_dir / "collector.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (evidence_dir / "collector.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return None, 4
    try:
        current_stat = source_output.lstat()
        if (not stat.S_ISREG(current_stat.st_mode)
                or (current_stat.st_dev, current_stat.st_ino) == previous_identity):
            return None, 4
        data = json.loads(source_output.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, 4
    return data, 0


def _publish(json_source: Path, markdown_source: Path) -> None:
    training = PUBLISHED_JSON.parent
    json_temp = None
    markdown_temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".courses.", suffix=".tmp", dir=training, delete=False) as stream:
            json_temp = Path(stream.name)
            stream.write(json_source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        with tempfile.NamedTemporaryFile(prefix=".comparison.", suffix=".tmp", dir=training, delete=False) as stream:
            markdown_temp = Path(stream.name)
            stream.write(markdown_source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(json_temp, PUBLISHED_JSON)
        json_temp = None
        os.replace(markdown_temp, PUBLISHED_MARKDOWN)
        markdown_temp = None
    finally:
        for temporary in (json_temp, markdown_temp):
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.dry_run:
        return _dry_run(args.offline)
    limits = (args.run_token_limit, args.max_output_tokens, args.max_model_calls)
    if any(value is None for value in limits):
        parser.error("actual execution requires --run-token-limit, --max-output-tokens, and --max-model-calls")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("ERROR: OPENAI_API_KEY is required for model extraction; its value is never displayed.", file=sys.stderr)
        return 3

    training = ROOT / "out" / "training"
    try:
        training.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix=f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-", dir=training))
    except OSError:
        print("ERROR: could not create a fresh run evidence directory.", file=sys.stderr)
        return 8
    print(f"Run evidence: {run_dir.relative_to(ROOT)}")

    source_bundle, collection_status = _collect_sources(args.offline, run_dir)
    if collection_status:
        print(f"ERROR: source collection failed; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return collection_status

    try:
        source_bytes = _json_bytes(source_bundle)
        snapshot = run_dir / "course-sources.json"
        snapshot.write_bytes(source_bytes)
        snapshot.chmod(0o444)
        source_bundle = json.loads(snapshot.read_text(encoding="utf-8"))
        ledger = TokenLedger(
            ledger_path=run_dir / "ledger.json",
            run_token_limit=args.run_token_limit,
            max_output_tokens=args.max_output_tokens,
            max_model_calls=args.max_model_calls,
        )
    except Exception:
        print(f"ERROR: source snapshot or ledger setup failed; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return 8

    try:
        client = create_live_client(timeout_seconds=MODEL_TIMEOUT_SECONDS)
    except CourseClientError:
        print(f"ERROR: model client is unavailable; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return 7

    try:
        result = run_course_workflow(source_bundle, ledger, client, run_dir / "case")
    except (KeyboardInterrupt, SystemExit):
        _safe_block(ledger, "request_interrupted")
        print(f"ERROR: course workflow interrupted; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return 130
    except Exception:
        _safe_block(ledger, "protocol_failure")
        print(f"ERROR: course controller failed; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return 8
    finally:
        try:
            client.close()
        except Exception:
            pass

    if result.failure_code == "interrupted":
        print(f"ERROR: course workflow interrupted; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return 130
    if result.status != "accepted":
        codes = {
            "source_rejected": 4,
            "candidate_rejected": 5,
            "budget_exhausted": 6,
            "provider_abort": 7,
            "infrastructure_abort": 8,
        }
        code = codes.get(result.status, 8)
        print(f"ERROR: course workflow ended with {result.status}; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return code

    try:
        _publish(Path(result.rendered_json_path), Path(result.rendered_markdown_path))
    except OSError:
        print(f"ERROR: publication failed after accepted rendering; evidence: {run_dir.relative_to(ROOT)}", file=sys.stderr)
        return 8
    print("Validated records published to out/training/courses.json and out/training/comparison.md.")
    print("The two published files are replaced separately, not as one atomic transaction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
