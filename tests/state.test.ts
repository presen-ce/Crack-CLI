import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { MarkdownState } from "../src/state";

test("listPlanRecords classifies incomplete plans as active", async () => {
  await withRepo(async (root) => {
    const state = new MarkdownState(root);
    const plan = await state.createPlan({
      branchName: "codex/current",
      planTitle: "Current",
      prompt: "Initial request",
      reason: "test setup",
    });
    await writePlan(plan.plan);
    await writeFile(plan.log, "# Log\n\n- Completed commit unit 1.\n", "utf8");

    const records = await state.listPlanRecords();
    assert.equal(records.length, 1);
    assert.equal(records[0].status, "active");
    assert.equal(records[0].statusSummary.progress.completed, 1);
    assert.equal(records[0].statusSummary.progress.remaining, 1);
    assert.equal(records[0].statusSummary.progress.next?.number, 2);
    assert.equal(records[0].statusSummary.routing.routeToExistingPlanCandidate, true);
  });
});

test("listPlanRecords classifies completed plans as complete and excludes them from routing", async () => {
  await withRepo(async (root) => {
    const state = new MarkdownState(root);
    const plan = await state.createPlan({
      branchName: "codex/current",
      planTitle: "Current",
      prompt: "Initial request",
      reason: "test setup",
    });
    await writePlan(plan.plan);
    await writeFile(
      plan.log,
      [
        "# Log",
        "",
        "- Completed commit unit 1.",
        "- Completed commit unit 2.",
        "",
      ].join("\n"),
      "utf8",
    );

    const records = await state.listPlanRecords();
    const routablePlans = await state.listRoutablePlans();
    assert.equal(records.length, 1);
    assert.equal(records[0].status, "complete");
    assert.equal(records[0].statusSummary.progress.completed, 2);
    assert.equal(records[0].statusSummary.progress.remaining, 0);
    assert.equal(records[0].statusSummary.routing.routeToExistingPlanCandidate, false);
    assert.match(records[0].statusSummary.routing.exclusionReason ?? "", /excluded from default existing-plan routing/);
    assert.deepEqual(routablePlans, []);
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

async function writePlan(planPath: string): Promise<void> {
  await writeFile(
    planPath,
    [
      "# Plan: Current",
      "",
      "Branch: codex/current",
      "",
      "## Commit Units",
      "",
      "### Commit 1: Add model",
      "",
      "Create the model.",
      "",
      "### Commit 2: Wire command",
      "",
      "Add the command.",
      "",
    ].join("\n"),
    "utf8",
  );
}
