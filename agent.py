#!/usr/bin/env python3
"""
agent.py — AI Coding Agent entry point.

Usage:
  python agent.py "Add search to notes" --repo-url https://github.com/callicoder/node-easy-notes-app
  python agent.py "Add note pinning" --repo /path/to/repo --yes
"""
import argparse, json, os, sys
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from config import get_llm_config
from core.workspace import acquire_repo, restore_file
from core.explorer import explore, summary_text
from core.tools import set_repo_root
from core.planner import create_plan
from core.modifier import apply_step
from core.validator import validate_repo
from core.reporter import generate_report

console = Console()

def main():
    parser = argparse.ArgumentParser(description="AI Coding Agent")
    parser.add_argument("request", nargs="?", default=None, help="Plain-English feature request")
    parser.add_argument("--repo-url", help="Git URL to clone")
    parser.add_argument("--repo",     help="Path to existing repo")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--model",    help="Override model name")
    args = parser.parse_args()

    if not args.request:
        console.print("[red]Error:[/red] Please provide a feature request as the first argument.")
        sys.exit(1)

    # ── Config ────────────────────────────────────────────────────────────────
    try:
        llm_cfg = get_llm_config()
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    if args.model:
        llm_cfg["model"] = args.model

    console.print(Panel(
        f"[bold cyan]AI Coding Agent[/bold cyan]\n"
        f"Provider: [green]{llm_cfg['provider']}[/green]  Model: [green]{llm_cfg['model']}[/green]\n"
        f"Request : [yellow]{args.request}[/yellow]",
        expand=False
    ))

    # ── 1. Repo acquisition ───────────────────────────────────────────────────
    console.rule("[bold blue]1 · Repo Acquisition")
    try:
        repo_root = acquire_repo(args.repo_url, args.repo)
    except Exception as e:
        console.print(f"[red]Failed to acquire repo: {e}[/red]")
        sys.exit(1)
    console.print(f"[green]✓[/green] Repo: {repo_root}")
    set_repo_root(repo_root)

    # ── 2. Explore ────────────────────────────────────────────────────────────
    console.rule("[bold blue]2 · 🔍 Exploring Repository")
    summary = explore(repo_root)
    summary_str = summary_text(summary)
    console.print(summary_str)

    # ── 3. Plan ───────────────────────────────────────────────────────────────
    console.rule("[bold blue]3 · 📋 Planning")
    with open(os.path.join(os.path.dirname(__file__), "prompts/planner_system.txt")) as f:
        planner_system = f.read()
    console.print("[dim]Calling LLM to create plan (may use search_code/read_file tools)…[/dim]")
    try:
        plan = create_plan(llm_cfg, planner_system, summary_str, args.request, console=console)
    except Exception as e:
        console.print(f"[red]Planning failed: {e}[/red]")
        sys.exit(1)

    console.print(Syntax(json.dumps(plan, indent=2), "json", theme="monokai"))

    if not args.yes:
        answer = console.input("\n[bold]Proceed with this plan? [y/N][/bold] ").strip().lower()
        if answer != "y":
            console.print("[yellow]Aborted by user.[/yellow]")
            sys.exit(0)

    # ── 4. Modify ─────────────────────────────────────────────────────────────
    console.rule("[bold blue]4 · ✏️  Modifying Files")
    with open(os.path.join(os.path.dirname(__file__), "prompts/modifier_system.txt")) as f:
        modifier_system = f.read()
    results = []
    all_backups = []  # for full rollback

    for step in plan.get("steps", []):
        file_path = step["file"]
        console.print(f"\n[bold cyan]✏️  Editing:[/bold cyan] {file_path}")
        console.print(f"   [dim]{step['description']}[/dim]")

        result = apply_step(llm_cfg, modifier_system, repo_root, step, console=console)
        results.append(result)

        if result["backup"]:
            all_backups.append((result["backup"], os.path.join(repo_root, file_path)))

        if result["status"] == "ok":
            console.print(f"  [green]✅ Done[/green] ({len(result['edits'])} edit(s))")
        else:
            console.print(f"  [red]⚠️  Skipped — {result['error']}[/red]")

    # ── 5. Whole-repo validation ───────────────────────────────────────────────
    console.rule("[bold blue]5 · ✅ Validating Repository")
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
            llm_cfg, repo_root, args.request, summary_str, plan, results, (val_ok, val_msg)
        )
        console.print(f"\n[bold green]Report:[/bold green] {report_path}")
        console.print(f"\n[bold]Summary:[/bold] {llm_summary}")
        console.print(f"\n[bold]Git diff --stat:[/bold]\n{diff_stat}")
    except Exception as e:
        console.print(f"[red]Report generation failed: {e}[/red]")

if __name__ == "__main__":
    main()
