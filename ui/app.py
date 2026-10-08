"""
ui/app.py  —  CreditFlow AI · Finance Credit Follow-Up Dashboard

Run:
    streamlit run ui/app.py        (direct)
    python main.py                 (via run_ui())

Architecture notes
──────────────────
* Background jobs are dispatched by `core.upload_handler.handle_csv_upload`.
  The UI never blocks: live progress is polled from the jobs table using an
  `st.fragment(run_every=…)` so only the progress panel refreshes, not the
  whole page (falls back to sleep + rerun on older Streamlit versions).
* Service boot (DB, tracing, scheduler) runs exactly once per server process
  via `st.cache_resource` — previously a module global was reset on every
  script rerun, which could start duplicate schedulers.
* All page code lives inside `main()`, so importing this module from main.py
  does not execute Streamlit calls outside a Streamlit runtime.
"""

from __future__ import annotations

import html
import logging
import os
import subprocess
import sys
import tempfile
import time

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

# ── Path bootstrap ────────────────────────────────────────────────────────────
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# ══════════════════════════════════════════════════════════════════════════════
#  DESIGN TOKENS
# ══════════════════════════════════════════════════════════════════════════════
C_ACCENT = "#0F766E"   # teal  – primary / sent
C_INFO = "#2563EB"     # blue  – running
C_WARN = "#B45309"     # amber – queued / pending
C_DANGER = "#B91C1C"   # red   – failed
C_ESCAL = "#7C3AED"    # violet – escalated
C_MUTED = "#64748B"

_STATUS_STYLE: dict[str, tuple[str, str]] = {
    # status      → (foreground, tinted background)
    "running": (C_INFO, "rgba(37,99,235,.14)"),
    "queued": (C_WARN, "rgba(180,83,9,.14)"),
    "completed": (C_ACCENT, "rgba(15,118,110,.14)"),
    "failed": (C_DANGER, "rgba(185,28,28,.14)"),
    "sent": (C_ACCENT, "rgba(15,118,110,.14)"),
    "not_sent": (C_MUTED, "rgba(100,116,139,.16)"),
    "pending": (C_WARN, "rgba(180,83,9,.14)"),
    "resolved": (C_ACCENT, "rgba(15,118,110,.14)"),
    "permanent_failure": (C_DANGER, "rgba(185,28,28,.14)"),
}

_TONE_COLOR = {
    "Warm & Friendly": "#16A34A",
    "Polite but Firm": "#2563EB",
    "Formal & Serious": "#7C3AED",
    "Stern & Urgent": "#EA580C",
    "Legal Review Required": "#DC2626",
}

_POLL_INTERVAL = 2  # seconds between DB polls while a job is active

PAGES = [
    "📤 Upload CSV",
    "📋 Jobs",
    "🔍 Audit Logs",
    "📧 Email Logs",
    "⚠️ Failed Invoices",
]

# Written for light AND dark Streamlit themes: only translucent tints and
# `inherit` colours are used, so nothing is hard-coded to one background.
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700;800&display=swap');

html, body, .stApp, .stMarkdown, button, input, textarea, select {
  font-family: 'Public Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
/* Keep Streamlit's icon font intact (otherwise icons render as raw text such
   as "keyboard_double_arrow_left", "upload" or "info"). */
[data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons,
span[class*="material-symbols"] {
  font-family: 'Material Symbols Rounded', 'Material Icons' !important;
  font-feature-settings: 'liga' !important;
}
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1280px; }
#MainMenu, footer { visibility: hidden; }

/* Hide the toolbar clutter (deploy button, menu, "File change" widget) but
   KEEP the sidebar re-open button. `display:none` on a parent can't be undone
   by its children, so the toolbar is hidden with `visibility` instead and the
   expand button explicitly opts back in below. */
[data-testid="stStatusWidget"], [data-testid="stDecoration"],
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"] { display: none !important; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }

/* Sidebar expand button (test-id differs across Streamlit versions) */
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
  visibility: visible !important;
  display: flex !important;
  opacity: 1 !important;
}
[data-testid="stExpandSidebarButton"] *,
[data-testid="stSidebarCollapsedControl"] *,
[data-testid="collapsedControl"] * { visibility: visible !important; }

/* ── Page header ─────────────────────────────────────────── */
.cf-header { margin: 0 0 1.4rem 0; padding-bottom: 1rem;
  border-bottom: 1px solid rgba(128,128,128,.25); }
.cf-header h1 { font-size: 1.85rem; font-weight: 800; letter-spacing: -.02em;
  margin: 0; padding: 0; line-height: 1.2; }
.cf-header p { margin: .35rem 0 0 0; opacity: .68; font-size: .95rem; max-width: 70ch; }

/* ── Metric cards (native st.metric) ─────────────────────── */
[data-testid="stMetric"] {
  background: rgba(128,128,128,.06);
  border: 1px solid rgba(128,128,128,.22);
  border-left: 4px solid var(--cf-accent, #0F766E);
  border-radius: 10px; padding: .85rem 1rem;
}
[data-testid="stMetricLabel"] p { font-size: .78rem; font-weight: 600; opacity: .72; }
[data-testid="stMetricValue"] { font-weight: 800; font-variant-numeric: tabular-nums; }

/* ── Buttons ─────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button {
  border-radius: 8px; font-weight: 600; transition: transform .08s ease;
}
.stButton > button:active { transform: scale(.98); }
.stButton > button:focus-visible { outline: 2px solid #0F766E; outline-offset: 2px; }

/* ── Sidebar ─────────────────────────────────────────────── */
.cf-brand { display:flex; align-items:center; gap:.65rem; margin:.2rem 0 1rem 0; }
.cf-logo { width:38px; height:38px; border-radius:10px; display:grid; place-items:center;
  font-size:1.2rem; color:#fff; background:linear-gradient(135deg,#0F766E,#115E59); }
.cf-brand b { font-size:1.1rem; letter-spacing:-.01em; display:block; line-height:1.1; }
.cf-brand span { font-size:.72rem; opacity:.6; }
[data-testid="stSidebar"] [role="radiogroup"] { gap:.2rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  padding: .5rem .75rem; border-radius: 8px; width:100%; cursor:pointer;
  transition: background .12s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(128,128,128,.12); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  background: rgba(15,118,110,.16); box-shadow: inset 3px 0 0 #0F766E; font-weight:700;
}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child { display:none; }
.cf-side-card { border:1px solid rgba(128,128,128,.22); background:rgba(128,128,128,.06);
  border-radius:10px; padding:.7rem .85rem; font-size:.8rem; line-height:1.7; }
.cf-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:.45rem; }

/* ── Pills ───────────────────────────────────────────────── */
.cf-pill { display:inline-flex; align-items:center; gap:.4rem; padding:2px 11px;
  border-radius:99px; font-size:.74rem; font-weight:700; letter-spacing:.02em; white-space:nowrap; }
.cf-pill i { width:7px; height:7px; border-radius:50%; background:currentColor; display:inline-block; }
.cf-pill.live i { animation: cf-pulse 1.4s ease-in-out infinite; }
@keyframes cf-pulse { 0%,100% { opacity:1; transform:scale(1);} 50% { opacity:.35; transform:scale(.7);} }
@media (prefers-reduced-motion: reduce) { .cf-pill.live i { animation:none; } }

/* ── Outcome bar ─────────────────────────────────────────── */
.cf-bar { display:flex; height:12px; border-radius:99px; overflow:hidden;
  background: rgba(128,128,128,.2); margin:.4rem 0 .35rem 0; }
.cf-bar span { height:100%; transition: width .4s ease; }
.cf-legend { display:flex; gap:1.1rem; flex-wrap:wrap; font-size:.78rem; opacity:.8; }
.cf-legend b { font-variant-numeric: tabular-nums; }

/* ── Stepper ─────────────────────────────────────────────── */
.cf-steps { display:flex; gap:.6rem; margin:.2rem 0 1.2rem 0; flex-wrap:wrap; }
.cf-step { flex:1; min-width:170px; display:flex; align-items:center; gap:.65rem;
  padding:.65rem .85rem; border-radius:10px; border:1px solid rgba(128,128,128,.22);
  background:rgba(128,128,128,.05); }
.cf-step .n { width:26px; height:26px; border-radius:50%; display:grid; place-items:center;
  font-size:.78rem; font-weight:800; background:rgba(128,128,128,.25); flex:none; }
.cf-step b { display:block; font-size:.86rem; }
.cf-step small { opacity:.65; font-size:.74rem; }
.cf-step.done { border-color: rgba(15,118,110,.55); }
.cf-step.done .n { background:#0F766E; color:#fff; }
.cf-step.now { border-color:#2563EB; background:rgba(37,99,235,.08); }
.cf-step.now .n { background:#2563EB; color:#fff; }

/* ── Email cards ─────────────────────────────────────────── */
.cf-mail { border:1px solid rgba(128,128,128,.25); border-left:5px solid var(--bar,#64748B);
  border-radius:10px; margin-bottom:.7rem; background:rgba(128,128,128,.045); overflow:hidden; }
.cf-mail.esc { background:rgba(220,38,38,.06); }
.cf-mail-top { display:flex; justify-content:space-between; align-items:center; gap:.5rem;
  flex-wrap:wrap; padding:.5rem .9rem; border-bottom:1px solid rgba(128,128,128,.18);
  font-size:.76rem; }
.cf-mail-top .l, .cf-mail-top .r { display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; }
.cf-ts { opacity:.65; font-variant-numeric: tabular-nums; }
.cf-mail-body { padding:.65rem .9rem .75rem .9rem; }
.cf-subject { font-weight:700; font-size:.95rem; margin-bottom:.45rem; }
.cf-meta { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:.45rem 1.2rem; font-size:.8rem; }
.cf-meta small { display:block; opacity:.55; font-size:.68rem; font-weight:600; }
.cf-meta span { font-variant-numeric: tabular-nums; word-break:break-word; }
.cf-err { margin-top:.6rem; padding:.45rem .65rem; border-radius:8px; font-size:.8rem;
  color:#B91C1C; background:rgba(185,28,28,.1); }

/* ── Empty state ─────────────────────────────────────────── */
.cf-empty { text-align:center; padding:2.6rem 1rem; border:1.5px dashed rgba(128,128,128,.35);
  border-radius:14px; background:rgba(128,128,128,.04); }
.cf-empty .ic { font-size:2rem; }
.cf-empty b { display:block; margin:.4rem 0 .15rem 0; font-size:1.02rem; }
.cf-empty p { margin:0; opacity:.65; font-size:.88rem; }
</style>
"""


# ══════════════════════════════════════════════════════════════════════════════
#  SERVICES & REPOSITORIES  (cached once per server process)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def _boot_services() -> dict:
    """Initialise DB, tracing and the retry scheduler exactly once."""
    state = {"db": False, "tracing": False, "scheduler": None}

    try:
        from database.schema import initialize_database
        initialize_database()
        state["db"] = True
    except Exception as exc:
        logger.warning("DB init warning: %s", exc)

    try:
        from observability.tracing import configure_tracing
        configure_tracing()
        state["tracing"] = True
    except Exception as exc:
        logger.warning("Tracing setup warning: %s", exc)

    try:
        from scheduler.retry_scheduler import start_scheduler
        state["scheduler"] = start_scheduler()
    except Exception as exc:
        logger.warning("Scheduler start warning: %s", exc)

    return state


@st.cache_resource(show_spinner=False)
def _repos():
    from database.jobs_repository import JobsRepository
    from database.audit_repository import AuditRepository
    from database.failed_repository import FailedInvoicesRepository
    return JobsRepository(), AuditRepository(), FailedInvoicesRepository()


def _list_jobs(limit: int = 50) -> list:
    return _repos()[0].list_jobs(limit=limit)


def _get_job(job_id: int) -> dict | None:
    return _repos()[0].get_job(job_id)


def _get_audit_logs(job_id: int) -> list:
    return _repos()[1].get_by_job(job_id)


def _get_failed() -> list:
    return _repos()[2].list_all(limit=100)


def _get_all_audit_logs(limit: int = 300, job_id: int | None = None) -> list:
    from database.db import get_connection
    with get_connection() as conn:
        if job_id is not None:
            rows = conn.execute(
                "SELECT * FROM audit_logs WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  SMALL UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _esc(value) -> str:
    """HTML-escape any value (invoice data is untrusted input)."""
    return html.escape("—" if value is None or value == "" else str(value))


def _to_df(records: list) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    rows = []
    for r in records:
        if hasattr(r, "__dict__"):
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            rows.append(d)
        else:
            rows.append(dict(r))
    return pd.DataFrame(rows)


def _dataframe(df: pd.DataFrame, **kwargs) -> None:
    """Render a dataframe, tolerant of different Streamlit versions."""
    kwargs.pop("use_container_width", None)
    for extra in ({"width": "stretch"}, {"use_container_width": True}, {}):
        try:
            st.dataframe(df, hide_index=True, **extra, **kwargs)
            return
        except TypeError:
            continue


def _page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="cf-header"><h1>{_esc(title)}</h1><p>{_esc(subtitle)}</p></div>',
        unsafe_allow_html=True,
    )


def _empty_state(icon: str, title: str, hint: str) -> None:
    st.markdown(
        f'<div class="cf-empty"><div class="ic">{icon}</div>'
        f"<b>{_esc(title)}</b><p>{_esc(hint)}</p></div>",
        unsafe_allow_html=True,
    )


def _pill(text: str, key: str | None = None, live: bool = False) -> str:
    fg, bg = _STATUS_STYLE.get((key or text).lower(), (C_MUTED, "rgba(100,116,139,.16)"))
    cls = "cf-pill live" if live else "cf-pill"
    return (
        f'<span class="{cls}" style="color:{fg};background:{bg}">'
        f"<i></i>{_esc(text)}</span>"
    )


def _status_badge(status: str) -> str:
    return _pill(status.upper(), status, live=status.lower() == "running")


def _goto(page: str) -> None:
    """on_click callback — safe place to change the nav radio's state."""
    st.session_state["nav"] = page


def _stepper(current: int) -> None:
    """current: 0 = upload, 1 = review, 2 = processing, 3 = all done."""
    steps = [
        ("Upload", "Choose your CSV"),
        ("Review", "Check the data"),
        ("Process", "AI sends follow-ups"),
    ]
    out = ['<div class="cf-steps">']
    for i, (name, hint) in enumerate(steps):
        cls = "done" if i < current else ("now" if i == current else "")
        mark = "✓" if i < current else str(i + 1)
        out.append(
            f'<div class="cf-step {cls}"><div class="n">{mark}</div>'
            f"<div><b>{name}</b><small>{hint}</small></div></div>"
        )
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)


def _outcome_bar(total: int, sent: int, escalated: int, failed: int) -> None:
    done = sent + escalated + failed
    base = max(total, done, 1)

    def seg(n: int, color: str, label: str) -> str:
        if not n:
            return ""
        return (
            f'<span style="width:{n / base * 100:.2f}%;background:{color}" '
            f'title="{label}: {n}"></span>'
        )

    legend = "".join(
        f'<span><i class="cf-dot" style="background:{c}"></i>{lbl} <b>{n}</b></span>'
        for lbl, n, c in (
            ("Sent", sent, C_ACCENT),
            ("Escalated", escalated, C_ESCAL),
            ("Failed", failed, C_DANGER),
            ("Remaining", max(total - done, 0), "rgba(128,128,128,.5)"),
        )
    )
    st.markdown(
        '<div class="cf-bar">'
        + seg(sent, C_ACCENT, "Sent")
        + seg(escalated, C_ESCAL, "Escalated")
        + seg(failed, C_DANGER, "Failed")
        + f'</div><div class="cf-legend">{legend}</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE JOB WIDGET
# ══════════════════════════════════════════════════════════════════════════════
def _live_body(job_id: int, *, in_fragment: bool = False, sleep_poll: bool = False) -> None:
    job = _get_job(job_id)
    if not job:
        st.warning(f"Job #{job_id} was not found. It may have been removed.")
        return

    status = str(job.get("status", "unknown"))
    total = int(job.get("total_records", 0) or 0)
    processed = int(job.get("processed_count", 0) or 0)
    sent = int(job.get("sent_count", 0) or 0)
    escalated = int(job.get("escalated_count", 0) or 0)
    failed_count = int(job.get("failed_count", 0) or 0)
    active = status.lower() in ("running", "queued")

    head_l, head_r = st.columns([3, 2])
    head_l.markdown(_status_badge(status), unsafe_allow_html=True)
    if active:
        head_r.caption(f"⟳ Live · updates every {_POLL_INTERVAL}s")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", total or "—")
    c2.metric("Processed", processed)
    c3.metric("Sent", sent)
    c4.metric("Escalated", escalated)
    c5.metric("Failed", failed_count)

    if total:
        pct = min(processed / total, 1.0)
        st.progress(pct, text=f"{processed} of {total} invoices processed · {pct:.0%}")
        _outcome_bar(total, sent, escalated, failed_count)

    if not active:
        if status.lower() == "completed":
            st.success("Job completed. All invoices have been processed.")
        elif status.lower() == "failed":
            err = job.get("error_message", "")
            st.error(f"Job failed. {err}" if err else "Job failed. Check the audit log for details.")
        if in_fragment:
            st.rerun()  # leave polling mode: next full run renders a static panel
    elif sleep_poll:
        time.sleep(_POLL_INTERVAL)
        st.rerun()


if hasattr(st, "fragment"):
    @st.fragment(run_every=_POLL_INTERVAL)
    def _live_fragment(job_id: int) -> None:
        _live_body(job_id, in_fragment=True)
else:  # pragma: no cover — very old Streamlit
    _live_fragment = None


def _render_live_job(job_id: int, *, auto_refresh: bool = True) -> None:
    job = _get_job(job_id)
    active = bool(job and str(job.get("status", "")).lower() in ("running", "queued"))

    if active and auto_refresh:
        if _live_fragment is not None:
            _live_fragment(job_id)
        else:
            _live_body(job_id, sleep_poll=True)
    else:
        _live_body(job_id)


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
def _render_sidebar(services: dict) -> str:
    from core.config import FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES

    with st.sidebar:
        st.markdown(
            '<div class="cf-brand"><div class="cf-logo">💳</div>'
            "<div><b>CreditFlow AI</b><span>Credit follow-up agent</span></div></div>",
            unsafe_allow_html=True,
        )

        st.session_state.setdefault("nav", PAGES[0])
        page = st.radio("Navigate", PAGES, key="nav", label_visibility="collapsed")

        # Live system status
        try:
            active_jobs = [
                j for j in _list_jobs(limit=50)
                if str(j.get("status", "")).lower() in ("running", "queued")
            ]
        except Exception:
            active_jobs = []

        def dot(ok: bool) -> str:
            return f'<i class="cf-dot" style="background:{C_ACCENT if ok else C_DANGER}"></i>'

        job_line = (
            f'<i class="cf-dot" style="background:{C_INFO}"></i>{len(active_jobs)} job(s) running'
            if active_jobs
            else '<i class="cf-dot" style="background:rgba(128,128,128,.6)"></i>No jobs running'
        )
        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.markdown(
            '<div class="cf-side-card">'
            f"{dot(services.get('db', False))}Database<br>"
            f"{dot(services.get('scheduler') is not None)}Retry scheduler "
            f"(every {FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES} min)<br>"
            f"{job_line}</div>",
            unsafe_allow_html=True,
        )
        st.caption("Powered by LangGraph + Groq")
    return page


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: UPLOAD CSV
# ══════════════════════════════════════════════════════════════════════════════
def _reset_upload_state() -> None:
    for key in ("submitted_job_id", "upload_result_flag"):
        st.session_state[key] = None
    st.session_state["upload_file_key"] = st.session_state.get("upload_file_key", 0) + 1


def _profile_csv(uploaded_file) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(uploaded_file)
        uploaded_file.seek(0)
        return df
    except Exception as exc:
        uploaded_file.seek(0)
        st.error(f"This file could not be read as a CSV: {exc}")
        return None


def page_upload() -> None:
    _page_header(
        "Upload invoice CSV",
        "Upload a CSV of overdue invoices. The AI agent drafts, sends and logs "
        "follow-ups, and escalates the ones that need a person.",
    )

    st.session_state.setdefault("submitted_job_id", None)
    st.session_state.setdefault("upload_result_flag", None)
    st.session_state.setdefault("upload_file_key", 0)

    job_id = st.session_state["submitted_job_id"]
    flag = st.session_state["upload_result_flag"]

    uploaded_file = st.file_uploader(
        "Drop a CSV here, or browse",
        type=["csv"],
        key=f"csv_uploader_{st.session_state['upload_file_key']}",
        help="One row per overdue invoice.",
    )

    # Stepper reflects where the user is
    if job_id is not None:
        _stepper(2)
    elif uploaded_file is not None:
        _stepper(1)
    else:
        _stepper(0)

    if uploaded_file is not None and job_id is None:
        df = _profile_csv(uploaded_file)
        if df is not None:
            empty_cells = int(df.isna().sum().sum())
            dupe_rows = int(df.duplicated().sum())

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Rows", f"{len(df):,}")
            m2.metric("Columns", len(df.columns))
            m3.metric("Empty cells", f"{empty_cells:,}")
            m4.metric("File size", f"{uploaded_file.size / 1024:.1f} KB")

            if len(df) == 0:
                st.error("The file has no data rows. Add at least one invoice and upload again.")
            if dupe_rows:
                st.warning(f"{dupe_rows} row(s) are exact duplicates of another row.")
            if empty_cells:
                st.info("Some cells are empty. Rows with missing required fields may be marked as failed.")

            tab_prev, tab_cols = st.tabs(["Preview", "Column check"])
            with tab_prev:
                n_rows = st.slider(
                    "Rows to preview", 5, min(100, max(len(df), 6)), 5, key="prev_rows"
                ) if len(df) > 5 else len(df)
                _dataframe(df.head(n_rows))
            with tab_cols:
                summary = pd.DataFrame({
                    "Column": df.columns,
                    "Type": [str(t) for t in df.dtypes],
                    "Filled %": [round(df[c].notna().mean() * 100, 1) for c in df.columns],
                    "Unique values": [int(df[c].nunique()) for c in df.columns],
                })
                _dataframe(
                    summary,
                    column_config={
                        "Filled %": st.column_config.ProgressColumn(
                            "Filled %", min_value=0, max_value=100, format="%.0f%%"
                        )
                    },
                )

            col_go, col_clear, _ = st.columns([2, 1, 5])
            go = col_go.button(
                "🚀 Start processing", type="primary", disabled=len(df) == 0,
                use_container_width=True,
            )
            col_clear.button("Clear", on_click=_reset_upload_state, use_container_width=True)
            if go:
                _submit_upload(uploaded_file)

    elif job_id is None:
        _empty_state(
            "📄", "No file selected",
            "Choose a CSV above to preview it before the pipeline starts.",
        )

    # ── Result / live progress ───────────────────────────────────────────────
    if job_id is None:
        return

    if flag == "in_progress":
        st.warning(
            f"This exact file is already being processed as Job #{job_id}. "
            "Live progress is shown below."
        )
    elif flag is True:
        st.warning(f"Duplicate file. Showing cached results from Job #{job_id}.")
    else:
        st.success(f"Job #{job_id} submitted. Processing continues in the background.")

    st.markdown(f"#### Job #{job_id}")
    _render_live_job(job_id, auto_refresh=(flag is not True))

    b1, b2, _ = st.columns([2, 2, 6])
    b1.button("Upload another file", on_click=_reset_upload_state, use_container_width=True)
    b2.button(
        "Open in Jobs", on_click=_goto, args=("📋 Jobs",), use_container_width=True
    )


def _submit_upload(uploaded_file) -> None:
    tmp_path = None
    with st.status("Preparing your file…", expanded=True) as upload_status:
        try:
            st.write("💾 Saving file to temporary storage…")
            suffix = os.path.splitext(uploaded_file.name)[-1] or ".csv"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getbuffer())
                tmp_path = tmp.name
            st.write(f"✅ Saved — **{uploaded_file.size / 1024:.1f} KB**")

            st.write("🔐 Computing SHA-256 hash and checking for duplicates…")
            from core.upload_handler import handle_csv_upload
            result = handle_csv_upload(tmp_path)

            st.write("📊 Parsing invoice rows…")
            if isinstance(result, (tuple, list)) and len(result) >= 2:
                job_id, flag = int(result[0]), result[1]
            else:
                job_id, flag = int(result), False

            if flag not in (True, "in_progress"):
                st.write("🚀 AI pipeline started in the background.")
            else:
                st.write("ℹ️ Duplicate or in-progress file detected — no new job dispatched.")

            st.session_state["submitted_job_id"] = job_id
            st.session_state["upload_result_flag"] = flag
            upload_status.update(label="Upload complete", state="complete", expanded=False)
        except Exception as exc:
            upload_status.update(label="Upload failed", state="error")
            st.error(f"Upload failed: {exc}. Check the file and try again.")
            return
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    st.toast("File submitted", icon="🚀")
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: JOBS
# ══════════════════════════════════════════════════════════════════════════════
def page_jobs() -> None:
    _page_header("Jobs", "Every upload run, with outcomes and live progress.")

    top_l, top_r = st.columns([6, 1])
    if top_r.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    try:
        jobs = _list_jobs(limit=50)
    except Exception as exc:
        st.error(f"Could not load jobs: {exc}")
        return

    if not jobs:
        _empty_state("📋", "No jobs yet", "Upload a CSV to start your first run.")
        st.button("Go to upload", on_click=_goto, args=(PAGES[0],))
        return

    df = _to_df(jobs)
    for col in ("total_records", "processed_count", "sent_count", "escalated_count", "failed_count"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    def _sum(col: str) -> int:
        return int(df[col].sum()) if col in df.columns else 0

    total_recs, emails_sent = _sum("total_records"), _sum("sent_count")
    success_pct = round(emails_sent / total_recs * 100, 1) if total_recs else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total jobs", len(df))
    c2.metric("Success rate", f"{success_pct}%")
    c3.metric("Emails sent", f"{emails_sent:,}")
    c4.metric("Escalations", f"{_sum('escalated_count'):,}")
    c5.metric("Failures", f"{_sum('failed_count'):,}")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    id_col = next((c for c in ("id", "job_id") if c in df.columns), None)

    # ── Filters ──────────────────────────────────────────────────────────────
    f1, f2 = st.columns([3, 2])
    statuses = sorted(df["status"].astype(str).unique()) if "status" in df.columns else []
    chosen = f1.multiselect("Status", statuses, default=statuses, placeholder="All statuses")
    search = f2.text_input("Job ID", placeholder="e.g. 12")

    view = df.copy()
    if statuses and chosen:
        view = view[view["status"].astype(str).isin(chosen)]
    if search.strip() and id_col:
        view = view[view[id_col].astype(str).str.contains(search.strip(), na=False)]

    if view.empty:
        st.info("No jobs match these filters. Clear a filter to see more.")
        return

    # ── Table ────────────────────────────────────────────────────────────────
    col_map = {
        "id": "Job ID", "job_id": "Job ID", "status": "Status", "created_at": "Created",
        "total_records": "Total", "processed_count": "Processed", "sent_count": "Sent",
        "escalated_count": "Escalated", "failed_count": "Failed",
    }
    keys = list(dict.fromkeys(k for k in col_map if k in view.columns))
    tdf = view[keys].rename(columns=col_map).copy()
    if "Created" in tdf.columns:
        tdf["Created"] = tdf["Created"].astype(str).str[:19]
    if {"Processed", "Total"} <= set(tdf.columns):
        tdf["Progress"] = (
            pd.to_numeric(tdf["Processed"] / tdf["Total"].replace(0, pd.NA) * 100, errors="coerce")
            .fillna(0).round(1)
        )
    if {"Sent", "Total"} <= set(tdf.columns):
        tdf["Success %"] = (
            pd.to_numeric(tdf["Sent"] / tdf["Total"].replace(0, pd.NA) * 100, errors="coerce")
            .fillna(0).round(1)
        )

    cfg = {}
    for name in ("Progress", "Success %"):
        if name in tdf.columns:
            cfg[name] = st.column_config.ProgressColumn(
                name, min_value=0, max_value=100, format="%.0f%%"
            )

    tab_table, tab_chart = st.tabs(["Table", "Outcomes by job"])
    with tab_table:
        _dataframe(tdf, column_config=cfg)
        st.download_button(
            "⬇️ Download CSV",
            data=tdf.to_csv(index=False).encode("utf-8"),
            file_name="jobs.csv",
            mime="text/csv",
        )
    with tab_chart:
        if {"Sent", "Escalated", "Failed", "Job ID"} <= set(tdf.columns):
            chart_df = tdf.head(15).copy()
            chart_df["Job"] = "#" + chart_df["Job ID"].astype(str)
            chart_df = chart_df.set_index("Job")[["Sent", "Escalated", "Failed"]].iloc[::-1]
            try:
                st.bar_chart(chart_df, color=[C_ACCENT, C_ESCAL, C_DANGER])
            except TypeError:
                st.bar_chart(chart_df)
            st.caption("Most recent 15 jobs in the current filter.")
        else:
            st.info("Outcome columns are not available for this data.")

    # ── Detail ───────────────────────────────────────────────────────────────
    if not id_col:
        return

    st.markdown("---")
    st.subheader("Job detail")
    selected = st.selectbox(
        "Choose a job",
        options=view[id_col].tolist(),
        format_func=lambda x: f"Job #{x}",
        label_visibility="collapsed",
    )
    if selected is None:
        return

    job = _get_job(int(selected))
    is_active = bool(job and str(job.get("status", "")).lower() in ("running", "queued"))

    tab_over, tab_recs = st.tabs(["Overview", "Invoice records"])
    with tab_over:
        watch = True
        if is_active:
            watch = st.toggle("Live updates", value=True, key=f"watch_{selected}")
        _render_live_job(int(selected), auto_refresh=watch and is_active)
    with tab_recs:
        try:
            recs = _to_df(_get_audit_logs(int(selected)))
        except Exception as exc:
            st.error(f"Could not load records: {exc}")
            recs = pd.DataFrame()
        if recs.empty:
            st.info("No invoice records for this job yet.")
        else:
            _dataframe(recs)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: AUDIT LOGS
# ══════════════════════════════════════════════════════════════════════════════
def page_audit_logs() -> None:
    _page_header("Audit logs", "A per-invoice record of everything the agent did in a job.")

    try:
        jobs = _list_jobs(limit=100)
    except Exception as exc:
        st.error(f"Could not load jobs: {exc}")
        return

    if not jobs:
        _empty_state("🔍", "No audit records yet", "Records appear here once a job has run.")
        return

    job_map: dict[str, int] = {}
    for j in jobs:
        jid = int(j.get("id", j.get("job_id", 0)))
        label = (
            f"Job #{jid}  ·  {str(j.get('status', '')).upper()}  ·  "
            f"{str(j.get('created_at', ''))[:16]}"
        )
        job_map[label] = jid

    sel_col, ref_col = st.columns([6, 1])
    label = sel_col.selectbox("Job", list(job_map.keys()))
    ref_col.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
    if ref_col.button("🔄", help="Refresh", use_container_width=True):
        st.rerun()
    job_id = job_map[label]

    try:
        logs = _get_audit_logs(job_id)
    except Exception as exc:
        st.error(f"Could not load logs: {exc}")
        return

    if not logs:
        st.info("No audit records for this job.")
        return

    df = _to_df(logs)
    invoice_col = next((c for c in ("invoice_no", "invoice_number") if c in df.columns), None)

    f1, f2, f3 = st.columns([3, 2, 2])
    search = f1.text_input("Invoice or client", placeholder="e.g. INV-001 or Acme")
    status_opts = sorted(df["send_status"].dropna().astype(str).unique()) if "send_status" in df.columns else []
    stage_opts = sorted(df["stage_key"].dropna().astype(str).unique()) if "stage_key" in df.columns else []
    sel_status = f2.multiselect("Send status", status_opts, placeholder="All")
    sel_stage = f3.multiselect("Stage", stage_opts, placeholder="All")

    if search.strip():
        needle = search.strip()
        mask = pd.Series(False, index=df.index)
        for c in (invoice_col, "client"):
            if c and c in df.columns:
                mask |= df[c].astype(str).str.contains(needle, case=False, na=False)
        df = df[mask]
    if sel_status:
        df = df[df["send_status"].astype(str).isin(sel_status)]
    if sel_stage:
        df = df[df["stage_key"].astype(str).isin(sel_stage)]

    m1, m2, m3 = st.columns(3)
    m1.metric("Records shown", len(df))
    m2.metric("Sent", int((df.get("send_status", pd.Series(dtype=str)) == "sent").sum()))
    m3.metric("Failed", int((df.get("send_status", pd.Series(dtype=str)) == "failed").sum()))

    if df.empty:
        st.info("No records match these filters.")
        return

    cfg = {}
    if "amount" in df.columns:
        cfg["amount"] = st.column_config.NumberColumn("Amount", format="₹%d")
    if "days_overdue" in df.columns:
        cfg["days_overdue"] = st.column_config.NumberColumn("Days overdue", format="%d")
    _dataframe(df, column_config=cfg)

    st.download_button(
        "⬇️ Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"audit_job_{job_id}.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: EMAIL LOGS
# ══════════════════════════════════════════════════════════════════════════════
_SEND_STATUS_ICON = {"sent": "✅", "failed": "❌", "not_sent": "↗️"}
_PAGE_SIZE = 20


def _email_card(log: dict) -> None:
    send_status = str(log.get("send_status", "not_sent") or "not_sent")
    is_escalation = bool(log.get("escalation_required", False))
    tone = str(log.get("tone_used", "") or "")
    tone_color = _TONE_COLOR.get(tone, C_MUTED)

    amount = log.get("amount")
    amount_str = f"₹{amount:,.0f}" if isinstance(amount, (int, float)) else _esc(amount)
    recipient = log.get("contact_email_masked") or log.get("recipient")
    error_msg = str(log.get("error_message", "") or "")
    bar = C_ESCAL if is_escalation else _STATUS_STYLE.get(send_status, (C_MUTED, ""))[0]

    esc_pill = (
        f'<span class="cf-pill" style="color:{C_DANGER};background:rgba(185,28,28,.14)">'
        "🚨 Escalated</span>" if is_escalation else ""
    )
    tone_pill = (
        f'<span class="cf-pill" style="color:{tone_color};background:{tone_color}22">'
        f"{_esc(tone)}</span>" if tone else ""
    )
    job_pill = f'<span class="cf-pill" style="color:{C_INFO};background:rgba(37,99,235,.12)">Job #{_esc(log.get("job_id"))}</span>'
    status_pill = _pill(
        f"{_SEND_STATUS_ICON.get(send_status, '—')} {send_status.replace('_', ' ').title()}",
        send_status,
    )
    err_html = f'<div class="cf-err"><b>Error:</b> {_esc(error_msg)}</div>' if error_msg else ""

    def meta(label: str, value: str) -> str:
        return f"<div><small>{label}</small><span>{value}</span></div>"

    card = (
        f'<div class="cf-mail{" esc" if is_escalation else ""}" style="--bar:{bar}">'
        '<div class="cf-mail-top">'
        f'<div class="l"><span class="cf-ts">{_esc(str(log.get("created_at", ""))[:19])}</span>{job_pill}</div>'
        f'<div class="r">{esc_pill}{tone_pill}{status_pill}</div></div>'
        '<div class="cf-mail-body">'
        f'<div class="cf-subject">{_esc(log.get("subject") or "(no subject)")}</div>'
        '<div class="cf-meta">'
        + meta("To", _esc(recipient))
        + meta("Invoice", _esc(log.get("invoice_no")))
        + meta("Client", _esc(log.get("client")))
        + meta("Amount", amount_str)
        + meta("Days overdue", _esc(log.get("days_overdue")))
        + meta("Stage", _esc(log.get("stage_key")))
        + "</div>"
        + err_html
        + "</div></div>"
    )
    st.markdown(card, unsafe_allow_html=True)


def page_email_logs() -> None:
    _page_header(
        "Email logs",
        "Every follow-up and escalation the agent has dispatched, newest first.",
    )

    try:
        all_jobs = _list_jobs(limit=100)
    except Exception:
        all_jobs = []

    job_options: dict[str, int | None] = {"All jobs": None}
    for j in all_jobs:
        jid = int(j.get("id", j.get("job_id", 0)))
        job_options[
            f"Job #{jid} — {str(j.get('status', '')).upper()} ({str(j.get('created_at', ''))[:16]})"
        ] = jid

    f0, f1, f2, f3, f4 = st.columns([2.2, 1.6, 1.8, 3, 0.7])
    filter_job = f0.selectbox("Job", list(job_options.keys()))
    filter_status = f1.selectbox("Status", ["All", "sent", "failed", "not_sent"])
    filter_type = f2.selectbox("Type", ["All", "Client emails", "Escalations", "No overdue"])
    filter_search = f3.text_input("Invoice or client", placeholder="INV-001 or Acme Corp")
    f4.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
    if f4.button("🔄", help="Refresh", use_container_width=True):
        st.rerun()

    try:
        logs = _get_all_audit_logs(limit=300, job_id=job_options[filter_job])
    except Exception as exc:
        st.error(f"Could not load email logs: {exc}")
        return

    if not logs:
        _empty_state("📧", "No email activity yet", "Sent emails and escalations will show up here.")
        return

    def _matches(log: dict) -> bool:
        stage = log.get("stage_key")
        if filter_status != "All" and log.get("send_status") != filter_status:
            return False
        if filter_type == "Client emails" and stage in ("Escalation Flag", "No_overdue"):
            return False
        if filter_type == "Escalations" and stage != "Escalation Flag":
            return False
        if filter_type == "No overdue" and stage != "No_overdue":
            return False
        if filter_search.strip():
            hay = (str(log.get("invoice_no", "")) + str(log.get("client", ""))).lower()
            if filter_search.strip().lower() not in hay:
                return False
        return True

    filtered = [l for l in logs if _matches(l)]

    # Reset pagination whenever the filters change
    sig = (filter_job, filter_status, filter_type, filter_search.strip())
    if st.session_state.get("email_sig") != sig:
        st.session_state["email_sig"] = sig
        st.session_state["email_limit"] = _PAGE_SIZE
    limit = st.session_state.setdefault("email_limit", _PAGE_SIZE)

    n_sent = sum(1 for l in filtered if l.get("send_status") == "sent")
    n_failed = sum(1 for l in filtered if l.get("send_status") == "failed")
    n_esc = sum(1 for l in filtered if l.get("escalation_required"))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Showing", len(filtered))
    m2.metric("Sent", n_sent)
    m3.metric("Failed", n_failed)
    m4.metric("Escalated", n_esc)

    if not filtered:
        st.info("No records match these filters. Clear a filter to see more.")
        return

    tab_feed, tab_tone = st.tabs(["Email feed", "Tone breakdown"])

    with tab_tone:
        tones = pd.Series([l.get("tone_used") or "Unspecified" for l in filtered]).value_counts()
        st.bar_chart(tones, color=C_ACCENT)
        st.caption("How often each tone was used in the filtered emails.")

    with tab_feed:
        top_l, top_r = st.columns([5, 1])
        top_l.caption(f"Showing {min(limit, len(filtered))} of {len(filtered)}")
        top_r.download_button(
            "⬇️ CSV",
            data=pd.DataFrame(filtered).to_csv(index=False).encode("utf-8"),
            file_name="email_logs.csv",
            mime="text/csv",
            use_container_width=True,
        )

        page_items = filtered[:limit]
        escalations = [l for l in page_items if l.get("escalation_required")]
        clients = [l for l in page_items if not l.get("escalation_required")]

        if escalations:
            st.markdown("##### 🚨 Escalations")
            for log in escalations:
                _email_card(log)
        if clients:
            st.markdown("##### 📨 Client follow-ups")
            for log in clients:
                _email_card(log)

        if limit < len(filtered):
            if st.button(f"Load {min(_PAGE_SIZE, len(filtered) - limit)} more", use_container_width=True):
                st.session_state["email_limit"] = limit + _PAGE_SIZE
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: FAILED INVOICES
# ══════════════════════════════════════════════════════════════════════════════
def page_failed_invoices() -> None:
    from core.config import FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES

    _page_header(
        "Failed invoices",
        "Invoices that could not be processed. Pending ones are retried automatically.",
    )

    top_l, top_r = st.columns([6, 1])
    if top_r.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    try:
        failed = _get_failed()
    except Exception as exc:
        st.error(f"Could not load failed invoices: {exc}")
        return

    if not failed:
        st.success("🎉 No failed invoices. Everything has been processed.")
        return

    df = _to_df(failed)
    status_series = (
        df["status"].astype(str).str.lower() if "status" in df.columns
        else pd.Series([""] * len(df))
    )
    pending = int((status_series == "pending").sum())
    resolved = int((status_series == "resolved").sum())
    permanent = int((status_series == "permanent_failure").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(df))
    c2.metric("Pending retry", pending)
    c3.metric("Resolved", resolved)
    c4.metric("Permanent failure", permanent)

    if pending:
        st.info(f"{pending} invoice(s) are waiting for retry.")
    else:
        st.success("No invoices are waiting for retry.")

    for col in ("next_retry_at", "created_at", "updated_at", "last_attempted_at"):
        if col in df.columns:
            df[col] = df[col].astype(str).str[:19]

    # Filters
    f1, f2 = st.columns([3, 3])
    opts = sorted(status_series.unique())
    chosen = f1.multiselect("Status", opts, default=opts, placeholder="All statuses")
    search = f2.text_input("Search", placeholder="Invoice, client or error text")

    view = df[status_series.isin(chosen)] if chosen else df
    if search.strip():
        needle = search.strip().lower()
        text = view.astype(str).agg(" ".join, axis=1).str.lower()
        view = view[text.str.contains(needle, regex=False)]

    if view.empty:
        st.info("No invoices match these filters.")
    else:
        _dataframe(view)
        st.download_button(
            "⬇️ Download CSV",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name="failed_invoices.csv",
            mime="text/csv",
        )

    st.markdown("---")
    st.caption(
        f"Eligible invoices are retried automatically every "
        f"**{FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES} minutes**. "
        "Run a retry now if you don't want to wait."
    )

    if pending:
        if st.button(f"⟳ Retry {pending} pending now", type="primary"):
            with st.spinner("Running retry cycle…"):
                try:
                    from scheduler.retry_scheduler import retry_failed_invoices
                    retry_failed_invoices()
                except Exception as exc:
                    st.error(f"Retry cycle failed: {exc}")
                else:
                    st.toast("Retry cycle finished", icon="✅")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════════════════════
_PAGE_FUNCS = {
    "📤 Upload CSV": page_upload,
    "📋 Jobs": page_jobs,
    "🔍 Audit Logs": page_audit_logs,
    "📧 Email Logs": page_email_logs,
    "⚠️ Failed Invoices": page_failed_invoices,
}


def main() -> None:
    st.set_page_config(
        page_title="CreditFlow AI",
        page_icon="💳",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    services = _boot_services()
    page = _render_sidebar(services)
    _PAGE_FUNCS[page]()


def _in_streamlit_runtime() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if _in_streamlit_runtime():
    main()


# ══════════════════════════════════════════════════════════════════════════════
#  run_ui() — entry point for main.py
# ══════════════════════════════════════════════════════════════════════════════
def run_ui() -> None:
    this_file = os.path.abspath(__file__)
    cmd = [sys.executable, "-m", "streamlit", "run", this_file, "--server.headless", "true"]
    logger.info("Launching Streamlit UI: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        logger.info("Streamlit UI shut down by user.")