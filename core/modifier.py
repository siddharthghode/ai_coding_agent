"""modifier.py — per-file LLM surgical edits with validation and retry.

For each plan step:
  1. Back up the file.
  2. Send file content + task to the modifier LLM.
  3. LLM returns [{old_str, new_str}, ...] edit operations.
  4. Apply edits via exact string match (old_str must match exactly once).
  5. Validate syntax immediately after applying.
  6. On any failure, restore backup and retry up to MAX_RETRIES times.
  7. After all retries exhausted, restore and mark step as 'skipped'.
"""
import json, os
import llm
from core.tools import read_file, write_file, edit_file
from core.workspace import backup_file, restore_file
from core.validator import validate_file

MAX_RETRIES = 3

def _parse_edits(text: str) -> list:
    raw = text.strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]
    return json.loads(raw.strip())

def apply_step(cfg: dict, system: str, repo_root: str, step: dict, console=None) -> dict:
    """
    Apply one plan step. Returns:
      {"file": path, "status": "ok"|"skipped", "edits": [...], "error": str|None, "backup": path}
    """
    path    = step["file"]
    desc    = step["description"]
    abs_path = os.path.join(repo_root, path)

    # Backup
    backup = None
    if os.path.isfile(abs_path):
        backup = backup_file(repo_root, abs_path)

    current_content = read_file(path) if os.path.isfile(abs_path) else ""

    messages = [{
        "role": "user",
        "content": (
            f"FILE: {path}\n\n"
            f"CURRENT CONTENT:\n```\n{current_content}\n```\n\n"
            f"TASK: {desc}\n\n"
            "Respond with ONLY the JSON array of edit operations."
        )
    }]

    last_error = None
    applied_edits = []

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1 and console:
            console.print(f"  [yellow]⚠️  Retry {attempt}/{MAX_RETRIES} — {last_error}[/yellow]")

        text, _ = llm.chat(cfg, messages, system, tools=None)

        try:
            edits = _parse_edits(text)
        except Exception as e:
            last_error = f"JSON parse error: {e}"
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"Your response was not valid JSON: {e}. Try again."})
            continue

        # Apply edits
        apply_errors = []
        applied_this = []
        for op in edits:
            old_s = op.get("old_str", "")
            new_s = op.get("new_str", "")
            if old_s == "__NEW_FILE__":
                result = write_file(path, new_s)
            else:
                result = edit_file(path, old_s, new_s)
            if result.startswith("ERROR"):
                apply_errors.append(result)
            else:
                applied_this.append(op)

        if apply_errors:
            last_error = "; ".join(apply_errors)
            # Restore for retry
            if backup:
                restore_file(backup, abs_path)
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user",
                              "content": f"Edit failed: {last_error}\nCurrent file content:\n```\n{read_file(path)}\n```\nFix and retry."})
            continue

        # Per-file syntax validation
        val_ok, val_msg = validate_file(abs_path)
        if not val_ok:
            last_error = val_msg
            if backup:
                restore_file(backup, abs_path)
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user",
                              "content": f"Syntax validation failed: {val_msg}\nCurrent file:\n```\n{read_file(path)}\n```\nFix and retry."})
            continue

        applied_edits = applied_this
        return {"file": path, "status": "ok", "edits": applied_edits, "error": None, "backup": backup}

    # All retries exhausted
    if backup and os.path.isfile(abs_path):
        restore_file(backup, abs_path)
    return {"file": path, "status": "skipped", "edits": [], "error": last_error, "backup": backup}
