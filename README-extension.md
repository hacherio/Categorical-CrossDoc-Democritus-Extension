# CLIFF AGI Extension Project
### Categorical Causal Discovery via Kan Extension and Sheaf Colimit
**CMPSCI 692CT — Category Theory for AGI — UMass Amherst**

---

## What This Project Does (Plain English)

Imagine you have three research papers on GLP-1 drugs (weight-loss drugs like Ozempic):

- **Paper 1** says: *"GLP-1 drugs reduce inflammation."*
- **Paper 2** says: *"Inflammation causes cardiovascular risk."*
- **Paper 3** says nothing about GLP-1 and cardiovascular risk directly.

A human reading all three would immediately infer: *"GLP-1 drugs must therefore reduce cardiovascular risk."*
No single paper said that — but it's **forced by logic**.

This project automates that reasoning using **category theory** — the branch of mathematics that studies how structures compose and how information flows between systems.
It takes the causal claims already stored in a CLIFF/Democritus database and discovers **new truths** that no paper ever explicitly stated, using two mathematical engines.

---

## The Two Core Ideas (Category Theory)

### 1. Kan Extension — "Path Composition"

**The math:** If functor `F: StatedCat → CausalSpace` knows `A→B` and `B→C`, the *right Kan extension* of `F` along the inclusion `J: StatedCat ↪ AllPathsCat` universally entails `A→C`.

**In plain English:** If we know two causal steps that chain together (A causes B, B causes C), then category theory *forces* the conclusion A causes C — even if no paper wrote that sentence. This is called "path composition." The confidence of the new claim is the **geometric mean** of the two steps (e.g., `√(0.92 × 0.85) = 0.88`), which is the same formula used in the Judo Calculus chapter of the course textbook for combining evidence.

**Example discovery:**
- Paper 1: `glp-1 receptor agonist → reduces → body weight` (conf 0.95)
- Paper 2: `body weight → reduces → cardiovascular risk` (conf 0.88)
- **Novel claim:** `glp-1 receptor agonist → indirectly_reduces → cardiovascular risk` (conf 0.91) ← *No paper said this!*

### 2. Sheaf Colimit — "Resolving Contradictions"

**The math:** When paper S₁ asserts `A→B` and paper S₂ asserts `B→A`, each provides a *local section* of the causal presheaf over the set `{A, B}`. These sections are incompatible — they cannot be glued globally. The *colimit* of the diagram of conflicting sections is the **universal causal model** `A ↔ B` (bidirectional feedback loop) that both papers factor through.

**In plain English:** When two papers directly contradict each other about causation (paper 1 says inflammation causes insulin resistance; paper 2 says insulin resistance causes inflammation), instead of picking a winner, the math says *both are right* — they're in a feedback loop. The colimit finds the most general model consistent with both papers. Confidence uses the **harmonic mean** (`2pq/(p+q)`).

**Example discovery:**
- Paper 2: `inflammation → causes → insulin resistance` (conf 0.85)
- Paper 3: `insulin resistance → causes → inflammation` (conf 0.80)
- **Novel claim:** `inflammation ↔ insulin resistance` bidirectional feedback (conf 0.82) ← *No single paper said "feedback loop"!*

---

## Project Architecture

```
CLIFF_AGI-Extension-Project/
│
├── functorflow_v3/                  ← The base CLIFF system (from the course repo)
│   ├── cliff.py                     ← Main CLIFF server (runs in browser)
│   ├── cliff_worker.py              ← Worker process for one query
│   ├── democritus_agentic.py        ← Democritus agent (downloads papers, builds cSQL)
│   │
│   ├── democritus_discovery.py      ← ★ NEW: Kan Extension + Sheaf Colimit engine
│   ├── seed_csql_from_pdfs.py       ← ★ NEW: Offline PDF → cSQL seeder (no API key)
│   └── run_glp1_discovery.py        ← ★ NEW: Full pipeline runner
│
├── cliff_results_v2/                ← CLIFF output directory (created at runtime)
│   └── <run-dir>/
│       ├── democritus/
│       │   ├── acquired_pdfs/       ← PDFs downloaded by Democritus
│       │   └── democritus_csql.sqlite  ← The causal claims database
│       └── discovery/
│           ├── discovery_summary.json  ← Machine-readable results
│           └── discovery_dashboard.html ← Visual results dashboard
│
└── Category-Theory-for-AGI-UMass-CMPSCI-692CT/  ← Course repo (for CLIFF)
```

---

## The Three New Files (What Each Does)

| File | Role |
|------|------|
| `democritus_discovery.py` | The **math engine**. Reads the SQLite database, runs Kan Extension and Sheaf Colimit, produces JSON + HTML output. This is the core contribution. |
| `seed_csql_from_pdfs.py` | The **data prep tool**. Takes PDF papers, extracts causal claims using regex patterns, and writes them to SQLite. Works offline — no OpenAI API key needed. |
| `run_glp1_discovery.py` | The **pipeline orchestrator**. Glues everything together: optionally runs CLIFF, finds/seeds the database, calls the discovery engine, and opens the results. |

---

## How the Data Flows

```
PDFs (research papers)
        │
        ▼
seed_csql_from_pdfs.py
  [regex pattern matching]
  "GLP-1 reduces body weight" → {subj: "glp-1 receptor agonist", rel: "reduces", obj: "body weight", conf: 0.95}
        │
        ▼
democritus_csql.sqlite
  [aggregated_edges view]
  groups claims by (subj, rel, obj), counts document support
        │
        ▼
democritus_discovery.py
  ┌─────────────────────────────────────────────────────┐
  │  Kan Extension Engine                               │
  │  For every A→B and B→C: entail A→C                  │
  │  conf(A→C) = √(conf(A→B) × conf(B→C))              │
  └─────────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────┐
  │  Sheaf Colimit Engine                               │
  │  For every A→B and B→A: resolve to A↔B             │
  │  conf = 2pq/(p+q)  (harmonic mean)                  │
  └─────────────────────────────────────────────────────┘
        │
        ▼
discovery_dashboard.html  +  discovery_summary.json
```

---

## How to Run It

### Prerequisites

```bash
pip install pdfplumber    # for PDF text extraction (pypdf works as fallback)
```

### Step 1: Run CLIFF and submit a query

```bash
cd C:\Users\hache\Documents\GitHub\CLIFF_AGI-Extension-Project

python -m functorflow_v3.cliff --outdir ./cliff_results_v2 `
  --course-repo-root "C:\Users\hache\Documents\GitHub\Category-Theory-for-AGI-UMass-CMPSCI-692CT"
```

Open the browser at `http://127.0.0.1:<port>/` and submit:
> *"Find me 3 recent studies on GLP-1 receptor agonists and their effects on obesity, diabetes, cardiovascular risk, and inflammation"*

Wait for CLIFF to finish downloading papers (this creates `acquired_pdfs/` and `democritus_csql.sqlite`).

### Step 2: Seed the database from PDFs and run discovery

```bash
python functorflow_v3\seed_csql_from_pdfs.py --run-discovery
```

This runs offline — no API key needed. It will:
- Find the PDFs downloaded by CLIFF
- Extract causal claims using regex
- Inject the built-in GLP-1 knowledge base (ensures rich cross-document data)
- Run Kan Extension + Sheaf Colimit
- Open the HTML dashboard in your browser

### Step 3 (Alternative): Run just the discovery on an existing database

```bash
python functorflow_v3\run_glp1_discovery.py --skip-cliff
```

Or point at a specific SQLite file:
```bash
python functorflow_v3\run_glp1_discovery.py --skip-cliff --csql "path/to/democritus_csql.sqlite"
```

---

## Expected Output

After running, you'll get a dashboard at `cliff_results_v2/discovery/discovery_dashboard.html` showing:

**Kan Extension claims (examples):**
```
[0.92]  glp-1 receptor agonist  –[indirectly_reduces]→  cardiovascular risk
        via bridge: body weight

[0.89]  glp-1 receptor agonist  –[indirectly_reduces]→  atherosclerosis
        via bridge: inflammation

[0.88]  obesity  –[indirectly_reduces]→  insulin sensitivity
        via bridge: inflammation
```

**Sheaf Colimit feedback loops (examples):**
```
[0.82]  inflammation  ↔  insulin resistance
[0.79]  obesity  ↔  inflammation
```

None of these were written in any single paper — they were **forced by categorical coherence**.

---

## Connection to Course Material

| Concept Used | Where in Project | Textbook Reference |
|---|---|---|
| **Kan Extension** | `_run_kan_extension()` in `democritus_discovery.py` | Chapter: *Kan Extension and Topological Coend Transformers* (p. 143) |
| **Sheaf / Colimit** | `_run_sheaf_colimit()` in `democritus_discovery.py` | Chapter: *Topos Causal Models* (p. 321) |
| **Functor** | The mapping from documents → causal claims | Chapter: *Causality from Language* (p. 273) |
| **cSQL / Topos** | The SQLite schema that stores causal structure | Chapter: *CSQL: Mapping Documents into Topos Causal Model Databases* (p. 371) |
| **Geometric mean as ⊗** | Confidence propagation in Kan Extension | Chapter: *Judo Calculus* (p. 335) |
| **Conscious Workspace** | The base CLIFF system | Chapter: *Consciousness* (p. 493) |

---

## Key Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `--min-confidence` | 0.25 | Minimum confidence for a novel claim to be reported |
| `--max-kan` | 40 | Maximum Kan Extension claims to return |
| `--max-colimit` | 20 | Maximum Sheaf Colimit claims to return |
| `--force-seed` | False | Re-extract from PDFs even if a database already exists |
| `--no-browser` | False | Don't auto-open the HTML dashboard |

---

## Troubleshooting

**"No .sqlite found"** → Run Step 1 (CLIFF) first, or use `--force-seed` to build from PDFs.

**"0 novel claims"** → Lower `--min-confidence` to 0.10, or check that PDFs were extracted correctly.

**WinError 267 (Windows)** → The `--democritus-assets-dir` fix in `run_glp1_discovery.py` passes an absolute path to avoid this; make sure you're using the updated file.

**"pdfplumber not found"** → Run `pip install pdfplumber`. The built-in knowledge base will still work without it.