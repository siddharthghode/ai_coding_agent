"""session.py — lightweight multi-turn session context.

Maintains a compact history of previous requests, changes, and validation
results so the planner can understand follow-up prompts (e.g. "now add logout"
after "add JWT auth").

Only the last N entries are kept to avoid unbounded context growth.
"""
from dataclasses import dataclass, field

MAX_HISTORY = 5  # keep last 5 turns in context


@dataclass
class SessionContext:
    recent_requests: list = field(default_factory=list)
    recent_changes: list = field(default_factory=list)
    validation_results: list = field(default_factory=list)
    current_repository_summary: str = ""

    def update(self, request: str, results: list, val_ok: bool, val_msg: str):
        """Record the outcome of one completed prompt cycle."""
        modified = [r["file"] for r in results if r["status"] == "ok"]
        skipped  = [r["file"] for r in results if r["status"] == "skipped"]

        self.recent_requests.append(request)
        self.recent_changes.append({"request": request, "modified": modified, "skipped": skipped})
        self.validation_results.append({"request": request, "ok": val_ok, "msg": val_msg})

        # trim to last N
        self.recent_requests  = self.recent_requests[-MAX_HISTORY:]
        self.recent_changes   = self.recent_changes[-MAX_HISTORY:]
        self.validation_results = self.validation_results[-MAX_HISTORY:]

    def as_text(self) -> str:
        """Compact text representation injected into the planner prompt."""
        if not self.recent_requests:
            return ""
        lines = ["PREVIOUS SESSION CONTEXT:"]
        for i, (req, chg, val) in enumerate(
            zip(self.recent_requests, self.recent_changes, self.validation_results), 1
        ):
            status = "✓ passed" if val["ok"] else "✗ failed"
            files  = ", ".join(chg["modified"]) or "none"
            lines.append(f"  [{i}] Request : {req}")
            lines.append(f"       Modified: {files}")
            lines.append(f"       Validation: {status}")
        return "\n".join(lines)
