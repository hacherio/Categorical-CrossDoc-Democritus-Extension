# Categorical Causal Discovery — Cross-Document Extension for CLIFF/Democritus

> **CMPSCI 692CT: Category Theory for AGI · University of Massachusetts Amherst**
> Forked from [sridharmahadevan/CLIFF_CatAgi](https://github.com/sridharmahadevan/CLIFF_CatAgi)

---

## What This Project Does

This repository extends the [CLIFF](https://github.com/sridharmahadevan/CLIFF_CatAgi) (Conscious Layer Interface in FunctorFlow) system with a **categorical causal discovery layer** that sits on top of the Democritus agent.

CLIFF's Democritus subsystem retrieves scientific documents and extracts structured causal relationships into a SQLite database (CSQL). It answers: *which causal claims are explicitly stated across documents?*

This extension answers the follow-up question:

> **Given the claims documents do state, what additional causal relationships are mathematically forced to exist — but no document ever directly wrote down?**

Two category-theoretic mechanisms close this gap:

### 1. Kan Extension
For every two-step chain **A → B → C** supported by retrieved papers, the system infers **A → C** with a conservative geometric-mean confidence, even if no paper ever stated that connection directly. This is the right Kan extension of the stated-claims functor along the path inclusion functor.

```
conf(A → C) = √(conf(A → B) × conf(B → C))
```

### 2. Sheaf Colimit
When one paper asserts **A → B** and another asserts **B → A**, these are conflicting local sections of the causal presheaf over the site {A, B}. Rather than discarding one, the system resolves the contradiction as a **bidirectional feedback loop A ↔ B** using harmonic-mean confidence.

```
conf(A ↔ B) = 2pq / (p + q)
```

---

## Key Results

Applied to a corpus of three documents on **sleep deprivation, cortisol, and related conditions**:

| Metric | Value |
|---|---|
| Source documents | 3 |
| Raw causal edges (pre-filter) | 401 |
| Domain-filtered edges | 177 |
| Edges with ≥1 successor | 83 / 177 (47%) |
| **Kan Extension novel claims** | **40** |
| **Sheaf Colimit feedback loops** | **20** |
| **Total novel claims** | **60** |

Example Kan Extension claim (never stated in any source document):
```
[0.33] childhood obesity –[increases]→ insulin resistance –[causes]→ higher blood pressure
```

Example Sheaf Colimit feedback loop:
```
[0.44] sleep deprivation ↔ cognitive performance in adults
```

---

## Architecture

```
User Query (CLIFF Browser)
        ↓
   CLIFF Router
        ↓
  Democritus Agent
  ├── Downloads & parses papers
  ├── Extracts causal claims
  └── Writes → democritus_csql.sqlite
        ↓
  run_causal_discovery.py          ← NEW (this extension)
  ├── Locates CSQL database
  ├── Reads run metadata & query
  ├── Applies domain filter
  ├── democritus_discovery.py      ← NEW (this extension)
  │   ├── Kan Extension engine
  │   └── Sheaf Colimit engine
  └── Writes → discovery_dashboard.html + discovery_summary.json
```

### New Files Added

| File | Purpose |
|---|---|
| `functorflow_v3/democritus_discovery.py` | Core categorical modules: Kan Extension, Sheaf Colimit, SQLite reader, JSON/HTML output |
| `functorflow_v3/run_causal_discovery.py` | Orchestrator: locates CSQL database, reads run metadata, launches discovery, opens browser |

Modified to integrate with the new files: `query_router_agentic.py`, `democritus_batch_agentic.py`, `democritus_agentic.py`, `cliff_worker.py`.

---

## Installation

```bash
git clone https://github.com/hacherio/Categorical-CrossDoc-Democritus-Extension
cd Categorical-CrossDoc-Democritus-Extension

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -e .
```

---

## Usage

### Step 1 — Run CLIFF and submit a query

```bash
python -m functorflow_v3.cliff \
  --outdir ./cliff_results_v2 \
  --course-repo-root "/path/to/Category-Theory-for-AGI-UMass-CMPSCI-692CT"
```

Then open the CLIFF browser UI and submit your query, for example:

> *"Find me 10 studies on the bidirectional relationship between sleep deprivation and cortisol, including papers that disagree on the primary causal direction."*

### Step 2 — Run categorical discovery

**Automatic** (finds the most recent CSQL database):
```bash
python functorflow_v3/run_causal_discovery.py --skip-cliff --min-confidence 0.10
```

**With an explicit database path:**
```bash
python functorflow_v3/run_causal_discovery.py \
  --skip-cliff \
  --csql path/to/democritus_csql.sqlite \
  --min-confidence 0.10
```

**Direct module invocation:**
```bash
python -m functorflow_v3.democritus_discovery \
  --outdir ./cliff_results_v2 \
  --query "your query here" \
  --min-confidence 0.10
```

### Outputs

Both commands write to a `discovery/` folder alongside the CSQL database:

- `discovery_summary.json` — machine-readable list of all novel claims with confidence scores, bridge nodes, and document support
- `discovery_dashboard.html` — interactive HTML dashboard opened automatically in your browser

---

## Domain Filtering

Before discovery runs, the system auto-detects domain tokens from the user's query and filters out causal edges from off-topic documents (a known Democritus drift issue). For example, a sleep/cortisol query reduced 401 raw edges to 177 relevant ones before discovery ran.

Safety guardrails halt discovery (with a warning) when:
- 0 documents were retrieved
- Fewer than 2 documents are present (Sheaf Colimit requires cross-document conflicts)
- Fewer than 4 domain-filtered edges remain after filtering

---

## Theory Background

This project applies two concepts from the course textbook *Categories for AGI* (Mahadevan, 2026):

**Kan Extensions** — The right Kan extension `RanJ F` of the stated-claims functor `F: StatedCat → CausalSpace` along the path inclusion `J: StatedCat ↪ AllPathsCat` entails new claims via universal path composition. The geometric mean is used as the monoidal ⊗ product in the UDM reward semiring (Judo Calculus), giving a conservative lower bound on confidence.

**Sheaf Colimits** — The CSQL database is modelled as a presheaf on the category of document contexts. When two local sections (papers) conflict over the same causal site {A, B}, the gluing axiom fails. The colimit is the universal model A ↔ B that both factor through, resolved with harmonic-mean confidence.

### References

1. S. Mahadevan, *Categories for AGI*, UMass Amherst / Adobe Research, 2026.
2. S. Mahadevan, [CLIFF_CatAgi](https://github.com/sridharmahadevan/CLIFF_CatAgi), GitHub, 2026.
3. S. Mahadevan, *Universal Decisions with Kan Extensions*, CMPSCI 692CT lecture slides, 2026. Also: [arXiv:2110.15431](https://arxiv.org/abs/2110.15431)
4. E. Riehl, *Category Theory in Context*, Dover Publications, 2016.

---

## Limitations & Future Work

- **Small corpora**: With 3 documents, Sheaf Colimit has limited material for cross-document conflicts. Larger corpora produce denser conflict structure and higher-confidence loops.
- **Topic drift**: Democritus can retrieve off-topic documents; the domain filter mitigates this but a stricter containment flag would help.
- **Chain depth**: The Kan Extension module currently composes only depth-1 paths (A → B → C). Iterated application could discover longer chains, though this risks exponential blowup.
- **Confidence calibration**: The geometric mean is an approximation. Longer chains with shared evidence nodes would benefit from a more rigorous scoring scheme over the full CSQL graph.

---

## Repo Structure

```
.
├── functorflow_v3/
│   ├── democritus_discovery.py     # Kan Extension + Sheaf Colimit engines (NEW)
│   ├── run_causal_discovery.py     # Discovery orchestrator (NEW)
│   ├── democritus_agentic.py       # Agentic Democritus runner (modified)
│   ├── cliff_worker.py             # CLIFF worker process (modified)
│   └── ...
├── tests/
├── examples/
├── docs/
├── catagi.pdf                      # Course textbook
├── CS692CT Report.pdf              # Final project report
└── README.md
```

---

*CMPSCI 692CT · Category Theory for AGI · University of Massachusetts Amherst*
