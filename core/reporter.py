"""reporter.py — generate a Markdown report for each agent run.

Output: reports/run_NNN.md containing:
  - Original request
  - Repository summary
  - Plan JSON
  - Per-file results (edited / read / skipped)
  - Validation status
  - Git diff stat + full diff  (edit runs)
  - "Repository Modified: No"  (read-only runs)
  - 3–5 sentence LLM-generated plain-English summary
"""
import os, json, subprocess
from datetime import datetime
from config import REPORTS_DIR
import llm

def _next_run_id() -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    existing = [f for f in os.listdir(REPORTS_DIR) if f.startswith("run_") and f.endswith(".md")]
    nums = [int(f[4:7]) for f in existing if f[4:7].isdigit()]
    return f"{(max(nums) + 1 if nums else 1):03d}"

def _git_diff_stat(repo_root: str) -> str:
    try:
        r = subprocess.run(["git", "diff", "--stat"], cwd=repo_root,
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "(no git diff)"
    except Exception:
        return "(git diff unavailable)"

def _git_diff(repo_root: str) -> str:
    try:
        r = subprocess.run(["git", "diff"], cwd=repo_root,
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()[:8000] or "(no changes)"
    except Exception:
        return "(git diff unavailable)"

def generate_report(cfg: dict, repo_root: str, request: str, repo_summary: str,
                    plan: dict, results: list, val_result: tuple) -> str:
    run_id   = _next_run_id()
    out_path = os.path.join(REPORTS_DIR, f"run_{run_id}.md")

    read_only = all(r["status"] == "read" for r in results) if results else False
    ok_files   = [r["file"] for r in results if r["status"] == "ok"]
    skip_files = [r["file"] for r in results if r["status"] == "skipped"]
    read_files = [r["file"] for r in results if r["status"] == "read"]

    # LLM summary
    if read_only:
        summary_prompt = (
            f"Request: {request}\n"
            f"Files read: {read_files}\n"
            f"Repository summary: {repo_summary}\n"
            "Write 3-5 sentences answering the request based on the repository summary. "
            "State clearly that no files were modified. Plain English, no markdown."
        )
    else:
        summary_prompt = (
            f"Request: {request}\n"
            f"Files modified: {ok_files}\n"
            f"Files skipped: {skip_files}\n"
            f"Validation: {'PASSED' if val_result[0] else 'FAILED'}\n"
            "Write 3-5 sentences: what changed, why, and any caveats. Plain English, no markdown."
        )
    llm_summary, _ = llm.chat(cfg, [{"role": "user", "content": summary_prompt}],
                               system="You are a technical writer summarising a code change.")

    lines = [
        f"# Run {run_id} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Request",
        f"> {request}",
        "",
        "## Repository Summary",
        f"```\n{repo_summary}\n```",
        "",
        "## Plan",
        f"```json\n{json.dumps(plan, indent=2)}\n```",
        "",
        "## Per-File Results",
    ]
    for r in results:
        icon = {"ok": "✅", "read": "📖 READ", "skipped": "⚠️ SKIPPED"}.get(r["status"], r["status"])
        lines.append(f"\n### {icon} `{r['file']}`")
        if r["error"]:
            lines.append(f"**Error:** {r['error']}")
        if r["edits"]:
            lines.append(f"**Edits applied:** {len(r['edits'])}")

    lines += [
        "",
        "## Validation",
        f"**Status:** {val_result[1]}",
        "",
    ]

    if read_only:
        lines += [
            "## Repository Modified",
            "No",
            "",
            "## Summary",
            llm_summary,
        ]
        diff_stat = "(no changes)"
    else:
        diff_stat = _git_diff_stat(repo_root)
        diff_full = _git_diff(repo_root)
        lines += [
            "## Git Diff Stat",
            f"```\n{diff_stat}\n```",
            "",
            "## Full Diff",
            f"```diff\n{diff_full}\n```",
            "",
            "## Summary",
            llm_summary,
        ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    return out_path, run_id, llm_summary, diff_stat
