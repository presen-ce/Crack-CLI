from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.flask_branch_visualizer.state import find_repo_root, read_repository_snapshot
else:
    from .state import find_repo_root, read_repository_snapshot


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_WEB_MAX_COMMITS = 12

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Crack Branch Visualizer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f6f1;
      --surface: #ffffff;
      --surface-muted: #f0efe8;
      --ink: #1f2523;
      --muted: #64706c;
      --line: #d7d3c8;
      --green: #2f7a5f;
      --amber: #a16322;
      --red: #a43f3b;
      --shadow: 0 18px 45px rgba(42, 38, 28, 0.09);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background:
        linear-gradient(120deg, rgba(47, 122, 95, 0.10), transparent 34%),
        linear-gradient(240deg, rgba(161, 99, 34, 0.12), transparent 32%),
        var(--bg);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }

    .shell {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }

    .masthead {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 420px);
      gap: 24px;
      align-items: end;
      padding: 24px 0 22px;
      border-bottom: 1px solid var(--line);
    }

    .eyebrow {
      margin: 0 0 8px;
      color: var(--green);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1,
    h2,
    h3,
    p {
      margin-top: 0;
    }

    h1 {
      max-width: 760px;
      margin-bottom: 0;
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      font-size: clamp(2.25rem, 5vw, 4.8rem);
      font-weight: 700;
      line-height: 0.95;
    }

    h2 {
      margin-bottom: 14px;
      font-size: 1rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h3 {
      margin-bottom: 12px;
      font-size: 1rem;
    }

    .repo-summary,
    .empty-state,
    .warning-list {
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
      box-shadow: var(--shadow);
    }

    .repo-summary {
      display: grid;
      gap: 8px;
      padding: 16px;
    }

    .repo-summary span,
    .metric-label,
    .meta,
    .muted {
      color: var(--muted);
      font-size: 0.86rem;
    }

    .repo-summary strong,
    code {
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .section {
      padding-top: 28px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }

    .card,
    .timeline-item {
      border: 1px solid var(--line);
      background: var(--surface);
      box-shadow: 0 10px 28px rgba(42, 38, 28, 0.06);
    }

    .card {
      padding: 16px;
    }

    .card.current {
      border-color: rgba(47, 122, 95, 0.55);
    }

    .card-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }

    .tag {
      align-self: flex-start;
      border: 1px solid var(--line);
      padding: 2px 8px;
      color: var(--muted);
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .tag.current {
      border-color: rgba(47, 122, 95, 0.38);
      color: var(--green);
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 12px 0;
    }

    .metric {
      padding: 10px;
      background: var(--surface-muted);
    }

    .metric-value {
      display: block;
      font-size: 1.2rem;
      font-weight: 800;
    }

    .progress {
      height: 8px;
      overflow: hidden;
      background: var(--surface-muted);
    }

    .progress span {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--green), var(--amber));
    }

    code {
      display: block;
      padding: 10px 12px;
      background: #242923;
      color: #f6f1df;
      font-size: 0.83rem;
    }

    .empty-state,
    .warning-list {
      margin-top: 20px;
      padding: 18px;
    }

    .warning-list {
      border-color: rgba(164, 63, 59, 0.28);
      color: var(--red);
    }

    .warning-list ul {
      margin: 8px 0 0;
      padding-left: 18px;
    }

    .timeline {
      display: grid;
      gap: 10px;
    }

    .timeline-item {
      display: grid;
      grid-template-columns: 112px minmax(0, 1fr);
      gap: 14px;
      padding: 14px 16px;
    }

    .hash {
      color: var(--green);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-weight: 800;
    }

    .refs {
      color: var(--amber);
      font-size: 0.86rem;
      overflow-wrap: anywhere;
    }

    .subject {
      margin-bottom: 6px;
      font-weight: 700;
    }

    @media (max-width: 760px) {
      .shell {
        width: min(100% - 20px, 1180px);
        padding-top: 14px;
      }

      .masthead,
      .timeline-item {
        grid-template-columns: 1fr;
      }

      .metrics {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="masthead">
      <div>
        <p class="eyebrow">Local read-only view</p>
        <h1>Crack Branch Visualizer</h1>
      </div>
      <div class="repo-summary" aria-label="Repository summary">
        <span>Repository</span>
        <strong>{{ snapshot.repo_root }}</strong>
        <span>Current branch</span>
        <strong>{{ snapshot.git.current_branch or "detached or unknown" }}</strong>
      </div>
    </header>

    {% if snapshot.warnings %}
      <section class="warning-list" aria-label="Warnings">
        <strong>Warnings</strong>
        <ul>
          {% for warning in snapshot.warnings %}
            <li>{{ warning }}</li>
          {% endfor %}
        </ul>
      </section>
    {% endif %}

    {% if not snapshot.initialized %}
      <section class="empty-state">
        <h2>No .crack State Found</h2>
        <p class="muted">This repository has no readable <strong>.crack/</strong> directory yet. Git branches and recent commits are still shown when available.</p>
      </section>
    {% else %}
      <section class="section" aria-labelledby="plans-heading">
        <h2 id="plans-heading">Crack Plans</h2>
        {% if snapshot.plans %}
          <div class="grid">
            {% for plan in snapshot.plans %}
              <article class="card">
                <div class="card-title">
                  <div>
                    <h3>{{ plan.title }}</h3>
                    <p class="meta">{{ plan.branch }}</p>
                  </div>
                  <span class="tag">{{ plan.queue_request_count }} queued</span>
                </div>
                <div class="progress" aria-label="Plan progress">
                  <span style="width: {{ progress_percent(plan) }}%"></span>
                </div>
                <div class="metrics">
                  <div class="metric">
                    <span class="metric-value">{{ plan.completed_commit_unit_count }}/{{ plan.total_commit_unit_count }}</span>
                    <span class="metric-label">commit units</span>
                  </div>
                  <div class="metric">
                    <span class="metric-value">{{ progress_percent(plan) }}%</span>
                    <span class="metric-label">complete</span>
                  </div>
                  <div class="metric">
                    <span class="metric-value">{{ plan.queue_request_count }}</span>
                    <span class="metric-label">queue</span>
                  </div>
                </div>
                <p><strong>Next:</strong> {{ next_commit_text(plan) }}</p>
                <code>{{ run_command(plan) }}</code>
              </article>
            {% endfor %}
          </div>
        {% else %}
          <p class="muted">No plan files were found under <strong>.crack/plans/</strong>.</p>
        {% endif %}
      </section>
    {% endif %}

    <section class="section" aria-labelledby="branches-heading">
      <h2 id="branches-heading">Local Branches</h2>
      {% if snapshot.git.branches %}
        <div class="grid">
          {% for branch in snapshot.git.branches %}
            <article class="card{% if branch.name == snapshot.git.current_branch %} current{% endif %}">
              <div class="card-title">
                <h3>{{ branch.name }}</h3>
                {% if branch.name == snapshot.git.current_branch %}
                  <span class="tag current">current</span>
                {% endif %}
              </div>
              <p><span class="hash">{{ branch.short_hash or "no hash" }}</span></p>
              <p class="subject">{{ branch.subject or "No commit subject" }}</p>
              <p class="meta">{{ branch.committed_at or "No commit date" }}</p>
            </article>
          {% endfor %}
        </div>
      {% else %}
        <p class="muted">No local branch data found.</p>
      {% endif %}
    </section>

    <section class="section" aria-labelledby="commits-heading">
      <h2 id="commits-heading">Recent Commits</h2>
      {% if snapshot.git.recent_commits %}
        <div class="timeline">
          {% for commit in snapshot.git.recent_commits %}
            <article class="timeline-item">
              <div>
                <div class="hash">{{ commit.short_hash }}</div>
                <div class="refs">{{ commit.refs or "no decorations" }}</div>
              </div>
              <div>
                <p class="subject">{{ commit.subject or "No commit subject" }}</p>
                <p class="meta">{{ commit.author or "Unknown author" }} &middot; {{ commit.committed_at or "No commit date" }}</p>
              </div>
            </article>
          {% endfor %}
        </div>
      {% else %}
        <p class="muted">No recent commits found.</p>
      {% endif %}
    </section>
  </main>
</body>
</html>
"""


def create_app(repo_path: str | Path | None = None, max_commits: int = DEFAULT_WEB_MAX_COMMITS) -> Flask:
    repo_root = find_repo_root(repo_path)
    app = Flask(__name__)
    app.config["REPO_ROOT"] = repo_root
    app.config["MAX_COMMITS"] = max_commits

    app.jinja_env.globals.update(
        next_commit_text=next_commit_text,
        progress_percent=progress_percent,
        run_command=run_command,
    )

    @app.get("/")
    def index() -> str:
        snapshot = read_repository_snapshot(repo_root, max_commits)
        return render_template_string(PAGE_TEMPLATE, snapshot=snapshot)

    @app.get("/api/state")
    def api_state() -> Any:
        snapshot = read_repository_snapshot(repo_root, max_commits)
        return jsonify(snapshot)

    return app


def progress_percent(plan: dict[str, Any]) -> int:
    total = int(plan.get("total_commit_unit_count") or 0)
    completed = int(plan.get("completed_commit_unit_count") or 0)
    if total <= 0:
        return 0

    return max(0, min(100, round((completed / total) * 100)))


def next_commit_text(plan: dict[str, Any]) -> str:
    next_unit = plan.get("next_commit_unit")
    if not next_unit:
        return "Plan complete"

    number = next_unit.get("number", "?")
    title = next_unit.get("title") or "Untitled commit unit"
    return f"Commit {number}: {title}"


def run_command(plan: dict[str, Any]) -> str:
    plan_path = plan.get("relative_plan_path") or plan.get("plan_path")
    if not plan_path:
        return "crack run-all"

    return f"crack run-all --plan {shlex.quote(str(plan_path))}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Crack branch visualizer.")
    parser.add_argument("--repo", default=None, help="Repository root to visualize. Defaults to the nearest git root.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host to bind. Defaults to {DEFAULT_HOST}.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help=f"Port to bind. Defaults to {DEFAULT_PORT}.")
    parser.add_argument(
        "--max-commits",
        default=DEFAULT_WEB_MAX_COMMITS,
        type=int,
        help=f"Recent commit count to show. Defaults to {DEFAULT_WEB_MAX_COMMITS}.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    app = create_app(args.repo, args.max_commits)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
