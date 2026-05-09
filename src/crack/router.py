from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Literal, Protocol

from .state import ActivePlan, MarkdownState, slugify, title_from_prompt


RouteAction = Literal[
    "pause_for_pr_review",
    "route_to_existing_plan",
    "create_new_plan",
]


@dataclass(frozen=True)
class RouteDecision:
    action: RouteAction
    target: Path
    reason: str


@dataclass(frozen=True)
class RouterContext:
    prompt: str
    pr_lock: str | None
    active_plans: tuple[ActivePlan, ...]


@dataclass(frozen=True)
class RouteFunctionCall:
    action: RouteAction
    reason: str
    plan_path: Path | str | None = None
    queued_prompt: str | None = None
    branch_name: str | None = None
    plan_title: str | None = None


class RouterAgent(Protocol):
    def choose_route(self, context: RouterContext) -> RouteFunctionCall:
        ...


class NewPlanRouterAgent:
    def choose_route(self, context: RouterContext) -> RouteFunctionCall:
        title = title_from_prompt(context.prompt)
        return RouteFunctionCall(
            action="create_new_plan",
            branch_name=f"codex/{slugify(title).lower()}",
            plan_title=title,
            reason="No active plan was selected; created a new plan.",
        )


class CodexCliRouterAgent:
    def __init__(self, repo_root: Path | str, executable: str = "codex") -> None:
        self.repo_root = Path(repo_root)
        self.executable = executable

    def choose_route(self, context: RouterContext) -> RouteFunctionCall:
        output_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as output_file:
                output_path = Path(output_file.name)

            result = subprocess.run(
                [
                    self.executable,
                    "exec",
                    "--ephemeral",
                    "--sandbox",
                    "read-only",
                    "-C",
                    str(self.repo_root),
                    "-o",
                    str(output_path),
                    "-",
                ],
                input=render_router_prompt(context),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Codex router command failed.")

            final_message = output_path.read_text(encoding="utf-8").strip()
            return parse_route_function_call(final_message or result.stdout)
        finally:
            if output_path is not None and output_path.exists():
                output_path.unlink()


class Router:
    def __init__(self, state: MarkdownState, agent: RouterAgent | None = None) -> None:
        self.state = state
        self.agent = agent or NewPlanRouterAgent()

    def route(
        self,
        prompt: str,
        *,
        plan_path: Path | str | None = None,
        branch_name: str | None = None,
        plan_title: str | None = None,
        reason: str | None = None,
        received_at: str | None = None,
    ) -> RouteDecision:
        self.state.initialize()

        pr_lock = self.state.read_pr_lock()
        if pr_lock is not None:
            route_reason = reason or "PR review lock is active, so new requests are paused."
            target = self.state.append_inbox(prompt, route_reason, received_at)
            return RouteDecision("pause_for_pr_review", target, route_reason)

        if plan_path is not None:
            return self.apply_function_call(
                RouteFunctionCall(
                    action="route_to_existing_plan",
                    plan_path=plan_path,
                    reason=reason or "Caller selected an existing active plan.",
                ),
                prompt=prompt,
                received_at=received_at,
            )

        if branch_name is not None or plan_title is not None or reason is not None:
            title = plan_title or title_from_prompt(prompt)
            return self.apply_function_call(
                RouteFunctionCall(
                    action="create_new_plan",
                    branch_name=branch_name or f"codex/{slugify(title).lower()}",
                    plan_title=title,
                    reason=reason or "Caller selected a new plan.",
                ),
                prompt=prompt,
                received_at=received_at,
            )

        context = RouterContext(
            prompt=prompt,
            pr_lock=pr_lock,
            active_plans=tuple(self.state.scan_active_plans()),
        )
        return self.apply_function_call(
            self.agent.choose_route(context),
            prompt=prompt,
            received_at=received_at,
        )

    def apply_function_call(
        self,
        call: RouteFunctionCall,
        *,
        prompt: str,
        received_at: str | None = None,
    ) -> RouteDecision:
        route_reason = call.reason.strip()
        if not route_reason:
            route_reason = f"Router selected `{call.action}`."

        routed_prompt = call.queued_prompt or prompt

        if call.action == "pause_for_pr_review":
            target = self.state.append_inbox(routed_prompt, route_reason, received_at)
            return RouteDecision(call.action, target, route_reason)

        if call.action == "route_to_existing_plan":
            if call.plan_path is None:
                raise ValueError("route_to_existing_plan requires plan_path")
            target = self.state.append_queue(
                call.plan_path,
                routed_prompt,
                route_reason,
                received_at,
            )
            return RouteDecision(call.action, target, route_reason)

        if call.action == "create_new_plan":
            title = call.plan_title or title_from_prompt(prompt)
            branch = call.branch_name or f"codex/{slugify(title).lower()}"
            paths = self.state.create_plan(branch, title, prompt, route_reason, received_at)
            return RouteDecision(call.action, paths.plan, route_reason)

        raise ValueError(f"Unknown router action: {call.action}")


def render_router_prompt(context: RouterContext) -> str:
    lines = [
        "# Agent 0: Router",
        "",
        "Decide where the new user request should go.",
        "",
        "Return exactly one function call:",
        "",
        "- pause_for_pr_review(reason)",
        "- route_to_existing_plan(planPath, reason, queuedPrompt)",
        "- create_new_plan(branchName, planTitle, reason)",
        "",
        "Use a single line with quoted string arguments.",
        "Use an active plan path exactly as listed when routing to an existing plan.",
        "",
        "## User Request",
        "",
        context.prompt.strip(),
        "",
        "## PR Lock",
        "",
        context.pr_lock.strip() if context.pr_lock else "No PR lock.",
        "",
        "## Active Plans",
        "",
    ]

    if not context.active_plans:
        lines.append("No active plans.")
        return "\n".join(lines).rstrip() + "\n"

    for plan in context.active_plans:
        lines.extend(
            [
                f"### {plan.branch_name}",
                "",
                f"Plan path: {plan.paths.plan}",
                "",
                "plan.md:",
                "",
                "```md",
                plan.plan_markdown.strip(),
                "```",
                "",
                "queue.md:",
                "",
                "```md",
                plan.queue_markdown.strip(),
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def parse_route_function_call(output: str) -> RouteFunctionCall:
    call_text = find_route_function_call(output)
    try:
        expression = ast.parse(call_text, mode="eval").body
    except SyntaxError as error:
        raise ValueError(f"Invalid router function call: {call_text}") from error

    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
        raise ValueError(f"Invalid router function call: {call_text}")

    action = expression.func.id
    if action not in {"pause_for_pr_review", "route_to_existing_plan", "create_new_plan"}:
        raise ValueError(f"Unknown router function call: {action}")

    positional = [literal_string(argument) for argument in expression.args]
    keywords = {
        normalize_argument(keyword.arg): literal_string(keyword.value)
        for keyword in expression.keywords
    }

    if action == "pause_for_pr_review":
        return RouteFunctionCall(
            action=action,
            reason=argument_value(keywords, positional, 0, "reason"),
        )

    if action == "route_to_existing_plan":
        plan_path = argument_value(keywords, positional, 0, "plan_path", "planPath")
        if not plan_path:
            raise ValueError("route_to_existing_plan requires planPath")
        return RouteFunctionCall(
            action=action,
            plan_path=plan_path,
            reason=argument_value(keywords, positional, 1, "reason"),
            queued_prompt=argument_value(
                keywords,
                positional,
                2,
                "queued_prompt",
                "queuedPrompt",
            ),
        )

    return RouteFunctionCall(
        action=action,
        branch_name=argument_value(keywords, positional, 0, "branch_name", "branchName"),
        plan_title=argument_value(keywords, positional, 1, "plan_title", "planTitle"),
        reason=argument_value(keywords, positional, 2, "reason"),
    )


def find_route_function_call(output: str) -> str:
    for line in reversed(output.splitlines()):
        stripped = line.strip().strip("`")
        if stripped.startswith(
            ("pause_for_pr_review(", "route_to_existing_plan(", "create_new_plan(")
        ) and stripped.endswith(")"):
            return stripped
    raise ValueError("Router did not return a supported function call.")


def literal_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise ValueError("Router function call arguments must be string literals.")


def normalize_argument(name: str | None) -> str:
    if not name:
        raise ValueError("Router function call does not support **kwargs.")
    return name.replace("-", "_")


def argument_value(
    keywords: dict[str, str],
    positional: list[str],
    index: int,
    *names: str,
) -> str:
    normalized_names = [normalize_argument(name) for name in names]
    for name in normalized_names:
        if name in keywords:
            return keywords[name]
    if index < len(positional):
        return positional[index]
    return ""
