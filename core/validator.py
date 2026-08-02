"""validator.py — per-file syntax checks and whole-repo validation.

validate_file()  — fast syntax check for a single file:
  .json           — json.loads
  .js/.jsx/.ts/.tsx — node --check

validate_repo()  — full repo health check (only runs when files were modified):
  1. npm install (root + client/ if present)
  2. Boot check  — npm start, wait 8s, look for listen/connect signal
  3. npm test    — if a test script exists in package.json
"""
import os, json, subprocess

def validate_file(abs_path: str) -> tuple[bool, str]:
    """Quick per-file syntax check. Returns (ok, message)."""
    ext = os.path.splitext(abs_path)[1].lower()
    if ext == ".json":
        try:
            with open(abs_path) as f:
                json.loads(f.read())
            return True, "JSON valid"
        except json.JSONDecodeError as e:
            return False, f"JSON parse error: {e}"
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        r = subprocess.run(["node", "--check", abs_path],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return True, "syntax ok"
        return False, (r.stderr or r.stdout).strip()[:500]
    return True, "no check"

def validate_repo(repo_root: str) -> tuple[bool, str]:
    """
    Whole-repo validation:
    1. npm install (backend + client/)
    2. Boot check (npm start with timeout, look for listen/connect signal)
    3. npm test if present
    """
    results = []

    def npm(cwd_rel, cmd, timeout=120):
        cwd = os.path.join(repo_root, cwd_rel) if cwd_rel else repo_root
        if not os.path.isfile(os.path.join(cwd, "package.json")):
            return True, f"no package.json in {cwd_rel or '.'}"
        r = subprocess.run(f"npm {cmd}", shell=True, cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        return ok, (r.stdout + r.stderr).strip()[-800:]

    # npm install
    for d in ["", "client"]:
        ok, msg = npm(d, "install", timeout=180)
        results.append(f"npm install {'(client)' if d else '(root)'}: {'OK' if ok else 'FAIL'}\n{msg}")
        if not ok:
            return False, "\n".join(results)

    # Boot check
    pkg_path = os.path.join(repo_root, "package.json")
    if os.path.isfile(pkg_path):
        with open(pkg_path) as f:
            pkg = json.load(f)
        start_cmd = pkg.get("scripts", {}).get("start", "")
        if start_cmd:
            import threading, time
            boot_output = []
            proc = subprocess.Popen("npm start", shell=True, cwd=repo_root,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            def reader():
                if proc.stdout:
                    for line in proc.stdout:
                        boot_output.append(line)
            t = threading.Thread(target=reader, daemon=True)
            t.start()
            time.sleep(8)
            proc.terminate()
            t.join(timeout=3)
            combined = "".join(boot_output)
            signals = ("listening", "connected", "running", "started", "ready", "server")
            crashed = ("error", "exception", "cannot", "eaddrinuse", "enoent")
            booted = any(s in combined.lower() for s in signals)
            crashed_flag = any(c in combined.lower() for c in crashed) and not booted
            results.append(f"Boot check: {'OK' if booted else 'WARN (no signal)'}\n{combined[-600:]}")
            if crashed_flag:
                return False, "\n".join(results)

        # npm test
        if "test" in pkg.get("scripts", {}):
            ok, msg = npm("", "test --passWithNoTests 2>/dev/null || npm test", timeout=60)
            results.append(f"npm test: {'OK' if ok else 'FAIL'}\n{msg}")

    return True, "\n".join(results)
