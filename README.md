# AI Coding Agent

A general-purpose CLI coding agent that explores a git repo, takes a plain-English request, plans changes via an LLM, applies surgical edits, validates each change, and generates a Markdown report.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env          # add your API key
python agent.py               # interactive mode — picks repo + prompts you
```

Or non-interactive (CI / demo):
```bash
python agent.py "Add search to notes" \
  --repo-url https://github.com/callicoder/node-easy-notes-app \
  --yes
```

## Interactive Mode

Running `python agent.py` with no arguments starts a guided session:

```
── Repo Selection ──
  1. Clone a new repo
  2. node-easy-notes-app  (workspace/node-easy-notes-app)

Select [1-2]: 2

── 2 · Exploring Repository ──
...

Enter your request (or 'exit' to quit): add search to notes

── 3 · Planning ──
{ ...plan JSON... }

── Confirm Edits ──
Proceed with editing files? (yes/no): yes

── 4 · Modifying Files ──  ...
── 5 · Validating ...      ...
── 6 · Report ...          reports/run_001.md

── Session ──
Run another prompt on this repo? (yes/no): yes

Enter your request (or 'exit' to quit): list all features
...
```

- Repo is explored **once** per session; all subsequent prompts reuse the same summary.
- Read-only requests (e.g. "list features", "what languages are used") never modify files and skip validation.
- `--yes` skips both the edit confirmation and the plan confirmation.

## Multi-LLM Support

Set **any one** of these keys in `.env` — the agent auto-detects the provider:

| Key | Provider | Default Model | Tool Calling |
|-----|----------|---------------|--------------|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | claude-opus-4-5 | ✅ Full |
| `OPENAI_API_KEY` | OpenAI (GPT) | gpt-4o | ✅ Full |
| `GEMINI_API_KEY` | Google (Gemini) | gemini-2.0-flash | ✅ Full |
| `XAI_API_KEY` | xAI (Grok) | grok-beta | ✅ Full |
| `OPENROUTER_API_KEY` | OpenRouter | openai/gpt-4o | ✅ Full |
| `GROQ_API_KEY` | Groq (LLaMA) | llama-3.3-70b-versatile | ⚠️ Tools disabled* |

Priority order if multiple keys are present: Anthropic → OpenAI → Gemini → xAI → OpenRouter → Groq.

Override the model with `--model <name>`.

> *Groq's tool-calling is unreliable — the planner runs without tools and relies on the repo summary alone. Modifier works normally.

## Architecture

```
agent.py              CLI entry point — repo selection, prompt loop, orchestrates steps 1–6
config.py             .env loading + provider auto-detection + directory constants
llm.py                Thin multi-provider LLM client (unified chat() interface)
core/
  workspace.py        Clone/locate repo, per-file backups, restore on failure
  explorer.py         Static repo scan → RepositorySummary (zero LLM calls)
  tools.py            Tool functions (read/write/search/run) + JSON schemas for LLM function-calling
  planner.py          LLM call #1 — produce structured JSON plan, optionally using tools
  modifier.py         LLM call(s) #2 — per-file surgical edits with retry loop
  validator.py        Per-file syntax check + whole-repo npm install / boot / test
  reporter.py         Generate reports/run_NNN.md with diffs + LLM plain-English summary
prompts/
  planner_system.txt  System prompt for the planner LLM
  modifier_system.txt System prompt for the modifier LLM
workspace/            Cloned repos live here
reports/              run_001.md, run_002.md, … generated after each request
backups/              Per-file .bak copies taken before every edit (auto-restored on failure)
```

## Agent Workflow

### 1 · Repo Acquisition
Clone via `--repo-url`, use an existing path (`--repo`), or pick interactively from `workspace/`. No LLM involved.

### 2 · Explore (static, no LLM)
Walk the directory tree (respecting `.gitignore`), parse `package.json`, classify files by conventional directory names (`models/`, `routes/`, `components/`, …). Produces a `RepositorySummary` — cheap and grounded, no hallucination risk.

### 3 · Plan (LLM call #1)
The planner LLM receives the `RepositorySummary` + user request. It can call `search_code` / `read_file` / `list_files` tools to inspect exact symbols before committing to a plan. Output is strict JSON:
```json
{
  "goal": "one sentence",
  "rationale": "why these changes",
  "files": ["list of files"],
  "steps": [
    { "file": "path", "action": "read|modify|create", "description": "what to do" }
  ]
}
```
Steps with `"action": "read"` are analysis-only — no files are touched.

### 4 · Modify (LLM call per file)
For each `modify`/`create` step in the plan:
- Back up the file to `backups/`.
- Send current content + task description to the modifier LLM.
- LLM returns a JSON array of `{old_str, new_str}` surgical edits.
- Apply edits via exact string match (fails loudly if `old_str` not found or not unique).
- Immediately validate the file (syntax check).
- On failure, restore backup and retry up to 3 times with the error fed back.
- After 3 failures, mark file as "skipped" and continue — one bad file never kills the run.

### 5 · Validate
Skipped entirely for read-only requests. For edit requests:
- Per-file: `node --check` for JS/JSX, `json.loads` for JSON.
- Whole-repo: `npm install` (root + `client/`), boot check (start server, wait 8 s, look for "listening"/"connected" signal), `npm test` if present.
- On whole-repo failure: restore all backups for this run and report rollback.

### 6 · Report
`reports/run_NNN.md` contains: original request, repo summary, plan JSON, per-file edit counts, validation output, full `git diff` (edit runs) or "Repository Modified: No" (read-only runs), and a 3–5 sentence LLM-generated plain-English summary.

## Design Trade-offs

**Surgical edits over full rewrites** — `{old_str, new_str}` blocks limit blast radius, reduce token cost, and make it easy to detect when the LLM drifts (`old_str` not found = immediate error). A full-file rewrite risks silently dropping unrelated code.

**Single provider abstraction** — `llm.py` supports 6 providers through a single `chat()` function. No LangChain/CrewAI overhead; easier to debug and extend.

**Per-file retry instead of full ReAct loop** — retrying at the file level keeps the blast radius small. A full ReAct loop would re-plan everything on any error, which is expensive and harder to reason about.

**Static exploration before LLM** — the explorer runs with zero LLM calls, giving the planner a grounded skeleton. The planner then uses targeted `search_code` calls for line-level detail rather than reading every file blindly.

**Read-only vs edit separation** — the planner emits `"action": "read"` for analysis tasks. The executor skips `apply_step`, skips validation, and generates a read-only report with no git diff.

**No hardcoded feature logic** — the agent's Python code only provides tools and infrastructure. All reasoning about *what* to build lives in the LLM prompts. Re-running with a completely different request requires zero code changes.

## CLI Options

```
python agent.py [request] [--repo-url URL] [--repo PATH] [--yes] [--model MODEL]

  request       Plain-English feature request (optional — prompted interactively if omitted)
  --repo-url    Git URL to clone into workspace/
  --repo        Path to an existing local repo (skips interactive picker)
  --yes / -y    Skip all yes/no confirmations (edit confirmation + session loop)
  --model       Override the default model for the detected provider
```

## Example Requests

```bash
# Read-only analysis — no files modified
python agent.py "what languages and frameworks are used?"
python agent.py "list all API endpoints"
python agent.py "suggest improvements"

# Code changes
python agent.py "add search functionality to notes"
python agent.py "add input validation to all routes"
python agent.py "add a DELETE /notes/:id endpoint"
```
