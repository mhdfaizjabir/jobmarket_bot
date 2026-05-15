"""
app.py  —  Qatar Job Market Intelligence Assistant
---------------------------------------------------
Run with:  streamlit run app.py
"""

import os
import streamlit as st
from pathlib import Path

# Load OpenAI key from Streamlit secrets (cloud deployment) if not already in env.
# Local dev: key comes from .env via load_dotenv() inside the engine files.
try:
    if not os.getenv("OPENAI_API_KEY") and "OPENAI_API_KEY" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
except Exception:
    pass

from config import DATA_DIR
from data_loader import load_all
from vector_store import VectorStore
from analytics import AnalyticsEngine
from rag_engine import RAGEngine

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Qatar Job Market Intelligence",
    page_icon="🇶🇦",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Cached resource loading
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading job data…", ttl=3600)
def _load_data():
    df, timelines = load_all(DATA_DIR)
    source_files = sorted(
        str(p) for p in list(DATA_DIR.glob("*.xlsx")) + list(DATA_DIR.glob("*.csv"))
    )
    return df, timelines, source_files


@st.cache_resource(show_spinner="Initialising vector store…")
def _get_vector_store() -> VectorStore:
    return VectorStore()


def _get_engine(df, vs: VectorStore) -> RAGEngine:
    """Not cached — cheap to create; depends on df which can change."""
    return RAGEngine(AnalyticsEngine(df), vs)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _render_sidebar(df, timelines, source_files, vs: VectorStore):
    with st.sidebar:
        st.title("🇶🇦 Qatar Job Market")
        st.markdown("**Intelligence Assistant**")
        st.divider()

        # Dataset metrics
        st.metric("Total Postings", f"{len(df):,}")
        for tl in timelines:
            n = int((df["_timeline"] == tl).sum()) if "_timeline" in df.columns else 0
            st.metric(tl, f"{n:,} jobs")

        st.divider()

        # Index status
        idx_count = vs.count()
        needs_idx = vs.needs_indexing(source_files)

        if idx_count == 0:
            st.error("Index not built yet")
            btn_type = "primary"
        elif needs_idx:
            st.warning(f"Index outdated ({idx_count:,} docs)")
            btn_type = "primary"
        else:
            st.success(f"Index ready  ({idx_count:,} docs)")
            btn_type = "secondary"

        if st.button("Build / Rebuild Index", type=btn_type, use_container_width=True):
            _build_index_ui(df, source_files, vs)

        if st.button("Refresh Data", use_container_width=True, help="Reload data files without restarting the app"):
            _load_data.clear()
            st.rerun()

        st.divider()

        # Quick dataset info
        if "_timeline" in df.columns:
            with st.expander("Top sectors"):
                if "category" in df.columns:
                    for sector, n in df["category"].value_counts().head(8).items():
                        st.caption(f"{sector}: {n}")

        st.divider()
        timelines_str = " & ".join(timelines) if timelines else "N/A"
        st.caption(f"Source: Bayt.com  |  {timelines_str}")
        st.caption("Built with ChromaDB + OpenAI + Streamlit")


def _build_index_ui(df, source_files, vs: VectorStore):
    progress_bar = st.sidebar.progress(0, text="Starting…")

    def _on_progress(done: int, total: int):
        pct = done / total
        progress_bar.progress(pct, text=f"Indexed {done:,} / {total:,}")

    vs.build_index(df, source_files, progress_callback=_on_progress)
    progress_bar.empty()
    st.sidebar.success("Index built!")
    st.rerun()


def _auto_index_if_needed(df, source_files, vs: VectorStore):
    """
    Automatically rebuild the index when new data is detected.
    Runs silently on every startup — no button click needed.
    Handles fresh deployments (empty index) and new data files equally.
    """
    if not vs.needs_indexing(source_files):
        return
    notice = st.empty()
    notice.info(
        "New data detected — building search index. "
        "This takes ~2 minutes on first run…",
        icon="⏳",
    )
    vs.build_index(df, source_files)
    notice.empty()
    st.rerun()


# ---------------------------------------------------------------------------
# Sample questions
# ---------------------------------------------------------------------------

_SAMPLE_QUESTIONS = [
    "What are the top 10 most in-demand jobs in Qatar?",
    "Which skills are growing fastest from November to February?",
    "What salary can I expect as a Data Analyst in Qatar?",
    "Which sectors are hiring the most right now?",
    "I have 3 years of Python and SQL experience — what roles match me?",
    "Compare entry-level vs senior job availability in Qatar.",
    "Which companies are the top employers in Qatar?",
    "What education level do most Tech jobs require?",
]


def _render_sample_questions():
    st.markdown("#### Try asking:")
    cols = st.columns(2)
    for i, q in enumerate(_SAMPLE_QUESTIONS):
        if cols[i % 2].button(q, key=f"sample_{i}", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": q})
            st.rerun()


# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

def _check_password() -> bool:
    """
    Returns True if the user has entered the correct password.
    Password is set in Streamlit secrets as APP_PASSWORD.
    If APP_PASSWORD is not set, the gate is skipped (open access — useful for local dev).
    """
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected = ""

    if not expected:
        return True   # no password configured → open access

    if st.session_state.get("_authenticated"):
        return True

    st.markdown("## Qatar Job Market Intelligence")
    pwd = st.text_input("Enter access password", type="password", key="_pwd_input")
    if st.button("Login", type="primary"):
        if pwd == expected:
            st.session_state._authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not _check_password():
        st.stop()

    df, timelines, source_files = _load_data()
    vs = _get_vector_store()

    # Auto-rebuild when new data files are added or on fresh deployment
    _auto_index_if_needed(df, source_files, vs)

    engine = _get_engine(df, vs)

    _render_sidebar(df, timelines, source_files, vs)

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("Qatar Labor Market Intelligence Assistant")
    st.caption(
        f"Powered by {len(df):,} job postings from Bayt.com  "
        f"({' & '.join(timelines)})"
    )

    st.divider()

    # ── Chat state ────────────────────────────────────────────────────────────
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display existing chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Show sample questions when chat is empty
    if not st.session_state.messages:
        _render_sample_questions()

    # ── Chat input ────────────────────────────────────────────────────────────
    if prompt := st.chat_input("Ask about Qatar's job market…"):
        # Append and display user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Stream assistant response
        with st.chat_message("assistant"):
            # Build history excluding the current user message
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages[:-1]
            ]
            response_text = st.write_stream(engine.answer(prompt, history))

        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
        })

    # ── Clear chat button ─────────────────────────────────────────────────────
    if st.session_state.messages:
        if st.button("Clear chat", key="clear"):
            st.session_state.messages = []
            st.rerun()


if __name__ == "__main__":
    main()
