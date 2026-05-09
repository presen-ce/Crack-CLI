import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { InboxDrainer } from "../src/inbox";
import type { InboxRequestRouter } from "../src/inbox";
import {
  PrCheckRunner,
  parsePrLock,
  parsePullRequestReviewStatus,
} from "../src/pr-check";
import type { PullRequestReviewStatus, PullRequestStatusChecker } from "../src/pr-check";
import type { RouteDecision } from "../src/router";
import { MarkdownState } from "../src/state";

test("parsePrLock reads the branch and PR URL", () => {
  assert.deepEqual(
    parsePrLock([
      "# PR Lock",
      "",
      "Branch: codex/current",
      "PR: https://github.com/example/repo/pull/7",
      "Status: reviewing",
      "",
    ].join("\n")),
    {
      branchName: "codex/current",
      prUrl: "https://github.com/example/repo/pull/7",
      status: "reviewing",
    },
  );
});

test("parsePullRequestReviewStatus treats mergedAt as merged", () => {
  assert.deepEqual(
    parsePullRequestReviewStatus(
      JSON.stringify({
        state: "CLOSED",
        mergedAt: "2026-05-09T03:00:00Z",
        title: "Current",
        url: "https://github.com/example/repo/pull/7",
      }),
      "fallback",
    ),
    {
      state: "merged",
      prUrl: "https://github.com/example/repo/pull/7",
      title: "Current",
      mergedAt: "2026-05-09T03:00:00Z",
    },
  );
});

test("pr check keeps the lock while the PR is still open", async () => {
  await withRepo(async (root) => {
    const state = new MarkdownState(root);
    await state.setPrLock({
      branchName: "codex/current",
      prUrl: "https://github.com/example/repo/pull/7",
      reason: "Reviewing.",
    });

    const checker = new StubChecker({ state: "open", prUrl: "https://github.com/example/repo/pull/7" });
    const result = await new PrCheckRunner(state, checker).check();

    assert.deepEqual(result, {
      action: "reviewing",
      lockPath: state.prLockPath,
      branchName: "codex/current",
      prUrl: "https://github.com/example/repo/pull/7",
      state: "open",
    });
    assert.equal(checker.urls[0], "https://github.com/example/repo/pull/7");
    assert.notEqual(await state.readPrLock(), null);
  });
});

test("pr check clears a merged lock and drains queued inbox requests", async () => {
  await withRepo(async (root) => {
    const state = new MarkdownState(root);
    await state.appendInbox("Next request", "PR lock.", "2026-05-09 12:00");
    await state.setPrLock({
      branchName: "codex/current",
      prUrl: "https://github.com/example/repo/pull/7",
      reason: "Reviewing.",
    });

    const router = new StubRouter();
    const checker = new StubChecker({ state: "merged", prUrl: "https://github.com/example/repo/pull/7" });
    const result = await new PrCheckRunner(state, checker, new InboxDrainer(state, router)).check();

    assert.equal(result.action, "merged");
    assert.equal(await state.readPrLock(), null);
    assert.deepEqual(router.inputs.map((input) => input.prompt), ["Next request"]);
    assert.deepEqual(await state.readInboxRequests(), []);
  });
});

async function withRepo(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(path.join(tmpdir(), "crack-"));

  try {
    await mkdir(path.join(root, ".git"));
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

class StubChecker implements PullRequestStatusChecker {
  readonly urls: string[] = [];

  constructor(private readonly status: PullRequestReviewStatus) {}

  async check(prUrl: string): Promise<PullRequestReviewStatus> {
    this.urls.push(prUrl);
    return this.status;
  }
}

class StubRouter implements InboxRequestRouter {
  readonly inputs: Array<{ prompt: string; receivedAt?: string }> = [];

  async route(prompt: string, options: { receivedAt?: string } = {}): Promise<RouteDecision> {
    this.inputs.push({ prompt, receivedAt: options.receivedAt });
    return {
      action: "create_new_plan",
      target: ".crack/plans/next/plan.md",
      reason: "test",
    };
  }
}
