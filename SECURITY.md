# Security notes

This library validates session identity and exposes file/exec tools to an agent loop. Treat those surfaces as production.

## Identity

- Accepts `agentId`/`sessionKey` or `agent_id`/`session_key`.
- Timestamps: unix seconds (int/float/numeric string) or ISO-8601. Unparseable values return `INVALID_TIMESTAMP` — they must not raise.
- HMAC, when configured, is computed over the payload keys as sent (canonical JSON). Mixing key styles in a signed payload will fail verification.

## Circuit breaker state

- Default path is `$XDG_STATE_HOME/lar/circuit_<agent>.json` (or `~/.local/state/lar/`).
- Never defaults to `/tmp`. Agent ids are sanitized for the filename.
- Writes are flocked and atomic (`tmp` + `os.replace`), mode `0o600`.

## File tools

- Paths are resolved and must stay inside `base_path` (`Path.relative_to`).
- Absolute paths, `../` prefix siblings, and out-of-base symlinks are denied.

## Exec tool

- Default allowlist is read-only inspection (`ls`, `cat`, `echo`, …).
- Interpreters (`python`, `node`), `git`, `npm`, and `curl` are **not** default-allowed.
- Commands are parsed with `shlex` and run with `shell=False`. Metacharacters (`;|&`$()<>`) are rejected.

## Reporting

Open an issue at https://github.com/smfworks/lar-agent-resilience/issues. Do not file exploit PoCs against live agents.
