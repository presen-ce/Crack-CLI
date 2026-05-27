import { GitCliBranchManager } from "./git";
import type { BranchManager } from "./git";
import { CodexPlannerAgent } from "./planner-agent";
import type { PlannerAgent } from "./planner-agent";
import { CodexRouterAgent } from "./router-agent";
import type { RouterPlanDiagnostic } from "./router-agent";
import type { RouterAgent, RouterAgentDecision } from "./router-agent";
import { MarkdownState, slugify, titleFromPrompt } from "./state";
import type { PlanRecord } from "./state";

export type RouteAction = "pause_for_pr_review" | "route_to_existing_plan" | "create_new_plan";

export type RouteDecision = {
  action: RouteAction;
  target: string;
  reason: string;
};

export type RouteOptions = {
  planPath?: string;
  branchName?: string;
  planTitle?: string;
  reason?: string;
  receivedAt?: string;
};

export class Router {
  private readonly state: MarkdownState;
  private readonly agent: RouterAgent;
  private readonly planner: PlannerAgent;
  private readonly branchManager: BranchManager;

  constructor(
    state: MarkdownState,
    agent: RouterAgent = new CodexRouterAgent(),
    planner: PlannerAgent = new CodexPlannerAgent(),
    branchManager?: BranchManager,
  ) {
    this.state = state;
    this.agent = agent;
    this.planner = planner;
    this.branchManager = branchManager ?? new GitCliBranchManager(state.repoRoot);
  }

  async route(prompt: string, options: RouteOptions = {}): Promise<RouteDecision> {
    await this.state.initialize();

    const prLock = await this.state.readPrLock();
    if (prLock) {
      const reason = options.reason ?? "PR review lock is active, so new requests are paused.";
      const target = await this.state.appendInbox(prompt, reason, options.receivedAt);
      return { action: "pause_for_pr_review", target, reason };
    }

    if (options.planPath) {
      const reason = options.reason ?? "Caller selected an existing plan.";
      const target = await this.state.appendQueue(options.planPath, prompt, reason, options.receivedAt);
      return { action: "route_to_existing_plan", target, reason };
    }

    if (!options.branchName && !options.planTitle) {
      const planRecords = await this.state.listPlanRecords();
      const routablePlans = planRecords.filter((plan) => plan.statusSummary.routing.routeToExistingPlanCandidate);

      if (routablePlans.length > 0) {
        const decision = await this.agent.decide({
          repoRoot: this.state.repoRoot,
          prompt,
          prLock,
          routablePlans,
          activePlans: routablePlans,
          planDiagnostics: routingDiagnostics(this.state.repoRoot, planRecords, routablePlans),
        });

        return this.applyAgentDecision(prompt, decision, options.receivedAt, routablePlans);
      }
    }

    const title = options.planTitle ?? titleFromPrompt(prompt);
    const branchName = options.branchName ?? `codex/${slugify(title).toLowerCase()}`;
    const reason = options.reason ?? "No PR lock or selected existing plan candidate; created a new plan.";
    const paths = await this.createNewPlan({
      branchName,
      planTitle: title,
      prompt,
      reason,
      receivedAt: options.receivedAt,
    });

    return { action: "create_new_plan", target: paths, reason };
  }

  private async applyAgentDecision(
    prompt: string,
    decision: RouterAgentDecision,
    receivedAt: string | undefined,
    routablePlans: PlanRecord[] = [],
  ): Promise<RouteDecision> {
    if (decision.action === "pause_for_pr_review") {
      const target = await this.state.appendInbox(prompt, decision.reason, receivedAt);
      return { action: "pause_for_pr_review", target, reason: decision.reason };
    }

    if (decision.action === "existing_plan") {
      if (!isRoutablePlanPath(this.state, decision.planPath, routablePlans)) {
        const title = titleFromPrompt(prompt);
        const branchName = `codex/${slugify(title).toLowerCase()}`;
        const reason = [
          `Router selected non-routable plan \`${decision.planPath}\`; created a new plan instead.`,
          decision.reason,
        ].join(" ");
        const planPath = await this.createNewPlan({
          branchName,
          planTitle: title,
          prompt,
          reason,
          receivedAt,
        });

        return { action: "create_new_plan", target: planPath, reason };
      }

      const target = await this.state.appendQueue(decision.planPath, prompt, decision.reason, receivedAt);
      return { action: "route_to_existing_plan", target, reason: decision.reason };
    }

    const title = decision.planTitle ?? titleFromPrompt(prompt);
    const branchName = decision.branchName ?? `codex/${slugify(title).toLowerCase()}`;
    const planPath = await this.createNewPlan({
      branchName,
      planTitle: title,
      prompt,
      reason: decision.reason,
      receivedAt,
    });

    return { action: "create_new_plan", target: planPath, reason: decision.reason };
  }

  private async createNewPlan(options: {
    branchName: string;
    planTitle: string;
    prompt: string;
    reason: string;
    receivedAt?: string;
  }): Promise<string> {
    await this.branchManager.prepareBranch(options.branchName);

    const paths = await this.state.createPlan(options);
    await this.planner.writePlan({
      repoRoot: this.state.repoRoot,
      branchName: options.branchName,
      planTitle: options.planTitle,
      planPath: paths.plan,
      queuePath: paths.queue,
      logPath: paths.log,
      prompt: options.prompt,
      reason: options.reason,
    });
    await this.state.appendPlanLog(
      paths,
      [
        `Created or switched to branch \`${options.branchName}\`.`,
        `Planner wrote \`${relativePath(this.state.repoRoot, paths.plan)}\`.`,
      ],
      options.receivedAt,
    );

    return paths.plan;
  }
}

function relativePath(repoRoot: string, filePath: string): string {
  return filePath.startsWith(repoRoot)
    ? filePath.slice(repoRoot.length + 1).split(/[\\/]/).join("/")
    : filePath;
}

function routingDiagnostics(
  repoRoot: string,
  planRecords: PlanRecord[],
  routablePlans: PlanRecord[],
): RouterPlanDiagnostic[] {
  const routableDirectories = new Set(routablePlans.map((plan) => plan.directory));

  return planRecords
    .filter((plan) => !routableDirectories.has(plan.directory))
    .map((plan) => ({
      planPath: relativePath(repoRoot, plan.plan),
      branchName: plan.branchName,
      status: plan.status,
      reason: plan.statusSummary.routing.exclusionReason ?? plan.statusSummary.reason,
    }));
}

function isRoutablePlanPath(state: MarkdownState, planPath: string, routablePlans: PlanRecord[]): boolean {
  const selected = state.existingPlanPaths(planPath);
  return routablePlans.some((plan) => plan.directory === selected.directory);
}
