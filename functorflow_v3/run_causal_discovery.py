"""
run_causal_discovery.py — COMMENTED VERSION
============================================
This is the "orchestrator" script. Think of it as the main control panel:
  1. (Optional) Launches CLIFF in a browser to download papers
  2. Finds the SQLite database that CLIFF/Democritus produced
  3. Calls democritus_discovery.py to run the two category-theory engines
  4. Saves results as JSON and HTML, then opens the dashboard in your browser

HOW TO RUN (examples):
  python run_causal_discovery.py --skip-cliff                          # skip CLIFF, use existing DB
  python run_causal_discovery.py --skip-cliff -csql path/to/file.sqlite  # point at a specific DB
  python run_causal_discovery.py --skip-cliff --min-confidence 0.10   # lower confidence threshold
"""


from __future__ import annotations  # allows using 'list[Path]' style hints in older Python

import argparse          # reads command-line flags like --skip-cliff, --csql, etc.
import importlib.util    # lets us load Python files dynamically (used to import democritus_discovery)
import json              # reads/writes .json files (CLIFF metadata)
import subprocess        # launches CLIFF as a child process
import sys               # access to sys.path (module search list) and sys.executable (path to Python)
import webbrowser        # opens the finished HTML dashboard in your default browser
from pathlib import Path # modern, OS-independent way to work with file paths


# ── Path setup ────────────────────────────────────────────────────────────────

_THIS = Path(__file__).resolve()
# __file__ is this script's own path; .resolve() turns it into an absolute path.

PROJECT_ROOT = _THIS.parent.parent if _THIS.parent.name == "functorflow_v3" else _THIS.parent
# If this script lives INSIDE a "functorflow_v3" folder, go two levels up to find the project root.
# Otherwise (script is at the top level already), go just one level up.
# Example: if _THIS = /home/user/CLIFF/functorflow_v3/run_causal_discovery.py
#   → _THIS.parent     = /home/user/CLIFF/functorflow_v3
#   → _THIS.parent.name = "functorflow_v3"  → condition is True
#   → PROJECT_ROOT      = /home/user/CLIFF

sys.path.insert(0, str(PROJECT_ROOT))
# Add the project root to the Python module search path so that
# 'import functorflow_v3.democritus_discovery' works from anywhere.


# ── Directory constants ───────────────────────────────────────────────────────

CLIFF_OUTDIR  = PROJECT_ROOT / "cliff_results_v2"
# Where CLIFF saves its output files (SQLite databases, HTML dashboards, etc.)

DEFAULT_REPO  = PROJECT_ROOT / "Category-Theory-for-AGI-UMass-CMPSCI-692CT"
# Path to the course repository (used by the CLIFF --course-repo-root argument).

DEFAULT_FALLBACK_QUERY = (
    "Causal discovery over retrieved documents"
)
# A generic label used on the dashboard when we can't figure out what query was run.
# (Previously this was hardcoded to "GLP-1 receptor agonists" — now it's generic.)


# ── Validation thresholds ─────────────────────────────────────────────────────

_MIN_DOCS_FOR_SHEAF = 2
# We need AT LEAST 2 documents to detect contradictions between papers.
# Sheaf Colimit looks for "paper 1 says A→B but paper 2 says B→A" — impossible with 1 paper.

_MIN_EDGES_FOR_KAN  = 4
# We need AT LEAST 4 causal edges to compose paths like A→B→C.
# Fewer than 4 usually means Democritus retrieved off-topic documents.


# ── Helper: find all SQLite databases ────────────────────────────────────────

def _find_sqlite(base: Path) -> list[Path]:
    """
    Search *base* folder (and all subfolders) for every file named
    'democritus_csql.sqlite', then return them sorted newest-first by
    modification time (so [0] is the most recent run).
    """
    return sorted(
        base.rglob("democritus_csql.sqlite"),  # rglob = recursive glob (search all subfolders)
        key=lambda p: p.stat().st_mtime,       # sort key: last-modified time (a Unix timestamp)
        reverse=True,                          # True = descending → newest first
    )


# ── Helper: read the original CLIFF query from saved metadata ─────────────────

def _read_query_for_sqlite(sqlite_path: Path) -> str:
    """
    After CLIFF runs, it writes a summary JSON file one level above the SQLite.
    This function walks UP the folder tree (up to 6 levels) looking for that JSON,
    then reads the 'query' field from it so we can display the right query on the dashboard.

    Typical folder layout:
        <run_root>/
            ff2_query_router_summary.json   ← this has {"query": "what the user typed"}
            democritus/
                democritus_runs/
                    csql/
                        democritus_csql.sqlite   ← sqlite_path (4 folders down)
    """
    _CANDIDATE_NAMES = (
        "ff2_query_router_summary.json",  # primary: written by the CLIFF router
        "worker_result.json",             # fallback 1: written by cliff_worker
        "cliff_result.json",              # fallback 2: older naming convention
    )
    p = Path(sqlite_path).resolve()      # start at the SQLite file itself
    for _ in range(6):                   # try walking up at most 6 directory levels
        p = p.parent                     # go one folder up
        for name in _CANDIDATE_NAMES:    # check each candidate JSON filename
            candidate = p / name         # build the full path to check
            if candidate.exists():       # if this JSON file actually exists...
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))  # parse the JSON
                    q = str(data.get("query", "")).strip()  # read the "query" field
                    if q:                # if it's non-empty, we found it
                        return q
                except Exception:
                    pass                 # file was unreadable / bad JSON → try next
    return ""                            # nothing found after 6 levels → return empty string


# ── Helper: print quality warnings before opening the dashboard ───────────────

def _validate_result(result, *, query: str) -> None:
    """
    After discovery runs, check if the result looks suspicious and print
    human-readable warnings so the user knows BEFORE they read the HTML.
    'result' is a DiscoveryResult dataclass from democritus_discovery.py.
    """
    warns: list[str] = []  # collect all warnings here; print them together at the end

    if result.total_documents < 1:
        # The SQLite database is completely empty — CLIFF ran but retrieved nothing.
        warns.append(
            "✗  CLIFF retrieved 0 documents. The database is empty.\n"
            "   → Re-run CLIFF in the browser first, then re-run discovery."
        )
    elif result.total_documents < _MIN_DOCS_FOR_SHEAF:
        # Only 1 document → Sheaf Colimit is useless (can't have cross-paper conflicts).
        warns.append(
            f"⚠  Only {result.total_documents} document(s) retrieved (need ≥{_MIN_DOCS_FOR_SHEAF} "
            f"for Sheaf Colimit).\n"
            f"   → Sheaf Colimit will always return 0 feedback loops with a single document.\n"
            f"   → Ask CLIFF for more papers, or broaden your query."
        )

    if result.total_stated_claims < _MIN_EDGES_FOR_KAN:
        # Too few edges after domain filtering → corpus is probably off-topic.
        warns.append(
            f"⚠  Only {result.total_stated_claims} domain-filtered edges remain after filtering.\n"
            f"   → This is very low. The retrieved document(s) may be off-topic for:\n"
            f"      '{query[:80]}'\n"   # show only the first 80 chars of the query
            f"   → Check the CLIFF Topos Synthesis page — look at 'Root topics' in\n"
            f"     Topic Partitions to see what Democritus actually retrieved."
        )

    if warns:
        # Print a visible separator box with all warnings collected above.
        print("\n" + "─" * 60)
        print("[runner] ⚠  QUALITY WARNINGS:")
        for w in warns:
            print(f"  {w}")
        print("─" * 60 + "\n")


# ── Helper: import democritus_discovery at runtime ────────────────────────────

def _load_discovery():
    """
    Try to import democritus_discovery.py in several ways:
      1. As a submodule of the functorflow_v3 package (cleanest)
      2. By searching for the .py file directly (fallback for standalone use)
    Returns the imported module object so we can call mod.run_discovery() etc.
    """
    try:
        import importlib
        return importlib.import_module("functorflow_v3.democritus_discovery")
        # This works when functorflow_v3 is a proper Python package (has __init__.py)
    except ImportError:
        # Package import failed → search for the .py file manually
        for candidate in [
            PROJECT_ROOT / "functorflow_v3" / "democritus_discovery.py",
            PROJECT_ROOT / "democritus_discovery.py",          # top-level copy
            _THIS.parent / "democritus_discovery.py",          # same folder as this script
        ]:
            if candidate.exists():
                spec = importlib.util.spec_from_file_location("democritus_discovery", candidate)
                # spec_from_file_location builds a module "spec" (blueprint) from the file path
                mod  = importlib.util.module_from_spec(spec)   # create a blank module object
                spec.loader.exec_module(mod)                   # execute the file to populate it
                return mod
    raise FileNotFoundError("democritus_discovery.py not found in project.")
    # If we reach here, neither import strategy worked → crash with a clear message.


# ── CLIFF launcher (optional step 1) ─────────────────────────────────────────

def _run_cliff(query: str, course_repo: Path) -> int:
    """
    Launch CLIFF's background worker subprocess.
    Returns the exit code (0 = success, non-zero = something went wrong).
    """
    import re, time
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower())[:50].strip("_")
    # Build a filesystem-safe "slug" from the query text.
    # re.sub replaces anything that isn't a letter/digit/underscore with "_",
    # lowercases the result, keeps only first 50 chars, and strips leading/trailing "_".
    # Example: "GLP-1 receptor agonists?" → "glp_1_receptor_agonists"

    outdir = CLIFF_OUTDIR.parent / f"{CLIFF_OUTDIR.name}-run-disc-{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    # Create a unique output folder for this CLIFF run.
    # Includes a timestamp (e.g. 20240503-143012) so parallel runs don't overwrite each other.

    outdir.mkdir(parents=True, exist_ok=True)
    # Create the directory (and any missing parent folders).
    # exist_ok=True means no error if it already exists.

    cmd = [
        sys.executable,                          # path to the current Python interpreter
        "-m", "functorflow_v3.cliff_worker",     # run cliff_worker as a module
        "--query", query,                        # the user's search query
        "--outdir", str(outdir),                 # where to save CLIFF's output
        "--route", "democritus",                 # use the Democritus agent (paper retrieval)
        "--execution-mode", "quick",             # quick = fewer papers, faster
        "--democritus-target-docs", "5",         # ask Democritus to retrieve up to 5 documents
        "--democritus-topk-claims", "50",        # extract top 50 causal claims per document
        "--democritus-assets-dir", str(outdir / "assets"),  # where to save images/assets
        "--course-repo-root", str(course_repo), # path to course repository (for demo mode)
    ]
    print("[runner] Launching CLIFF Democritus worker …")
    return subprocess.run(cmd, cwd=str(PROJECT_ROOT)).returncode
    # subprocess.run() runs the command and waits for it to finish.
    # .returncode is 0 if the process succeeded, non-zero if it crashed.


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    """
    Top-level function that runs when you execute this script.
    Orchestrates the full pipeline: (optional CLIFF) → find DB → discover → write outputs.
    """

    # ── Parse command-line arguments ──────────────────────────────────────────
    ap = argparse.ArgumentParser(
        description="Categorical causal discovery runner (Kan Extension + Sheaf Colimit).")
    # argparse reads sys.argv and turns --flag value pairs into ap.parse_args() attributes.

    ap.add_argument("--query", default="",
                    help="Override the query label shown in the dashboard. "
                         "If omitted, the actual CLIFF run query is read from metadata.")
    # --query is optional. If you leave it out, the script reads the query from CLIFF's metadata.

    ap.add_argument("--course-repo-root", default=str(DEFAULT_REPO))
    # Path to the course repository; defaults to the value of DEFAULT_REPO above.

    ap.add_argument("--skip-cliff", action="store_true",
                    help="Skip CLIFF worker; use existing outputs.")
    # --skip-cliff is a boolean flag: present = True, absent = False.
    # Use this when CLIFF has already run and you just want to re-run discovery.

    ap.add_argument("--csql", default=None,
                    help="Direct path to an existing democritus_csql.sqlite.")
    # Lets you point at a specific SQLite file instead of auto-detecting the newest one.

    ap.add_argument("--min-confidence", type=float, default=0.10,
                    help="Minimum confidence for novel claims (default 0.10).")
    # Claims with confidence below this threshold are filtered out.
    # 0.10 = 10% minimum. Lowering this makes more (but weaker) claims appear.

    ap.add_argument("--no-browser", action="store_true")
    # If present, the script writes the HTML but does NOT open it in a browser.

    args = ap.parse_args()
    # Actually parse sys.argv and populate 'args' with the flags above.


    # ── Step 1: optionally run CLIFF ──────────────────────────────────────────
    if not args.skip_cliff and not args.csql:
        # Only run CLIFF if the user didn't say --skip-cliff AND didn't provide --csql.
        launch_query = args.query or DEFAULT_FALLBACK_QUERY
        # Use the --query flag if given; otherwise use the generic fallback label.
        rc = _run_cliff(launch_query, Path(args.course_repo_root).resolve())
        # Launch CLIFF and capture its exit code.
        if rc != 0:
            print(f"\n[runner] CLIFF exited {rc}. Searching for existing DB …")
            # Non-zero exit = CLIFF failed. Keep going anyway — maybe there's an old DB.


    # ── Step 2: locate the SQLite database ───────────────────────────────────
    if args.csql:
        # User provided an explicit path → use it directly.
        sqlite_path = Path(args.csql).resolve()  # .resolve() converts to absolute path
        if not sqlite_path.exists():
            print(f"[runner] ✗  --csql not found: {sqlite_path}"); sys.exit(1)
            # sys.exit(1) stops the script immediately with error code 1.
    else:
        # Auto-detect: search cliff_results_v2, then the whole project root as a fallback.
        dbs = _find_sqlite(CLIFF_OUTDIR) or _find_sqlite(PROJECT_ROOT)
        # 'or' here means: if the first list is empty, use the second.

        if not dbs:
            print("\n[runner] ✗  No democritus_csql.sqlite found.")
            print("  Run CLIFF first, or pass --csql PATH/TO/file.sqlite")
            sys.exit(1)  # no database found → nothing to do, quit

        print(f"[runner] Found {len(dbs)} cSQL database(s):")
        for db in dbs: print(f"  {db}")  # list all found databases

        sqlite_path = dbs[0]   # use the most recent one (sorted newest-first by _find_sqlite)
        print(f"\n[runner] Using: {sqlite_path}")

        if len(dbs) > 1:
            # Warn the user that we're auto-picking — they may want a specific run.
            print(
                f"[runner] ⚠  Multiple DBs found. Using the most recent one.\n"
                f"         Pass --csql <path> to target a specific run."
            )


    # ── Step 2b: resolve the query label ─────────────────────────────────────
    effective_query = args.query
    # Start with whatever --query flag was passed (may be empty string "").

    if not effective_query:
        # No --query flag → try to read the original query from CLIFF's metadata JSON.
        effective_query = _read_query_for_sqlite(sqlite_path)
        if effective_query:
            print(f"[runner] Query from run metadata: {effective_query[:80]}")
            # Print first 80 chars so the terminal doesn't overflow.
        else:
            # Metadata not found or empty → fall back to the generic label.
            effective_query = DEFAULT_FALLBACK_QUERY
            print(f"[runner] No metadata found; using generic fallback query label.")


    # ── Step 3: run categorical discovery ────────────────────────────────────
    print("\n[runner] Running categorical discovery …")
    mod = _load_discovery()
    # Dynamically import democritus_discovery.py (the file with the actual math).

    result = mod.run_discovery(
        sqlite_path=sqlite_path,          # path to the SQLite database to analyse
        query=effective_query,            # label for the dashboard header
        min_confidence=args.min_confidence,  # only keep claims above this threshold
    )
    # run_discovery() returns a DiscoveryResult dataclass with all the novel claims.

    # Print a quick summary to the terminal.
    print(f"\n  Documents       : {result.total_documents}")      # how many papers Democritus retrieved
    print(f"  Stated edges    : {result.total_stated_claims}")   # causal claims already in the DB
    print(f"  Kan Extension   : {len(result.kan_extension_claims)}")   # NEW claims via path composition
    print(f"  Sheaf Colimit   : {len(result.sheaf_colimit_claims)}")   # NEW feedback loops via conflicts

    _validate_result(result, query=effective_query)
    # Print quality warnings (e.g. "only 1 document retrieved") before we write outputs.

    if result.total_stated_claims == 0:
        print("\n  ⚠  Database is empty. Re-run CLIFF to populate."); return
        # Nothing to analyse → quit early.


    # ── Step 4: write outputs ─────────────────────────────────────────────────
    out = sqlite_path.parent.parent / "discovery"
    # Place the outputs two folders above the SQLite file, in a "discovery" subfolder.
    # e.g. .../democritus/democritus_runs/csql/democritus_csql.sqlite
    #   → out = .../democritus/democritus_runs/discovery/

    json_path, html_path = mod.write_discovery_outputs(
        result, outdir=out, query=effective_query)
    # Writes two files:
    #   discovery_summary.json   — machine-readable list of all novel claims
    #   discovery_dashboard.html — human-readable dashboard with cards and stats

    print(f"\n[runner] ✓  JSON : {json_path}")
    print(f"[runner] ✓  HTML : {html_path}")


    # ── Step 5: print highlights to terminal ─────────────────────────────────
    if result.kan_extension_claims:
        print("\n── Top Kan Extension Claims ──────────────────────────────────")
        for c in result.kan_extension_claims[:6]:
            # Print first 6 Kan Extension claims (A –[relation]→ C via bridge B)
            print(f"  [{c.confidence:.2f}]  {c.source}  –[{c.relation}]→  {c.target}")
            print(f"         via: {c.intermediate}")  # c.intermediate = the bridge node B

    if result.sheaf_colimit_claims:
        print("\n── Sheaf Colimit Feedback Loops ──────────────────────────────")
        for c in result.sheaf_colimit_claims[:4]:
            # Print first 4 Sheaf Colimit feedback loops (A ↔ B)
            print(f"  [{c.confidence:.2f}]  {c.source}  ↔  {c.target}")


    # ── Step 6: open the dashboard in the browser ─────────────────────────────
    if not args.no_browser:
        webbrowser.open(html_path.as_uri())
        # .as_uri() converts the Path to a "file:///..." URL so the browser can open it.


# ── Script entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
    # This block only runs if you execute the script directly:
    #   python run_causal_discovery.py
    # It does NOT run if another script imports this file as a module.