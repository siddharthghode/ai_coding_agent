"""
config.py — load env, auto-detect LLM provider from whichever key is present.
Priority: ANTHROPIC > OPENAI > GEMINI > XAI (Grok) > GROQ
"""
import os
from dotenv import load_dotenv

load_dotenv()

def get_llm_config() -> dict:
    """Return {provider, api_key, model} for the first available key."""
    checks = [
        ("anthropic", os.getenv("ANTHROPIC_API_KEY"), "claude-opus-4-5"),
        ("openai",    os.getenv("OPENAI_API_KEY"),    "gpt-4o"),
        ("gemini",    os.getenv("GEMINI_API_KEY"),    "gemini-2.0-flash"),
        ("xai",         os.getenv("XAI_API_KEY"),         "grok-beta"),
        ("openrouter",  os.getenv("OPENROUTER_API_KEY"),  "openai/gpt-4o"),
        ("groq",         os.getenv("GROQ_API_KEY"),         "llama-3.3-70b-versatile"),
    ]
    for provider, key, model in checks:
        if key and not key.startswith("<"):
            return {"provider": provider, "api_key": key, "model": model}
    raise EnvironmentError(
        "No LLM API key found. Set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "GEMINI_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY in .env or environment."
    )

WORKSPACE_DIR = os.path.join(os.path.dirname(__file__), "workspace")
REPORTS_DIR   = os.path.join(os.path.dirname(__file__), "reports")
BACKUPS_DIR   = os.path.join(os.path.dirname(__file__), "backups")
LOGS_DIR      = os.path.join(os.path.dirname(__file__), "logs")
