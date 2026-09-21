---
name: branch-workflow
description: Branch, commit, and pull request procedure for this repository, where `develop` is the production branch and `main` only records releases. Use before starting any code or documentation change, when creating a branch or pull request, when asked where to merge, or when tempted to push to develop.
---

# Branch Workflow

Full rules: `docs/ブランチ運用ルール.md`. Summary: `AGENTS.md` の Branch Workflow.

## The one fact that drives everything

`develop` is production. A push to it deploys to Firebase Hosting and Cloud Run through
`.github/workflows/deploy-develop.yml`. `main` is the GitHub default branch but nothing
deploys from it; it is the release record.

So: branch from `develop`, and open the pull request against `develop`. Never push to
`develop` directly, and never force-push it.

## Starting work

```bash
git switch develop
git pull --ff-only origin develop
git switch -c <type>/<kebab-case-summary>
```

`<type>` is a Conventional Commits type: `feat`, `fix`, `docs`, `test`, `refactor`,
`chore`, `ci`. The summary is lowercase English kebab-case, three to five words.

Never branch from `main`, and never branch from another working branch. If work depends
on an unmerged branch, merge that branch into `develop` first.

## While working

- One concern per commit; do not mix refactoring with behavior changes.
- Message format `<type>(<scope>): <summary>`, scope matching the directory (`agent`,
  `web`, `contracts`, `evals`, `infra`, `docs`).
- The body explains why. Do not restate the diff.
- Never commit secrets, OAuth tokens, `.env` files, or generated credentials.

## Opening the pull request

```bash
git push -u origin <branch>
gh pr create --base develop
```

Use `gh`, not the GitHub MCP tools — the MCP session has been unreliable in this repo.

State in the description what changed, why, and how it was verified. When the change
touches Agent behavior, prompts, schemas, validation rules, or the model, add or update
cases under `evals/cases/`, run `./scripts/run-evals.sh`, and report the result (§13.3).

## Merging

Squash and merge a working branch, then delete the remote branch:

```bash
gh pr merge --squash --delete-branch
```

Syncing `develop` into `main` is the one exception: merge it, never squash. A
squash replaces the commits with a new one, which severs the shared history and
makes every later sync conflict on every file that changed on both sides.

The merge deploys. Check the run afterwards:

```bash
gh run list --branch develop --limit 1
```

## Releases and incidents

Sync into the record branch with a pull request: `gh pr create --base main --head develop`.

If production is broken, still use a `fix/` branch and a pull request. CI takes about
three minutes, which is cheaper than stacking a bad change onto a broken deploy. Roll back
with `git revert` through a pull request, never with a force push.
