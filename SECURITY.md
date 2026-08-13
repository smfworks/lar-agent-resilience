# Security Policy

## Supported versions

This repository tracks `main`. Report issues against the latest published commit of `agent-resilience`.

## Reporting a vulnerability

Email **michael@smfworks.com** with:

- a description of the issue
- affected module (exec, web_fetch, file tools, identity, checkpoint)
- reproduction steps that do **not** include exploit payloads against third-party systems

Please do not open a public issue for unfixed RCE, SSRF, or auth-bypass reports.

## Known attack surface

This library can execute local programs and fetch URLs when those tools are registered.

| Tool | Intended use | Hardening |
|---|---|---|
| `exec` | Allowlisted argv only | `shell=False`; no `;` `\|` `&` backticks; default allowlist excludes `python`, `git`, `curl`, `node` |
| `web_fetch` | Public HTTPS pages | https only; `file://` denied; loopback / private / link-local / metadata hosts denied |
| `file_read` / `file_write` | Workspace files | Path jail uses resolved `relative_to`, not string prefix |
| Identity HMAC | Optional payload auth | Empty `HMAC_SECRET` disables signatures. Enable a real secret if you validate untrusted payloads |

Do not bind optional dashboards to `0.0.0.0` without authentication. Observatory/TUI are not shipped in 0.2.0.

## Disclosure contact

Michael Gannotti / SMF Works — michael@smfworks.com
