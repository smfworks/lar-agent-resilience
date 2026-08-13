from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional
import hashlib
import hmac
import time
import structlog

logger = structlog.get_logger("agent_resilience.identity")


class ValidationResult(Enum):
    """Identity validation outcomes."""

    OK = auto()
    WRONG_AGENT_ID = auto()
    WRONG_SESSION_KEY = auto()
    STALE_PAYLOAD = auto()
    INVALID_SIGNATURE = auto()
    MISSING_FIELDS = auto()


@dataclass(frozen=True)
class ValidationError:
    """Structured validation failure."""

    result: ValidationResult
    reason: str
    payload_agent_id: Optional[str] = None
    expected_agent_id: Optional[str] = None
    payload_session_key: Optional[str] = None
    expected_session_key: Optional[str] = None


def _first(payload: dict, *keys: str):
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def parse_timestamp(value) -> float | None:
    """Accept unix seconds, numeric strings, or ISO-8601 datetimes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        try:
            iso = text.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


class SessionIdentityValidator:
    """
    Validates incoming payloads before processing.

    Inspired by the Harry→Gabriel cron misfire (June 2026):
    Every payload MUST prove it belongs to this agent/session
    before the agent loop processes it.
    """

    def __init__(
        self,
        expected_agent_id: str,
        expected_session_key: str,
        max_payload_age_seconds: int = 300,
        hmac_secret: Optional[str] = None,
        strict_session_key: bool = True,
    ):
        self.expected_agent_id = expected_agent_id
        self.expected_session_key = expected_session_key
        self.max_payload_age_seconds = max_payload_age_seconds
        self.hmac_secret = hmac_secret or None
        self.strict_session_key = strict_session_key
        self._validation_history: list[ValidationError] = []

    def validate(self, payload: dict) -> tuple[bool, Optional[ValidationError]]:
        if not self._has_required_fields(payload):
            error = ValidationError(
                result=ValidationResult.MISSING_FIELDS,
                reason="Payload missing required identity fields (agentId/agent_id, sessionKey/session_key, timestamp)",
            )
            self._log_rejection(error, payload)
            return False, error

        payload_agent_id = _first(payload, "agentId", "agent_id")
        payload_session_key = _first(payload, "sessionKey", "session_key")
        payload_timestamp = parse_timestamp(_first(payload, "timestamp"))
        payload_signature = _first(payload, "signature")

        if payload_agent_id != self.expected_agent_id:
            error = ValidationError(
                result=ValidationResult.WRONG_AGENT_ID,
                reason=f"Payload agentId '{payload_agent_id}' does not match expected '{self.expected_agent_id}'",
                payload_agent_id=payload_agent_id,
                expected_agent_id=self.expected_agent_id,
            )
            self._log_rejection(error, payload)
            return False, error

        if self.strict_session_key and payload_session_key != self.expected_session_key:
            error = ValidationError(
                result=ValidationResult.WRONG_SESSION_KEY,
                reason=f"Payload sessionKey '{payload_session_key}' does not match expected '{self.expected_session_key}'",
                payload_session_key=payload_session_key,
                expected_session_key=self.expected_session_key,
            )
            self._log_rejection(error, payload)
            return False, error

        if payload_timestamp is None or not self._is_fresh(payload_timestamp):
            error = ValidationError(
                result=ValidationResult.STALE_PAYLOAD,
                reason=f"Payload timestamp {payload_timestamp} is stale or unparseable (max age: {self.max_payload_age_seconds}s)",
            )
            self._log_rejection(error, payload)
            return False, error

        if self.hmac_secret and not self._verify_signature(payload, payload_signature):
            error = ValidationError(
                result=ValidationResult.INVALID_SIGNATURE,
                reason="Payload HMAC signature verification failed",
            )
            self._log_rejection(error, payload)
            return False, error

        logger.info(
            "identity_validation_passed",
            agent_id=payload_agent_id,
            session_key=payload_session_key,
        )
        return True, None

    def _has_required_fields(self, payload: dict) -> bool:
        has_agent = "agentId" in payload or "agent_id" in payload
        has_session = "sessionKey" in payload or "session_key" in payload
        has_ts = "timestamp" in payload
        return has_agent and has_session and has_ts

    def _is_fresh(self, timestamp: float) -> bool:
        now = time.time()
        age = now - timestamp
        return 0 <= age <= self.max_payload_age_seconds

    def _verify_signature(self, payload: dict, signature: Optional[str]) -> bool:
        if not signature:
            return False

        canonical = self._canonicalize_payload(payload)
        expected = hmac.new(
            self.hmac_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _canonicalize_payload(payload: dict) -> str:
        import json

        clean = {k: v for k, v in payload.items() if k != "signature"}
        return json.dumps(clean, sort_keys=True, separators=(",", ":"))

    def _log_rejection(self, error: ValidationError, payload: dict) -> None:
        logger.warning(
            "identity_validation_rejected",
            result=error.result.name,
            reason=error.reason,
            payload_agent_id=error.payload_agent_id,
            expected_agent_id=error.expected_agent_id,
            payload_session_key=error.payload_session_key,
            expected_session_key=error.expected_session_key,
            payload_preview=str(payload)[:200],
        )
        self._validation_history.append(error)

    @property
    def rejection_count(self) -> int:
        return len(self._validation_history)

    def get_rejection_summary(self) -> dict:
        from collections import Counter

        counts = Counter(e.result.name for e in self._validation_history)
        return {
            "total_rejections": self.rejection_count,
            "by_reason": dict(counts),
        }
