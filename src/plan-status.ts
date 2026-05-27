export type CommitUnit = {
  number: number;
  title: string;
  content: string;
};

export type PlanStatus = "active" | "complete";

export type PlanCommitUnitSummary = {
  number: number;
  title: string;
};

export type PlanProgressSummary = {
  total: number;
  completed: number;
  remaining: number;
  completedNumbers: number[];
  next: PlanCommitUnitSummary | null;
};

export type PlanRoutingSummary = {
  routeToExistingPlanCandidate: boolean;
  exclusionReason?: string;
  contextHints: string[];
};

export type PlanStatusSummary = {
  status: PlanStatus;
  reason: string;
  progress: PlanProgressSummary;
  routing: PlanRoutingSummary;
};

export function parseCommitUnits(planContent: string): CommitUnit[] {
  const lines = planContent.split(/\r?\n/);
  const starts: Array<{ index: number; number: number; title: string }> = [];

  lines.forEach((line, index) => {
    const match = line.match(/^###\s+Commit\s+(\d+)\s*:?\s*(.*?)\s*$/i);
    if (!match) {
      return;
    }

    starts.push({
      index,
      number: Number.parseInt(match[1], 10),
      title: match[2]?.trim() || `Commit unit ${match[1]}`,
    });
  });

  return starts.map((start, index) => {
    const nextStart = starts[index + 1]?.index ?? lines.length;
    return {
      number: start.number,
      title: start.title,
      content: lines.slice(start.index, nextStart).join("\n").trim(),
    };
  });
}

export function completedCommitUnitNumbers(logContent: string): Set<number> {
  const completed = new Set<number>();

  for (const match of logContent.matchAll(/Completed commit unit\s+(\d+)\b/gi)) {
    completed.add(Number.parseInt(match[1], 10));
  }

  return completed;
}

export function selectNextCommitUnit(planContent: string, logContent: string): CommitUnit | undefined {
  const completed = completedCommitUnitNumbers(logContent);
  return parseCommitUnits(planContent).find((unit) => !completed.has(unit.number));
}

export function summarizePlanStatus(planContent: string, logContent: string): PlanStatusSummary {
  const units = parseCommitUnits(planContent);
  const completed = completedCommitUnitNumbers(logContent);
  const completedUnits = units.filter((unit) => completed.has(unit.number));
  const remainingUnits = units.filter((unit) => !completed.has(unit.number));
  const completedNumbers = completedUnits.map((unit) => unit.number);
  const next = remainingUnits[0] ? commitUnitSummary(remainingUnits[0]) : null;

  if (units.length === 0) {
    return {
      status: "active",
      reason: "No commit units were found in plan.md; treating the plan as active until it is corrected.",
      progress: {
        total: 0,
        completed: 0,
        remaining: 0,
        completedNumbers: [],
        next: null,
      },
      routing: {
        routeToExistingPlanCandidate: false,
        exclusionReason: "Plan has no commit units, so it is excluded from default existing-plan routing until corrected.",
        contextHints: [],
      },
    };
  }

  if (remainingUnits.length === 0) {
    const reason = "All commit units are completed according to log.md.";

    return {
      status: "complete",
      reason,
      progress: {
        total: units.length,
        completed: completedNumbers.length,
        remaining: 0,
        completedNumbers,
        next,
      },
      routing: {
        routeToExistingPlanCandidate: false,
        exclusionReason: "Plan is complete, so it is excluded from default existing-plan routing.",
        contextHints: [reason],
      },
    };
  }

  return {
    status: "active",
    reason: `Commit units not complete: ${remainingUnits.map((unit) => unit.number).join(", ")}.`,
    progress: {
      total: units.length,
      completed: completedNumbers.length,
      remaining: remainingUnits.length,
      completedNumbers,
      next,
    },
    routing: {
      routeToExistingPlanCandidate: true,
      contextHints: [],
    },
  };
}

function commitUnitSummary(unit: CommitUnit): PlanCommitUnitSummary {
  return {
    number: unit.number,
    title: unit.title,
  };
}
