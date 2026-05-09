from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .router import CodexCliRouterAgent, Router
from .state import MarkdownState, find_repo_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crack")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root. Defaults to the nearest parent containing .git.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create .crack state directories.")

    submit = subparsers.add_parser("submit", help="Route a new user prompt.")
    add_submit_arguments(submit)

    route = subparsers.add_parser("route", help="Alias for submit.")
    add_submit_arguments(route)

    lock = subparsers.add_parser("set-pr-lock", help="Pause new plans during PR review.")
    lock.add_argument("--branch", required=True)
    lock.add_argument("--pr-url", required=True)
    lock.add_argument("--reason", required=True)
    lock.add_argument("--status", default="reviewing")

    subparsers.add_parser("clear-pr-lock", help="Remove .crack/pr-lock.md.")

    return parser


def add_submit_arguments(route: argparse.ArgumentParser) -> None:
    route.add_argument("prompt")
    route.add_argument("--plan", type=Path, help="Existing plan directory or plan.md.")
    route.add_argument("--branch", help="Branch name for a new plan.")
    route.add_argument("--title", help="Plan title for a new plan.")
    route.add_argument("--reason", help="Routing reason to write into Markdown.")
    route.add_argument(
        "--no-codex",
        action="store_true",
        help="Skip Codex routing and create a new plan when no manual target is given.",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root or find_repo_root()
    state = MarkdownState(root)

    if args.command == "init":
        state.initialize()
        print(f"initialized {state.crack_dir}")
        return 0

    if args.command in {"submit", "route"}:
        agent = None
        if should_use_codex_router(args):
            agent = CodexCliRouterAgent(root)

        decision = Router(state, agent=agent).route(
            args.prompt,
            plan_path=args.plan,
            branch_name=args.branch,
            plan_title=args.title,
            reason=args.reason,
        )
        print(f"{decision.action}: {decision.target}")
        return 0

    if args.command == "set-pr-lock":
        target = state.set_pr_lock(
            pr_url=args.pr_url,
            branch_name=args.branch,
            reason=args.reason,
            status=args.status,
        )
        print(f"set_pr_lock: {target}")
        return 0

    if args.command == "clear-pr-lock":
        removed = state.clear_pr_lock()
        print("clear_pr_lock: removed" if removed else "clear_pr_lock: no lock")
        return 0

    return 1


def should_use_codex_router(args: argparse.Namespace) -> bool:
    return not (
        args.no_codex
        or args.plan is not None
        or args.branch is not None
        or args.title is not None
        or args.reason is not None
    )


if __name__ == "__main__":
    sys.exit(main())
