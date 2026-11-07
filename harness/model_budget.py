"""Durable, single-process token accounting for bounded model requests.

The ledger deliberately has no numerical defaults and cannot resume an old
file. A caller must create it at a fresh path inside the current run's
evidence directory and keep the same instance for every attempt in that run.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid


class LedgerError(RuntimeError):
    """Base class for safe ledger failures."""


class InvalidLimit(LedgerError, ValueError):
    """A caller supplied a missing, non-integer, or non-positive limit."""


class LedgerAlreadyExists(LedgerError):
    """The requested ledger path is not fresh."""


class LedgerPersistenceError(LedgerError):
    """A ledger update could not be written safely."""


class BudgetBlocked(LedgerError):
    """A previous uncertain or invalid operation permanently blocked the run."""


class BudgetExhausted(LedgerError):
    """No further model attempt can fit the explicit limits."""


class ReservationError(LedgerError):
    """A reservation handle is unknown or in the wrong state."""


class UsageValidationError(LedgerError):
    """A completed response did not provide trustworthy bounded usage."""


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_HASH = re.compile(r"^[a-f0-9]{64}$")
_RESERVATION_STATES = {"reserved", "dispatched", "settled", "uncertain", "contradiction"}
_AUDIT_KEYS = {
    "count_input_sha256", "create_input_sha256", "count_request_id",
    "request_id", "response_id", "requested_model", "returned_model",
    "service_tier", "background", "store", "stream", "sdk_max_retries",
    "timeout_seconds",
}


def _positive_limit(name, value):
    if type(value) is not int or value <= 0:
        raise InvalidLimit(f"{name} must be a positive integer")
    return value


def _safe_identifier(value):
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else None


def _safe_audit(values):
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError("audit metadata must be an object")
    result = {}
    for key, value in values.items():
        if key not in _AUDIT_KEYS:
            continue
        if key == "service_tier":
            if value == "default":
                result[key] = value
        elif key in {"background", "store", "stream"}:
            if value is False:
                result[key] = value
        elif key == "sdk_max_retries":
            if type(value) is int and value == 0:
                result[key] = value
        elif key == "timeout_seconds":
            if type(value) in (int, float) and math.isfinite(value) and value > 0:
                result[key] = value
        elif key.endswith("_sha256"):
            if isinstance(value, str) and _SAFE_HASH.fullmatch(value):
                result[key] = value
        else:
            identifier = _safe_identifier(value)
            prefix = ("resp_" if key == "response_id" else
                      "gpt-" if key in {"requested_model", "returned_model"} else "req_")
            if identifier is not None and identifier.startswith(prefix) and len(identifier) > len(prefix):
                result[key] = identifier
    return result


class TokenLedger:
    """One-run token ledger with durable reservations and permanent blocking.

    ``run_token_limit``, ``max_output_tokens``, and ``max_model_calls`` are
    mandatory caller choices. ``ledger_path`` must name a new file whose
    parent directory already exists. The class is for one controlling process
    with serial requests; it is not cross-process coordination.
    """

    FORMAT_VERSION = 1

    def __init__(self, *, ledger_path, run_token_limit, max_output_tokens,
                 max_model_calls):
        self._limits = (
            _positive_limit("run_token_limit", run_token_limit),
            _positive_limit("max_output_tokens", max_output_tokens),
            _positive_limit("max_model_calls", max_model_calls),
        )
        if ledger_path is None or not isinstance(ledger_path, (str, os.PathLike)):
            raise ValueError("ledger_path must be caller supplied")
        self.path = Path(ledger_path)
        if not self.path.name:
            raise ValueError("ledger_path must name a file")
        if not self.path.parent.is_dir():
            raise LedgerPersistenceError("ledger directory must already exist")

        self._state = {
            "format_version": self.FORMAT_VERSION,
            "run_token_limit": self.run_token_limit,
            "max_output_tokens": self.max_output_tokens,
            "max_model_calls": self.max_model_calls,
            "confirmed_tokens": 0,
            "model_calls": 0,
            "blocked": False,
            "block_reason": None,
            "reservations": [],
        }
        self._file_identity = None
        self._create_fresh_file()

    @property
    def run_token_limit(self):
        return self._limits[0]

    @property
    def max_output_tokens(self):
        return self._limits[1]

    @property
    def max_model_calls(self):
        return self._limits[2]

    @property
    def state(self):
        """Return a detached copy of the safe evidence state."""
        return copy.deepcopy(self._state)

    @property
    def pending_tokens(self):
        return sum(
            item["reserved_tokens"] for item in self._state["reservations"]
            if item["status"] in {"reserved", "dispatched", "uncertain", "contradiction"}
        )

    @property
    def remaining_tokens(self):
        return self.run_token_limit - self._state["confirmed_tokens"] - self.pending_tokens

    @property
    def remaining_model_calls(self):
        return self.max_model_calls - self._state["model_calls"]

    def _encode(self, state):
        return (json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")

    def _create_fresh_file(self):
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise LedgerAlreadyExists("ledger path already exists; refusing to reset it") from None
        except OSError:
            raise LedgerPersistenceError("could not create fresh ledger") from None
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(self._encode(self._state))
                stream.flush()
                os.fsync(stream.fileno())
                stat = os.fstat(stream.fileno())
                self._file_identity = (stat.st_dev, stat.st_ino)
        except OSError:
            # Keep any partial file in place: the next constructor must refuse
            # it rather than silently treating a failed run as fresh.
            raise LedgerPersistenceError("could not persist fresh ledger") from None

    def _assert_owned_file(self):
        try:
            stat = self.path.lstat()
        except OSError:
            raise LedgerPersistenceError("ledger path is unavailable") from None
        if not self.path.is_file() or (stat.st_dev, stat.st_ino) != self._file_identity:
            raise LedgerPersistenceError("ledger path changed during the run")

    def _persist_state(self, state):
        """Atomically replace only the ledger file created by this instance."""
        self._assert_owned_file()
        temporary_path = None
        try:
            fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            temporary_path = Path(temporary_name)
            os.chmod(temporary_path, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(self._encode(state))
                stream.flush()
                os.fsync(stream.fileno())
            self._assert_owned_file()
            os.replace(temporary_path, self.path)
            temporary_path = None
            stat = self.path.lstat()
            self._file_identity = (stat.st_dev, stat.st_ino)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            raise LedgerPersistenceError("could not persist ledger update") from None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def _commit(self, next_state):
        try:
            self._persist_state(next_state)
        except BaseException as error:
            # A failed write makes this in-memory run unusable. Any durable
            # reservation already on disk remains, and the path cannot resume.
            self._state["blocked"] = True
            self._state["block_reason"] = "ledger_persistence_failure"
            if not isinstance(error, Exception):
                raise
            raise LedgerPersistenceError("could not persist ledger update") from None
        self._state = next_state

    def _reservation(self, handle):
        if not isinstance(handle, str):
            raise ReservationError("unknown reservation handle")
        for item in self._state["reservations"]:
            if item["handle"] == handle:
                return item
        raise ReservationError("unknown reservation handle")

    def _assert_open(self):
        if self._state["blocked"]:
            raise BudgetBlocked("run budget is permanently blocked")

    def assert_can_count(self):
        """Reject blocked/exhausted runs before an input-token count request."""
        self._assert_open()
        if self.remaining_model_calls <= 0 or self.remaining_tokens <= self.max_output_tokens:
            raise BudgetExhausted("no further request can fit the explicit budget")

    def reserve(self, counted_input_tokens, *, audit=None):
        """Persist ``counted input + maximum output`` before dispatch."""
        if type(counted_input_tokens) is not int or counted_input_tokens <= 0:
            raise ValueError("counted_input_tokens must be a positive integer")
        self.assert_can_count()
        reserved = counted_input_tokens + self.max_output_tokens
        if self._state["confirmed_tokens"] + self.pending_tokens + reserved > self.run_token_limit:
            raise BudgetExhausted("counted request cannot fit the remaining token budget")
        if self.remaining_model_calls <= 0:
            raise BudgetExhausted("model-call allowance is exhausted")

        item = {
            "handle": uuid.uuid4().hex,
            "counted_input_tokens": counted_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "reserved_tokens": reserved,
            "status": "reserved",
            "actual_tokens": None,
            "cached_input_tokens": None,
            "reasoning_tokens": None,
            "audit": _safe_audit(audit),
            "failure_code": None,
            "observed_usage": None,
        }
        next_state = copy.deepcopy(self._state)
        next_state["reservations"].append(item)
        self._commit(next_state)
        return item["handle"]

    def dispatch(self, handle):
        """Durably mark one generation attempt immediately before calling it."""
        self._assert_open()
        item = self._reservation(handle)
        if item["status"] != "reserved":
            raise ReservationError("reservation is not dispatchable")
        if self.remaining_model_calls <= 0:
            raise BudgetExhausted("model-call allowance is exhausted")
        next_state = copy.deepcopy(self._state)
        next_item = next(entry for entry in next_state["reservations"] if entry["handle"] == handle)
        next_item["status"] = "dispatched"
        next_state["model_calls"] += 1
        self._commit(next_state)

    def _usage_failure(self, handle, code, *, contradiction=False, observed=None):
        next_state = copy.deepcopy(self._state)
        next_state["blocked"] = True
        next_state["block_reason"] = code
        item = next(entry for entry in next_state["reservations"] if entry["handle"] == handle)
        item["status"] = "contradiction" if contradiction else "uncertain"
        item["failure_code"] = code
        item["observed_usage"] = observed
        try:
            self._persist_state(next_state)
        except BaseException as error:
            self._state["blocked"] = True
            self._state["block_reason"] = "ledger_persistence_failure"
            current = self._reservation(handle)
            current["status"] = "contradiction" if contradiction else "uncertain"
            current["failure_code"] = code
            current["observed_usage"] = observed
            if not isinstance(error, Exception):
                raise
            raise LedgerPersistenceError("could not persist ledger update") from None
        self._state = next_state
        raise UsageValidationError("response usage is untrusted or violates the request bound")

    def settle(self, handle, *, input_tokens, output_tokens, total_tokens,
               cached_input_tokens=0, reasoning_tokens=0, audit=None):
        """Settle only complete, internally consistent, bounded usage.

        Cached input is a detail of ``input_tokens`` and reasoning is a detail
        of ``output_tokens``. Neither is added a second time.
        """
        self._assert_open()
        item = self._reservation(handle)
        if item["status"] != "dispatched":
            raise ReservationError("only a dispatched reservation can be settled")
        values = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        if any(type(value) is not int for value in values.values()):
            self._usage_failure(handle, "usage_untrusted", observed={
                key: value if type(value) is int else None for key, value in values.items()
            })
        if any(value < 0 for value in values.values()):
            self._usage_failure(handle, "usage_untrusted", observed=values)
        if (input_tokens != item["counted_input_tokens"]
                or output_tokens > item["max_output_tokens"]
                or input_tokens + output_tokens > item["reserved_tokens"]):
            self._usage_failure(handle, "usage_bound_contradiction", contradiction=True, observed=values)
        if total_tokens != input_tokens + output_tokens:
            self._usage_failure(handle, "usage_untrusted", observed=values)
        if cached_input_tokens > input_tokens or reasoning_tokens > output_tokens:
            self._usage_failure(handle, "usage_untrusted", observed=values)

        safe_metadata = _safe_audit(audit)
        next_state = copy.deepcopy(self._state)
        next_item = next(entry for entry in next_state["reservations"] if entry["handle"] == handle)
        next_item["status"] = "settled"
        next_item["actual_tokens"] = total_tokens
        next_item["cached_input_tokens"] = cached_input_tokens
        next_item["reasoning_tokens"] = reasoning_tokens
        next_item["audit"].update(safe_metadata)
        next_state["confirmed_tokens"] += total_tokens
        self._commit(next_state)
        return total_tokens

    def mark_uncertain(self, handle, *, reason="dispatch_outcome_uncertain", observed_usage=None):
        """Permanently block the ledger and retain an unresolved reservation."""
        if reason not in {
            "dispatch_outcome_uncertain", "response_incomplete", "usage_untrusted",
            "protocol_failure", "usage_bound_contradiction", "request_interrupted",
        }:
            reason = "dispatch_outcome_uncertain"
        item = self._reservation(handle)
        if item["status"] not in {"reserved", "dispatched"}:
            if self._state["blocked"]:
                return
            raise ReservationError("reservation cannot be marked uncertain")
        next_state = copy.deepcopy(self._state)
        next_state["blocked"] = True
        next_state["block_reason"] = reason
        next_item = next(entry for entry in next_state["reservations"] if entry["handle"] == handle)
        next_item["status"] = "uncertain"
        next_item["failure_code"] = reason
        if isinstance(observed_usage, dict):
            # Preserve only numeric usage fields, including contradictions in
            # incomplete responses. The unresolved reservation stays in place.
            observed = {key: value if type(value) is int else None
                        for key, value in observed_usage.items()
                        if key in {"input_tokens", "output_tokens", "total_tokens",
                                   "cached_input_tokens", "reasoning_tokens"}}
            next_item["observed_usage"] = observed
            counted = observed.get("input_tokens")
            output = observed.get("output_tokens")
            total = observed.get("total_tokens")
            if ((counted is not None and counted >= 0 and counted != item["counted_input_tokens"])
                    or (output is not None and output > item["max_output_tokens"])
                    or (total is not None and total > item["reserved_tokens"])):
                next_item["status"] = "contradiction"
                next_item["failure_code"] = "usage_bound_contradiction"
                next_state["block_reason"] = "usage_bound_contradiction"
        self._commit(next_state)

    def block(self, *, reason="protocol_failure"):
        """Permanently prevent future counts and dispatches."""
        if reason not in {
            "protocol_failure", "request_interrupted", "usage_bound_contradiction",
            "usage_untrusted", "input_count_failed", "client_contract_invalid",
        }:
            reason = "protocol_failure"
        if self._state["blocked"]:
            return
        next_state = copy.deepcopy(self._state)
        next_state["blocked"] = True
        next_state["block_reason"] = reason
        self._commit(next_state)
