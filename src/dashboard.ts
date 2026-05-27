import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";

import type { GitStatusEntry, GitStatusSnapshot } from "./git";
import { GitCliCommitter } from "./git";
import type { PlanStatus } from "./plan-status";
import { parsePrLock } from "./pr-check";
import type { PrLock } from "./pr-check";
import type { MarkdownState, PlanRecord, QueuedRequest } from "./state";
import { parseQueuedRequests } from "./state";

export type DashboardSnapshot = {
  repoRoot: string;
  crackDir: string;
  initialized: boolean;
  inbox: DashboardRequestQueueSummary;
  prLock: DashboardPrLockSummary | null;
  plans: DashboardPlanSummary[];
  activePlans: DashboardPlanSummary[];
  completePlans: DashboardPlanSummary[];
  git: DashboardGitStatusSummary;
};

export type DashboardPlanSummary = {
  directory: string;
  planPath: string;
  queuePath: string;
  logPath: string;
  relativeDirectory: string;
  relativePlanPath: string;
  branchName: string;
  title: string;
  status: PlanStatus;
  statusReason: string;
  routingExclusionReason?: string;
  commitUnits: DashboardCommitUnitProgress;
  queuedRequestCount: number;
  recentLogEntries: DashboardLogEntry[];
  nextCommands: DashboardNextCommand[];
};

export type DashboardRequestQueueSummary = {
  path: string;
  count: number;
  requests: QueuedRequest[];
};

export type DashboardPrLockSummary =
  | (PrLock & {
      path: string;
      raw: string;
      valid: true;
    })
  | {
      path: string;
      raw: string;
      valid: false;
      branchName?: string;
      prUrl?: string;
      status?: string;
    };

export type DashboardCommitUnitProgress = {
  total: number;
  completed: number;
  remaining: number;
  completedNumbers: number[];
  next: DashboardCommitUnitSummary | null;
};

export type DashboardCommitUnitSummary = {
  number: number;
  title: string;
};

export type DashboardNextCommand = {
  kind: "run-next" | "run-all";
  command: string;
};

export type DashboardLogEntry = {
  loggedAt?: string;
  text: string;
};

export type DashboardGitStatusSummary = {
  raw: string;
  entries: GitStatusEntry[];
  isDirty: boolean;
  changedFileCount: number;
  stagedFileCount: number;
  unstagedFileCount: number;
  untrackedFileCount: number;
};

export interface GitStatusReader {
  status(): Promise<GitStatusSnapshot>;
}

export const DEFAULT_DASHBOARD_WATCH_INTERVAL_SECONDS = 2;
export const DASHBOARD_CLEAR_SCREEN = "\x1b[2J\x1b[H";

export type ReadDashboardSnapshotOptions = {
  gitStatusReader?: GitStatusReader;
};

export type DashboardRefreshOptions = ReadDashboardSnapshotOptions & {
  clearScreen?: boolean;
};

export type DashboardWatchOptions = DashboardRefreshOptions & {
  intervalSeconds?: number;
  write?: (output: string) => void;
};

export async function readDashboardSnapshot(
  state: MarkdownState,
  options: ReadDashboardSnapshotOptions = {},
): Promise<DashboardSnapshot> {
  const [inbox, prLock, plans, gitStatus] = await Promise.all([
    readRequestQueue(state.inboxPath),
    readPrLock(state.prLockPath),
    readPlans(state),
    (options.gitStatusReader ?? new GitCliCommitter(state.repoRoot)).status(),
  ]);

  const activePlans = plans.filter((plan) => plan.status === "active");
  const completePlans = plans.filter((plan) => plan.status === "complete");

  return {
    repoRoot: state.repoRoot,
    crackDir: state.crackDir,
    initialized: existsSync(state.crackDir),
    inbox,
    prLock,
    plans,
    activePlans,
    completePlans,
    git: summarizeGitStatus(gitStatus),
  };
}

export function parseDashboardWatchInterval(value: string | boolean | undefined): number {
  if (value === undefined) {
    return DEFAULT_DASHBOARD_WATCH_INTERVAL_SECONDS;
  }

  if (typeof value !== "string") {
    throw new Error("--interval requires a positive number of seconds");
  }

  const seconds = Number(value.trim());
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new Error("--interval must be a positive number of seconds");
  }

  return seconds;
}

export async function refreshDashboard(
  state: MarkdownState,
  write: (output: string) => void,
  options: DashboardRefreshOptions = {},
): Promise<string> {
  const { clearScreen = true, ...snapshotOptions } = options;
  const snapshot = await readDashboardSnapshot(state, snapshotOptions);
  const output = `${clearScreen ? DASHBOARD_CLEAR_SCREEN : ""}${renderDashboard(snapshot)}\n`;
  write(output);

  return output;
}

export async function watchDashboard(
  state: MarkdownState,
  options: DashboardWatchOptions = {},
): Promise<never> {
  const {
    intervalSeconds = DEFAULT_DASHBOARD_WATCH_INTERVAL_SECONDS,
    write = (output: string) => {
      process.stdout.write(output);
    },
    ...refreshOptions
  } = options;
  const delayMs = dashboardWatchDelayMs(intervalSeconds);

  await refreshDashboard(state, write, refreshOptions);

  return new Promise<never>((_resolve, reject) => {
    const timer = setInterval(() => {
      void refreshDashboard(state, write, refreshOptions).catch((error) => {
        clearInterval(timer);
        reject(error);
      });
    }, delayMs);
  });
}

export function renderDashboard(snapshot: DashboardSnapshot): string {
  const lines = [
    "Crack Dashboard",
    `Repo: ${snapshot.repoRoot}`,
    `State: ${snapshot.initialized ? "initialized" : ".crack not initialized"}`,
    `PR lock: ${formatPrLock(snapshot.prLock)}`,
    `Inbox: ${formatCount(snapshot.inbox.count, "request")}`,
    `Dirty files: ${formatGitStatus(snapshot.git)}`,
    "",
    "Active plans:",
  ];

  if (snapshot.activePlans.length === 0) {
    const message = snapshot.initialized
      ? "No active plans."
      : "No active plans because .crack is not initialized.";
    lines.push(`  ${message}`);
  } else {
    for (const plan of snapshot.activePlans) {
      lines.push(...formatPlanSummary(plan, { includeSuggestedCommand: true }));
    }
  }

  lines.push("", "Complete plans:");

  if (snapshot.completePlans.length === 0) {
    lines.push("  No complete plans.");
  } else {
    for (const plan of snapshot.completePlans) {
      lines.push(...formatPlanSummary(plan, { includeRoutingExclusion: true }));
    }
  }

  lines.push("", "Recent activity:");

  if (snapshot.plans.length === 0) {
    lines.push("  No recent activity.");
  } else {
    for (const plan of snapshot.plans) {
      lines.push(`- ${plan.title}`);

      if (plan.recentLogEntries.length === 0) {
        lines.push("  No recent activity.");
        continue;
      }

      for (const entry of plan.recentLogEntries.slice(-3)) {
        lines.push(`  - ${formatLogEntry(entry)}`);
      }
    }
  }

  return lines.join("\n");
}

async function readRequestQueue(queuePath: string): Promise<DashboardRequestQueueSummary> {
  const content = await readTextIfExists(queuePath);
  const requests = parseQueuedRequests(content);

  return {
    path: queuePath,
    count: requests.length,
    requests,
  };
}

async function readPrLock(lockPath: string): Promise<DashboardPrLockSummary | null> {
  if (!existsSync(lockPath)) {
    return null;
  }

  const raw = await readFile(lockPath, "utf8");
  const parsed = parsePrLock(raw);
  if (!parsed) {
    return {
      path: lockPath,
      raw,
      valid: false,
    };
  }

  return {
    ...parsed,
    path: lockPath,
    raw,
    valid: true,
  };
}

async function readPlans(state: MarkdownState): Promise<DashboardPlanSummary[]> {
  const plans = await state.listPlanRecords({ initialize: false });
  return plans.map((plan) => summarizePlan(state.repoRoot, plan));
}

function summarizePlan(repoRoot: string, plan: PlanRecord): DashboardPlanSummary {
  const relativePlanPath = relativePath(repoRoot, plan.plan);
  const progress = plan.statusSummary.progress;

  return {
    directory: plan.directory,
    planPath: plan.plan,
    queuePath: plan.queue,
    logPath: plan.log,
    relativeDirectory: relativePath(repoRoot, plan.directory),
    relativePlanPath,
    branchName: plan.branchName,
    title: titleFromPlan(plan.planContent) ?? path.basename(plan.directory),
    status: plan.status,
    statusReason: plan.statusSummary.reason,
    routingExclusionReason: plan.statusSummary.routing.exclusionReason,
    commitUnits: {
      total: progress.total,
      completed: progress.completed,
      remaining: progress.remaining,
      completedNumbers: progress.completedNumbers,
      next: progress.next,
    },
    queuedRequestCount: parseQueuedRequests(plan.queueContent).length,
    recentLogEntries: recentLogEntries(plan.logContent),
    nextCommands: progress.remaining > 0 ? nextCommands(relativePlanPath) : [],
  };
}

function summarizeGitStatus(status: GitStatusSnapshot): DashboardGitStatusSummary {
  let stagedFileCount = 0;
  let unstagedFileCount = 0;
  let untrackedFileCount = 0;

  for (const entry of status.entries) {
    if (entry.status === "??") {
      untrackedFileCount += 1;
      continue;
    }

    if (entry.status[0] && entry.status[0] !== " ") {
      stagedFileCount += 1;
    }

    if (entry.status[1] && entry.status[1] !== " ") {
      unstagedFileCount += 1;
    }
  }

  return {
    raw: status.raw,
    entries: status.entries,
    isDirty: status.entries.length > 0,
    changedFileCount: status.entries.length,
    stagedFileCount,
    unstagedFileCount,
    untrackedFileCount,
  };
}

async function readTextIfExists(filePath: string): Promise<string> {
  if (!existsSync(filePath)) {
    return "";
  }

  return readFile(filePath, "utf8");
}

function nextCommands(planPath: string): DashboardNextCommand[] {
  const planArg = shellQuote(planPath);

  return [
    {
      kind: "run-next",
      command: `crack run-next --plan ${planArg}`,
    },
    {
      kind: "run-all",
      command: `crack run-all --plan ${planArg}`,
    },
  ];
}

function recentLogEntries(logContent: string, limit = 3): DashboardLogEntry[] {
  const entries: DashboardLogEntry[] = [];
  let loggedAt: string | undefined;

  for (const line of logContent.split(/\r?\n/)) {
    const heading = line.match(/^##\s+(.+?)\s*$/);
    if (heading) {
      loggedAt = heading[1].trim();
      continue;
    }

    const bullet = line.match(/^-\s+(.+?)\s*$/);
    if (bullet) {
      entries.push({ loggedAt, text: bullet[1].trim() });
    }
  }

  return entries.slice(-limit);
}

function titleFromPlan(content: string): string | undefined {
  return content.match(/^#\s+Plan:\s*(.+)\s*$/m)?.[1]?.trim() || undefined;
}

function relativePath(repoRoot: string, filePath: string): string {
  return path.relative(repoRoot, filePath).split(path.sep).join("/");
}

function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_./:-]+$/.test(value)) {
    return value;
  }

  return `'${value.replace(/'/g, "'\\''")}'`;
}

function formatPrLock(lock: DashboardPrLockSummary | null): string {
  if (!lock) {
    return "none";
  }

  if (!lock.valid) {
    return `invalid (${lock.path})`;
  }

  const parts = [`branch ${lock.branchName}`];
  if (lock.status) {
    parts.push(`status ${lock.status}`);
  }
  parts.push(lock.prUrl);

  return `active - ${parts.join(", ")}`;
}

function formatGitStatus(git: DashboardGitStatusSummary): string {
  if (!git.isDirty) {
    return "0";
  }

  return [
    `${git.changedFileCount}`,
    `(staged ${git.stagedFileCount}, unstaged ${git.unstagedFileCount}, untracked ${git.untrackedFileCount})`,
  ].join(" ");
}

function formatNextCommitUnit(unit: DashboardCommitUnitSummary | null): string {
  if (!unit) {
    return "none";
  }

  return `Commit ${unit.number} - ${unit.title}`;
}

function formatSuggestedCommand(plan: DashboardPlanSummary): string {
  return plan.nextCommands.find((command) => command.kind === "run-all")?.command
    ?? plan.nextCommands[0]?.command
    ?? "none";
}

function formatPlanSummary(
  plan: DashboardPlanSummary,
  options: { includeSuggestedCommand?: boolean; includeRoutingExclusion?: boolean } = {},
): string[] {
  const lines = [
    `- ${plan.title}`,
    `  Branch: ${plan.branchName}`,
    `  Progress: ${plan.commitUnits.completed}/${plan.commitUnits.total} completed`,
    `  Next: ${formatNextCommitUnit(plan.commitUnits.next)}`,
    `  Queued requests: ${formatCount(plan.queuedRequestCount, "request")}`,
  ];

  if (options.includeSuggestedCommand) {
    lines.push(`  Suggested command: ${formatSuggestedCommand(plan)}`);
  }

  if (options.includeRoutingExclusion && plan.routingExclusionReason) {
    lines.push(`  Routing: ${plan.routingExclusionReason}`);
  }

  return lines;
}

function formatLogEntry(entry: DashboardLogEntry): string {
  return entry.loggedAt ? `[${entry.loggedAt}] ${entry.text}` : entry.text;
}

function formatCount(count: number, label: string): string {
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}

function dashboardWatchDelayMs(intervalSeconds: number): number {
  if (!Number.isFinite(intervalSeconds) || intervalSeconds <= 0) {
    throw new Error("--interval must be a positive number of seconds");
  }

  return Math.max(1, Math.round(intervalSeconds * 1000));
}
