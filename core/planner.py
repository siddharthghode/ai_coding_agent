"""planner.py — LLM call #1: produce a structured JSON plan.

The planner receives the RepositorySummary + user request and may call
read_file / search_code / list_files tools to inspect the repo before
committing to a plan.

Output schema:
  {
    "goal": str,
    "rationale": str,
    "files": [str],
    "steps": [{"file": str, "action": "read|modify|create", "description": str}]
  }

Note: tools are disabled for Groq (unreliable tool-call generation).
"""
import json
import llm
from core.tools import TOOL_SCHEMAS, TOOL_MAP

PLANNER_TOOLS = [s for s in TOOL_SCHEMAS if s["name"] in ("list_files", "read_file", "search_code")]

def create_plan(cfg: dict, system: str, repo_summary: str, request: str,
                console=None, session_context: str = "") -> dict:
    context_block = f"\n\n{session_context}" if session_context else ""
    messages = [{
        "role": "user",
        "content": (
            f"REPOSITORY SUMMARY:\n{repo_summary}"
            f"{context_block}"
            f"\n\nUSER REQUEST:\n{request}\n\nProduce the plan JSON."
        )
    }]

    # Groq's tool-calling is disabled — remove tool prompts so it produces JSON directly
    tools = None if cfg["provider"] == "groq" else PLANNER_TOOLS
    if tools is None:
        system = system.replace("You have access to tools: list_files, read_file, search_code. Use them to inspect the repo before finalising the plan.\n", "")
        system = system.replace("- Call search_code / read_file as needed to find exact symbols, routes, schema fields.\n", "")

    for _ in range(10):  # tool-use loop
        text, calls = llm.chat(cfg, messages, system, tools=tools)

        if not calls:
            # LLM is done — extract JSON
            raw = text.strip()
            # strip markdown fences if present
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())

        # Execute tool calls and feed results back
        messages.append(llm.make_tool_call_message(cfg, text, calls))
        for call in calls:
            fn   = TOOL_MAP.get(call["name"])
            result = fn(call["input"]) if fn else f"Unknown tool: {call['name']}"
            if console:
                console.print(f"  [dim]🔧 {call['name']}({list(call['input'].values())[:1]})[/dim]")
            messages.append(llm.make_tool_result(cfg, call["id"], call["name"], result))

    raise RuntimeError("Planner did not produce a plan after 10 iterations.")
