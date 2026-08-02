"""tools.py — tool functions callable by the LLM + their JSON schema definitions."""
import os, re, subprocess, json

_repo_root: str = ""

def set_repo_root(path: str):
    global _repo_root
    _repo_root = path

def _abs(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(_repo_root, path)

# ── tool implementations ──────────────────────────────────────────────────────

def list_files(path: str = ".") -> str:
    base = _abs(path)
    if not os.path.exists(base):
        return f"Path not found: {path}"
    lines = []
    ignored = {"node_modules", ".git", "__pycache__", "dist", "build", ".next"}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ignored]
        rel_root = os.path.relpath(root, _repo_root)
        depth = rel_root.count(os.sep)
        indent = "  " * depth
        lines.append(f"{indent}{os.path.basename(root)}/")
        for f in files:
            lines.append(f"{indent}  {f}")
    return "\n".join(lines)

def read_file(path: str) -> str:
    try:
        with open(_abs(path)) as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {e}"

def write_file(path: str, content: str) -> str:
    full = _abs(path)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return f"Written: {path}"

def edit_file(path: str, old_str: str, new_str: str) -> str:
    full = _abs(path)
    try:
        with open(full) as f:
            src = f.read()
    except Exception as e:
        return f"ERROR reading {path}: {e}"
    count = src.count(old_str)
    if count == 0:
        return f"ERROR: old_str not found in {path}"
    if count > 1:
        return f"ERROR: old_str matches {count} locations in {path} — make it more specific"
    with open(full, "w") as f:
        f.write(src.replace(old_str, new_str, 1))
    return f"OK: edited {path}"

def search_code(query: str) -> str:
    results = []
    ignored = {"node_modules", ".git", "__pycache__", "dist", "build"}
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    for root, dirs, files in os.walk(_repo_root):
        dirs[:] = [d for d in dirs if d not in ignored]
        for fname in files:
            if not fname.endswith((".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".css")):
                continue
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, _repo_root)
            try:
                with open(full) as fh:
                    for i, line in enumerate(fh, 1):
                        if pattern.search(line):
                            results.append(f"{rel}:{i}: {line.rstrip()}")
            except Exception:
                pass
    return "\n".join(results[:80]) if results else "No matches found."

def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    work_dir = _abs(cwd) if cwd != "." else _repo_root
    try:
        r = subprocess.run(cmd, shell=True, cwd=work_dir, capture_output=True,
                           text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return f"exit={r.returncode}\n{out[:3000]}"
    except subprocess.TimeoutExpired:
        return f"exit=timeout after {timeout}s"
    except Exception as e:
        return f"exit=error: {e}"

# ── LLM tool schemas ──────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "list_files",
        "description": "List directory tree of the repo (ignores node_modules/.git).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path, default '.'"}},
            "required": []
        }
    },
    {
        "name": "read_file",
        "description": "Read full content of a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "search_code",
        "description": "Regex/keyword search across all source files. Returns file:line matches.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    },
    {
        "name": "edit_file",
        "description": "Surgical find-and-replace in a file. old_str must match exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "old_str": {"type": "string", "description": "Exact string to find (must be unique)"},
                "new_str": {"type": "string", "description": "Replacement string"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    {
        "name": "write_file",
        "description": "Write a brand-new file. Do NOT use for existing files — use edit_file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the repo. Returns stdout+stderr+exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd":     {"type": "string"},
                "cwd":     {"type": "string", "description": "Relative dir, default repo root"},
                "timeout": {"type": "integer", "default": 30}
            },
            "required": ["cmd"]
        }
    },
]

TOOL_MAP = {
    "list_files":   lambda i: list_files(i.get("path", ".")),
    "read_file":    lambda i: read_file(i["path"]),
    "write_file":   lambda i: write_file(i["path"], i["content"]),
    "edit_file":    lambda i: edit_file(i["path"], i["old_str"], i["new_str"]),
    "search_code":  lambda i: search_code(i["query"]),
    "run_command":  lambda i: run_command(i["cmd"], i.get("cwd", "."), i.get("timeout", 30)),
}
