# Security Policy

## Supported versions

`0.2.x` on `main` is the supported line.

## Reporting a vulnerability

Email **michael@smfworks.com**. Do not open a public issue for credential leaks or exploitable tool-execution bugs.

## Trust model

LAR is a **local** runtime. It is not a hosted control plane.

- **Identity:** incoming payloads must carry agent id, session key, and a fresh timestamp. HMAC is optional and off unless `identity.hmac_secret` is set.
- **Tools:** `exec` and file tools are dangerous. Restrict `allowed_commands` and `base_path` in config. Default file write should not overwrite unless explicitly enabled.
- **Secrets:** never commit `.env`, HMAC secrets, or API keys. `config.example.yaml` uses `${VAR:}` substitution — keep real values in the environment.
- **State:** circuit-breaker and checkpoint files contain operational history. Treat `~/.local/state/lar/` and checkpoint DBs as sensitive logs.
- **Models:** fallbacks are local/Ollama-oriented. Do not put cloud API keys in YAML; use env substitution.

## Known limitations

- Observatory / TUI are operator visibility, not an auth boundary.
- Built-in `web_search` / `web_fetch` / `exec` talk to the network or shell when invoked. Run LAR only on hosts you control.
