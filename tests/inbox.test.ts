import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { InboxDrainer } from "../src/inbox";
import type { InboxRequestRouter } from "../src/inbox";
import type { RouteDecision } from "../src/router";
import { MarkdownState, parseQueuedRequests } from "../src/state";

test("parseQueuedRequests reads queued prompts in order", () => {
  const requests = parseQueuedRequests([
    "# Inbox",
    "",
    "## Queued Request",
    "",
    "Received: 2026-05-09 12:00",
    "",
    "User prompt:",
    "",
    "> First line",
    "> second line",
    "",
    "Reason:",
    "",
    "Locked.",
    "",
    "## Queued Request",
    "",
    "Received: 2026-05-09 12:05",
    "",
    "User prompt:",
    "",
    "> Second request",
    "",
    "Reason:",
    "",
    "Still locked.",
    "",
  ].join("\n"));

  assert.deepEqual(requests, [
    {
      prompt: "First line\nsecond line",
      reason: "Locked.",
      receivedAt: "2026-05-09 12:00",
    },
    {
      prompt: "Second request",
      reason: "Still locked.",
      receivedAt: "2026-05-09 12:05",
    },
  ]);
});

test("drain routes inbox requests and clears processed entries", async () => {
  await withRepo(async (root) => {
    const state = new MarkdownState(root);
    await state.appendInbox("First request", "PR lock.", "2026-05-09 12:00");
    await state.appendInbox("Second request", "PR lock.", "2026-05-09 12:05");

    const router = new StubRouter();
    const result = await new InboxDrainer(state, router).drain();

    assert.equal(result.action, "drained");
    assert.equal(router.inputs.length, 2);
    assert.deepEqual(router.inputs.map((input) => input.prompt), ["First request", "Second request"]);
    assert.deepEqual(router.inputs.map((input) => input.receivedAt), ["2026-05-09 12:00", "2026-05-09 12:05"]);
    assert.deepEqual(await state.readInboxRequests(), []);
    assert.equal(await readFile(state.inboxPath, "utf8"), "# Inbox\n\n");
  });
});

test("drain keeps inbox unchanged while PR lock exists", async () => {
  await withRepo(async (root) => {
    const state = new MarkdownState(root);
    await state.appendInbox("First request", "PR lock.", "2026-05-09 12:00");
    await state.setPrLock({
      branchName: "codex/current",
      prUrl: "https://github.com/example/repo/pull/7",
      reason: "Reviewing.",
    });

    const router = new StubRouter();
    const result = await new InboxDrainer(state, router).drain();

    assert.equal(result.action, "locked");
    assert.equal(router.inputs.length, 0);
    assert.match(await readFile(state.inboxPath, "utf8"), /> First request/);
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

class StubRouter implements InboxRequestRouter {
  readonly inputs: Array<{ prompt: string; receivedAt?: string }> = [];

  async route(prompt: string, options: { receivedAt?: string } = {}): Promise<RouteDecision> {
    this.inputs.push({ prompt, receivedAt: options.receivedAt });
    return {
      action: "create_new_plan",
      target: `.crack/plans/${this.inputs.length}/plan.md`,
      reason: "test",
    };
  }
}
