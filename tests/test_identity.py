"""Identity validator: camel/snake fields, HMAC, timestamps, no TypeError."""

import hashlib
import hmac
import json
import time

import pytest

from agent_resilience.identity import SessionIdentityValidator, ValidationResult


def _validator(**kwargs) -> SessionIdentityValidator:
    defaults = dict(
        expected_agent_id="gabriel",
        expected_session_key="agent:gabriel:main",
        hmac_secret=None,
        strict_session_key=True,
    )
    defaults.update(kwargs)
    return SessionIdentityValidator(**defaults)


def test_constructor_requires_session_key():
    with pytest.raises(TypeError):
        SessionIdentityValidator("gabriel")  # type: ignore[call-arg]


def test_camel_case_payload_accepted():
    v = _validator()
    ok, err = v.validate(
        {
            "agentId": "gabriel",
            "sessionKey": "agent:gabriel:main",
            "timestamp": time.time(),
        }
    )
    assert ok is True
    assert err is None


def test_snake_case_payload_accepted():
    v = _validator()
    ok, err = v.validate(
        {
            "agent_id": "gabriel",
            "session_key": "agent:gabriel:main",
            "timestamp": time.time(),
        }
    )
    assert ok is True
    assert err is None


def test_iso_string_timestamp_does_not_typeerror():
    v = _validator()
    from datetime import datetime, timezone

    ok, err = v.validate(
        {
            "agentId": "gabriel",
            "sessionKey": "agent:gabriel:main",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    assert ok is True
    assert err is None


def test_stale_timestamp_rejected():
    v = _validator(max_payload_age_seconds=10)
    ok, err = v.validate(
        {
            "agentId": "gabriel",
            "sessionKey": "agent:gabriel:main",
            "timestamp": time.time() - 120,
        }
    )
    assert ok is False
    assert err is not None
    assert err.result is ValidationResult.STALE_PAYLOAD


def test_hmac_off_skips_signature():
    v = _validator(hmac_secret=None)
    ok, _ = v.validate(
        {
            "agentId": "gabriel",
            "sessionKey": "agent:gabriel:main",
            "timestamp": time.time(),
        }
    )
    assert ok is True


def test_hmac_on_rejects_missing_signature():
    v = _validator(hmac_secret="s3cret")
    ok, err = v.validate(
        {
            "agentId": "gabriel",
            "sessionKey": "agent:gabriel:main",
            "timestamp": time.time(),
        }
    )
    assert ok is False
    assert err is not None
    assert err.result is ValidationResult.INVALID_SIGNATURE


def test_hmac_on_accepts_valid_signature():
    secret = "s3cret"
    payload = {
        "agentId": "gabriel",
        "sessionKey": "agent:gabriel:main",
        "timestamp": time.time(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["signature"] = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    v = _validator(hmac_secret=secret)
    ok, err = v.validate(payload)
    assert ok is True
    assert err is None
