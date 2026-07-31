# CLIFF AGI Extension Project
### Categorical Causal Discovery via Kan Extension and Sheaf Colimit
**CMPSCI 692CT — Category Theory for AGI — UMass Amherst**


## Project Architecture
| File | Role |
|------|------|
| `democritus_discovery.py` | The **math engine**. Reads the SQLite database, runs Kan Extension and Sheaf Colimit, produces JSON + HTML output. This is the core contribution. |
| `seed_csql_from_pdfs.py` | The **data prep tool**. Takes PDF papers, extracts causal claims using regex patterns, and writes them to SQLite. Works offline — no OpenAI API key needed. |
| `run_glp1_discovery.py` | The **pipeline orchestrator**. Glues everything together: optionally runs CLIFF, finds/seeds the database, calls the discovery engine, and opens the results. |



## How to Run It

### Prereq.

```bash
pip install pdfplumber    # for PDF text extraction
```

### Step 1: Run CLIFF and submit a query

```bash
cd C:\Users\hache\Documents\GitHub\CLIFF_AGI-Extension-Project

python -m functorflow_v3.cliff --outdir ./cliff_results_v2 `
  --course-repo-root "C:\Users\hache\Documents\GitHub\Category-Theory-for-AGI-UMass-CMPSCI-692CT"
```

Open the browser at `http://127.0.0.1:<port>/` and submit:
> *"Find me 3 recent studies on GLP-1 receptor agonists and their effects on obesity, diabetes, cardiovascular risk, and inflammation"*

Wait for CLIFF to finish downloading papers (creates `acquired_pdfs/` and `democritus_csql.sqlite`).

### Step 2: Seed the database from PDFs and run discovery

```bash
python functorflow_v3\seed_csql_from_pdfs.py --run-discovery
```

### Step 3 (alternative command): Run the discovery on existing database

```bash
python functorflow_v3\run_glp1_discovery.py --skip-cliff
```

Or point at specific SQLite file:
```bash
python functorflow_v3\run_glp1_discovery.py --skip-cliff --csql "path/to/democritus_csql.sqlite"
```