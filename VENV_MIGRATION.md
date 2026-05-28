# Migrate chess-book-ai to a per-repo `.venv`

**Goal:** stop relying on the global Python install. After this migration, each
repo on the machine pins its own `cchess` version and the cross-repo footgun
("don't `pip install --upgrade cchess` globally") goes away.

**Sibling repo context:** `../chess-book-editor` already uses `.venv` with
cchess **1.26.2** (from `git+https://github.com/walker8088/cchess.git@master`,
needed for its `PatchedXQFWriter` subclass). This repo currently uses the
global Python with cchess **1.25.5** because `from cchess import read_from_xqf`
was removed from `cchess/__init__.py`'s public exports in 1.26. We want to
keep 1.25.5 *here*, in a `.venv`.

---

## Step 0 — Snapshot current state

```powershell
# Confirm what the global Python is running today
python --version                          # expect Python 3.10.x
python -m pip show cchess | Select-String "Name|Version|Location"
#   expect: Name=cchess  Version=1.25.5  Location=...AppData\Local\Programs\Python\Python310\...
python -c "from cchess import read_from_xqf; print('OK')"   # must print OK
```

If `Version` is anything other than `1.25.5`, **stop** and figure out why
before continuing — the import test below relies on that exact version.

---

## Step 1 — Create the venv

```powershell
# At the repo root: D:\Elton\TestArea\chess-book-ai
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

## Step 2 — Install dependencies

```powershell
# Pin to the exact version the global currently has, to avoid surprises.
.\.venv\Scripts\python.exe -m pip install cchess==1.25.5
```

No other third-party dependencies are needed. A scan of the codebase (excluding
`cchess` itself) shows only stdlib imports + `cchess`. Pikafish is an external
binary, not a Python dep.

## Step 3 — Verify imports + smoke tests

```powershell
# Sanity-check the same import that drives the whole codebase
.\.venv\Scripts\python.exe -c "from cchess import read_from_xqf; print('OK')"

# Run the existing smoke tests
.\.venv\Scripts\python.exe smoke_engine.py
.\.venv\Scripts\python.exe smoke_xqf.py
```

Both should print success without errors. If `smoke_engine.py` fails, that's
usually a Pikafish path issue (`engine\Windows\pikafish.exe` + NNUE missing),
not a venv problem.

## Step 4 — Rewrite the PowerShell scripts that hard-code `py`

Four scripts currently invoke `py` directly. Each needs the leading `py`
replaced with the venv interpreter. Two safe patterns:

**Option A (explicit path, no activation):**
```powershell
.\.venv\Scripts\python.exe site_builder\build_data.py -d 12
```

**Option B (activate at the top of the script):**
```powershell
.\.venv\Scripts\Activate.ps1
python site_builder\build_data.py -d 12
```

Recommend **Option A** for unattended scripts (no activation state to worry
about, no `Set-ExecutionPolicy` prompt). Files to update:

| File | Line(s) | Current |
|---|---|---|
| [nightly_build.ps1](nightly_build.ps1) | 3 invocations | `py site_builder\build_data.py …` → `.\.venv\Scripts\python.exe site_builder\build_data.py …` |
| [site_builder/run_verify_d28_shunbao.ps1](site_builder/run_verify_d28_shunbao.ps1) | 1 invocation | same pattern |
| [site_builder/run_verify_d32.ps1](site_builder/run_verify_d32.ps1) | 1 invocation | same pattern |
| [site_builder/run_verify_traps.ps1](site_builder/run_verify_traps.ps1) | 1 invocation | same pattern |

The `Set-Location $REPO` line in `nightly_build.ps1` keeps the relative
`.\.venv\…` path valid; no further restructuring needed.

## Step 5 — Update docs

Files referencing the bare `py` command:

| File | Change |
|---|---|
| [README.md](README.md) | "需要 Python 3.10、Pikafish…" → add a venv setup block; rewrite the example commands from `py analyze.py …` to `.\.venv\Scripts\python.exe analyze.py …` |
| [CLAUDE.md](CLAUDE.md) | Wherever it says to invoke `py …`, update to the venv command; also strip the implicit "global cchess is the source of truth" framing |
| [AGENTS.md](AGENTS.md) | Same as CLAUDE.md |

Suggested README setup block (mirrors chess-book-editor's pattern):

```markdown
## Setup

### Prerequisites
- Python 3.10+
- Pikafish exe + NNUE (under `engine\Windows\`, git-ignored)
- Git

### Create venv + install deps
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install cchess==1.25.5
```

### Run anything
Either activate (`.\.venv\Scripts\Activate.ps1` then `python …`) or
prefix every call with `.\.venv\Scripts\python.exe …`. The PowerShell
scripts in this repo use the explicit-prefix form so no activation is
needed.
```

## Step 6 — Add `.venv/` to `.gitignore` (if not already)

```powershell
Select-String -Path .gitignore -Pattern "\.venv" -SimpleMatch
```

If nothing matches, append `.venv/` to `.gitignore`.

## Step 7 — Full pipeline dry-run

Run a representative slice to confirm nothing else hard-codes a `py` path:

```powershell
# A short build (won't take overnight) — proves the entry points work.
.\.venv\Scripts\python.exe site_builder\build_data.py -d 8
```

If that succeeds, the migration is done.

## Step 8 — Update the sibling repo's warning

In `../chess-book-editor/README.md`, the "Setup → Create venv + install deps"
section has a callout block warning *don't `pip install --upgrade cchess`
globally*. After this migration, the global cchess is no longer load-bearing
for anything. Two options:

1. **Delete the warning entirely** — both repos are now self-contained.
2. **Rewrite as historical note** — "both sibling repos use per-repo venvs;
   the global Python's cchess version is irrelevant."

Option 1 is cleaner. Leave the cchess pin-to-`master` line in
chess-book-editor's setup intact; that one still matters.

Also update memory files:
- `~/.claude/projects/d--Elton-TestArea-chess-book-editor/memory/reference_cchess_version_split.md`
  → either delete, or rewrite to "both repos use venvs; no shared state".
- `~/.claude/projects/d--Elton-TestArea-chess-book-editor/memory/MEMORY.md`
  → remove or update the corresponding line.

---

## Rollback

If something breaks badly, just delete `.venv/` and the old `py` commands
will fall back to the global Python exactly as before. The PowerShell
script edits are pure-text changes — `git checkout -- nightly_build.ps1`
(etc.) reverts them.

---

## Why this is worth doing once

Today: a stray `pip install --upgrade cchess` from any shell on this
machine instantly breaks chess-book-ai's 5 `from cchess import read_from_xqf`
sites. The warning in chess-book-editor's README is the only thing
preventing the footgun. Per-repo venvs make the warning unnecessary and
the setup reproducible on the next machine.
