"""
app.py — GCC Job Market Intelligence Assistant
------------------------------------------------
Run:  streamlit run app.py

Tabs
----
  📊 Dashboard  — live Plotly charts, dynamically filtered by selected dumps
  💬 Chat       — RAG-powered Q&A with retrieval transparency + answer verification
"""

import os
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Generator

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Load OpenAI key from Streamlit secrets when deployed
try:
    if not os.getenv("OPENAI_API_KEY") and "OPENAI_API_KEY" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
except Exception:
    pass

from config import DATA_DIR, COUNTRY_FLAGS, COUNTRY_COLORS, AVAILABLE_MODELS
from data_loader import load_all, parse_file_info, sort_timelines
from vector_store import VectorStore
from analytics import AnalyticsEngine
from rag_engine import RAGEngine

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="GCC Job Market Intelligence",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; }
  .stTabs [data-baseweb="tab"] { font-size: 0.95rem; font-weight: 600; padding: 8px 20px; }
  div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stCheckbox"]) {
      background: #1a1e2e; border-radius: 10px; padding: 10px 12px;
      border: 1px solid #2a2e3b; margin-bottom: 4px;
  }
  .dump-card { background:#1a1e2e; border:1px solid #2a2e3b; border-radius:10px;
               padding:10px; text-align:center; }
  .src-card  { background:#0f1117; border-left:3px solid #6366f1;
               border-radius:4px; padding:8px 12px; margin:4px 0; font-size:0.83rem; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading job data…", ttl=3600)
def _load_data():
    df, timelines = load_all(DATA_DIR)
    # Only EN source files for indexing (exclude AR files)
    source_files = sorted(
        str(p) for p in (list(DATA_DIR.glob("*.xlsx")) + list(DATA_DIR.glob("*.csv")))
        if not parse_file_info(p)["is_ar"]
    )
    return df, timelines, source_files


@st.cache_resource(show_spinner="Initialising vector store…")
def _get_vector_store() -> VectorStore:
    return VectorStore()


# ---------------------------------------------------------------------------
# Dump metadata helpers
# ---------------------------------------------------------------------------

def _get_dump_info(df: pd.DataFrame) -> list[dict]:
    """Return one dict per unique dataset dump, with job count."""
    if "_dump_id" not in df.columns:
        return []
    groups = df.groupby(["_dump_id", "_country", "_timeline", "_dump_label"]).size().reset_index(name="count")
    dumps = groups.to_dict("records")
    # Sort: country → timeline
    dumps.sort(key=lambda d: (d["_country"], d["_timeline"]))
    return dumps


def _filter_by_dumps(df: pd.DataFrame, selected_ids: list[str]) -> pd.DataFrame:
    if not selected_ids or "_dump_id" not in df.columns:
        return df
    return df[df["_dump_id"].isin(selected_ids)]


# ---------------------------------------------------------------------------
# Answer verifier
# ---------------------------------------------------------------------------

def _verify(answer_text: str, df: pd.DataFrame) -> list[dict]:
    """
    Scan the LLM answer for numbers next to known labels.
    Compare against pandas ground truth. Return list of check results.
    """
    results = []

    # Employment type checks
    col = "_employment_norm" if "_employment_norm" in df.columns else "employment_type"
    emp_counts = df[col].dropna().value_counts().to_dict()
    for et in ["Full-Time", "Part-Time", "Contract", "Freelance", "Internship"]:
        for pat in [rf"(\d[\d,]*)\s+{re.escape(et)}", rf"{re.escape(et)}[:\s]+(\d[\d,]*)"]:
            m = re.search(pat, answer_text, re.IGNORECASE)
            if m:
                claimed = int(m.group(1).replace(",", ""))
                actual  = int(emp_counts.get(et, 0))
                results.append({
                    "label":   f"{et} jobs",
                    "claimed": claimed,
                    "actual":  actual,
                    "ok":      abs(claimed - actual) <= max(5, actual * 0.05),
                })

    # Total postings check — only when bot explicitly says "total ... postings"
    # Avoids false positives when bot mentions a subset count (e.g. "based on 843 postings")
    m = re.search(r"(\d[\d,]*)\s+total\s+(?:job\s+)?postings?", answer_text, re.IGNORECASE)
    if m:
        claimed = int(m.group(1).replace(",", ""))
        actual  = len(df)
        results.append({
            "label":   "Total postings",
            "claimed": claimed,
            "actual":  actual,
            "ok":      abs(claimed - actual) <= max(10, actual * 0.05),
        })

    return results


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _render_sidebar(df, timelines, source_files, vs) -> tuple[list[str], str]:
    """
    Render sidebar controls.
    Returns (selected_dump_ids, selected_model_id).
    """
    with st.sidebar:
        st.markdown("## 🌍 GCC Job Market")
        st.markdown("*Intelligence Assistant*")
        st.divider()

        # ── Dataset selector ───────────────────────────────────────────────
        st.markdown("### 📂 Select Datasets")
        st.caption("Toggle dumps on/off — filters the dashboard and chat.")

        all_dumps = _get_dump_info(df)
        selected_dump_ids: list[str] = []

        if all_dumps:
            from collections import defaultdict
            by_country: dict = defaultdict(list)
            for d in all_dumps:
                by_country[d["_country"]].append(d)

            c1, c2 = st.columns(2)
            if c1.button("Select All",  use_container_width=True):
                for d in all_dumps:
                    st.session_state[f"dump_{d['_dump_id']}"] = True
            if c2.button("Clear All", use_container_width=True):
                for d in all_dumps:
                    st.session_state[f"dump_{d['_dump_id']}"] = False

            for country, dumps in sorted(by_country.items()):
                flag  = COUNTRY_FLAGS.get(country, "🌍")
                color = COUNTRY_COLORS.get(country, "#666")
                st.markdown(f"**{flag} {country}**")
                cols = st.columns(max(1, min(len(dumps), 3)))
                for i, dump in enumerate(sorted(dumps, key=lambda d: d["_timeline"])):
                    key = f"dump_{dump['_dump_id']}"
                    with cols[i % len(cols)]:
                        checked = st.checkbox(
                            f"{dump['_timeline']}\n{dump['count']:,} jobs",
                            value=st.session_state.get(key, True),
                            key=key,
                        )
                    if checked:
                        selected_dump_ids.append(dump["_dump_id"])

            total_sel = _filter_by_dumps(df, selected_dump_ids).shape[0] if selected_dump_ids else 0
            st.markdown(f"**📊 {total_sel:,} jobs selected**")
        else:
            st.info("No data loaded yet.")

        st.divider()

        # ── File upload ────────────────────────────────────────────────────
        st.markdown("### ➕ Upload New Dataset")
        st.caption("Name format: `bayt_jobs_Country_DD_Mon_YYYY.xlsx`")
        uploaded = st.file_uploader(
            "Drop Excel file here", type=["xlsx", "csv"],
            label_visibility="collapsed",
        )
        if uploaded:
            dest = DATA_DIR / uploaded.name
            if dest.exists():
                st.warning(f"{uploaded.name} already exists — overwriting.")
            with open(dest, "wb") as fout:
                shutil.copyfileobj(uploaded, fout)
            info = parse_file_info(dest)
            st.success(
                f"Saved: **{uploaded.name}**\n"
                f"Country: {info['country']} | Timeline: {info['timeline']}"
            )
            _load_data.clear()
            st.rerun()

        st.divider()

        # ── Index control ──────────────────────────────────────────────────
        idx_count  = vs.count()
        needs_idx  = vs.needs_indexing(source_files)
        filt_df    = _filter_by_dumps(df, selected_dump_ids) if selected_dump_ids else df

        if idx_count == 0:
            st.error("Index not built — click below")
            btn_type = "primary"
        elif needs_idx:
            st.warning(f"Index outdated ({idx_count:,} docs)")
            btn_type = "primary"
        else:
            st.success(f"Index ready ({idx_count:,} docs)")
            btn_type = "secondary"

        if st.button("Build / Update Index", type=btn_type, use_container_width=True):
            bar = st.sidebar.progress(0, text="Embedding…")
            msg = vs.build_index_incremental(
                df, source_files,
                progress_callback=lambda d, t: bar.progress(d / t)
            )
            bar.empty()
            st.sidebar.success(msg)
            st.rerun()

        if st.button("Refresh Data", use_container_width=True):
            _load_data.clear()
            st.rerun()

        st.divider()

        # ── Model selector ─────────────────────────────────────────────────
        st.markdown("### 🤖 LLM Model")
        model_labels  = list(AVAILABLE_MODELS.keys())
        model_choice  = st.radio("", model_labels, index=0, label_visibility="collapsed")
        selected_model = AVAILABLE_MODELS[model_choice]

        st.divider()
        st.caption(f"Source: Bayt.com | {' & '.join(timelines)}")
        st.caption("ChromaDB · OpenAI · Streamlit")

    return selected_dump_ids, selected_model


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

_PLOT_LAYOUT = dict(paper_bgcolor="#0f1117", plot_bgcolor="#0f1117", font_color="#e4e6f0")


def _apply_plot_layout(fig, **extra):
    fig.update_layout(**_PLOT_LAYOUT, **extra)
    return fig


def _parse_salary_mid(val) -> float | None:
    """Parse 'min-max USD/month' or SAR strings → monthly USD midpoint."""
    if pd.isna(val) or not str(val).strip():
        return None
    s = str(val)
    nums = re.findall(r"[\d,]+", s)
    if len(nums) < 2:
        return None
    try:
        lo, hi = float(nums[0].replace(",", "")), float(nums[1].replace(",", ""))
    except ValueError:
        return None
    if lo < 1 or hi < 1:
        return None
    if "year" in s.lower() or "annual" in s.lower():
        lo, hi = lo / 12, hi / 12
    if any(x in s.upper() for x in ["SAR", " SR", "SR "]):
        lo, hi = lo / 3.75, hi / 3.75   # SAR → USD (approx)
    return (lo + hi) / 2


def _extract_city(loc) -> str:
    if pd.isna(loc):
        return "Unknown"
    s = str(loc).strip()
    for sep in ["·", ","]:
        if sep in s:
            city = s.split(sep)[0].strip()
            if city and len(city) > 1:
                return city
    return s[:35]


# ---------------------------------------------------------------------------
# Supply-Demand Insights engine
# ---------------------------------------------------------------------------

def _compute_insights(df: pd.DataFrame) -> dict:
    """
    Pull all key market stats from the filtered DataFrame.
    Returns a plain dict — no LLM needed, instant computation.
    """
    total   = len(df)
    sec_col = "_sector_norm" if "_sector_norm" in df.columns else "category"
    emp_col = "_employment_norm" if "_employment_norm" in df.columns else "employment_type"
    car_col = "_career_norm"    if "_career_norm"    in df.columns else "career_level"
    sal_col = "salary"          if "salary"          in df.columns else None

    # ── sectors ───────────────────────────────────────────────────────────
    top_sectors = []
    if sec_col in df.columns:
        for sec, cnt in df[sec_col].value_counts().head(5).items():
            top_sectors.append({"name": sec, "count": int(cnt), "pct": cnt / total * 100})

    # ── salary ────────────────────────────────────────────────────────────
    sal_mids = pd.Series(dtype=float)
    if sal_col:
        _tmp = df.copy()
        _tmp["_mid"] = _tmp[sal_col].apply(_parse_salary_mid)
        sal_mids = _tmp["_mid"].dropna()
    n_sal   = len(sal_mids)
    avg_sal = float(sal_mids.mean()) if n_sal > 0 else None

    top_paying: list[tuple] = []
    if sal_col and sec_col in df.columns and n_sal > 0:
        _tmp["_mid"] = _tmp[sal_col].apply(_parse_salary_mid)
        grp = (
            _tmp.dropna(subset=["_mid"])
            .groupby(sec_col)["_mid"]
            .agg(mean="mean", count="count")
            .query("count >= 3")
            .sort_values("mean", ascending=False)
            .head(3)
        )
        top_paying = [(sec, float(row["mean"]), int(row["count"])) for sec, row in grp.iterrows()]

    # ── skills ────────────────────────────────────────────────────────────
    top_skills: list[tuple] = []
    if "skills" in df.columns:
        bag: Counter = Counter()
        for s in df["skills"].dropna():
            for sk in re.split(r"[;,|\n/]+", str(s)):
                sk = sk.strip().lower()
                if 2 < len(sk) < 60:
                    bag[sk] += 1
        top_skills = [(sk, cnt, cnt / total * 100) for sk, cnt in bag.most_common(5)]

    # ── distributions ─────────────────────────────────────────────────────
    career_dist = df[car_col].dropna().value_counts().to_dict() if car_col in df.columns else {}
    emp_dist    = df[emp_col].dropna().value_counts().to_dict() if emp_col in df.columns else {}
    edu_dist    = df["education"].dropna().value_counts().head(4).to_dict() if "education" in df.columns else {}

    # ── month-over-month growth ───────────────────────────────────────────
    timelines = sort_timelines(df["_timeline"].dropna().unique().tolist()) if "_timeline" in df.columns else []
    growth_info: dict | None = None
    if len(timelines) >= 2 and sec_col in df.columns:
        t1, t2 = timelines[0], timelines[-1]
        sub1, sub2 = df[df["_timeline"] == t1], df[df["_timeline"] == t2]
        n1, n2 = max(len(sub1), 1), max(len(sub2), 1)
        c1 = sub1[sec_col].value_counts()
        c2 = sub2[sec_col].value_counts()
        rows = []
        for sec in set(c1.index) | set(c2.index):
            r1, r2 = c1.get(sec, 0) / n1, c2.get(sec, 0) / n2
            if r1 > 0.005:
                rows.append((sec, int(c1.get(sec, 0)), int(c2.get(sec, 0)), (r2 - r1) / r1 * 100))
        rows.sort(key=lambda x: -x[3])
        growth_info = {
            "t1": t1, "t2": t2, "n1": n1, "n2": n2,
            "growing":   rows[:3],
            "declining": [r for r in rows if r[3] < 0][:3],
            "overall_pct": (n2 - n1) / n1 * 100,
        }

    # ── companies ─────────────────────────────────────────────────────────
    top_companies = [(co, int(cnt)) for co, cnt in df["company"].value_counts().head(3).items()] \
                    if "company" in df.columns else []

    return {
        "total":        total,
        "top_sectors":  top_sectors,
        "n_sal":        n_sal,
        "sal_pct":      n_sal / total * 100 if total > 0 else 0,
        "avg_sal":      avg_sal,
        "top_paying":   top_paying,
        "top_skills":   top_skills,
        "career_dist":  career_dist,
        "emp_dist":     emp_dist,
        "edu_dist":     edu_dist,
        "growth_info":  growth_info,
        "top_companies":top_companies,
        "timelines":    timelines,
    }


def _insight_card(title: str, icon: str, items: list[tuple[str, str, str]], color: str):
    """
    Render one insight card.
    items = list of (tag_label, tag_color_hex, text)
    """
    rows = ""
    for tag, tag_color, text in items:
        rows += (
            f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05);'
            f'font-size:0.85rem;color:#c9d1d9;line-height:1.55">'
            f'<span style="background:{tag_color}22;color:{tag_color};font-size:0.7rem;'
            f'font-weight:700;padding:2px 7px;border-radius:4px;margin-right:6px">{tag}</span>'
            f'{text}</div>'
        )
    st.markdown(
        f'<div style="background:#161b22;border:1px solid #30363d;border-top:3px solid {color};'
        f'border-radius:10px;padding:16px 18px;height:100%">'
        f'<div style="font-size:1rem;font-weight:700;margin-bottom:12px;color:#e6edf3">'
        f'{icon} {title}</div>{rows}</div>',
        unsafe_allow_html=True,
    )


def _render_insights_section(plot_df: pd.DataFrame, engine, selected_model: str):
    """
    Section 10 of the dashboard: auto-computed insight cards + LLM narrative.
    """
    st.divider()
    st.subheader("Supply-Demand Analysis & Insights")
    st.caption("Auto-computed from the filtered data — updates every time you change a filter.")

    stats = _compute_insights(plot_df)
    total = stats["total"]
    gi    = stats["growth_info"]

    # ── Row 1: High-demand + Salary ───────────────────────────────────────
    r1c1, r1c2 = st.columns(2)

    with r1c1:
        items = []
        for s in stats["top_sectors"]:
            items.append((f"#{stats['top_sectors'].index(s)+1}", "#2ECC71",
                           f"<strong>{s['name']}</strong> — {s['count']:,} jobs ({s['pct']:.1f}%)"))
        if stats["top_companies"]:
            co, cnt = stats["top_companies"][0]
            items.append(("Top employer", "#58a6ff",
                           f"{co} · {cnt:,} postings"))
        _insight_card("High-Demand Sectors", "▲", items, "#2ECC71")

    with r1c2:
        items = []
        items.append(("Coverage", "#f59e0b",
                       f"Only {stats['sal_pct']:.1f}% of postings disclose salary "
                       f"({stats['n_sal']:,} of {total:,}) — common on Bayt.com"))
        if stats["avg_sal"]:
            items.append(("Avg salary", "#2ECC71",
                           f"${stats['avg_sal']:,.0f}/month across disclosing postings"))
        for sec, avg, n in stats["top_paying"]:
            items.append(("Top pay", "#58a6ff",
                           f"{sec} — avg ${avg:,.0f}/mo (n={n})"))
        _insight_card("Salary Intelligence", "💰", items, "#f59e0b")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 2: Skills + Career gaps ───────────────────────────────────────
    r2c1, r2c2 = st.columns(2)

    with r2c1:
        items = []
        for i, (sk, cnt, pct) in enumerate(stats["top_skills"]):
            items.append((f"#{i+1}", "#a855f7",
                           f"<strong>{sk.title()}</strong> — {cnt:,} postings ({pct:.1f}%)"))
        _insight_card("Top Skills Demanded", "🛠", items, "#a855f7")

    with r2c2:
        items = []
        cd = stats["career_dist"]
        if cd:
            top_level = max(cd, key=cd.get)
            items.append(("Dominant level", "#2ECC71",
                           f"{top_level} has the most roles — {cd[top_level]:,} postings"))
            if "Entry-Level" in cd:
                items.append(("Entry-level", "#58a6ff",
                               f"{cd['Entry-Level']:,} entry-level roles available ({cd['Entry-Level']/total*100:.1f}%)"))
            if "Manager" in cd and "Mid-Level" in cd:
                ratio = cd["Mid-Level"] / max(cd.get("Manager", 1), 1)
                items.append(("Progression", "#f59e0b",
                               f"{ratio:.0f}× more mid-level than manager roles — career bottleneck"))
        ft = stats["emp_dist"].get("Full-Time", 0)
        ct = stats["emp_dist"].get("Contract", 0)
        if ft or ct:
            items.append(("Contract growth", "#ec4899",
                           f"Full-Time: {ft:,} · Contract: {ct:,} ({ct/(ft+ct)*100:.0f}% contract rate)"))
        _insight_card("Career & Workforce Gaps", "📊", items, "#58a6ff")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 3: Trends + Recommendations ──────────────────────────────────
    r3c1, r3c2 = st.columns(2)

    with r3c1:
        items = []
        if gi:
            items.append(("Overall", "#2ECC71" if gi["overall_pct"] >= 0 else "#E74C3C",
                           f"{gi['t1']} → {gi['t2']}: {gi['n1']:,} → {gi['n2']:,} postings "
                           f"({gi['overall_pct']:+.1f}%)"))
            for sec, c1v, c2v, pct in gi["growing"]:
                items.append(("▲ Growing", "#2ECC71",
                               f"{sec}: {c1v} → {c2v} ({pct:+.0f}%)"))
            for sec, c1v, c2v, pct in gi["declining"]:
                items.append(("▼ Declining", "#E74C3C",
                               f"{sec}: {c1v} → {c2v} ({pct:+.0f}%)"))
        else:
            items.append(("Note", "#8b98a5",
                           "Select multiple timelines to see growth trends"))
        _insight_card("Market Trends", "📈", items, "#06b6d4")

    with r3c2:
        items = []
        if stats["top_skills"]:
            top_sk = stats["top_skills"][0][0].title()
            items.append(("Job seekers", "#2ECC71",
                           f"Learn <strong>{top_sk}</strong> — the #1 demanded skill in this selection"))
        if stats["sal_pct"] < 15:
            items.append(("Employers", "#f59e0b",
                           f"Post salaries to stand out — only {stats['sal_pct']:.1f}% of competitors do"))
        if gi and gi["overall_pct"] > 0:
            items.append(("Policy", "#58a6ff",
                           f"Market grew {gi['overall_pct']:+.1f}% — opportunity to expand training pipelines"))
        cd = stats["career_dist"]
        if cd.get("Entry-Level", 0) < cd.get("Mid-Level", 0) * 0.4:
            items.append(("Entry-level", "#a855f7",
                           "Few entry-level roles relative to mid-level — gap for fresh graduates"))
        _insight_card("Recommendations", "★", items, "#ffc547")

    # ── AI Narrative button ───────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 🤖 Generate AI Market Summary")
    st.caption("LLM reads the computed stats above and writes a professional narrative.")

    ai_col1, ai_col2 = st.columns([2, 1])
    audience = ai_col1.selectbox(
        "Target audience",
        ["General overview", "For Students & Job Seekers",
         "For Employers", "For Policymakers", "For Researchers"],
        key="insight_audience",
    )
    generate_btn = ai_col2.button("Generate Summary", type="primary",
                                  use_container_width=True, key="gen_insights_btn")

    if generate_btn:
        # Build a compact stats prompt
        stats_text = f"""
MARKET STATISTICS (computed from {total:,} job postings):

Total postings: {total:,}
Timelines in data: {', '.join(stats['timelines'])}

TOP SECTORS:
{chr(10).join(f"  {s['name']}: {s['count']:,} ({s['pct']:.1f}%)" for s in stats['top_sectors'])}

SALARY:
  Disclosed: {stats['n_sal']:,} of {total:,} ({stats['sal_pct']:.1f}%)
  Average: ${stats['avg_sal']:,.0f}/month
  Top-paying sectors: {', '.join(f"{s[0]} (${s[1]:,.0f}/mo)" for s in stats['top_paying'])}

TOP SKILLS:
{chr(10).join(f"  {sk.title()}: {cnt:,} ({pct:.1f}%)" for sk, cnt, pct in stats['top_skills'])}

CAREER LEVELS:
{chr(10).join(f"  {k}: {v:,}" for k, v in list(stats['career_dist'].items())[:6])}

EMPLOYMENT TYPES:
{chr(10).join(f"  {k}: {v:,}" for k, v in list(stats['emp_dist'].items())[:5])}

{f'''TRENDS ({gi['t1']} → {gi['t2']}):
  Overall: {gi['n1']:,} → {gi['n2']:,} ({gi['overall_pct']:+.1f}%)
  Top growing: {", ".join(f"{s[0]} ({s[3]:+.0f}%)" for s in gi["growing"])}''' if gi else 'Single timeline — no trend data.'}
"""
        narrative_prompt = (
            f"You are a GCC labor market analyst. Based on the following real statistics "
            f"from Bayt.com job postings, write a concise, data-driven market summary "
            f"targeted at: **{audience}**.\n\n"
            f"Use specific numbers. Be actionable. Structure with short paragraphs. "
            f"3-5 paragraphs max.\n\n{stats_text}"
        )

        with st.spinner("Generating AI summary…"):
            try:
                from config import make_client
                client, bare_model = make_client(selected_model)
                stream = client.chat.completions.create(
                    model=bare_model,
                    messages=[{"role": "user", "content": narrative_prompt}],
                    temperature=0.3,
                    stream=True,
                )
                with st.container():
                    st.markdown(
                        f'<div style="background:#161b22;border:1px solid #30363d;border-left:'
                        f'4px solid #ffc547;border-radius:8px;padding:16px 20px;margin-top:8px">',
                        unsafe_allow_html=True,
                    )
                    st.write_stream(chunk.choices[0].delta.content or ""
                                    for chunk in stream
                                    if chunk.choices[0].delta.content)
                    st.markdown("</div>", unsafe_allow_html=True)
            except Exception as ex:
                st.error(f"Could not generate summary: {ex}")


# ---------------------------------------------------------------------------
# Dashboard tab
# ---------------------------------------------------------------------------

def _dashboard(filt_df: pd.DataFrame):
    if filt_df.empty:
        st.warning("No data for selected filters — select at least one dataset.")
        return

    timelines     = sort_timelines(filt_df["_timeline"].dropna().unique().tolist()) if "_timeline" in filt_df.columns else []
    countries     = sorted(filt_df["_country"].dropna().unique().tolist())  if "_country"  in filt_df.columns else []
    multi_country = len(countries) > 1
    sal_col       = "salary" if "salary" in filt_df.columns else None

    # ── Inline filters (drive every chart below) ────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns(4)
    country_filter  = fc1.selectbox("Country",  ["All"] + countries, key="db_country") if multi_country else "All"
    sec_col         = "_sector_norm" if "_sector_norm" in filt_df.columns else "category"
    sectors         = sorted(filt_df[sec_col].dropna().unique().tolist()) if sec_col in filt_df.columns else []
    sector_filter   = fc2.selectbox("Sector",   ["All"] + sectors,   key="db_sector")
    timeline_filter = fc3.selectbox("Timeline", ["All"] + timelines, key="db_timeline")

    # Compare two specific months when ≥3 timelines available
    compare_pair: tuple | None = None
    if len(timelines) >= 3 and timeline_filter == "All":
        # timelines is already chronologically sorted — earlier always first
        compare_options = [f"{timelines[i]} vs {timelines[j]}"
                           for i in range(len(timelines))
                           for j in range(i + 1, len(timelines))]
        default_pair = f"{timelines[0]} vs {timelines[-1]}"   # earliest → latest
        default_idx  = compare_options.index(default_pair) if default_pair in compare_options else 0
        chosen = fc4.selectbox("Compare months", compare_options,
                               index=default_idx,
                               key="db_compare")
        parts = chosen.split(" vs ")
        compare_pair = (parts[0].strip(), parts[1].strip())
    else:
        fc4.empty()

    # Apply filters to produce plot_df
    plot_df = filt_df.copy()
    if country_filter  != "All" and "_country"  in plot_df.columns:
        plot_df = plot_df[plot_df["_country"]  == country_filter]
    if sector_filter   != "All" and sec_col     in plot_df.columns:
        plot_df = plot_df[plot_df[sec_col]     == sector_filter]
    if timeline_filter != "All" and "_timeline" in plot_df.columns:
        plot_df = plot_df[plot_df["_timeline"] == timeline_filter]

    if plot_df.empty:
        st.warning("No postings match these filters.")
        return

    active_timelines = sort_timelines(plot_df["_timeline"].dropna().unique().tolist()) if "_timeline" in plot_df.columns else []

    # ── KPI row — all derived from plot_df so they update with every filter ─
    kpis = st.columns(5)
    kpis[0].metric("Total Postings", f"{len(plot_df):,}")
    kpis[1].metric("Countries",      plot_df["_country"].nunique() if "_country" in plot_df.columns else len(countries))
    kpis[2].metric("Companies",      f"{plot_df['company'].nunique():,}" if "company" in plot_df.columns else "—")

    # Month-over-month comparison — uses compare_pair if set, else first vs last
    if len(active_timelines) >= 2:
        t1, t2 = (compare_pair if compare_pair else (active_timelines[0], active_timelines[-1]))
        counts = plot_df["_timeline"].value_counts()
        c1, c2 = int(counts.get(t1, 0)), int(counts.get(t2, 0))
        pct    = (c2 - c1) / c1 * 100 if c1 > 0 else 0
        kpis[3].metric(f"{t1} → {t2}", f"{c2:,}", f"{pct:+.1f}%")   # :+ always shows sign correctly
    elif active_timelines:
        kpis[3].metric(active_timelines[0], f"{len(plot_df):,}")
    else:
        kpis[3].metric("Postings", f"{len(plot_df):,}")

    # Salary KPI — avg where disclosed
    if sal_col:
        mids = plot_df[sal_col].apply(_parse_salary_mid).dropna()
        n_sal = len(mids)
        avg_s = f"${mids.mean():,.0f}/mo" if n_sal > 0 else "N/A"
        kpis[4].metric("Avg Salary (reported)", avg_s,
                       f"{n_sal}/{len(plot_df)} postings ({n_sal/len(plot_df)*100:.1f}%)")
    else:
        kpis[4].metric("Salary coverage", "—")

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # 1. POSTINGS BY SECTOR
    # ════════════════════════════════════════════════════════════════════════
    if sec_col in plot_df.columns:
        st.subheader("Postings by Sector")
        n_sec = st.slider("Top N sectors", 5, 40, 15, key="n_sec_slider",
                          help="Increase when you add more country data — prevents crowding")

        color_dim = "_timeline" if len(active_timelines) > 1 else ("_country" if multi_country and country_filter == "All" else None)

        if color_dim:
            sec_g = (plot_df.groupby([sec_col, color_dim]).size().reset_index(name="count"))
            top_secs = sec_g.groupby(sec_col)["count"].sum().nlargest(n_sec).index
            sec_g    = sec_g[sec_g[sec_col].isin(top_secs)]
            cmap     = COUNTRY_COLORS if color_dim == "_country" else None
            fig = px.bar(sec_g, x="count", y=sec_col, color=color_dim,
                         barmode="group", orientation="h",
                         color_discrete_map=cmap,
                         labels={sec_col: "", "count": "Postings", color_dim: "Period" if color_dim == "_timeline" else "Country"},
                         height=max(400, n_sec * 28))
        else:
            sc = plot_df[sec_col].value_counts().head(n_sec).reset_index()
            sc.columns = ["sector", "count"]
            fig = px.bar(sc, x="count", y="sector", orientation="h",
                         color="count", color_continuous_scale="Blues",
                         labels={"sector": "", "count": "Postings"},
                         height=max(400, n_sec * 28))
            fig.update_layout(coloraxis_showscale=False)

        _apply_plot_layout(fig, yaxis={"categoryorder": "total ascending"}, margin=dict(l=0, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 2. SALARY INTELLIGENCE
    # ════════════════════════════════════════════════════════════════════════
    if sal_col:
        st.subheader("Salary Intelligence")
        st.caption(f"Only postings that disclosed salary — {len(plot_df[sal_col].dropna()):,} of {len(plot_df):,} ({len(plot_df[sal_col].dropna())/len(plot_df)*100:.1f}%)")

        plot_df["_sal_mid"] = plot_df[sal_col].apply(_parse_salary_mid)
        sal_df = plot_df[plot_df["_sal_mid"].notna()].copy()

        if not sal_df.empty:
            sc1, sc2 = st.columns(2)

            with sc1:
                st.markdown("**Average Monthly Salary by Sector (USD)**")
                if sec_col in sal_df.columns:
                    sal_sec = (
                        sal_df.groupby(sec_col)["_sal_mid"]
                        .agg(mean="mean", count="count")
                        .query("count >= 3")
                        .sort_values("mean", ascending=False)
                        .head(15)
                        .reset_index()
                    )
                    sal_sec.columns = ["sector", "avg_salary", "count"]
                    fig_s1 = px.bar(sal_sec, x="avg_salary", y="sector", orientation="h",
                                    color="avg_salary", color_continuous_scale="Teal",
                                    labels={"sector": "", "avg_salary": "USD/month"},
                                    text=sal_sec["avg_salary"].apply(lambda x: f"${x:,.0f}"),
                                    height=420)
                    fig_s1.update_traces(textposition="outside")
                    fig_s1.update_layout(coloraxis_showscale=False,
                                         yaxis={"categoryorder": "total ascending"},
                                         margin=dict(l=0, r=80, t=10, b=10))
                    _apply_plot_layout(fig_s1)
                    st.plotly_chart(fig_s1, use_container_width=True)

            with sc2:
                st.markdown("**Salary Distribution Brackets**")
                bins   = [0, 500, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000, float("inf")]
                labels = ["<$500","$500-1K","$1K-1.5K","$1.5K-2K","$2K-3K","$3K-5K","$5K-7.5K","$7.5K-10K","$10K-15K","$15K+"]
                sal_df["bracket"] = pd.cut(sal_df["_sal_mid"], bins=bins, labels=labels, right=False)
                bkt = sal_df["bracket"].value_counts().reindex(labels).fillna(0).reset_index()
                bkt.columns = ["bracket", "count"]
                colors = ["#ff6b6b","#ff8e53","#ffd93d","#ffd93d","#4ecdc4","#00c9a7","#44b09e","#6c63ff","#a855f7","#ec4899"]
                fig_s2 = px.bar(bkt, x="bracket", y="count",
                                color="bracket", color_discrete_sequence=colors,
                                labels={"bracket": "", "count": "# Jobs"},
                                height=420)
                fig_s2.update_layout(showlegend=False, margin=dict(l=0, r=10, t=10, b=50))
                _apply_plot_layout(fig_s2)
                st.plotly_chart(fig_s2, use_container_width=True)
        else:
            st.info("No salary data in current filter selection.")

    # ════════════════════════════════════════════════════════════════════════
    # 3. CAREER LEVEL + EMPLOYMENT TYPE
    # ════════════════════════════════════════════════════════════════════════
    career_col = "_career_norm" if "_career_norm" in plot_df.columns else "career_level"
    emp_col    = "_employment_norm" if "_employment_norm" in plot_df.columns else "employment_type"

    cc1, cc2 = st.columns(2)

    if career_col in plot_df.columns:
        with cc1:
            st.subheader("Career Level")
            cl = plot_df[career_col].dropna().value_counts().reset_index()
            cl.columns = ["level", "count"]
            fig_c = px.pie(cl, values="count", names="level",
                           color_discrete_sequence=px.colors.qualitative.Set2, height=360)
            fig_c.update_traces(textposition="inside", textinfo="percent+label")
            _apply_plot_layout(fig_c, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_c, use_container_width=True)

    if emp_col in plot_df.columns:
        with cc2:
            st.subheader("Employment Type")
            et = plot_df[emp_col].dropna().value_counts().reset_index()
            et.columns = ["type", "count"]
            fig_e = px.pie(et, values="count", names="type",
                           color_discrete_sequence=px.colors.qualitative.Pastel, height=360)
            fig_e.update_traces(textposition="inside", textinfo="percent+label")
            _apply_plot_layout(fig_e, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_e, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 4. TOP SKILLS
    # ════════════════════════════════════════════════════════════════════════
    if "skills" in plot_df.columns:
        st.subheader("Top In-Demand Skills")
        n_skills = st.slider("Number of skills", 10, 40, 20, key="n_skills_slider")
        bag: Counter = Counter()
        for s in plot_df["skills"].dropna():
            for sk in re.split(r"[;,|\n/]+", str(s)):
                sk = sk.strip().lower()
                if 2 < len(sk) < 60:
                    bag[sk] += 1
        sk_df = pd.DataFrame(bag.most_common(n_skills), columns=["skill", "count"])
        if not sk_df.empty:
            fig_sk = px.bar(sk_df, x="count", y="skill", orientation="h",
                            color="count", color_continuous_scale="Purples",
                            labels={"skill": "", "count": "Mentions"},
                            height=max(360, n_skills * 22))
            fig_sk.update_layout(coloraxis_showscale=False, yaxis={"categoryorder": "total ascending"},
                                  margin=dict(l=0))
            _apply_plot_layout(fig_sk)
            st.plotly_chart(fig_sk, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 5. EXPERIENCE & WORKFORCE
    # ════════════════════════════════════════════════════════════════════════
    exp_col  = "experience"   if "experience"   in plot_df.columns else None
    size_col = "company_size" if "company_size" in plot_df.columns else None

    if exp_col or size_col:
        st.subheader("Experience & Workforce")
        ew1, ew2 = st.columns(2)

        if exp_col:
            with ew1:
                st.markdown("**Years of Experience Required**")
                exp_df = (
                    plot_df[exp_col].dropna()
                    .value_counts()
                    .head(15)
                    .reset_index()
                )
                exp_df.columns = ["experience", "count"]
                palette = ["#6c63ff","#00c9a7","#ff6b6b","#ffd93d","#a855f7",
                           "#4ecdc4","#ff8e53","#44b09e","#667eea","#f093fb",
                           "#4facfe","#43e97b","#fa709a","#fee140","#30cfd0"]
                fig_exp = px.bar(exp_df, x="experience", y="count",
                                 color="experience",
                                 color_discrete_sequence=palette,
                                 labels={"experience": "", "count": "Postings"},
                                 height=340)
                fig_exp.update_layout(showlegend=False, margin=dict(l=0, r=10, t=10, b=60))
                _apply_plot_layout(fig_exp)
                st.plotly_chart(fig_exp, use_container_width=True)

        if size_col:
            with ew2:
                st.markdown("**Company Size Distribution**")
                size_df = plot_df[size_col].dropna().value_counts().reset_index()
                size_df.columns = ["size", "count"]
                fig_sz = px.pie(size_df, values="count", names="size",
                                color_discrete_sequence=["#6c63ff","#00c9a7","#ffd93d","#ff6b6b","#a855f7","#4ecdc4"],
                                height=340)
                fig_sz.update_traces(textposition="inside", textinfo="percent+label")
                _apply_plot_layout(fig_sz, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_sz, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 6. LANGUAGE & LOCATION
    # ════════════════════════════════════════════════════════════════════════
    lang_col = "language" if "language" in plot_df.columns else None
    loc_col  = "location" if "location" in plot_df.columns else None

    if lang_col or loc_col:
        st.subheader("Language & Location")
        ll1, ll2 = st.columns(2)

        if lang_col:
            with ll1:
                st.markdown("**Language Requirements**")
                lang_df = (
                    plot_df[lang_col]
                    .dropna()
                    .loc[lambda s: s.str.strip() != ""]
                    .value_counts()
                    .head(8)
                    .reset_index()
                )
                lang_df.columns = ["language", "count"]
                if not lang_df.empty:
                    fig_lang = px.bar(lang_df, x="language", y="count",
                                      color="language",
                                      color_discrete_sequence=["#6c63ff","#00c9a7","#ffd93d","#ff6b6b","#a855f7","#4ecdc4","#ff8e53","#44b09e"],
                                      labels={"language": "", "count": "Postings"},
                                      height=320)
                    fig_lang.update_layout(showlegend=False, margin=dict(l=0, r=10, t=10, b=60))
                    _apply_plot_layout(fig_lang)
                    st.plotly_chart(fig_lang, use_container_width=True)
                else:
                    st.info("No language requirement data in this filter.")

        if loc_col:
            with ll2:
                st.markdown("**Location Breakdown**")
                city_series = plot_df[loc_col].apply(_extract_city)
                city_df = city_series.value_counts().head(10).reset_index()
                city_df.columns = ["city", "count"]
                if not city_df.empty:
                    fig_loc = px.pie(city_df, values="count", names="city",
                                     color_discrete_sequence=["#6c63ff","#00c9a7","#ffd93d","#ff6b6b","#a855f7",
                                                               "#4ecdc4","#ff8e53","#44b09e","#667eea","#f093fb"],
                                     height=320)
                    fig_loc.update_traces(textposition="inside", textinfo="percent+label")
                    _apply_plot_layout(fig_loc, margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig_loc, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 7. MOST ADVERTISED POSITIONS
    # ════════════════════════════════════════════════════════════════════════
    title_col = "job_title" if "job_title" in plot_df.columns else None
    if title_col:
        st.subheader("Most Advertised Positions")
        n_titles = st.slider("Number of job titles", 10, 30, 20, key="n_titles_slider")
        title_df = plot_df[title_col].dropna().value_counts().head(n_titles).reset_index()
        title_df.columns = ["title", "count"]
        palette20 = ["#6c63ff","#00c9a7","#ff6b6b","#ffd93d","#a855f7","#4ecdc4","#ff8e53",
                     "#44b09e","#667eea","#f093fb","#4facfe","#43e97b","#fa709a","#fee140",
                     "#30cfd0","#a18cd1","#fbc2eb","#8fd3f4","#e0c3fc","#d4fc79"]
        fig_t = px.bar(title_df, x="count", y="title", orientation="h",
                       color="title", color_discrete_sequence=palette20,
                       labels={"title": "", "count": "Postings"},
                       height=max(400, n_titles * 26))
        fig_t.update_layout(showlegend=False, yaxis={"categoryorder": "total ascending"},
                             margin=dict(l=0, r=10, t=10, b=10))
        _apply_plot_layout(fig_t)
        st.plotly_chart(fig_t, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 8. TOP HIRING COMPANIES
    # ════════════════════════════════════════════════════════════════════════
    if "company" in plot_df.columns:
        st.subheader("Top Hiring Companies")
        n_comp = st.slider("Number of companies", 5, 30, 15, key="n_comp_slider")
        comp_df = plot_df["company"].value_counts().head(n_comp).reset_index()
        comp_df.columns = ["company", "count"]
        fig_co = px.bar(comp_df, x="count", y="company", orientation="h",
                        color="count", color_continuous_scale="Blues",
                        labels={"company": "", "count": "Postings"},
                        height=max(300, n_comp * 24))
        fig_co.update_layout(coloraxis_showscale=False,
                              yaxis={"categoryorder": "total ascending"},
                              margin=dict(l=0))
        _apply_plot_layout(fig_co)
        st.plotly_chart(fig_co, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 9. COUNTRY COMPARISON (only when multiple countries visible)
    # ════════════════════════════════════════════════════════════════════════
    if multi_country and "_country" in plot_df.columns and country_filter == "All":
        st.subheader("Country Comparison")
        mc1, mc2 = st.columns(2)

        with mc1:
            vol = plot_df["_country"].value_counts().reset_index()
            vol.columns = ["country", "count"]
            fig_vol = px.pie(vol, values="count", names="country",
                             color="country", color_discrete_map=COUNTRY_COLORS,
                             title="Posting volume share", height=340)
            fig_vol.update_traces(textposition="inside", textinfo="percent+label")
            _apply_plot_layout(fig_vol, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig_vol, use_container_width=True)

        with mc2:
            if career_col in plot_df.columns:
                mc_df = (
                    plot_df.groupby(["_country", career_col]).size()
                    .reset_index(name="count")
                    .dropna(subset=[career_col])
                )
                fig_mc = px.bar(mc_df, x="_country", y="count", color=career_col,
                                barmode="stack",
                                labels={"_country": "", "count": "Postings", career_col: "Level"},
                                title="Career level by country", height=340,
                                color_discrete_sequence=px.colors.qualitative.Set2)
                _apply_plot_layout(fig_mc, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_mc, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 10. SUPPLY-DEMAND INSIGHTS + AI NARRATIVE
    # ════════════════════════════════════════════════════════════════════════
    _render_insights_section(plot_df, None, st.session_state.get("_selected_model", "gpt-4o"))


# ---------------------------------------------------------------------------
# Chat tab
# ---------------------------------------------------------------------------

def _chat(filt_df: pd.DataFrame, engine: RAGEngine, selected_model: str):
    st.markdown(f"**{len(filt_df):,} postings** loaded from selected datasets · model: `{selected_model}`")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Sample questions
    if not st.session_state.messages:
        st.markdown("#### Try asking:")
        samples = [
            "How many Full-Time jobs are in Feb 2026?",
            "Which career level has the most opportunities?",
            "What are the top in-demand skills?",
            "Compare Construction vs Tech salaries.",
            "Which companies are hiring the most?",
            "I have 5 years in Finance and SAP — what jobs match me?",
            "How did job postings change from Nov to Feb?",
            "Which sector is growing fastest?",
        ]
        cols = st.columns(2)
        for i, q in enumerate(samples):
            if cols[i % 2].button(q, key=f"sample_{i}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": q})
                st.rerun()

    # Render history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("retrieval_info"):
                _render_retrieval_panel(msg["retrieval_info"])
            if msg.get("verification"):
                _render_verification_panel(msg["verification"])

    # New input
    if prompt := st.chat_input("Ask about the GCC job market…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get retrieval info BEFORE streaming (fast, same decomposition)
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ]
        with st.spinner("Searching database…"):
            ret_info = engine.get_retrieval_info(prompt, history)

        with st.chat_message("assistant"):
            _render_retrieval_panel(ret_info)
            response_text = st.write_stream(
                engine.answer(prompt, history, model=selected_model)
            )
            checks = _verify(response_text, filt_df)
            if checks:
                _render_verification_panel(checks)

        st.session_state.messages.append({
            "role":          "assistant",
            "content":       response_text,
            "retrieval_info": ret_info,
            "verification":  checks,
        })

    if st.session_state.messages:
        if st.button("Clear chat", key="clear_chat"):
            st.session_state.messages = []
            st.rerun()


def _render_retrieval_panel(info: dict):
    with st.expander("🔍 Retrieval process", expanded=False):
        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**Query decomposition**")
            dc = info.get("decomposed", {})
            st.markdown(f"- Needs aggregation: `{'Yes' if info.get('needs_agg') else 'No'}`")
            if dc.get("filters"):
                st.markdown(f"- Filters: `{dc['filters']}`")
            if info.get("analysis_types"):
                st.markdown(f"- Analysis: `{', '.join(info['analysis_types'])}`")
            if dc.get("resolved_question"):
                st.caption(f"Resolved: *{dc['resolved_question'][:120]}*")

        with c2:
            st.markdown(f"**Layers used:** {', '.join(info.get('layers_used', ['—']))}")
            hits = info.get("semantic_hits", [])
            if hits:
                st.markdown(f"**Top {len(hits)} semantic matches:**")
                for h in hits:
                    bar = "█" * round(h["score"] * 10) + "░" * (10 - round(h["score"] * 10))
                    st.markdown(
                        f'<div class="src-card">'
                        f'`{h["score"]:.2f}` {bar} &nbsp; '
                        f'**{h["title"][:40]}** · {h["company"][:25]} · {h["timeline"]}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        if info.get("sql_snippet"):
            with st.expander("SQL / Pandas result (preview)"):
                st.code(info["sql_snippet"], language="")


def _render_verification_panel(checks: list[dict]):
    if not checks:
        return
    with st.expander("✅ Answer verification", expanded=True):
        for c in checks:
            icon  = "✅" if c["ok"] else "⚠️"
            color = "green" if c["ok"] else "orange"
            st.markdown(
                f'{icon} **{c["label"]}** — '
                f'bot said `{c["claimed"]:,}`, '
                f'database says `:{color}[{c["actual"]:,}]`'
            )


# ---------------------------------------------------------------------------
# Auto-index helper
# ---------------------------------------------------------------------------

def _auto_index_if_needed(df, source_files, vs: VectorStore):
    if not vs.needs_indexing(source_files):
        return
    note = st.empty()
    new  = vs.new_files(source_files)
    note.info(
        f"New data detected ({len(new)} file(s)) — updating index…  "
        f"Tip: run `python build_index.py` offline for instant startup.",
        icon="⏳",
    )
    vs.build_index_incremental(df, source_files)
    note.empty()
    st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Load data
    try:
        df, timelines, source_files = _load_data()
    except FileNotFoundError as e:
        st.error(f"No data files found: {e}")
        st.info(f"Drop Excel files into `{DATA_DIR}` and refresh.")
        st.stop()

    vs     = _get_vector_store()
    _auto_index_if_needed(df, source_files, vs)

    engine = RAGEngine(AnalyticsEngine(df), vs)

    # Sidebar — get selected dumps + model
    selected_dump_ids, selected_model = _render_sidebar(df, timelines, source_files, vs)
    st.session_state["_selected_model"] = selected_model   # shared with insights section

    # Apply dump filter
    filt_df = _filter_by_dumps(df, selected_dump_ids) if selected_dump_ids else df

    # Header
    country_str = " · ".join(sorted(
        filt_df["_country"].dropna().unique().tolist()
    )) if "_country" in filt_df.columns else "GCC"
    st.title(f"GCC Job Market Intelligence — {country_str}")
    st.caption(
        f"Bayt.com data · {len(filt_df):,} postings selected · "
        f"{' & '.join(timelines)}"
    )

    # Tabs
    tab_dash, tab_chat = st.tabs(["📊 Dashboard", "💬 Chat"])

    with tab_dash:
        _dashboard(filt_df)

    with tab_chat:
        _chat(filt_df, engine, selected_model)


if __name__ == "__main__":
    main()
