---
name: crack-cli
description: "Use when operating the Crack CLI workflow orchestrator in a repository: initialize state, submit or route requests, run commit units, inspect dashboards, open or merge pull requests, manage PR locks, check PR status, or drain inbox queues."
metadata:
  short-description: Operate the Crack CLI workflow
---

# Crack CLI

## Purpose

Use this skill to operate Crack, a repository-local CLI orchestrator for Codex workflows. Crack stores workflow state in Markdown under `.crack/`, routes user requests into plans, runs plan commit units through Codex CLI sessions, and optionally opens or merges GitHub pull requests.

## Preconditions

- Work inside the target git repository, or pass `--root <path>` to every `crack` command.
- Prefer the installed `crack` binary. If unavailable in this repo, run `npm run build` and use `node dist/src/cli.js` in place of `crack`.
- `submit`, `route`, `run-next`, `run-all`, and merge conflict resolution require the `codex` CLI.
- Remote PR operations require the `gh` CLI to be authenticated.
- Before `run-next`, `run-all`, or `merge`, check `git status --short`; these commands expect a clean working tree.

## State Model

Crack uses `.crack/` as the source of truth:

```text
.crack/
  inbox.md
  pr-lock.md
  plans/
    <plan-name>/
      plan.md
      queue.md
      log.md
```

`plan.md` contains readable commit units named like `### Commit 1: ...`. `log.md` records completed units using `Completed commit unit N`. Crack compares those two files to classify each plan as `active` when commit units remain incomplete, or `complete` when all commit units are completed. `queue.md` holds follow-up requests for that plan. `inbox.md` holds requests paused by an active PR lock.

Complete plans stay visible in `crack dashboard`, but they are not default `route_to_existing_plan` candidates. Router context should contain active incomplete plans as candidates; completed plans may appear only as conservative diagnostics such as "excluded from routing because complete." Do not treat this as dependency scheduling or automatic parallelization.

## Core Workflow

1. Initialize if needed:

   ```bash
   crack init
   ```

2. Submit the user request:

   ```bash
   crack submit "..."
   ```

   If a PR lock exists, the request goes to `.crack/inbox.md`. If `--plan <path>` is provided, the request goes to that plan's `queue.md`. Otherwise Crack routes to an active incomplete plan or creates a new plan and branch.

3. When submitting multiple requests, submit them sequentially:

   ```bash
   crack submit "first request"
   crack dashboard
   crack submit "second request"
   crack dashboard
   ```

   Do not run multiple `crack submit` or `crack route` commands in parallel. Each submit updates `.crack/plans/`, `queue.md`, and active branch state; the next submit must see those updates so the Router can decide whether the new request depends on an existing plan or should become a new plan. If the user provides a batch of requests, process one request at a time and inspect the result before submitting the next.

4. Inspect state:

   ```bash
   crack dashboard
   crack dashboard --watch
   ```

5. Run implementation:

   ```bash
   crack run-next --plan .crack/plans/<plan>/plan.md
   crack run-all --plan .crack/plans/<plan>/plan.md
   ```

   `run-next` implements one pending commit unit. `run-all` repeats until the plan is complete or a unit returns `needs_work`.

6. Keep completed work local by default, or explicitly use remote mode:

   ```bash
   crack run-all --plan .crack/plans/<plan>/plan.md --remote
   crack open-pr --plan .crack/plans/<plan>/plan.md
   ```

   `run-next` and `run-all` default to local branch completion. `open-pr` defaults to remote mode and creates a draft PR when the plan is ready.

7. Merge when appropriate:

   ```bash
   crack merge --plan .crack/plans/<plan>/plan.md
   crack merge --plan .crack/plans/<plan>/plan.md --target release
   crack merge --plan .crack/plans/<plan>/plan.md --remote
   ```

   `merge` defaults to local mode and target `main`. Remote mode pushes the source branch, ensures a ready PR, and merges it with `gh pr merge --merge`.

## Command Reference

- `crack init`: create `.crack/` state files without overwriting an existing inbox.
- `crack submit <prompt>` or `crack route <prompt>`: route a request. Options: `--plan <path>`, `--branch <name>`, `--title <title>`, `--reason <text>`.
- `crack dashboard [--watch] [--interval <seconds>]`: read-only state view. `--interval` only works with `--watch`.
- `crack run-next [--plan <path>] [--branch-mode local|remote] [--remote]`: run the next commit unit and commit produced changes.
- `crack run-all [--plan <path>] [--branch-mode local|remote] [--remote]`: run all remaining units, stopping on `needs_work`.
- `crack open-pr [--plan <path>] [--branch-mode local|remote] [--remote]`: open the PR stage; default branch mode is `remote`.
- `crack merge [--plan <path>] [--target <branch>] [--branch-mode local|remote] [--remote]`: merge a complete plan branch; default target is `main`.
- `crack pr-check`: inspect the active PR lock. If the PR is merged, clear the lock and drain inbox requests.
- `crack drain`: reroute queued inbox requests when no PR lock is active.
- `crack set-pr-lock --branch <name> --pr-url <url> --reason <text> [--status <status>]`: create a manual PR lock.
- `crack clear-pr-lock`: remove the active PR lock.

All commands accept `--root <path>`.

## Operating Rules

- Use `--plan` whenever more than one active incomplete plan exists.
- For multiple new requests, never submit or route them concurrently. Submit one request, let Crack finish creating or queuing the plan, then inspect `crack dashboard` before submitting the next request.
- Treat `submit` and `route` as state-mutating operations. They must be serialized so Router decisions are based on the latest active incomplete plans and queues.
- Do not run multiple `run-all` commands in the same worktree at the same time. Current local execution shares one checkout and one `.git/index`; parallel runs can race on `git switch`, `git add`, and branch state. Run them one at a time unless the workflow has explicit per-plan worktree isolation.
- Do not use `--remote` unless the user wants a pushed branch, PR, or remote merge.
- If `run-next`, `run-all`, or `merge` reports `needs_work`, stop and report the reason. Do not keep retrying blindly.
- If `pr-check` reports a PR is still open or closed but not merged, keep the lock and leave inbox requests queued.
- After manually clearing a lock, run `crack drain` only if the user wants queued inbox requests routed now.
- Treat `.crack/plan.md`, `queue.md`, `log.md`, and `inbox.md` as user-readable state. Preserve readability and avoid unnecessary manual edits.

## Useful Outputs

Common successful outputs include:

```text
create_new_plan: .crack/plans/<name>/plan.md
route_to_existing_plan: .crack/plans/<name>/queue.md
pause_for_pr_review: .crack/inbox.md
committed unit 1: <hash> <message>
local_branch: codex/<name>; Plan is complete on a local branch; remote PR was not opened.
opened_pr: https://github.com/example/repo/pull/123 (Title)
merged_local: codex/<name> -> main
merged_remote: https://github.com/example/repo/pull/123
```

Problem outputs include:

```text
needs_work unit N: <reason>
pr_locked: <reason>
pr_not_ready: <reason>
merge_needs_work: <reason>
drain: locked with N request(s) remaining
```
