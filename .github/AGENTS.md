# .github navigation card

This directory contains GitHub Actions workflow configuration. Read this card before
modifying workflow triggers, jobs, permissions, or validation commands.
Key files: `workflows/static-check.yml`, `workflows/build-console-bundle.yml`,
`workflows/deploy-hf-space.yml`.

## Why this is high-risk

- CI is the public regression gate for this HFS package.
- Weakening the workflow can let broken Docker Space contracts reach `main`.
- Workflow changes may run with GitHub-provided permissions and public logs.

## Local invariants

- The static-check workflow must run `bash scripts/static-check.sh` for pushes to `main`
  and pull requests unless the validation strategy is intentionally changed.
- CI should remain a no-secret static gate. It must not require Hugging Face tokens,
  provider API keys, Docker Hub credentials, or local `.env.local` values.
- Keep workflow logs free of real tokens, Space secrets, browser session data, and private
  deployment records.
- The manual console-bundle workflow must validate an immutable upstream source SHA and
  version before uploading the short-lived build artifact. Publishing that artifact as a
  release asset remains an explicit maintainer action.
- The manual candidate deploy workflow must bind its input to `GITHUB_SHA` and current
  `origin/main`, use the `hfs-candidate` environment, target only the fixed private candidate,
  upload only the verified exporter allowlist, and read back the exact path/checksum set.
- Candidate repo upload is not runtime takeover or smoke evidence. The deploy workflow must
  not sync Settings, change volumes/visibility, restart lifecycle state, or delete remote files.

## Required before changes

- Check `scripts/static-check.sh` before changing workflow commands.
- If adding a new CI command, confirm it works without Docker, network credentials, sudo,
  interactive prompts, or private local files.
- If changing branch filters or triggers, mention the coverage change in the final report.

## Do not

- Do not add deployment or remote-push steps unless the user explicitly requested release
  automation.
- Do not echo secrets or load `.env.local` in CI.
- Do not skip repository checkout or the static validation gate.
- Do not expose `HF_TOKEN` outside the remote preflight/upload/readback steps, and bind it only
  from the GitHub environment Secret.

## Validation

Use root validation commands. For workflow edits, also inspect YAML structure manually; this
repository does not currently define a separate YAML linter.
