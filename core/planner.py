"""planner.py — LLM call #1: produce structured plan with optional tool use."""
import json
import llm
from core.tools import TOOL_SCHEMAS, TOOL_MAP

PLANNER_TOOLS = [s for s in TOOL_SCHEMAS if s["name"] in ("list_files", "read_file", "search_code")]

def create_plan(cfg: dict, system: str, repo_summary: str, request: str, console=None) -> dict:
    messages = [{
        "role": "user",
        "content": f"REPOSITORY SUMMARY:\n{repo_summary}\n\nUSER REQUEST:\n{request}\n\nProduce the plan JSON."
    }]

    # Groq's tool-calling is unreliable — disable tools to avoid malformed calls
    tools = None if cfg["provider"] == "groq" else PLANNER_TOOLS

    for _ in range(10):  # tool-use loop
        text, calls = llm.chat(cfg, messages, system, tools=tools)

        if not calls:
            # LLM is done — extract JSON
            raw = text.strip()
            # strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
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
