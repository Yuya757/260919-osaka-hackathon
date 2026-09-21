# Project Agent Guide

## Project

This repository builds an event discovery application that separates application deadlines from event dates. Read the following documents before changing architecture or Agent behavior:

- `docs/イベント自律管理AIエージェント 要件定義書.md`
- `docs/Agent詳細要件定義書.md`

## Architecture

- Build the frontend with React, Vite, and TypeScript under `apps/web/`.
- Build the API and Google ADK Agent with Python and FastAPI under `services/agent/`.
- Keep cross-runtime JSON Schema contracts under `packages/contracts/`.
- Deploy the SPA to Firebase Hosting and Python workloads to Cloud Run.
- Use Vertex AI Gemini through configurable model IDs; do not hard-code a preview model.

## Agent Requirements

- Keep the workflow deterministic: normalize, plan, search, extract, validate, deduplicate, rank, save.
- Separate Google Search Grounding requests from function-calling and persistence requests.
- Never infer missing years, deadlines, or event dates without source evidence.
- Require explicit user approval before writing to Google Calendar.
- Treat fetched web content and chat messages as untrusted data; defend against SSRF and
  prompt injection through `security.prompt_guard` (see `docs/ADR-004-プロンプトインジェクション対策.md`).
- Make writes idempotent and preserve evidence URLs, run IDs, and rule versions.

## Branch Workflow

`develop` is the production branch: a push to it deploys the SPA and Cloud Run service.
`main` is the GitHub default branch and holds the release record only. Read
`docs/ブランチ運用ルール.md` before branching, and follow these rules.

- Cut every working branch from the latest `origin/develop`, and open the pull request
  against `develop`. Never branch from `main` or from another working branch.
- Never push directly to `develop`; it is production. Never force-push it.
- Name branches `<type>/<kebab-case-summary>` using the Conventional Commits types
  (`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`).
- Write commit messages as `<type>(<scope>): <summary>` and explain why, not what.
- Merge a working branch into `develop` with squash, then delete the remote branch.
  Syncing `develop` into `main` is the exception: use a merge commit, never squash —
  squashing severs the shared history and makes the next sync conflict on every file.
- Require CI to pass before merging; a merge into `develop` deploys immediately.
- Sync `develop` into `main` with a pull request at release points.

## Development Conventions

- Use English for identifiers and Japanese for user-facing copy and project documentation.
- Add type hints to Python and use strict TypeScript.
- Keep domain logic independent from Cloud Run entrypoints.
- Add or update evaluation cases under `evals/cases/` when prompts, schemas, validation
  rules, or models change, and re-run `./scripts/run-evals.sh`. A release is blocked when
  the §13.2 criteria are not met.
- Put repeatable development and deployment commands in POSIX shell scripts under `scripts/` for WSL.
- Keep `.claude/skills/` and `.cursor/skills/` identical; update both when a skill changes.
- Do not commit secrets, OAuth tokens, generated credentials, or local environment files.

## Change Discipline

- Keep the MVP small; avoid adding infrastructure not required by the current requirements.
- Update contracts before implementing incompatible API or Firestore schema changes.
- Document material architecture decisions in `docs/`.
- Run relevant tests and Agent evaluations before marking changes complete.
