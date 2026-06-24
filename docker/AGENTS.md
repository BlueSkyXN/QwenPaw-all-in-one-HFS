# docker navigation card

Runtime glue copied into the Hugging Face Docker Space image. Read this card before
editing entrypoint behavior, Nginx routing, Supervisor layout, health checks, or the
Python `/_ops` and `/_admin` services.
Key files: `entrypoint.sh`, `nginx.conf`, `supervisord.conf`, `ops_service.py`,
`admin_service.py`, `healthcheck.sh`, `qwenpaw.env.runtime`.

## Local invariants

- Public Nginx port: `7860`; internal QwenPaw: `127.0.0.1:8088`.
- ops-service: `127.0.0.1:8081`; admin-service: `127.0.0.1:8082`.
- Runtime state stays under `/data/qwenpaw/*`; logs under `/data/var/logs`; transient
  files under `/tmp/qwenpaw-run`.
- `/_ops` stays read-only; protected diagnostics require `OPS_TOKEN`; config output never
  returns secret values.
- `/_admin` stays disabled by default and only allows whitelisted actions with admin token,
  CSRF token, `confirm=true`, and audit logging.
- Nginx owns the only public port; route or port drift must update smoke and validation.

## Required before changes

- Check `hfs-dev.toml`, root docs, and `scripts/validate-hfs-contract.sh` for affected
  contract rules.
- If routes, ports, health semantics, env vars, or release pin reporting change, update
  validation and docs in the same patch.

## Do not

- Do not add request-supplied shell command execution to `/_ops` or `/_admin`.
- Do not log token values, provider keys, usernames, prompts, memory, or private file names.
- Do not remove `hmac.compare_digest` token checks or security headers.
- Do not make admin enabled by default or add broad restart/exec/file actions.

## Validation

Use root validation commands. Targeted checks:

```bash
bash -n docker/entrypoint.sh
bash -n docker/healthcheck.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile docker/ops_service.py docker/admin_service.py
```

Runtime behavior changes should also get Docker build/run/smoke when Docker and network
are available.
