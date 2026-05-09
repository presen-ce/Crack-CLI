import { Router } from "./router";
import type { RouteDecision } from "./router";
import type { MarkdownState, QueuedRequest } from "./state";

export interface InboxRequestRouter {
  route(prompt: string, options?: { receivedAt?: string }): Promise<RouteDecision>;
}

export type DrainInboxResult =
  | {
      action: "empty";
      inboxPath: string;
    }
  | {
      action: "locked";
      inboxPath: string;
      lockPath: string;
      remaining: number;
      reason: string;
    }
  | {
      action: "drained";
      inboxPath: string;
      drained: number;
      decisions: RouteDecision[];
    };

export class InboxDrainer {
  private readonly state: MarkdownState;
  private readonly router: InboxRequestRouter;

  constructor(state: MarkdownState, router: InboxRequestRouter = new Router(state)) {
    this.state = state;
    this.router = router;
  }

  async drain(): Promise<DrainInboxResult> {
    const requests = await this.state.readInboxRequests();
    if (requests.length === 0) {
      return { action: "empty", inboxPath: this.state.inboxPath };
    }

    const existingLock = await this.state.readPrLock();
    if (existingLock) {
      return {
        action: "locked",
        inboxPath: this.state.inboxPath,
        lockPath: this.state.prLockPath,
        remaining: requests.length,
        reason: "PR review lock is still active.",
      };
    }

    const decisions: RouteDecision[] = [];
    for (let index = 0; index < requests.length; index += 1) {
      const request = requests[index];
      const lock = await this.state.readPrLock();
      if (lock) {
        return {
          action: "locked",
          inboxPath: this.state.inboxPath,
          lockPath: this.state.prLockPath,
          remaining: requests.length - index,
          reason: "PR review lock became active during inbox drain.",
        };
      }

      decisions.push(await this.routeRequest(request));
      await this.state.writeInboxRequests(requests.slice(index + 1));
    }

    return {
      action: "drained",
      inboxPath: this.state.inboxPath,
      drained: decisions.length,
      decisions,
    };
  }

  private routeRequest(request: QueuedRequest): Promise<RouteDecision> {
    return this.router.route(request.prompt, {
      receivedAt: request.receivedAt || undefined,
    });
  }
}
