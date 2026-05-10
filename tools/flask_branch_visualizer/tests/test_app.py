from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import flask  # noqa: F401
except ImportError as error:
    create_app = None
    FLASK_IMPORT_ERROR = error
else:
    from tools.flask_branch_visualizer.app import create_app

    FLASK_IMPORT_ERROR = None


@unittest.skipIf(create_app is None, f"Flask is not installed: {FLASK_IMPORT_ERROR}")
class FlaskAppTest(unittest.TestCase):
    def test_index_and_api_state_return_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            snapshot = sample_snapshot(root)

            with patch(
                "tools.flask_branch_visualizer.app.read_repository_snapshot",
                return_value=snapshot,
            ) as read_snapshot:
                app = create_app(root, max_commits=5)
                client = app.test_client()

                index_response = client.get("/")
                api_response = client.get("/api/state")

            self.assertEqual(index_response.status_code, 200)
            self.assertIn("text/html", index_response.content_type)
            self.assertIn(b"Crack Branch Visualizer", index_response.data)
            self.assertIn(b"codex/demo", index_response.data)
            self.assertIn(b"Commit 2: Add the Flask view", index_response.data)

            self.assertEqual(api_response.status_code, 200)
            self.assertTrue(api_response.is_json)
            self.assertEqual(api_response.get_json(), snapshot)
            self.assertEqual(read_snapshot.call_count, 2)
            read_snapshot.assert_any_call(str(root), 5)

    def test_index_renders_empty_state_without_crack_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            snapshot = sample_snapshot(root)
            snapshot["initialized"] = False
            snapshot["plans"] = []
            snapshot["warnings"] = ["No .crack directory found."]

            with patch("tools.flask_branch_visualizer.app.read_repository_snapshot", return_value=snapshot):
                app = create_app(root)
                response = app.test_client().get("/")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"No .crack State Found", response.data)
            self.assertIn(b"No .crack directory found.", response.data)


def sample_snapshot(root: Path) -> dict[str, object]:
    return {
        "repo_root": str(root),
        "crack_dir": str(root / ".crack"),
        "initialized": True,
        "warnings": [],
        "plans": [
            {
                "directory": str(root / ".crack" / "plans" / "demo"),
                "plan_path": str(root / ".crack" / "plans" / "demo" / "plan.md"),
                "queue_path": str(root / ".crack" / "plans" / "demo" / "queue.md"),
                "log_path": str(root / ".crack" / "plans" / "demo" / "log.md"),
                "relative_directory": ".crack/plans/demo",
                "relative_plan_path": ".crack/plans/demo/plan.md",
                "title": "Demo Visualizer",
                "branch": "codex/demo",
                "commit_units": [
                    {"number": 1, "title": "Add the data layer"},
                    {"number": 2, "title": "Add the Flask view"},
                ],
                "total_commit_unit_count": 2,
                "completed_commit_unit_count": 1,
                "completed_commit_unit_numbers": [1],
                "queue_request_count": 1,
                "next_commit_unit": {"number": 2, "title": "Add the Flask view"},
            }
        ],
        "git": {
            "current_branch": "codex/demo",
            "branches": [
                {
                    "name": "codex/demo",
                    "short_hash": "abc1234",
                    "committed_at": "2026-05-10T10:00:00+09:00",
                    "subject": "Add the data layer",
                }
            ],
            "recent_commits": [
                {
                    "hash": "abc123456789",
                    "short_hash": "abc1234",
                    "refs": "HEAD -> codex/demo",
                    "author": "Dev",
                    "committed_at": "2026-05-10T10:00:00+09:00",
                    "subject": "Add the data layer",
                }
            ],
        },
    }


if __name__ == "__main__":
    unittest.main()
