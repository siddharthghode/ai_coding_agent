"""workspace.py — repo acquisition and file backup/restore.

acquire_repo()  — clone a URL into workspace/, use an existing path, or fall back to cwd.
backup_file()   — copy a file to backups/ before editing; returns the backup path.
restore_file()  — copy backup back to original path (used on validation failure or retry).
"""
import os, shutil, subprocess
from datetime import datetime
from config import WORKSPACE_DIR, BACKUPS_DIR

def acquire_repo(repo_url: str | None, repo_path: str | None) -> str:
    """Return absolute path to the working repo directory."""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    if repo_path:
        path = os.path.abspath(repo_path)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"Repo path not found: {path}")
        return path
    if repo_url:
        name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        dest = os.path.join(WORKSPACE_DIR, name)
        if os.path.isdir(dest):
            return dest
        subprocess.run(["git", "clone", repo_url, dest], check=True)
        return dest
    # fallback: cwd
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, ".git")):
        return cwd
    raise ValueError("No repo specified and cwd has no .git. Use --repo or --repo-url.")

def backup_file(repo_root: str, file_path: str) -> str:
    """Copy file to backups/ and return backup path."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    rel = os.path.relpath(file_path, repo_root)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(BACKUPS_DIR, f"{rel.replace(os.sep,'_')}_{ts}.bak")
    shutil.copy2(file_path, bak)
    return bak

def restore_file(backup_path: str, original_path: str):
    shutil.copy2(backup_path, original_path)
