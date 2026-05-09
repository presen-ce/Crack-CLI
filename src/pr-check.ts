import { InboxDrainer } from "./inbox";
import type { DrainInboxResult } from "./inbox";
import { runProcess } from "./process";
import type { MarkdownState } from "./state";

export type PrLock = {
  branchName: string;
  prUrl: string;
  status: string;
};

export type PullRequestReviewState = "open" | "closed" | "merged";

export type PullRequestReviewStatus = {
  state: PullRequestReviewState;
  prUrl: string;
  title?: string;
  mergedAt?: string;
};

export interface PullRequestStatusChecker {
  check(prUrl: string): Promise<PullRequestReviewStatus>;
}

export type PrCheckResult =
  | {
      action: "no_lock";
      lockPath: string;
    }
  | {
      action: "reviewing";
      lockPath: string;
      branchName: string;
      prUrl: string;
      state: "open" | "closed";
    }
  | {
      action: "merged";
      lockPath: string;
      branchName: string;
      prUrl: string;
      drain: DrainInboxResult;
    };

type GhPullRequestView = {
  state?: string;
  mergedAt?: string;
  title?: string;
  url?: string;
};

export class GitHubCliPullRequestStatusChecker implements PullRequestStatusChecker {
  constructor(
    private readonly repoRoot: string,
    private readonly command = "gh",
  ) {}

  async check(prUrl: string): Promise<PullRequestReviewStatus> {
    const result = await runProcess(
      this.command,
      ["pr", "view", prUrl, "--json", "state,mergedAt,title,url"],
      { cwd: this.repoRoot },
    );

    if (result.status !== 0) {
      const details = result.stderr.trim() || result.stdout.trim();
      const suffix = details ? `: ${details}` : "";
      throw new Error(`Failed to check PR status${suffix}`);
    }

    return parsePullRequestReviewStatus(result.stdout, prUrl);
  }
}

export class PrCheckRunner {
  private readonly state: MarkdownState;
  private readonly checker: PullRequestStatusChecker;
  private readonly drainer: InboxDrainer;

  constructor(
    state: MarkdownState,
    checker: PullRequestStatusChecker = new GitHubCliPullRequestStatusChecker(state.repoRoot),
    drainer: InboxDrainer = new InboxDrainer(state),
  ) {
    this.state = state;
    this.checker = checker;
    this.drainer = drainer;
  }

  async check(): Promise<PrCheckResult> {
    const lockContent = await this.state.readPrLock();
    if (!lockContent) {
      return { action: "no_lock", lockPath: this.state.prLockPath };
    }

    const lock = parsePrLock(lockContent);
    if (!lock) {
      throw new Error(`Invalid PR lock: ${this.state.prLockPath}`);
    }

    const status = await this.checker.check(lock.prUrl);
    if (status.state !== "merged") {
      return {
        action: "reviewing",
        lockPath: this.state.prLockPath,
        branchName: lock.branchName,
        prUrl: lock.prUrl,
        state: status.state,
      };
    }

    await this.state.clearPrLock();
    const drain = await this.drainer.drain();

    return {
      action: "merged",
      lockPath: this.state.prLockPath,
      branchName: lock.branchName,
      prUrl: lock.prUrl,
      drain,
    };
  }
}

export function parsePrLock(content: string): PrLock | null {
  const branchName = matchLine(content, /^Branch:\s*(.+)\s*$/m);
  const prUrl = matchLine(content, /^PR:\s*(.+)\s*$/m);
  const status = matchLine(content, /^Status:\s*(.+)\s*$/m) ?? "";

  if (!branchName || !prUrl) {
    return null;
  }

  return { branchName, prUrl, status };
}

export function parsePullRequestReviewStatus(output: string, fallbackUrl: string): PullRequestReviewStatus {
  const data = parseGhPullRequestView(output);
  const state = normalizePullRequestState(data);

  return {
    state,
    prUrl: data.url || fallbackUrl,
    title: data.title,
    mergedAt: data.mergedAt,
  };
}

function parseGhPullRequestView(output: string): GhPullRequestView {
  try {
    const value = JSON.parse(output) as GhPullRequestView;
    return value && typeof value === "object" ? value : {};
  } catch {
    throw new Error(`Failed to parse PR status JSON: ${output.trim()}`);
  }
}

function normalizePullRequestState(data: GhPullRequestView): PullRequestReviewState {
  const state = (data.state ?? "").toUpperCase();
  if (state === "MERGED" || data.mergedAt) {
    return "merged";
  }

  if (state === "CLOSED") {
    return "closed";
  }

  return "open";
}

function matchLine(content: string, pattern: RegExp): string | undefined {
  return content.match(pattern)?.[1]?.trim();
}
