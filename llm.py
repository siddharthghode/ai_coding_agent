"""
llm.py — thin multi-provider LLM client.

Supports 6 providers through a single chat() interface:
  - Anthropic (Claude)   — native tool calling
  - OpenAI (GPT)         — native tool calling
  - Google (Gemini)      — FunctionDeclaration tool calling
  - xAI (Grok)           — OpenAI-compatible
  - OpenRouter           — OpenAI-compatible proxy
  - Groq (LLaMA)         — OpenAI-compatible, tools disabled in planner

Public API:
  chat(cfg, messages, system, tools)         — unified LLM call
  make_tool_result(cfg, id, name, content)   — build tool-result message
  make_tool_call_message(cfg, text, calls)   — build assistant tool-call message
"""
import json

def _anthropic_chat(cfg, messages, system, tools):
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["api_key"])
    kwargs = dict(model=cfg["model"], max_tokens=8096, system=system, messages=messages)
    if tools:
        kwargs["tools"] = tools
    resp = client.messages.create(**kwargs)
    text = next((b.text for b in resp.content if b.type == "text"), "")
    calls = [
        {"name": b.name, "id": b.id, "input": b.input}
        for b in resp.content if b.type == "tool_use"
    ]
    return text, calls

def _openai_chat(cfg, messages, system, tools):
    from openai import OpenAI
    client = OpenAI(api_key=cfg["api_key"],
                    base_url="https://api.x.ai/v1" if cfg["provider"] == "xai"
                    else "https://openrouter.ai/api/v1" if cfg["provider"] == "openrouter"
                    else "https://api.groq.com/openai/v1" if cfg["provider"] == "groq"
                    else None)
    msgs = [{"role": "system", "content": system}] + messages
    kwargs = dict(model=cfg["model"], messages=msgs)
    if tools:
        kwargs["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["input_schema"]
        }} for t in tools]
        kwargs["tool_choice"] = "auto"
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    text = msg.content or ""
    calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            calls.append({"name": tc.function.name, "id": tc.id,
                          "input": json.loads(tc.function.arguments)})
    return text, calls

def _gemini_chat(cfg, messages, system, tools):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=cfg["api_key"])
    tool_defs = None
    if tools:
        decls = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                            parameters=t["input_schema"]) for t in tools]
        tool_defs = [types.Tool(function_declarations=decls)]
    # Build contents from messages
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        content = m["content"] if isinstance(m["content"], str) else str(m["content"])
        contents.append(types.Content(role=role, parts=[types.Part(text=content)]))
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tool_defs,
    )
    resp = client.models.generate_content(model=cfg["model"], contents=contents, config=config)
    text = ""
    calls = []
    for part in resp.candidates[0].content.parts:
        if part.text:
            text += part.text
        if part.function_call and part.function_call.name:
            fc = part.function_call
            calls.append({"name": fc.name, "id": fc.name, "input": dict(fc.args)})
    return text, calls

def chat(cfg: dict, messages: list, system: str, tools: list | None = None):
    """Unified chat call. Returns (text: str, tool_calls: list[dict])."""
    p = cfg["provider"]
    if p == "anthropic":
        return _anthropic_chat(cfg, messages, system, tools)
    elif p in ("openai", "xai", "openrouter", "groq"):
        return _openai_chat(cfg, messages, system, tools)
    elif p == "gemini":
        return _gemini_chat(cfg, messages, system, tools)
    else:
        raise ValueError(f"Unknown provider: {p}")

def make_tool_result(cfg: dict, tool_id: str, tool_name: str, content: str) -> dict:
    """Build a tool-result message in the format the provider expects."""
    p = cfg["provider"]
    if p == "anthropic":
        return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}]}
    elif p == "gemini":
        return {"role": "user", "content": f"Tool {tool_name} result: {content}"}
    else:  # openai / xai / openrouter / groq
        return {"role": "tool", "tool_call_id": tool_id, "name": tool_name, "content": content}

def make_tool_call_message(cfg: dict, text: str, calls: list) -> dict:
    """Build the assistant message that contains tool calls (for conversation history)."""
    p = cfg["provider"]
    if p == "anthropic":
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for c in calls:
            content.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]})
        return {"role": "assistant", "content": content}
    else:
        return {"role": "assistant", "content": text or None,
                "tool_calls": [{"id": c["id"], "type": "function",
                                 "function": {"name": c["name"],
                                              "arguments": json.dumps(c["input"])}} for c in calls]}
