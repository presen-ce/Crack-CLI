from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from crack.router import RouteFunctionCall, Router, RouterContext, parse_route_function_call
from crack.state import MarkdownState


class FakeRouterAgent:
    def __init__(self, call: RouteFunctionCall) -> None:
        self.call = call
        self.context: RouterContext | None = None

    def choose_route(self, context: RouterContext) -> RouteFunctionCall:
        self.context = context
        return self.call


class RouterTests(unittest.TestCase):
    def make_state(self, root: Path) -> MarkdownState:
        (root / ".git").mkdir()
        return MarkdownState(root)

    def test_route_creates_new_plan(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            state = self.make_state(root)

            decision = Router(state).route(
                "Add router state files",
                branch_name="codex/router-state",
                plan_title="Router State",
                received_at="2026-05-09 12:00",
            )

            self.assertEqual(decision.action, "create_new_plan")
            plan_dir = root / ".crack" / "plans" / "codex-router-state"
            self.assertEqual(decision.target, plan_dir / "plan.md")
            self.assertTrue((plan_dir / "queue.md").exists())
            self.assertIn(
                "Branch: codex/router-state",
                (plan_dir / "plan.md").read_text(encoding="utf-8"),
            )

    def test_pr_lock_routes_prompt_to_inbox(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            state = self.make_state(root)
            state.set_pr_lock(
                pr_url="https://github.com/example/repo/pull/1",
                branch_name="codex/reviewing",
                reason="PR is reviewing.",
            )

            decision = Router(state).route(
                "Start another feature",
                received_at="2026-05-09 12:00",
            )

            self.assertEqual(decision.action, "pause_for_pr_review")
            inbox = (root / ".crack" / "inbox.md").read_text(encoding="utf-8")
            self.assertIn("> Start another feature", inbox)
            self.assertFalse((root / ".crack" / "plans" / "codex-start-another-feature").exists())

    def test_existing_plan_routes_prompt_to_queue(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            state = self.make_state(root)
            paths = state.create_plan(
                branch_name="codex/current",
                plan_title="Current",
                prompt="Initial request",
                reason="test setup",
                received_at="2026-05-09 12:00",
            )

            decision = Router(state).route(
                "Add dependent follow-up",
                plan_path=paths.directory,
                reason="Depends on current plan.",
                received_at="2026-05-09 12:05",
            )

            self.assertEqual(decision.action, "route_to_existing_plan")
            queue = paths.queue.read_text(encoding="utf-8")
            self.assertIn("> Add dependent follow-up", queue)
            self.assertIn("Depends on current plan.", queue)

    def test_router_agent_receives_active_plan_context(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            state = self.make_state(root)
            paths = state.create_plan(
                branch_name="codex/current",
                plan_title="Current",
                prompt="Initial request",
                reason="test setup",
                received_at="2026-05-09 12:00",
            )
            state.append_queue(
                paths.plan,
                "Queued follow-up",
                "test setup",
                received_at="2026-05-09 12:01",
            )
            agent = FakeRouterAgent(
                RouteFunctionCall(
                    action="route_to_existing_plan",
                    plan_path=paths.plan,
                    reason="The request depends on Current.",
                )
            )

            decision = Router(state, agent=agent).route(
                "Extend current work",
                received_at="2026-05-09 12:05",
            )

            self.assertEqual(decision.action, "route_to_existing_plan")
            self.assertIsNotNone(agent.context)
            self.assertEqual(len(agent.context.active_plans), 1)
            active_plan = agent.context.active_plans[0]
            self.assertEqual(active_plan.branch_name, "codex/current")
            self.assertIn("Initial request", active_plan.plan_markdown)
            self.assertIn("Queued follow-up", active_plan.queue_markdown)
            self.assertIn(
                "> Extend current work",
                paths.queue.read_text(encoding="utf-8"),
            )

    def test_router_agent_can_create_new_plan(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            state = self.make_state(root)
            agent = FakeRouterAgent(
                RouteFunctionCall(
                    action="create_new_plan",
                    branch_name="codex/new-router-plan",
                    plan_title="New Router Plan",
                    reason="Independent request.",
                )
            )

            decision = Router(state, agent=agent).route(
                "Build an independent router plan",
                received_at="2026-05-09 12:00",
            )

            plan_dir = root / ".crack" / "plans" / "codex-new-router-plan"
            self.assertEqual(decision.action, "create_new_plan")
            self.assertEqual(decision.target, plan_dir / "plan.md")
            self.assertIn(
                "Branch: codex/new-router-plan",
                (plan_dir / "plan.md").read_text(encoding="utf-8"),
            )

    def test_parse_route_function_call(self) -> None:
        call = parse_route_function_call(
            'route_to_existing_plan(planPath=".crack/plans/current/plan.md", '
            'reason="Depends on current plan.", queuedPrompt="Follow-up")'
        )

        self.assertEqual(call.action, "route_to_existing_plan")
        self.assertEqual(call.plan_path, ".crack/plans/current/plan.md")
        self.assertEqual(call.reason, "Depends on current plan.")
        self.assertEqual(call.queued_prompt, "Follow-up")


if __name__ == "__main__":
    unittest.main()
