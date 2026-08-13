"""Tests for agent_resilience.identity — SessionIdentityValidator.

Covers: valid payloads, wrong agent ID, wrong session key, stale payloads,
missing fields, HMAC signature verification, rejection history.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import time

import pytest

from agent_resilience.identity import (
    SessionIdentityValidator,
    ValidationError,
    ValidationResult,
)


@pytest.fixture
def validator():
    return SessionIdentityValidator(
        expected_agent_id="gabriel",
        expected_session_key="agent:gabriel:main",
        max_payload_age_seconds=300,
        hmac_secret=None,
        strict_session_key=True,
    )


@pytest.fixture
def valid_payload():
    return {
        "agentId": "gabriel",
        "sessionKey": "agent:gabriel:main",
        "timestamp": time.time(),
    }


class TestSessionIdentityValidator:
    def test_valid_payload_accepted(self, validator, valid_payload):
        ok, err = validator.validate(valid_payload)
        assert ok is True
        assert err is None

    def test_wrong_agent_id_rejected(self, validator, valid_payload):
        valid_payload["agentId"] = "harry"
        ok, err = validator.validate(valid_payload)
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.WRONG_AGENT_ID
        assert "harry" in err.reason
        assert "gabriel" in err.reason

    def test_wrong_session_key_rejected(self, validator, valid_payload):
        valid_payload["sessionKey"] = "agent:harry:main"
        ok, err = validator.validate(valid_payload)
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.WRONG_SESSION_KEY

    def test_wrong_session_key_allowed_when_not_strict(self, valid_payload):
        validator = SessionIdentityValidator(
            expected_agent_id="gabriel",
            expected_session_key="agent:gabriel:main",
            strict_session_key=False,
        )
        valid_payload["sessionKey"] = "agent:harry:main"
        ok, err = validator.validate(valid_payload)
        assert ok is True
        assert err is None

    def test_stale_payload_rejected(self, valid_payload):
        validator = SessionIdentityValidator(
            expected_agent_id="gabriel",
            expected_session_key="agent:gabriel:main",
            max_payload_age_seconds=5,
        )
        valid_payload["timestamp"] = time.time() - 100
        ok, err = validator.validate(valid_payload)
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.STALE_PAYLOAD

    def test_future_payload_rejected(self, validator, valid_payload):
        valid_payload["timestamp"] = time.time() + 1000
        ok, err = validator.validate(valid_payload)
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.STALE_PAYLOAD

    def test_missing_fields_rejected(self, validator):
        ok, err = validator.validate({"agentId": "gabriel"})
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.MISSING_FIELDS

    def test_empty_payload_rejected(self, validator):
        ok, err = validator.validate({})
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.MISSING_FIELDS

    def test_rejection_count_tracks(self, validator, valid_payload):
        valid_payload["agentId"] = "wrong"
        validator.validate(valid_payload)
        validator.validate(valid_payload)
        validator.validate(valid_payload)
        assert validator.rejection_count == 3

    def test_rejection_summary(self, validator, valid_payload):
        valid_payload["agentId"] = "wrong"
        validator.validate(valid_payload)
        summary = validator.get_rejection_summary()
        assert summary["total_rejections"] == 1
        assert "WRONG_AGENT_ID" in summary["by_reason"]

    def test_valid_payload_does_not_increment_rejections(self, validator, valid_payload):
        validator.validate(valid_payload)
        assert validator.rejection_count == 0

    def test_hmac_valid_signature_accepted(self, valid_payload):
        secret = "super-secret-key"
        validator = SessionIdentityValidator(
            expected_agent_id="gabriel",
            expected_session_key="agent:gabriel:main",
            hmac_secret=secret,
        )
        # Compute valid signature
        clean = {k: v for k, v in valid_payload.items() if k != "signature"}
        canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
        sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        valid_payload["signature"] = sig
        ok, err = validator.validate(valid_payload)
        assert ok is True
        assert err is None

    def test_hmac_invalid_signature_rejected(self, valid_payload):
        secret = "super-secret-key"
        validator = SessionIdentityValidator(
            expected_agent_id="gabriel",
            expected_session_key="agent:gabriel:main",
            hmac_secret=secret,
        )
        valid_payload["signature"] = "invalid-signature-string"
        ok, err = validator.validate(valid_payload)
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.INVALID_SIGNATURE

    def test_hmac_missing_signature_rejected(self, valid_payload):
        secret = "super-secret-key"
        validator = SessionIdentityValidator(
            expected_agent_id="gabriel",
            expected_session_key="agent:gabriel:main",
            hmac_secret=secret,
        )
        # No signature field at all
        ok, err = validator.validate(valid_payload)
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.INVALID_SIGNATURE

    def test_validation_error_is_frozen(self):
        err = ValidationError(
            result=ValidationResult.WRONG_AGENT_ID,
            reason="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            err.reason = "modified"  # type: ignore
