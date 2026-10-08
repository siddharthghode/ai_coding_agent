> 🎥 **Demo video:** https://drive.google.com/file/d/1u8Zj0pEViLBS1OVrxemZ_Dj2CwZC79dp/view?usp=drive_link

---

# 🤖 AI Coding Agent

A CLI tool that acts as your personal coding assistant for any Git repository.

You describe what you want in plain English — *"add JWT authentication"*, *"add a search endpoint"*, *"what routes exist?"* — and the agent plans the changes, edits the files surgically, validates the result, and writes a Markdown report. All without you touching a single line of code.

It runs as a **continuous interactive session**: one repository, one conversation, as many requests as you need.

---

## ✨ What it does

- 🔍 **Explores** your repository structure automatically (no LLM needed for this step)
- 🧠 **Plans** changes using an LLM — reads relevant files before deciding what to touch
- ✏️ **Edits** files surgically using `{old_str → new_str}` patches (never rewrites whole files)
- ✅ **Validates** changes — syntax check, `npm install`, server boot check
- ↩️ **Rolls back** automatically if validation fails
- 📋 **Reports** every run to `reports/run_NNN.md` with a full git diff
- 🔁 **Remembers** previous requests in the session so follow-up prompts make sense

---

## 🚀 Quick Start

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Add your API key**
```bash
cp .env.example .env
# Open .env and add one API key (any provider works — see table below)
```

**3. Run**
```bash
python3 agent.py               # interactive session — choose a repo and start prompting
```

That's it. The agent will guide you from there.

---

## 💬 Interactive Session

Running `python3 agent.py` starts a guided session that stays open until you type `exit`.

```
── 1 · Repo Acquisition ──
── 2 · 🔍 Exploring Repository ──

╭──────────────────────────────────────╮
│  🤖 AI CODING AGENT                  │
│                                      │
│  Repository: node-easy-notes-app     │
│  Provider  : openai                  │
│  Model     : gpt-4o                  │
╰──────────────────────────────────────╯

✓ Repository analyzed
✓ Agent ready

Type your coding request.
Type 'exit' to quit.

You › Add JWT authentication

  🤖 Planning...
  ✏️  Modifying...
  ✅ Validating...
  📋 Generating report...

──────────── ✓ Request completed ────────────

You › Now add a logout endpoint

  🤖 Planning...        ← agent remembers the JWT work from the previous request
  ✏️  Modifying...
  ✅ Validating...

──────────── ✓ Request completed ────────────

You › What routes exist now?

  🤖 Planning...        ← read-only, no files touched
  📋 Generating report...

──────────── ✓ Request completed ────────────

You › exit
👋 Session ended.
```

The repository is **selected once** at the start. Every subsequent request works on the same local copy — no re-cloning, no re-selecting.

---

## ⚡ One-shot / CI Mode

Pass the request directly on the command line to skip all prompts:

```bash
# Clone a repo and apply a change non-interactively
python3 agent.py "Add search to notes" \
  --repo-url https://github.com/callicoder/node-easy-notes-app \
  --yes

# Use an existing local repo
python3 agent.py "Add input validation to all routes" \
  --repo ./my-project \
  --yes
```

`--yes` skips the edit-confirmation prompt, making it suitable for CI pipelines.

---

## 🔑 LLM Providers

Set **any one** key in your `.env` file — the agent picks it up automatically.

| `.env` Key | Provider | Default Model | Tool Calling |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | claude-opus-4-5 | ✅ Full |
| `OPENAI_API_KEY` | OpenAI (GPT) | gpt-4o | ✅ Full |
| `GEMINI_API_KEY` | Google (Gemini) | gemini-2.0-flash | ✅ Full |
| `XAI_API_KEY` | xAI (Grok) | grok-beta | ✅ Full |
| `OPENROUTER_API_KEY` | OpenRouter | openai/gpt-4o | ✅ Full |
| `GROQ_API_KEY` | Groq | openai/gpt-oss-120b | ⚠️ Limited* |

If multiple keys are present, priority is: **Anthropic → OpenAI → Gemini → xAI → OpenRouter → Groq**

Override the model for any provider:
```bash
python3 agent.py --model claude-3-5-sonnet-20241022
```

> ⚠️ *Groq's tool-calling is unreliable. The planner falls back to using the repo summary only. File editing still works normally.*

---

## 📁 Project Structure

```
ai_coding_agent/
│
├── agent.py              ← CLI entry point, session loop, orchestration
├── config.py             ← Reads .env, detects provider, exports directory paths
├── llm.py                ← Unified LLM client (all 6 providers, one chat() function)
│
├── core/
│   ├── session.py        ← Multi-turn session context (remembers previous requests)
│   ├── workspace.py      ← Clone/locate repo, file backups, restore on failure
│   ├── explorer.py       ← Static repo scan → RepositorySummary (zero LLM calls)
│   ├── tools.py          ← read_file / search_code / list_files tools for the planner
│   ├── planner.py        ← LLM call #1 — produces a structured JSON plan
│   ├── modifier.py       ← LLM call(s) #2 — applies surgical edits per file
│   ├── validator.py      ← Syntax check + npm install + server boot check
│   └── reporter.py       ← Writes reports/run_NNN.md with diff + LLM summary
│
├── prompts/
│   ├── planner_system.txt   ← System prompt for the planner LLM
│   └── modifier_system.txt  ← System prompt for the modifier LLM
│
├── workspace/            ← Cloned repositories live here
├── reports/              ← run_001.md, run_002.md, … one per request
├── backups/              ← .bak copies taken before every edit (auto-restored on failure)
│
├── .env                  ← Your API key (not committed)
├── .env.example          ← Template — copy this to .env
└── requirements.txt      ← Python dependencies
```

---

## 🔄 How It Works — Step by Step

### Step 1 · Repo Acquisition
The agent clones a repo from a URL or uses an existing local path. This happens **once per session** — the same local copy is reused for all subsequent requests.

### Step 2 · Repository Exploration
The agent walks the directory tree, reads `package.json`, and classifies files by role (`routes/`, `models/`, `components/`, etc.). This produces a `RepositorySummary` with **zero LLM calls** — fast, cheap, and grounded in reality.

After any request that modifies files, the summary is **refreshed automatically** so the next request sees the updated state.

### Step 3 · Planning
The planner LLM receives:
- The current repository summary
- Any relevant session history (previous requests + what was changed)
- Your current request

It can call `read_file`, `search_code`, and `list_files` tools to inspect exact code before deciding what to change. It outputs a strict JSON plan:

```json
{
  "goal": "Add JWT authentication middleware",
  "rationale": "Protect routes using signed tokens",
  "files": ["middleware/auth.js", "routes/notes.js"],
  "steps": [
    { "file": "middleware/auth.js", "action": "create", "description": "Create JWT verify middleware" },
    { "file": "routes/notes.js",   "action": "modify", "description": "Apply auth middleware to all routes" }
  ]
}
```

Steps with `"action": "read"` are analysis-only — no files are touched.

### Step 4 · Modification
For each `modify` or `create` step:
1. Back up the file to `backups/`
2. Send the current file content + task to the modifier LLM
3. LLM returns a list of `{ old_str, new_str }` patches
4. Apply patches via exact string match
5. Validate the file immediately (syntax check)
6. On failure: restore backup and retry up to **3 times**, feeding the error back to the LLM
7. After 3 failures: mark as "skipped" and continue — one bad file never kills the whole run

### Step 5 · Validation
Skipped for read-only requests. For edit requests:
- **Per-file:** `node --check` for JS/JSX, `json.loads` for JSON
- **Whole-repo:** `npm install`, server boot check (waits 8s for "listening"/"connected"), `npm test` if present
- **On failure:** all files from this run are restored from backup and the rollback is reported

### Step 6 · Report
A Markdown report is written to `reports/run_NNN.md` containing:
- Your original request
- The plan JSON
- Per-file edit counts and any errors
- Validation output
- Full `git diff` (or "no changes" for read-only runs)
- A 3–5 sentence plain-English summary generated by the LLM

---

## 🧠 Multi-Turn Context

The agent maintains a **session context** across requests. After each completed request, it records:
- What you asked
- Which files were modified
- Whether validation passed

This compact history is injected into the next planning call, so follow-up requests work naturally:

```
You › Add JWT authentication
  → modifies middleware/auth.js, routes/notes.js

You › Now add a logout endpoint
  → planner sees: "previous request added JWT auth to middleware/auth.js"
  → correctly adds logout to the auth system, not somewhere unrelated
```

Only the last **5 turns** are kept to avoid bloating the LLM context.

---

## 🛡️ Safety & Rollback

- Every file is backed up to `backups/` before being touched
- If a file edit fails after 3 retries, it is skipped — the run continues
- If whole-repo validation fails, **all** files modified in that run are restored
- If a request fails entirely, the session stays alive — just type your next request

```
❌ Request failed

Reason: Planning failed: ...

The session is still active.

You ›
```

---

## 🖥️ Session Commands

| Command | What it does |
|---|---|
| `exit` or `quit` | End the session |
| `/help` | Show available commands |
| `/status` | Show current repo, turn count, last request |
| `/clear` | Clear session history (start fresh context) |

---

## ⚙️ CLI Reference

```
python3 agent.py [request] [--repo-url URL] [--repo PATH] [--yes] [--model MODEL]

  request       Plain-English request (optional — prompted interactively if omitted)
  --repo-url    Git URL to clone into workspace/
  --repo        Path to an existing local repo
  --yes / -y    Skip the edit-confirmation prompt (useful for CI)
  --model       Override the default model for the detected provider
```

---

## 📝 Example Requests

```bash
# ── Read-only analysis (no files modified) ──────────────────────────────────
You › what languages and frameworks are used?
You › list all API endpoints
You › what does the authentication flow look like?
You › suggest improvements to the codebase

# ── Code changes ─────────────────────────────────────────────────────────────
You › add search functionality to notes
You › add input validation to all routes
You › add a DELETE /notes/:id endpoint
You › add JWT authentication
You › now add a logout endpoint
You › add rate limiting to the API
```

---

## 🔧 Design Decisions

**Surgical edits, not full rewrites**
The modifier uses `{old_str → new_str}` patches instead of rewriting entire files. This limits the blast radius, reduces token cost, and makes drift immediately detectable — if `old_str` isn't found, the edit fails loudly rather than silently corrupting the file.

**Static exploration before LLM**
The explorer scans the repo with zero LLM calls, giving the planner a grounded skeleton. The planner then uses targeted `search_code` / `read_file` calls for line-level detail — rather than blindly reading every file.

**Per-file retry, not full re-plan**
Retrying at the file level keeps failures isolated. A full ReAct re-plan on every error would be expensive and hard to reason about.

**Single provider abstraction**
`llm.py` supports 6 providers through one `chat()` function. No LangChain or CrewAI — easier to debug, extend, and understand.

**Compact session context**
Instead of sending the full conversation history to the LLM, a structured summary of the last 5 turns is injected. This keeps context useful without ballooning token usage.

**No hardcoded feature logic**
The Python code only provides tools and infrastructure. All reasoning about *what* to build lives in the LLM prompts. Changing the agent's behaviour requires editing a `.txt` file, not Python code.
