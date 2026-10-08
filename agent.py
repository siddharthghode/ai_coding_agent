#!/usr/bin/env python3
"""
agent.py — CLI entry point for the AI Coding Agent.

Orchestrates the 6-step workflow:
  1. Repo acquisition  — clone or select from workspace/ (ONCE per session)
  2. Explore           — static scan, zero LLM calls (refreshed after edits)
  3. Plan              — LLM produces structured JSON plan
  4. Modify            — per-file surgical edits with retry
  5. Validate          — syntax + npm install + boot check (edit runs only)
  6. Report            — reports/run_NNN.md + terminal summary

Usage:
  python agent.py                           # fully interactive session
  python agent.py "Add search to notes" --repo-url https://github.com/callicoder/node-easy-notes-app
  python agent.py "Add note pinning" --repo /path/to/repo --yes
"""
import argparse, json, os, sys
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from config import get_llm_config, WORKSPACE_DIR
from core.workspace import acquire_repo, restore_file
from core.explorer import explore, summary_text
from core.tools import set_repo_root
from core.planner import create_plan
from core.modifier import apply_step
from core.validator import validate_repo
from core.reporter import generate_report
from core.session import SessionContext

console = Console()

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name)) as f:
        return f.read()


def _pick_repo(args) -> str:
    """Interactive repo selection or use CLI args. Returns repo_root."""
    if args.repo_url or args.repo:
        return acquire_repo(args.repo_url, args.repo)

    existing = []
    if os.path.isdir(WORKSPACE_DIR):
        existing = [d for d in sorted(os.listdir(WORKSPACE_DIR))
                    if os.path.isdir(os.path.join(WORKSPACE_DIR, d))]

    console.print("\n[bold cyan]── Repo Selection ──[/bold cyan]")
    console.print("  [bold]1.[/bold] Clone a new repo")
    for i, name in enumerate(existing, start=2):
        console.print(f"  [bold]{i}.[/bold] {name}  [dim](workspace/{name})[/dim]")

    choice = console.input("\n[bold]Select [1-{}]: [/bold]".format(1 + len(existing))).strip()

    if choice == "1":
        url = console.input("[bold]Git URL: [/bold]").strip()
        return acquire_repo(url, None)
    else:
        try:
            idx = int(choice) - 2
            if 0 <= idx < len(existing):
                return acquire_repo(None, os.path.join(WORKSPACE_DIR, existing[idx]))
        except ValueError:
            pass
        console.print("[red]Invalid selection.[/red]")
        sys.exit(1)


def _run_prompt(llm_cfg: dict, repo_root: str, summary_str: str,
                request: str, yes: bool, session: SessionContext) -> bool:
    """
    Run one full plan→modify→validate→report cycle.
    Returns True if files were modified (so caller can refresh summary).
    Never raises — errors are caught and displayed.
    """
    planner_system = _load_prompt("planner_system.txt")
    modifier_system = _load_prompt("modifier_system.txt")

    # ── 3. Plan ───────────────────────────────────────────────────────────────
    console.print("\n[bold blue]🤖 Planning...[/bold blue]")
    try:
        plan = create_plan(
            llm_cfg, planner_system, summary_str, request,
            console=console, session_context=session.as_text()
        )
    except Exception as e:
        console.print(f"\n[red]❌ Planning failed:[/red] {e}")
        return False

    console.print(Syntax(json.dumps(plan, indent=2), "json", theme="monokai"))

    # ── Pre-edit confirmation ─────────────────────────────────────────────────
    edit_steps = [s for s in plan.get("steps", []) if s.get("action", "modify") != "read"]
    if edit_steps and not yes:
        answer = console.input(
            "\n[bold yellow]Proceed with editing files? (yes/no): [/bold yellow]"
        ).strip().lower()
        if answer not in ("y", "yes"):
            console.print("[yellow]Skipped edits — no files changed.[/yellow]")
            return False

    # ── 4. Modify ─────────────────────────────────────────────────────────────
    console.print("\n[bold blue]✏️  Modifying...[/bold blue]")
    results = []
    all_backups = []
    files_modified = False

    for step in plan.get("steps", []):
        file_path = step["file"]
        action = step.get("action", "modify")

        if action == "read":
            console.print(f"  [bold blue]📖 Reading:[/bold blue] {file_path}  [dim]{step['description']}[/dim]")
            results.append({"file": file_path, "status": "read", "edits": [], "error": None, "backup": None})
            continue

        console.print(f"  [bold cyan]✏️  Editing:[/bold cyan] {file_path}  [dim]{step['description']}[/dim]")
        result = apply_step(llm_cfg, modifier_system, repo_root, step, console=console)
        results.append(result)

        if result["backup"]:
            all_backups.append((result["backup"], os.path.join(repo_root, file_path)))

        if result["status"] == "ok":
            files_modified = True
            console.print(f"    [green]✅ Done[/green] ({len(result['edits'])} edit(s))")
        else:
            console.print(f"    [red]⚠️  Skipped — {result['error']}[/red]")

    # ── 5. Whole-repo validation ───────────────────────────────────────────────
    console.print("\n[bold blue]✅ Validating...[/bold blue]")
    if not files_modified:
        val_ok, val_msg = True, "Skipped (read-only request — no files modified)"
        console.print(f"  [dim]{val_msg}[/dim]")
    else:
        try:
            val_ok, val_msg = validate_repo(repo_root)
        except Exception as e:
            val_ok, val_msg = False, str(e)

        if val_ok:
            console.print("  [green]✅ Validation passed[/green]")
        else:
            console.print("  [red]❌ Validation failed — rolling back all files[/red]")
            for bak, orig in all_backups:
                try:
                    restore_file(bak, orig)
                    console.print(f"    [yellow]↩ Restored {os.path.relpath(orig, repo_root)}[/yellow]")
                except Exception as re_err:
                    console.print(f"    [red]Could not restore {orig}: {re_err}[/red]")

    # ── 6. Report ─────────────────────────────────────────────────────────────
    console.print("\n[bold blue]📋 Generating report...[/bold blue]")
    try:
        report_path, run_id, llm_summary, diff_stat = generate_report(
            llm_cfg, repo_root, request, summary_str, plan, results, (val_ok, val_msg)
        )
        console.print(f"  [bold green]Report:[/bold green] {report_path}")
        console.print(f"  [bold]Summary:[/bold] {llm_summary}")
        if files_modified:
            console.print(f"  [bold]Git diff --stat:[/bold]\n{diff_stat}")
    except Exception as e:
        console.print(f"  [red]Report generation failed: {e}[/red]")

    # ── Update session context ────────────────────────────────────────────────
    session.update(request, results, val_ok, val_msg)

    return files_modified


def _print_banner(llm_cfg: dict, repo_root: str):
    repo_name = os.path.basename(repo_root.rstrip("/"))
    console.print(Panel(
        f"[bold cyan]🤖 AI CODING AGENT[/bold cyan]\n\n"
        f"Repository: [green]{repo_name}[/green]\n"
        f"Provider  : [green]{llm_cfg['provider']}[/green]\n"
        f"Model     : [green]{llm_cfg['model']}[/green]",
        expand=False
    ))


def main():
    parser = argparse.ArgumentParser(description="AI Coding Agent")
    parser.add_argument("request", nargs="?", default=None, help="Plain-English feature request")
    parser.add_argument("--repo-url", help="Git URL to clone")
    parser.add_argument("--repo",     help="Path to existing repo")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--model",    help="Override model name")
    args = parser.parse_args()

    # ── Config ────────────────────────────────────────────────────────────────
    try:
        llm_cfg = get_llm_config()
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    if args.model:
        llm_cfg["model"] = args.model

    # ── 1. Repo acquisition (ONCE) ────────────────────────────────────────────
    console.rule("[bold blue]1 · Repo Acquisition")
    try:
        repo_root = _pick_repo(args)
    except Exception as e:
        console.print(f"[red]Failed to acquire repo: {e}[/red]")
        sys.exit(1)
    set_repo_root(repo_root)

    # ── 2. Initial exploration (ONCE) ─────────────────────────────────────────
    console.rule("[bold blue]2 · 🔍 Exploring Repository")
    console.print("[dim]Analyzing repository...[/dim]")
    summary = explore(repo_root)
    summary_str = summary_text(summary)
    console.print(summary_str)

    # ── Session init ──────────────────────────────────────────────────────────
    session = SessionContext(current_repository_summary=summary_str)
    _print_banner(llm_cfg, repo_root)
    console.print("\n[green]✓ Repository analyzed[/green]")
    console.print("[green]✓ Agent ready[/green]\n")
    console.print("Type your coding request.")
    console.print("Type [bold]'exit'[/bold] to quit.\n")

    # ── Non-interactive single-shot mode (--request provided) ─────────────────
    if args.request:
        _run_prompt(llm_cfg, repo_root, summary_str, args.request, args.yes, session)
        return

    # ── Interactive session loop ───────────────────────────────────────────────
    while True:
        try:
            request = console.input("[bold green]You ›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]👋 Session ended.[/yellow]")
            break

        if not request:
            continue

        if request.lower() in ("exit", "quit"):
            console.print("[yellow]👋 Session ended.[/yellow]")
            break

        if request.lower() == "/help":
            console.print("  Commands: exit, quit, /help, /status, /clear")
            continue

        if request.lower() == "/status":
            console.print(f"  Repo   : {repo_root}")
            console.print(f"  Turns  : {len(session.recent_requests)}")
            if session.recent_requests:
                console.print(f"  Last   : {session.recent_requests[-1]}")
            continue

        if request.lower() == "/clear":
            session = SessionContext(current_repository_summary=summary_str)
            console.print("  [dim]Session context cleared.[/dim]")
            continue

        try:
            files_modified = _run_prompt(
                llm_cfg, repo_root, summary_str, request, args.yes, session
            )
        except Exception as e:
            console.print(f"\n[red]❌ Request failed[/red]\n\nReason:\n{e}\n")
            console.print("[dim]The session is still active.[/dim]")
            console.print()
            continue

        # Refresh repo summary after modifications so next prompt sees new files
        if files_modified:
            summary = explore(repo_root)
            summary_str = summary_text(summary)
            session.current_repository_summary = summary_str

        console.rule("[green]✓ Request completed[/green]")
        console.print()


if __name__ == "__main__":
    main()
