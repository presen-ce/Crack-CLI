from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / ".git").exists():
            return path
    return current


def timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def quote_prompt(prompt: str) -> str:
    lines = prompt.strip().splitlines() or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def slugify(value: str, default: str = "request") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return slug or default


def branch_to_plan_dir(branch_name: str) -> str:
    return slugify(branch_name)


def title_from_prompt(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    if not first_line:
        return "User Request"
    return first_line[:80]


@dataclass(frozen=True)
class PlanPaths:
    directory: Path
    plan: Path
    queue: Path
    log: Path


@dataclass(frozen=True)
class ActivePlan:
    paths: PlanPaths
    branch_name: str
    plan_markdown: str
    queue_markdown: str


class MarkdownState:
    def __init__(self, repo_root: Path | str | None = None) -> None:
        self.repo_root = Path(repo_root).resolve() if repo_root else find_repo_root()
        self.crack_dir = self.repo_root / ".crack"
        self.inbox_path = self.crack_dir / "inbox.md"
        self.pr_lock_path = self.crack_dir / "pr-lock.md"
        self.plans_dir = self.crack_dir / "plans"

    def initialize(self) -> None:
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        if not self.inbox_path.exists():
            self.inbox_path.write_text("# Inbox\n\n", encoding="utf-8")

    def read_pr_lock(self) -> str | None:
        if not self.pr_lock_path.exists():
            return None
        return self.pr_lock_path.read_text(encoding="utf-8")

    def plan_paths(self, branch_name: str) -> PlanPaths:
        directory = self.plans_dir / branch_to_plan_dir(branch_name)
        return PlanPaths(
            directory=directory,
            plan=directory / "plan.md",
            queue=directory / "queue.md",
            log=directory / "log.md",
        )

    def existing_plan_paths(self, plan_path: Path | str) -> PlanPaths:
        path = Path(plan_path)
        if not path.is_absolute():
            path = self.repo_root / path
        directory = path if path.is_dir() else path.parent
        return PlanPaths(
            directory=directory,
            plan=directory / "plan.md",
            queue=directory / "queue.md",
            log=directory / "log.md",
        )

    def scan_active_plans(self) -> list[ActivePlan]:
        self.initialize()
        plans: list[ActivePlan] = []
        if not self.plans_dir.exists():
            return plans

        for directory in sorted(path for path in self.plans_dir.iterdir() if path.is_dir()):
            paths = self.existing_plan_paths(directory)
            if not paths.plan.exists():
                continue

            plan_markdown = paths.plan.read_text(encoding="utf-8")
            queue_markdown = paths.queue.read_text(encoding="utf-8") if paths.queue.exists() else ""
            plans.append(
                ActivePlan(
                    paths=paths,
                    branch_name=branch_from_plan(plan_markdown, directory.name),
                    plan_markdown=plan_markdown,
                    queue_markdown=queue_markdown,
                )
            )

        return plans

    def append_inbox(
        self,
        prompt: str,
        reason: str,
        received_at: str | None = None,
    ) -> Path:
        self.initialize()
        entry = (
            "## Queued Request\n\n"
            f"Received: {received_at or timestamp()}\n\n"
            "User prompt:\n\n"
            f"{quote_prompt(prompt)}\n\n"
            "Reason:\n\n"
            f"{reason.strip()}\n\n"
        )
        with self.inbox_path.open("a", encoding="utf-8") as file:
            file.write(entry)
        return self.inbox_path

    def create_plan(
        self,
        branch_name: str,
        plan_title: str,
        prompt: str,
        reason: str,
        received_at: str | None = None,
    ) -> PlanPaths:
        self.initialize()
        branch = branch_name.strip()
        if not branch:
            raise ValueError("branch_name is required")

        title = plan_title.strip() or title_from_prompt(prompt)
        paths = self.plan_paths(branch)
        if paths.directory.exists():
            raise FileExistsError(f"Plan already exists: {paths.directory}")

        paths.directory.mkdir(parents=True)
        received = received_at or timestamp()
        paths.plan.write_text(
            (
                f"# Plan: {title}\n\n"
                f"Branch: {branch}\n\n"
                "## Intent\n\n"
                f"{prompt.strip()}\n\n"
                "## Commit Units\n\n"
                "- TODO: Planner should split this request into commit-sized units.\n\n"
                "## Router Note\n\n"
                f"{reason.strip()}\n"
            ),
            encoding="utf-8",
        )
        paths.queue.write_text("# Queue\n\n", encoding="utf-8")
        paths.log.write_text(
            (
                "# Log\n\n"
                f"## {received}\n\n"
                f"- Created plan directory for `{branch}`.\n"
                f"- Reason: {reason.strip()}\n"
            ),
            encoding="utf-8",
        )
        return paths

    def append_queue(
        self,
        plan_path: Path | str,
        prompt: str,
        reason: str,
        received_at: str | None = None,
    ) -> Path:
        self.initialize()
        paths = self.existing_plan_paths(plan_path)
        if not paths.directory.exists():
            raise FileNotFoundError(f"Plan does not exist: {paths.directory}")
        if not paths.queue.exists():
            paths.queue.write_text("# Queue\n\n", encoding="utf-8")

        entry = (
            "## Queued Request\n\n"
            f"Received: {received_at or timestamp()}\n\n"
            "User prompt:\n\n"
            f"{quote_prompt(prompt)}\n\n"
            "Reason:\n\n"
            f"{reason.strip()}\n\n"
        )
        with paths.queue.open("a", encoding="utf-8") as file:
            file.write(entry)
        return paths.queue

    def set_pr_lock(
        self,
        pr_url: str,
        branch_name: str,
        reason: str,
        status: str = "reviewing",
    ) -> Path:
        self.initialize()
        branch = branch_name.strip()
        if not branch:
            raise ValueError("branch_name is required")

        self.pr_lock_path.write_text(
            (
                "# PR Lock\n\n"
                f"Branch: {branch}\n"
                f"PR: {pr_url.strip()}\n"
                f"Status: {status.strip()}\n\n"
                f"{reason.strip()}\n"
            ),
            encoding="utf-8",
        )
        return self.pr_lock_path

    def clear_pr_lock(self) -> bool:
        if not self.pr_lock_path.exists():
            return False
        self.pr_lock_path.unlink()
        return True


def branch_from_plan(markdown: str, fallback: str) -> str:
    match = re.search(r"^Branch:\s*(.+?)\s*$", markdown, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback
