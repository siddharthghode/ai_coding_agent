#!/usr/bin/env python3
"""
agent.py — CLI entry point for the AI Coding Agent.

Orchestrates the 6-step workflow:
  1. Repo acquisition  — clone or select from workspace/
  2. Explore           — static scan, zero LLM calls
  3. Plan              — LLM produces structured JSON plan
  4. Modify            — per-file surgical edits with retry
  5. Validate          — syntax + npm install + boot check (edit runs only)
  6. Report            — reports/run_NNN.md + terminal summary

Usage:
  python agent.py                           # fully interactive
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

console = Console()


def _pick_repo(args) -> str:
    """Interactive repo selection or use CLI args. Returns repo_root."""
    # If CLI args provided, use them directly
    if args.repo_url or args.repo:
        return acquire_repo(args.repo_url, args.repo)

    # Discover existing repos in workspace/
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


def _run_prompt(llm_cfg: dict, repo_root: str, summary_str: str, request: str, yes: bool):
    """Run one full plan→modify→validate→report cycle for a single request."""

    console.print(Panel(
        f"[bold cyan]AI Coding Agent[/bold cyan]\n"
        f"Provider: [green]{llm_cfg['provider']}[/green]  Model: [green]{llm_cfg['model']}[/green]\n"
        f"Request : [yellow]{request}[/yellow]",
        expand=False
    ))

    # ── 3. Plan ───────────────────────────────────────────────────────────────
    console.rule("[bold blue]3 · 📋 Planning")
    with open(os.path.join(os.path.dirname(__file__), "prompts/planner_system.txt")) as f:
        planner_system = f.read()
    console.print("[dim]Calling LLM to create plan…[/dim]")
    try:
        plan = create_plan(llm_cfg, planner_system, summary_str, request, console=console)
    except Exception as e:
        console.print(f"[red]Planning failed: {e}[/red]")
        return

    console.print(Syntax(json.dumps(plan, indent=2), "json", theme="monokai"))

    # ── Pre-edit confirmation ─────────────────────────────────────────────────
    edit_steps = [s for s in plan.get("steps", []) if s.get("action", "modify") != "read"]
    if edit_steps and not yes:
        console.rule("[bold yellow]── Confirm Edits ──")
        answer = console.input("[bold yellow]Proceed with editing files? (yes/no): [/bold yellow]").strip().lower()
        console.rule()
        if answer not in ("y", "yes"):
            console.print("[yellow]Skipped edits — no files changed.[/yellow]")
            return

    # ── 4. Modify ─────────────────────────────────────────────────────────────
    console.rule("[bold blue]4 · ✏️  Modifying Files")
    with open(os.path.join(os.path.dirname(__file__), "prompts/modifier_system.txt")) as f:
        modifier_system = f.read()
    results = []
    all_backups = []
    files_modified = False

    for step in plan.get("steps", []):
        file_path = step["file"]
        action = step.get("action", "modify")

        if action == "read":
            console.print(f"\n[bold blue]📖 Reading:[/bold blue] {file_path}")
            console.print(f"   [dim]{step['description']}[/dim]")
            results.append({"file": file_path, "status": "read", "edits": [], "error": None, "backup": None})
            continue

        console.print(f"\n[bold cyan]✏️  Editing:[/bold cyan] {file_path}")
        console.print(f"   [dim]{step['description']}[/dim]")

        result = apply_step(llm_cfg, modifier_system, repo_root, step, console=console)
        results.append(result)

        if result["backup"]:
            all_backups.append((result["backup"], os.path.join(repo_root, file_path)))

        if result["status"] == "ok":
            files_modified = True
            console.print(f"  [green]✅ Done[/green] ({len(result['edits'])} edit(s))")
        else:
            console.print(f"  [red]⚠️  Skipped — {result['error']}[/red]")

    # ── 5. Whole-repo validation ───────────────────────────────────────────────
    console.rule("[bold blue]5 · ✅ Validating Repository")
    if not files_modified:
        val_ok, val_msg = True, "Skipped (read-only request — no files modified)"
        console.print(f"[dim]{val_msg}[/dim]")
    else:
        console.print("[dim]Running npm install + boot check…[/dim]")
        try:
            val_ok, val_msg = validate_repo(repo_root)
        except Exception as e:
            val_ok, val_msg = False, str(e)

        if val_ok:
            console.print("[green]✅ Validation passed[/green]")
        else:
            console.print(f"[red]❌ Validation failed — rolling back all files[/red]")
            for bak, orig in all_backups:
                try:
                    restore_file(bak, orig)
                    console.print(f"  [yellow]↩ Restored {os.path.relpath(orig, repo_root)}[/yellow]")
                except Exception as re_err:
                    console.print(f"  [red]Could not restore {orig}: {re_err}[/red]")

    # ── 6. Report ─────────────────────────────────────────────────────────────
    console.rule("[bold blue]6 · 🧾 Generating Report")
    try:
        report_path, run_id, llm_summary, diff_stat = generate_report(
            llm_cfg, repo_root, request, summary_str, plan, results, (val_ok, val_msg)
        )
        console.print(f"\n[bold green]Report:[/bold green] {report_path}")
        console.print(f"\n[bold]Summary:[/bold] {llm_summary}")
        if files_modified:
            console.print(f"\n[bold]Git diff --stat:[/bold]\n{diff_stat}")
    except Exception as e:
        console.print(f"[red]Report generation failed: {e}[/red]")


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

    # ── 1. Repo selection ─────────────────────────────────────────────────────
    console.rule("[bold blue]1 · Repo Acquisition")
    try:
        repo_root = _pick_repo(args)
    except Exception as e:
        console.print(f"[red]Failed to acquire repo: {e}[/red]")
        sys.exit(1)
    console.print(f"[green]✓[/green] Repo: {repo_root}")
    set_repo_root(repo_root)

    # ── 2. Explore (once per repo) ────────────────────────────────────────────
    console.rule("[bold blue]2 · 🔍 Exploring Repository")
    summary = explore(repo_root)
    summary_str = summary_text(summary)
    console.print(summary_str)

    # ── Prompt loop ───────────────────────────────────────────────────────────
    first = True
    while True:
        if args.request and first:
            request = args.request
            first = False
        else:
            console.print()
            request = console.input("[bold green]Enter your request[/bold green] [dim](or 'exit' to quit)[/dim]: ").strip()
            if request.lower() in ("exit", "quit", ""):
                console.print("[yellow]Goodbye![/yellow]")
                break

        _run_prompt(llm_cfg, repo_root, summary_str, request, args.yes)

        console.print()
        console.rule("[bold yellow]── Session ──")
        again = console.input("[bold yellow]Run another prompt on this repo? (yes/no): [/bold yellow]").strip().lower()
        console.rule()
        if again not in ("y", "yes"):
            console.print("[yellow]Done.[/yellow]")
            break
        args.request = None

if __name__ == "__main__":
    main()
