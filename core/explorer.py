"""explorer.py — static repo scan, no LLM."""
import os, json
from dataclasses import dataclass, field

ROLE_DIRS = {
    "models": "model", "model": "model",
    "controllers": "controller", "controller": "controller",
    "routes": "route", "route": "route",
    "middleware": "middleware",
    "components": "component", "pages": "page", "views": "view",
    "services": "service", "utils": "util", "helpers": "util",
    "tests": "test", "test": "test", "__tests__": "test",
    "config": "config", "configs": "config",
    "public": "static", "static": "static",
}

@dataclass
class RepositorySummary:
    name: str = ""
    language: str = ""
    framework: str = ""
    db: str = ""
    entry_point: str = ""
    readme_snippet: str = ""
    dependencies: list = field(default_factory=list)
    files_by_role: dict = field(default_factory=dict)
    all_files: list = field(default_factory=list)

def _load_gitignore(root: str) -> set:
    gi = os.path.join(root, ".gitignore")
    ignored = {".git", "node_modules", "__pycache__", ".DS_Store", "dist", "build", ".next"}
    if os.path.isfile(gi):
        for line in open(gi).read().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ignored.add(line.strip("/"))
    return ignored

def explore(root: str) -> RepositorySummary:
    s = RepositorySummary()
    ignored = _load_gitignore(root)

    # package.json
    pkg_path = os.path.join(root, "package.json")
    if os.path.isfile(pkg_path):
        with open(pkg_path) as f:
            pkg = json.load(f)
        s.name = pkg.get("name", os.path.basename(root))
        s.language = "JavaScript/Node.js"
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        s.dependencies = list(deps.keys())
        frameworks = []
        if "express" in deps:   frameworks.append("Express")
        if "react" in deps:     frameworks.append("React")
        s.framework = "+".join(frameworks)
        if "mongoose" in deps:  s.db = "MongoDB/Mongoose"
        if "sequelize" in deps: s.db = "SQL/Sequelize"
        s.entry_point = pkg.get("main", pkg.get("scripts", {}).get("start", ""))

    # README
    for rname in ("README.md", "readme.md", "README.txt"):
        rp = os.path.join(root, rname)
        if os.path.isfile(rp):
            with open(rp) as f:
                s.readme_snippet = f.read()[:800]
            break

    # Walk tree
    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored dirs in-place
        dirnames[:] = [d for d in dirnames if d not in ignored and not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".css", ".html", ".env"):
                continue
            full = os.path.join(dirpath, fname)
            rel  = os.path.relpath(full, root)
            s.all_files.append(rel)
            # classify by parent dir name
            parts = rel.replace("\\", "/").split("/")
            role = "other"
            for part in parts[:-1]:
                if part.lower() in ROLE_DIRS:
                    role = ROLE_DIRS[part.lower()]
                    break
            s.files_by_role.setdefault(role, []).append(rel)

    return s

def summary_text(s: RepositorySummary) -> str:
    lines = [
        f"Project : {s.name}",
        f"Language: {s.language}",
        f"Framework: {s.framework}",
        f"Database: {s.db}",
        f"Entry   : {s.entry_point}",
        f"Files   : {len(s.all_files)} total",
    ]
    for role, files in s.files_by_role.items():
        lines.append(f"  [{role}] {', '.join(files[:5])}{'...' if len(files)>5 else ''}")
    return "\n".join(lines)
