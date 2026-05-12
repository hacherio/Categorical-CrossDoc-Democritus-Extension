"""
Categorical Causal discovery for democritus and CLIFF 
This file reads SQLite database of causal claims that CLIFF

Categorical Causal Discovery for Democritus / CLIFF
-  stated-claims graph stored in cSQL (SQLite) databases produced by CLIFF/Democritus:

  1. Kan Extension  — A→B (doc 1) + B→C (doc 2) ⟹ A→C  (conf = geometric mean)
  2. Sheaf Colimit  — A→B conflicts with B→A ⟹ A↔B feedback loop (conf = harmonic mean)

Usage (standalone):
    python -m functorflow_v3.democritus_discovery --outdir ./cliff_results_v2
    python -m functorflow_v3.democritus_discovery --csql PATH/TO/democritus_csql.sqlite

Usage (as module):
    from functorflow_v3.democritus_discovery import run_discovery, write_discovery_outputs
"""
from __future__ import annotations

import argparse, html, json, math, re, sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path


# data class
@dataclass(frozen=True)
class StatedEdge:
    subj: str; rel: str; obj: str; domain: str
    document_support: int; claim_count: int; confidence: float

@dataclass(frozen=True)
class NovelClaim:
    source: str; relation: str; target: str; domain: str
    confidence: float; mechanism: str; explanation: str
    intermediate: str = ""; chain_doc_support_1: int = 0; chain_doc_support_2: int = 0
    domain_relevance: float = 0.0  # used for ranking only, not serialised to HTML
    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("domain_relevance", None)
        return d

@dataclass
class DiscoveryResult:
    query: str; sqlite_path: str
    total_stated_claims: int; total_documents: int
    kan_extension_claims: list[NovelClaim] = field(default_factory=list)
    sheaf_colimit_claims: list[NovelClaim] = field(default_factory=list)
    @property
    def all_novel_claims(self) -> list[NovelClaim]:
        return self.kan_extension_claims + self.sheaf_colimit_claims


# ── Query metadata helper ─────────────────────────────────────────────────────

def _read_query_from_run_metadata(sqlite_path: Path) -> str:
    """
    FIX 7: Walk up from the sqlite to find the CLIFF run summary JSON and read
    the original browser query from it.

    Expected layout (produced by cliff_worker / query_router_agentic):
        <run_root>/
            ff2_query_router_summary.json   ← contains {"query": "..."}
            democritus/
                democritus_runs/
                    csql/
                        democritus_csql.sqlite   ← sqlite_path (4 levels down)

    We also check 3 and 2 levels up in case the layout differs slightly, and
    look for alternative filenames (worker_result.json, cliff_result.json).
    """
    _CANDIDATE_NAMES = (
        "ff2_query_router_summary.json",
        "worker_result.json",
        "cliff_result.json",
    )
    p = Path(sqlite_path).resolve()
    # Walk up at most 6 levels
    for _ in range(6):
        p = p.parent
        for name in _CANDIDATE_NAMES:
            candidate = p / name
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    q = str(data.get("query", "")).strip()
                    if q:
                        return q
                except Exception:
                    pass
    return ""


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_total_docs(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
    return int(row[0]) if row else 1

def _load_stated_edges(conn: sqlite3.Connection, total_docs: int) -> list[StatedEdge]:
    rows = conn.execute("""
        SELECT canonical_subj, canonical_rel, canonical_obj, canonical_domain,
               document_support, claim_count
        FROM   aggregated_edges
        WHERE  canonical_subj != '' AND canonical_obj != ''
        ORDER  BY document_support DESC, claim_count DESC
    """).fetchall()
    denom = max(total_docs, 1)

    if total_docs <= 1:
        # With 1 document every edge has document_support=1, so ds/denom=1.0
        # for everything — confidence becomes meaningless and all Kan/Colimit
        # scores collapse to 1.00.  Use log-normalised claim_count as a proxy
        # so that edges mentioned more times in the paper score higher than
        # edges mentioned once.
        max_cc = max((cc for *_, cc in rows), default=1)
        return [
            StatedEdge(subj=s, rel=r, obj=o, domain=d or "general",
                       document_support=ds, claim_count=cc,
                       confidence=round(
                           min(1.0, math.log1p(cc) / math.log1p(max(max_cc, 1))), 3
                       ))
            for s, r, o, d, ds, cc in rows if s and o and r and s != o
        ]

    return [
        StatedEdge(subj=s, rel=r, obj=o, domain=d or "general",
                   document_support=ds, claim_count=cc,
                   confidence=min(1.0, ds / denom))
        for s, r, o, d, ds, cc in rows if s and o and r and s != o
    ]


# domain filtering
_GLP1_TOKENS: frozenset[str] = frozenset({
    "glp", "semaglutide", "liraglutide", "exenatide", "dulaglutide", "tirzepatide",
    "obesity", "diabetes", "insulin", "cardiovascular", "inflammation", "hba1c",
    "glucose", "weight", "beta cell", "ldl", "hdl", "triglyceride", "blood pressure",
    "hypertension", "crp", "interleukin", "tnf", "atherosclerosis", "heart", "renal",
    "liver", "nafld", "glucagon", "mortality", "receptor", "agonist", "glycemic",
    "adipose", "visceral", "fat", "pancreatic", "endothelial", "oxidative",
    "mace", "stroke", "myocardial",
})

# filter doesn't strip out all edges when the query is not GLP-1 related.
_DEPRESSION_CVD_TOKENS: frozenset[str] = frozenset({
    "depression", "depressive", "anxiety", "mental", "mood", "psychiatric",
    "cardiovascular", "cardiac", "heart", "coronary", "myocardial", "stroke",
    "atherosclerosis", "hypertension", "blood pressure", "inflammation",
    "inflammatory", "cytokine", "serotonin", "cortisol", "hpa", "autonomic",
    "endothelial", "platelet", "arrhythmia", "mortality", "morbidity",
    "antidepressant", "ssri", "psychosocial", "stress", "ischemic",
    "thrombosis", "fibrinogen", "crp", "interleukin", "cholesterol",
    "diabetes", "obesity", "insulin", "aging", "gender",
})

_GENERAL_BIOMEDICAL_TOKENS: frozenset[str] = frozenset({
    "disease", "disorder", "syndrome", "condition", "patient", "clinical",
    "treatment", "therapy", "drug", "medication", "risk", "factor",
    "mechanism", "pathway", "signaling", "gene", "protein", "cell",
    "tissue", "organ", "blood", "immune", "metabolic", "neural",
    "cognitive", "behavioral", "chronic", "acute", "severity",
    "mortality", "morbidity", "prevalence", "incidence",
})


def _detect_domain_tokens(query: str) -> frozenset[str] | None:
    """
    FIX 3: Detect the relevant domain from the query string so that the domain
    filter does not strip out edges for non-GLP-1 queries.

    Returns None when the query is unrecognisably broad (disables filtering).
    """
    q = query.lower()
    if any(t in q for t in ("glp", "semaglutide", "liraglutide", "obesity weight loss drug")):
        return _GLP1_TOKENS
    if any(t in q for t in ("depression", "anxiety", "mental health", "mood")):
        return _DEPRESSION_CVD_TOKENS | _GLP1_TOKENS
    if any(t in q for t in ("cardiovascular", "cardiac", "heart disease", "stroke")):
        return _DEPRESSION_CVD_TOKENS | _GLP1_TOKENS
    if any(t in q for t in ("cancer", "tumor", "oncol")):
        return None  # no filter — let all edges through
    # For all other queries, use a broad biomedical filter so we don't drop
    # legitimate edges just because they aren't GLP-1 specific.
    return _GENERAL_BIOMEDICAL_TOKENS

def _domain_filter(edges: list[StatedEdge],
                   tokens: frozenset[str] | None = None) -> list[StatedEdge]:
    if not tokens:
        return edges
    def hit(t: str) -> bool:
        low = t.lower()
        return any(tok in low for tok in tokens)
    return [e for e in edges if hit(e.subj) or hit(e.obj)]

def _domain_relevance_score(text: str, tokens: frozenset[str] = _GLP1_TOKENS) -> float:
    """Return fraction of domain tokens found in text; used for ranking."""
    low = text.lower()
    hits = sum(1 for tok in tokens if tok in low)
    return hits / max(len(tokens), 1)


# ── Token-overlap bridge matching ─────────────────────────────────────────────

_STOP: frozenset[str] = frozenset({
    "a","an","the","of","in","on","to","by","with","and","or","is","are","be",
    "as","for","its","their","that","this","which","when","while","through",
    "from","into","via","due","because","between","within","among","after",
    "before","during","under","over","about","against","without","increase",
    "decrease","effect","effects","impact","impacts","lead","leads","cause",
    "causes","result","results","may","can","could","would","should","will",
    "has","have","had","not","no","also","well","more","less","most","least",
    "one","two","three","high","low","new","specific","certain","overall",
    "significant","various","including","such","other","both","each","all",
    "some","any","these","those","they","them","there","here","been","being",
})

# FIX 1: Raised from 1 → 2.
MIN_OVERLAP: int = 2

# FIX 2 (revised again): Lowered from 2 → 1.
# MIN_COLIMIT_OVERLAP=2 was still too strict for single-concept entities.
# For a genuine polarity conflict like "depression → heart disease" vs
# "heart disease → depression", the backward token overlap is:
#   |tokens("depression") ∩ tokens("depression")| = |{"depress"}| = 1
# which fails ≥2, silently discarding every single-word entity conflict.
# ANY entity whose canonical form is one word (depression, obesity,
# stress, insulin, aging …) will always produce bwd_overlap=1 no matter
# how obvious the polarity conflict is.  Lowering to 1 catches all genuine
# conflicts; the domain filter already guards against unrelated pairs.
MIN_COLIMIT_OVERLAP: int = 1

def _token_set(text: str) -> frozenset[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    return frozenset(
        w.rstrip("s") if len(w) > 4 else w
        for w in words
        if w not in _STOP and len(w) >= 3
    )

def _build_bridge_index(edges: list[StatedEdge]) -> dict[str, list[StatedEdge]]:
    """Token → edges whose subj contains that token."""
    index: dict[str, list[StatedEdge]] = defaultdict(list)
    for e in edges:
        for tok in _token_set(e.subj):
            index[tok].append(e)
    return index

def _successors(e1: StatedEdge,
                index: dict[str, list[StatedEdge]]) -> list[tuple[StatedEdge, int]]:
    """Return (edge, overlap_count) for edges whose subj shares ≥MIN_OVERLAP tokens with e1.obj."""
    obj_toks = _token_set(e1.obj)
    if not obj_toks:
        return []
    counts: dict[int, int] = defaultdict(int)
    edges_by_id: dict[int, StatedEdge] = {}
    for tok in obj_toks:
        for e2 in index.get(tok, []):
            eid = id(e2)
            counts[eid] += 1
            edges_by_id[eid] = e2
    return [(e, counts[eid]) for eid, e in edges_by_id.items()
            if counts[eid] >= MIN_OVERLAP]


# ── FIX 4: Relation synthesis considers BOTH leg polarities ──────────────────

_NEG_RELS = {"reduces", "decreases", "prevents", "blocks", "inhibits"}
_POS_RELS = {"increases", "causes", "affects", "promotes", "leads", "leads_to"}

def _rel_polarity(rel: str) -> str:
    r = rel.lower().replace("-", "_")
    if any(w in r for w in _NEG_RELS):
        return "neg"
    if any(w in r for w in _POS_RELS):
        return "pos"
    return "neu"

def _synth_rel(rel1: str, rel2: str) -> str:
    """
    Derive the synthesised relation for A→B→C from leg polarities.

    Polarity table:
      pos × pos → causes  (A causes B, B causes C ⟹ A causes C)
      pos × neg → indirectly_reduces
      neg × pos → indirectly_reduces  (A reduces B, B causes C ⟹ A reduces C)
      neg × neg → indirectly_increases (double negation)
      anything with neu → indirectly_affects
    """
    if rel1 == rel2:
        return rel1
    p1, p2 = _rel_polarity(rel1), _rel_polarity(rel2)
    if p1 == "neg" and p2 == "neg":
        return "indirectly_increases"
    if "neg" in (p1, p2):
        return "indirectly_reduces"
    if p1 == "pos" and p2 == "pos":
        return "causes"  # BUG FIX: was "indirectly_increases" — pos×pos is "causes"
    return "indirectly_affects"


# ── Kan Extension Engine ──────────────────────────────────────────────────────

def _kan_domain_rank(c: NovelClaim) -> float:
    """FIX 6: Score for re-ranking — penalise generic/non-GLP-1 claims."""
    src_rel = _domain_relevance_score(c.source) + _domain_relevance_score(c.target)
    return -(c.confidence * 10 + src_rel)  # negate so higher = better when sorted ascending

def _run_kan_extension(
    edges: list[StatedEdge],
    stated_pairs: set[tuple[str, str]],
    *,
    bridge_index: dict[str, list[StatedEdge]] | None = None,
    max_novel: int = 40,
    min_confidence: float = 0.10,
) -> list[NovelClaim]:
    """
    Right Kan Extension: for every composable A→B, B→C, entail A→C.
    Uses token-overlap bridge matching (MIN_OVERLAP=2 shared content words).
    Results are re-ranked: domain-relevant claims (GLP-1 terms) come first.
    Accepts a pre-built bridge_index to avoid rebuilding it if run_discovery
    already built one for diagnostics.
    """
    index = bridge_index if bridge_index is not None else _build_bridge_index(edges)
    seen: set[tuple[str, str]] = set()
    novel: list[NovelClaim] = []

    for e1 in edges:
        for e2, overlap in _successors(e1, index):
            A, C = e1.subj, e2.obj
            if A == C: continue
            # BUG FIX: was `& _token_set(A)` (subset check), which wrongly pruned
            # A→C whenever all of A's tokens appeared anywhere in C's text — e.g.
            # "glp1 receptor agonist" → anything that mentions receptor/agonist.
            # The intent is only to skip A and C that are *the same concept*.
            if _token_set(A) == _token_set(C): continue
            key = (A, C)
            if key in stated_pairs or key in seen: continue
            seen.add(key)
            conf = math.sqrt(e1.confidence * e2.confidence)
            if conf < min_confidence: continue
            dom_rel = _domain_relevance_score(A) + _domain_relevance_score(C)
            novel.append(NovelClaim(
                source=A, relation=_synth_rel(e1.rel, e2.rel), target=C,
                domain=e1.domain, confidence=round(conf, 3),
                mechanism="kan_extension",
                explanation=(
                    f"Kan extension: {A} –[{e1.rel}]→ {e1.obj} –[{e2.rel}]→ {C}. "
                    f"Bridge overlap={overlap} tokens. "
                    f"No document stated A→C directly. "
                    f"conf = √({e1.confidence:.2f}×{e2.confidence:.2f}) = {conf:.2f}."
                ),
                intermediate=e1.obj,
                chain_doc_support_1=e1.document_support,
                chain_doc_support_2=e2.document_support,
                domain_relevance=dom_rel,
            ))

    # FIX 6: Sort by (confidence DESC, domain_relevance DESC) so GLP-1-specific
    # claims surface before generic receptor/agonist chains.
    novel.sort(key=lambda c: (-c.confidence, -c.domain_relevance))
    return novel[:max_novel]


# sheaf colimit
def _run_sheaf_colimit(
    edges: list[StatedEdge],
    *,
    total_docs: int = 1,
    max_novel: int = 20,
    min_confidence: float = 0.10,
) -> list[NovelClaim]:
    if total_docs < 2:
        print(
            f"[discovery] ⚠  Sheaf Colimit skipped: only {total_docs} source document(s). "
            "A categorical polarity conflict requires ≥2 papers asserting opposite "
            "directions. Re-run CLIFF with a query that retrieves more documents."
        )
        return []
    seen: set[str] = set()
    novel: list[NovelClaim] = []
    n_checked = n_overlap_fail = 0  # FIX 5: diagnostic counters

    for i, e1 in enumerate(edges):
        s1, o1 = _token_set(e1.subj), _token_set(e1.obj)
        if not s1 or not o1: continue
        for e2 in edges[i+1:]:
            s2, o2 = _token_set(e2.subj), _token_set(e2.obj)
            n_checked += 1
            fwd_overlap = len(s2 & o1)
            bwd_overlap = len(o2 & s1)
            if fwd_overlap < MIN_COLIMIT_OVERLAP or bwd_overlap < MIN_COLIMIT_OVERLAP:
                n_overlap_fail += 1
                continue
            canonical_subj = " ".join(sorted(s1))
            canonical_obj  = " ".join(sorted(o1))
            pair_key = f"{canonical_subj}||{canonical_obj}"
            if pair_key in seen: continue
            seen.add(pair_key)
            p, q = e1.confidence, e2.confidence
            if p + q == 0: continue
            conf = round(2 * p * q / (p + q), 3)
            if conf < min_confidence: continue
            novel.append(NovelClaim(
                source=e1.subj, relation="bidirectional_feedback", target=e1.obj,
                domain=e1.domain, confidence=conf, mechanism="sheaf_colimit",
                explanation=(
                    f"Sheaf colimit: {e1.subj}→{e1.obj} (support={e1.document_support}) "
                    f"conflicts with {e2.subj}→{e2.obj} (support={e2.document_support}). "
                    f"Colimit = {e1.subj}↔{e1.obj}; "
                    f"conf = 2·{p:.2f}·{q:.2f}/({p:.2f}+{q:.2f}) = {conf:.2f}."
                ),
                chain_doc_support_1=e1.document_support,
                chain_doc_support_2=e2.document_support,
            ))
    print(f"[discovery] Sheaf colimit: {n_checked} pairs checked, "
          f"{n_overlap_fail} failed overlap≥{MIN_COLIMIT_OVERLAP}, "
          f"{len(novel)} conflicts found.")
    novel.sort(key=lambda c: (-c.confidence, c.source))
    return novel[:max_novel]


# ── Public API ────────────────────────────────────────────────────────────────

def run_discovery(
    *,
    sqlite_path: Path,
    query: str = "",
    max_kan: int = 40,
    max_colimit: int = 20,
    min_confidence: float = 0.10,
    domain_tokens: frozenset[str] | None = None,  # FIX 3: default None → auto-detect
) -> DiscoveryResult:
    sqlite_path = Path(sqlite_path).resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"cSQL not found: {sqlite_path}")

    # FIX 7: if no query was supplied by the caller, read the original CLIFF
    # browser query from the run-level ff2_query_router_summary.json so that
    # the dashboard always shows the query that was actually submitted.
    if not query:
        query = _read_query_from_run_metadata(sqlite_path)

    # FIX 3: auto-detect domain tokens from the query if not supplied explicitly.
    if domain_tokens is None:
        domain_tokens = _detect_domain_tokens(query)
        if domain_tokens is None:
            print("[discovery] No domain filter applied (broad/unknown query topic).")
        else:
            print(f"[discovery] Auto-detected domain filter: {len(domain_tokens)} tokens.")

    with sqlite3.connect(str(sqlite_path)) as conn:
        total_docs = _load_total_docs(conn)
        edges_raw  = _load_stated_edges(conn, total_docs)

    edges = _domain_filter(edges_raw, domain_tokens)
    print(f"[discovery] Raw edges: {len(edges_raw)}  →  Domain-filtered: {len(edges)}")

    # If domain filtering is too aggressive (keeps <10% of edges), fall back to
    # unfiltered so the sheaf colimit has enough material to work with.
    if edges_raw and len(edges) < max(5, len(edges_raw) // 10):
        print(f"[discovery] ⚠  Filter too aggressive ({len(edges)}/{len(edges_raw)} edges). "
              "Falling back to unfiltered edges.")
        edges = edges_raw

    index = _build_bridge_index(edges)
    n_with_succ = sum(1 for e in edges if _successors(e, index))
    print(f"[discovery] MIN_OVERLAP={MIN_OVERLAP}: {n_with_succ}/{len(edges)} edges have ≥1 successor")
    samples = [(e, _successors(e, index)) for e in edges if _successors(e, index)][:3]
    for e, succs in samples:
        print(f"  BRIDGE  {e.subj[:50]} → {e.obj[:40]}")
        print(f"    SUCC  {succs[0][0].subj[:50]}")

    stated = {(e.subj, e.obj) for e in edges}
    return DiscoveryResult(
        query=query, sqlite_path=str(sqlite_path),
        total_stated_claims=len(edges), total_documents=total_docs,
        kan_extension_claims=_run_kan_extension(
            edges, stated, bridge_index=index,  # reuse already-built index
            max_novel=max_kan, min_confidence=min_confidence),
        sheaf_colimit_claims=_run_sheaf_colimit(
            edges, total_docs=total_docs, max_novel=max_colimit, min_confidence=min_confidence),
    )


# ── HTML Dashboard ────────────────────────────────────────────────────────────

_CSS = """
:root{--bg:#f8f7f4;--card:#fff;--accent:#1a6b3a;--text:#1c1c1c;--muted:#6b6b6b;
  --border:#e0ddd8;--kan-bg:#e8f5ed;--kan-b:#2e7d52;--col-bg:#fef3e8;--col-b:#c0591e}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Georgia,serif;background:var(--bg);color:var(--text)}
.hero{background:linear-gradient(135deg,#0d3d24,#1a6b3a,#2e9e5c);color:#fff;padding:2.5rem}
.hero h1{font-size:2rem;margin-bottom:.4rem}
.meta{margin-top:.8rem;display:flex;gap:1rem;flex-wrap:wrap}
.badge{background:rgba(255,255,255,.15);border-radius:999px;padding:.2rem .7rem;font-size:.83rem}
.container{max-width:1100px;margin:0 auto;padding:2rem 1.5rem}
.section-title{font-size:1.4rem;margin:2rem 0 .6rem;color:var(--accent);
  border-bottom:2px solid var(--border);padding-bottom:.3rem}
.theory-box{background:#f0f8f4;border-left:4px solid var(--accent);
  padding:.9rem 1.1rem;margin-bottom:1.2rem;border-radius:4px}
.theory-box h3{color:var(--accent);margin-bottom:.3rem}
.theory-box p{font-size:.9rem;line-height:1.6}
.theory-box code{background:#e0ede7;padding:0 .25rem;border-radius:3px;font-family:monospace}
.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:.8rem;margin-bottom:1.5rem}
.stat-box{background:var(--card);border-radius:8px;padding:.9rem;text-align:center;
  box-shadow:0 1px 4px rgba(0,0,0,.07)}
.stat-box .num{font-size:2rem;font-weight:bold;color:var(--accent)}
.stat-box .label{font-size:.8rem;color:var(--muted);margin-top:.15rem}
.claim-grid{display:grid;gap:.9rem;margin-bottom:1.5rem}
.claim-card{background:var(--card);border-radius:8px;padding:1.1rem 1.3rem;
  box-shadow:0 1px 4px rgba(0,0,0,.08)}
.claim-card.kan{border-left:5px solid var(--kan-b);background:var(--kan-bg)}
.claim-card.colimit{border-left:5px solid var(--col-b);background:var(--col-bg)}
.claim-header{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;margin-bottom:.5rem}
.claim-triple{font-size:1rem;font-weight:bold}
.claim-triple .arrow{color:var(--muted)}
.pill{border-radius:999px;padding:.15rem .6rem;font-size:.78rem;font-weight:bold;color:#fff}
.pill.high{background:#1a6b3a}.pill.mid{background:#e07b30}.pill.low{background:#888}
.pill.mech{background:#333}
.claim-explanation{font-size:.87rem;color:#444;line-height:1.6;margin-top:.4rem}
.via{font-size:.8rem;color:var(--muted);margin-top:.25rem}
.footer{text-align:center;padding:1.5rem;color:var(--muted);font-size:.83rem}
"""

def _esc(t: str) -> str: return html.escape(str(t))

def _render_card(c: NovelClaim) -> str:
    kind = "kan" if c.mechanism == "kan_extension" else "colimit"
    mech = "Kan Extension" if c.mechanism == "kan_extension" else "Sheaf Colimit"
    cc   = "high" if c.confidence >= 0.7 else "mid" if c.confidence >= 0.4 else "low"
    via  = (f'<div class="via">via bridge: <strong>{_esc(c.intermediate)}</strong> '
            f'(chain support: {c.chain_doc_support_1}×{c.chain_doc_support_2})</div>'
            if c.intermediate else "")
    return f"""<div class="claim-card {kind}">
  <div class="claim-header">
    <span class="claim-triple"><strong>{_esc(c.source)}</strong>
      <span class="arrow"> –[{_esc(c.relation)}]→ </span>
      <strong>{_esc(c.target)}</strong></span>
    <span class="pill {cc}">conf {c.confidence:.2f}</span>
    <span class="pill mech">{_esc(mech)}</span>
  </div>
  <div class="claim-explanation">{_esc(c.explanation)}</div>
  {via}
</div>"""

def render_discovery_html(result: DiscoveryResult, *, query: str = "") -> str:
    q     = _esc(query or result.query or "GLP-1 causal discovery")
    total = len(result.all_novel_claims)
    stats = f"""<div class="stats-row">
  <div class="stat-box"><div class="num">{result.total_documents}</div><div class="label">source docs</div></div>
  <div class="stat-box"><div class="num">{result.total_stated_claims}</div><div class="label">stated edges</div></div>
  <div class="stat-box"><div class="num">{len(result.kan_extension_claims)}</div><div class="label">Kan Extension</div></div>
  <div class="stat-box"><div class="num">{len(result.sheaf_colimit_claims)}</div><div class="label">Sheaf Colimit</div></div>
  <div class="stat-box"><div class="num">{total}</div><div class="label">total novel</div></div>
</div>"""
    kan_theory = """<div class="theory-box"><h3>Right Kan Extension</h3>
<p>The stated-claims functor <code>F: StatedCat → CausalSpace</code> knows A→B and B→C.
The right Kan extension <code>RanJF</code> along <code>J: StatedCat ↪ AllPathsCat</code>
entails A→C by universal path composition.
Confidence: <code>conf(A→C) = √(conf(A→B)·conf(B→C))</code> — the monoidal ⊗ product
in the UDM reward semiring (Judo Calculus).</p></div>"""
    col_theory = f"""<div class="theory-box"><h3>Sheaf Colimit</h3>
<p>When paper S₁ asserts A→B and S₂ asserts B→A, each is a <em>local section</em>
of the causal presheaf over {{A,B}}. These conflict and cannot glue globally.
The <em>colimit</em> is the <strong>universal model</strong> A↔B that both factor through.
Confidence: <code>2pq/(p+q)</code> (harmonic mean). Requires ≥{MIN_COLIMIT_OVERLAP}
shared content tokens on each side to qualify as a genuine polarity conflict.</p></div>"""
    kan_cards = "\n".join(_render_card(c) for c in result.kan_extension_claims) or \
        "<p>No Kan-extension novel claims found at this confidence threshold.</p>"
    col_cards = "\n".join(_render_card(c) for c in result.sheaf_colimit_claims) or \
        "<p>No sheaf-colimit feedback loops found at this confidence threshold.</p>"
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Categorical Causal Discovery – {q}</title>
<style>{_CSS}</style></head><body>
<div class="hero">
  <h1>Categorical Causal Discovery</h1>
  <div style="opacity:.8">Novel claims forced by Kan Extension and Sheaf Colimit coherence</div>
  <div class="meta">
    <span class="badge">Query: {q}</span>
    <span class="badge">Source: {_esc(Path(result.sqlite_path).name)}</span>
    <span class="badge">{total} novel claims</span>
  </div>
</div>
<div class="container">
  <h2 class="section-title">Overview</h2>{stats}
  <h2 class="section-title">Part I — Kan Extension: Path-Composed Claims</h2>
  {kan_theory}<div class="claim-grid">{kan_cards}</div>
  <h2 class="section-title">Part II — Sheaf Colimit: Bidirectional Feedback Loops</h2>
  {col_theory}<div class="claim-grid">{col_cards}</div>
</div>
<div class="footer">CMPSCI 692CT · Category Theory for AGI · UMass Amherst ·
  cSQL: {_esc(result.sqlite_path)}</div>
</body></html>"""

def write_discovery_outputs(
    result: DiscoveryResult, *, outdir: Path, query: str = ""
) -> tuple[Path, Path]:
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "discovery_summary.json"
    html_path = outdir / "discovery_dashboard.html"
    # FIX 7: prefer the caller-supplied query, then result.query (which was already
    # resolved from metadata inside run_discovery), so the HTML always matches the
    # actual CLIFF browser query rather than a hardcoded default.
    effective_query = query or result.query
    json_path.write_text(json.dumps({
        "query": effective_query, "sqlite_path": result.sqlite_path,
        "total_documents": result.total_documents,
        "total_stated_claims": result.total_stated_claims,
        "novel_kan_extension_count": len(result.kan_extension_claims),
        "novel_sheaf_colimit_count": len(result.sheaf_colimit_claims),
        "kan_extension_claims": [c.as_dict() for c in result.kan_extension_claims],
        "sheaf_colimit_claims": [c.as_dict() for c in result.sheaf_colimit_claims],
    }, indent=2), encoding="utf-8")
    html_path.write_text(
        render_discovery_html(result, query=effective_query), encoding="utf-8")
    return json_path, html_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Categorical Causal Discovery via Kan Extension and Sheaf Colimit")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--csql",   metavar="SQLITE_PATH")
    grp.add_argument("--outdir", metavar="CLIFF_OUTDIR")
    p.add_argument("--query", default="",
                   help="Query label for the dashboard. If omitted, read from CLIFF run metadata.")
    p.add_argument("--min-confidence",  type=float, default=0.10)
    p.add_argument("--max-kan",         type=int,   default=40)
    p.add_argument("--max-colimit",     type=int,   default=20)
    p.add_argument("--discovery-outdir",default=None)
    args = p.parse_args()

    if args.csql:
        sqlite_path = Path(args.csql)
    else:
        # FIX 5: sort by mtime descending → pick the MOST RECENT database.
        candidates = (
            sorted(Path(args.outdir).rglob("democritus_csql.sqlite"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
            or sorted(Path(args.outdir).rglob("*.sqlite"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        )
        if not candidates:
            print(f"[discovery] No .sqlite found under {args.outdir}. Run CLIFF first.")
            return
        print(f"[discovery] Found {len(candidates)} database(s):")
        for pb in candidates: print(f"  {pb}")
        sqlite_path = candidates[0]  # most recent

    print(f"\n[discovery] Reading: {sqlite_path}")

    # FIX 7: if --query was not supplied on the CLI, try to read it from the
    # CLIFF run metadata so the dashboard header matches the browser query.
    effective_query = args.query or _read_query_from_run_metadata(sqlite_path)
    if effective_query and effective_query != args.query:
        print(f"[discovery] Query read from run metadata: {effective_query[:80]}")

    result = run_discovery(
        sqlite_path=sqlite_path, query=effective_query,
        max_kan=args.max_kan, max_colimit=args.max_colimit,
        min_confidence=args.min_confidence,
    )
    print(f"[discovery] Stated claims : {result.total_stated_claims}")
    print(f"[discovery] Documents     : {result.total_documents}")
    print(f"[discovery] Kan Extension : {len(result.kan_extension_claims)}")
    print(f"[discovery] Sheaf Colimit : {len(result.sheaf_colimit_claims)}")

    out = Path(args.discovery_outdir) if args.discovery_outdir \
          else sqlite_path.parent.parent / "discovery"
    json_path, html_path = write_discovery_outputs(result, outdir=out, query=effective_query)
    print(f"\n[discovery] JSON : {json_path}")
    print(f"[discovery] HTML : {html_path}")
    print(f'  Open:  start "{html_path}"  (Windows)')

    if result.kan_extension_claims:
        print("\n── Top Kan Extension Claims ──")
        for c in result.kan_extension_claims[:6]:
            print(f"  [{c.confidence:.2f}] {c.source}")
            print(f"        –[{c.relation}]→  {c.target}")
            print(f"        via: {c.intermediate}")
    if result.sheaf_colimit_claims:
        print("\n── Sheaf Colimit Feedback Loops ──")
        for c in result.sheaf_colimit_claims[:6]:
            print(f"  [{c.confidence:.2f}] {c.source} ↔ {c.target}")

if __name__ == "__main__":
    main()