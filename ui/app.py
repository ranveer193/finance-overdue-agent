"""
ui/app.py  —  Finance Credit Follow-Up AI Agent Dashboard
Invoked via:
    streamlit run ui/app.py        (direct)
    python main.py                 (via run_ui())

Key architecture note
─────────────────────
`master_graph.workflow.invoke()` is a BLOCKING call that runs the entire
batch pipeline.  Calling it on Streamlit's main thread prevents any
`st.rerun()` from firing until the whole job is done, breaking live
progress.

Fix: every new job is dispatched onto a daemon `threading.Thread`.
Streamlit's main thread stays free and polls `jobs_repository.get_job()`
every N seconds with `time.sleep` + `st.rerun()`.
"""

from __future__ import annotations

import os
import sys
import time
import logging
import tempfile
import subprocess

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

# ── Path bootstrap ────────────────────────────────────────────────────────────
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# ── One-time service boot (DB + scheduler) ───────────────────────────────────
_scheduler = None

def _boot_services() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    try:
        from database.schema import initialize_database
        initialize_database()
    except Exception as exc:
        logger.warning("DB init warning: %s", exc)

    try:
        from observability.tracing import configure_tracing
        configure_tracing()
    except Exception as exc:
        logger.warning("Tracing setup warning: %s", exc)

    try:
        from scheduler.retry_scheduler import start_scheduler
        _scheduler = start_scheduler()
    except Exception as exc:
        logger.warning("Scheduler start warning: %s", exc)

if "services_booted" not in st.session_state:
    _boot_services()
    st.session_state["services_booted"] = True

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CreditFlow AI",
    page_icon="💳",
    layout="wide",
)
from core.config import FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES

# ── Sidebar navigation ────────────────────────────────────────────────────────
st.sidebar.title("💳 CreditFlow AI")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    [
        "📤 Upload CSV",
        "📋 Jobs",
        "🔍 Audit Logs",
        "📧 Email Logs",
        "⚠️ Failed Invoices",
    ],
)
st.sidebar.markdown("---")
st.sidebar.caption("Powered by LangGraph + Mistral")

# ── Repository singletons ─────────────────────────────────────────────────────
from database.jobs_repository   import JobsRepository
from database.audit_repository  import AuditRepository
from database.failed_repository import FailedInvoicesRepository

_jobs_repo   = JobsRepository()
_audit_repo  = AuditRepository()
_failed_repo = FailedInvoicesRepository()


# ── Repository helpers ────────────────────────────────────────────────────────
def _list_jobs(limit: int = 50) -> list:
    return _jobs_repo.list_jobs(limit=limit)

def _get_job(job_id: int) -> dict | None:
    return _jobs_repo.get_job(job_id)

def _get_audit_logs(job_id: int) -> list:
    return _audit_repo.get_by_job(job_id)

def _get_retryable() -> list:
    return _failed_repo.list_all(limit=100)

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


# ── Data helpers ──────────────────────────────────────────────────────────────
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
    """
    Render a dataframe.  Uses the new `width` parameter to avoid the
    use_container_width deprecation warning (removed after 2025-12-31).
    Falls back gracefully for older Streamlit installs.
    """
    # Remove any caller-supplied use_container_width to avoid conflicts.
    kwargs.pop("use_container_width", None)
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except TypeError:
        # Streamlit version that doesn't yet support width='stretch'
        try:
            st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)
        except TypeError:
            st.dataframe(df, hide_index=True, **kwargs)


# ── Job status badge ──────────────────────────────────────────────────────────
_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "running":   ("#1d4ed8", "#dbeafe"),
    "queued":    ("#92400e", "#fef3c7"),
    "completed": ("#065f46", "#d1fae5"),
    "failed":    ("#991b1b", "#fee2e2"),
}

def _status_badge(status: str) -> str:
    fg, bg = _STATUS_COLORS.get(status.lower(), ("#374151", "#f3f4f6"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:99px;font-size:0.78rem;font-weight:700;'
        f'letter-spacing:0.05em">{status.upper()}</span>'
    )

# ── Auto-refresh poll interval ────────────────────────────────────────────────
_POLL_INTERVAL = 2   # seconds between DB polls while job is active


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE JOB WIDGET
# ══════════════════════════════════════════════════════════════════════════════

def _render_live_job(job_id: int, *, auto_refresh: bool = True) -> None:
    job = _get_job(job_id)
    if not job:
        st.warning(f"Job #{job_id} not found.")
        return

    status       = str(job.get("status", "unknown"))
    total        = int(job.get("total_records",   0) or 0)
    processed    = int(job.get("processed_count", 0) or 0)
    sent         = int(job.get("sent_count",      0) or 0)
    escalated    = int(job.get("escalated_count", 0) or 0)
    failed_count = int(job.get("failed_count",    0) or 0)

    st.markdown(_status_badge(status), unsafe_allow_html=True)
    st.markdown("")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total",     total        or "—")
    c2.metric("Processed", processed    or "—")
    c3.metric("Sent ✅",   sent)
    c4.metric("Escalated", escalated)
    c5.metric("Failed ❌", failed_count)

    if total and processed:
        st.progress(
            min(processed / total, 1.0),
            text=f"Processed {processed} / {total}",
        )

    still_active = status in ("running", "queued")

    if still_active and auto_refresh:
        st.caption(f"⟳ Auto-refreshing every {_POLL_INTERVAL} s…")
        time.sleep(_POLL_INTERVAL)
        st.rerun()

    if not still_active:
        if status == "completed":
            st.success("✅ Job completed successfully.")
        elif status == "failed":
            err = job.get("error_message", "")
            st.error(f"❌ Job failed. {err}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Upload CSV
# ══════════════════════════════════════════════════════════════════════════════

def _reset_upload_state() -> None:
    for key in ("submitted_job_id", "upload_result_flag", "upload_file_key"):
        st.session_state.pop(key, None)


def page_upload() -> None:
    st.title("📤 Upload Invoice CSV")
    st.caption("Upload a CSV of overdue invoices to start the AI follow-up pipeline.")

    st.session_state.setdefault("submitted_job_id",   None)
    st.session_state.setdefault("upload_result_flag", None)
    st.session_state.setdefault("upload_file_key", 0)

    col_clear, col_refresh, _ = st.columns([1, 1, 8])

    with col_clear:
        if st.button("🗑️ Clear", help="Reset the upload form and result panel"):
            _reset_upload_state()
            st.session_state["upload_file_key"] = (
                st.session_state.get("upload_file_key", 0) + 1
            )
            st.rerun()

    with col_refresh:
        if st.button("🔄 Refresh", help="Re-read job status from the database"):
            st.rerun()

    st.markdown("---")

    uploaded_file = st.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        key=f"csv_uploader_{st.session_state['upload_file_key']}",
    )

    if uploaded_file is not None:
        try:
            preview = pd.read_csv(uploaded_file, nrows=5)
            uploaded_file.seek(0)
            st.markdown(f"**Preview** — first {len(preview)} rows")
            _dataframe(preview)
        except Exception as exc:
            st.warning(f"Could not render preview: {exc}")

        if st.button("🚀 Start Processing", type="primary"):
            tmp_path = None
            # ── Multi-step status panel ───────────────────────────────────
            with st.status("Preparing your file…", expanded=True) as upload_status:
                try:
                    # Step 1: save to temp
                    st.write("💾 Saving file to temporary storage…")
                    suffix = os.path.splitext(uploaded_file.name)[-1] or ".csv"
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=suffix
                    ) as tmp:
                        tmp.write(uploaded_file.getbuffer())
                        tmp_path = tmp.name
                    st.write(f"✅ File saved — **{uploaded_file.size / 1024:.1f} KB**")

                    # Step 2: hash + duplicate check
                    st.write("🔐 Computing SHA-256 hash & checking for duplicates…")
                    from core.upload_handler import handle_csv_upload
                    result = handle_csv_upload(tmp_path)

                    # Step 3: decode result
                    st.write("📊 Parsing invoice rows…")
                    if isinstance(result, (tuple, list)) and len(result) >= 2:
                        job_id, flag = int(result[0]), result[1]
                    else:
                        job_id, flag = int(result), False

                    # Step 4: dispatch background job
                    if flag not in (True, "in_progress"):
                        st.write("🚀 AI pipeline has been started in the background.")
                    else:
                        st.write(
                            "ℹ️ Duplicate or in-progress file detected — skipping dispatch."
                        )

                    st.session_state.submitted_job_id   = job_id
                    st.session_state.upload_result_flag = flag
                    upload_status.update(
                        label="✅ Upload complete — pipeline is running!",
                        state="complete",
                        expanded=False,
                    )

                except Exception as exc:
                    upload_status.update(label="❌ Upload failed", state="error")
                    st.error(f"Upload failed: {exc}")
                    return
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

            st.rerun()

    # ── Result / progress panel ───────────────────────────────────────────
    job_id = st.session_state.submitted_job_id
    flag   = st.session_state.upload_result_flag

    if job_id is None:
        return

    if flag == "in_progress":
        st.warning(
            f"⚙️ This exact file is **already being processed** as Job **#{job_id}**. "
            "Live progress is shown below."
        )
    elif flag is True:
        st.warning(
            f"♻️ Duplicate file detected — showing cached results from Job **#{job_id}**."
        )
    else:
        st.success(
            f"✅ Job **#{job_id}** submitted and processing in the background."
        )

    st.markdown(f"### Job #{job_id} — Live Progress")
    _render_live_job(job_id, auto_refresh=(flag is not True))


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Jobs
# ══════════════════════════════════════════════════════════════════════════════
def page_jobs() -> None:
    st.title("📋 Jobs Dashboard")

    col_refresh, _ = st.columns([1, 8])
    if col_refresh.button("🔄 Refresh"):
        st.rerun()

    try:
        jobs = _list_jobs(limit=50)
    except Exception as exc:
        st.error(f"Could not load jobs: {exc}")
        return

    if not jobs:
        st.info("No jobs yet. Go to Upload CSV to get started.")
        return

    df = _to_df(jobs)

    for col in ("total_records", "processed_count", "sent_count",
                "escalated_count", "failed_count"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    def _sum(col: str) -> int:
        return int(df[col].sum()) if col in df.columns else 0

    total_recs  = _sum("total_records")
    emails_sent = _sum("sent_count")
    escalations = _sum("escalated_count")
    failures    = _sum("failed_count")
    success_pct = round(emails_sent / total_recs * 100, 1) if total_recs else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Jobs",   len(df))
    c2.metric("Success Rate", f"{success_pct}%")
    c3.metric("Emails Sent",  emails_sent)
    c4.metric("Escalations",  escalations)
    c5.metric("Failures",     failures)

    st.markdown("---")

    col_map = {
        "id":              "Job ID",
        "job_id":          "Job ID",
        "status":          "Status",
        "created_at":      "Created At",
        "total_records":   "Total",
        "processed_count": "Processed",
        "sent_count":      "Sent",
        "escalated_count": "Escalated",
        "failed_count":    "Failed",
    }
    present_keys = list(dict.fromkeys(k for k in col_map if k in df.columns))
    tdf = df[present_keys].rename(columns=col_map).copy()

    if "Created At" in tdf.columns:
        tdf["Created At"] = tdf["Created At"].astype(str).str[:19]

    if "Sent" in tdf.columns and "Total" in tdf.columns:
        tdf["Success %"] = pd.to_numeric(
            tdf["Sent"] / tdf["Total"].replace(0, pd.NA) * 100,
            errors="coerce",
        ).round(1).fillna(0)

    _dataframe(tdf)

    st.markdown("---")
    id_col = next((c for c in ("id", "job_id") if c in df.columns), None)
    if not id_col:
        return

    selected = st.selectbox(
        "Inspect a job in detail",
        options=df[id_col].tolist(),
        format_func=lambda x: f"Job #{x}",
    )
    if selected is None:
        return

    st.markdown(f"**Job #{selected}**")

    job       = _get_job(int(selected))
    is_active = bool(
        job and job.get("status") in ("running", "queued")
    )

    if is_active:
        watch = st.button("📡 Watch live (auto-refresh)", key=f"watch_{selected}")
        _render_live_job(int(selected), auto_refresh=watch)
    else:
        _render_live_job(int(selected), auto_refresh=False)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Audit Logs
# ══════════════════════════════════════════════════════════════════════════════
def page_audit_logs() -> None:
    st.title("🔍 Audit Logs")
    st.caption("Per-invoice processing records for any job.")

    try:
        jobs = _list_jobs(limit=100)
    except Exception as exc:
        st.error(f"Could not load jobs: {exc}")
        return

    if not jobs:
        st.info("No jobs available yet.")
        return

    job_map: dict[str, int] = {}
    for j in jobs:
        jid   = int(j.get("id", j.get("job_id", 0)))
        label = (
            f"Job #{jid}  |  "
            f"{str(j.get('status', '')).upper()}  |  "
            f"{str(j.get('created_at', ''))[:16]}"
        )
        job_map[label] = jid

    label  = st.selectbox("Select Job", list(job_map.keys()))
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

    invoice_col = next(
        (c for c in ("invoice_no", "invoice_number") if c in df.columns), None
    )
    search = st.text_input("Filter by invoice number", placeholder="e.g. INV-001")
    if search.strip() and invoice_col:
        df = df[
            df[invoice_col].astype(str).str.contains(
                search.strip(), case=False, na=False
            )
        ]
        st.caption(f"{len(df)} result(s) for '{search}'")

    _dataframe(df)

    st.download_button(
        "⬇️ Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"audit_job_{job_id}.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Email Logs
# ══════════════════════════════════════════════════════════════════════════════
_SEND_STATUS_ICON = {
    "sent":     "✅",
    "failed":   "❌",
    "not_sent": "↗️",
}
_TONE_COLOR = {
    "Warm & Friendly":       "#22c55e",
    "Polite but Firm":       "#3b82f6",
    "Formal & Serious":      "#8b5cf6",
    "Stern & Urgent":        "#f97316",
    "Legal Review Required": "#ef4444",
}


def _email_card(log: dict) -> None:
    send_status   = log.get("send_status", "not_sent")
    is_escalation = bool(log.get("escalation_required", False))
    tone          = log.get("tone_used", "")
    tone_color    = _TONE_COLOR.get(tone, "#6b7280")
    icon          = _SEND_STATUS_ICON.get(send_status, "—")

    subject    = log.get("subject", "(no subject)")
    recipient  = log.get("contact_email_masked") or log.get("recipient", "—")
    stage      = log.get("stage_key", "—")
    invoice_no = log.get("invoice_no", "—")
    client     = log.get("client", "—")
    amount     = log.get("amount")
    overdue    = log.get("days_overdue", "—")
    ts         = str(log.get("created_at", ""))[:19]
    error_msg  = str(log.get("error_message", "") or "")
    job_id_val = log.get("job_id", "—")

    amount_str = (
        f"₹{amount:,.0f}" if isinstance(amount, (int, float)) else str(amount or "—")
    )
    header_bg  = "#1e293b" if not is_escalation else "#3b1c1c"
    border_col = "#334155" if not is_escalation else "#dc2626"
    escalation_badge = (
        '&nbsp;&nbsp;<span style="background:#dc2626;color:#fff;'
        'padding:1px 8px;border-radius:99px;font-size:0.72rem">🚨 ESCALATED</span>'
        if is_escalation else ""
    )
    error_html = (
        f'<div style="color:#f87171;margin-top:6px"><b>Error:</b> {error_msg}</div>'
        if error_msg else ""
    )
    job_badge = (
        f'<span style="background:#1e40af22;color:#93c5fd;padding:1px 8px;'
        f'border-radius:99px;font-size:0.70rem;font-weight:600">Job #{job_id_val}</span>'
    )

    st.markdown(
        f"""
<div style="border:1px solid {border_col};border-radius:8px;
            margin-bottom:10px;overflow:hidden;font-size:0.82rem">
  <div style="background:{header_bg};padding:7px 14px;display:flex;
              justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
    <span style="display:flex;align-items:center;gap:8px">
      <span style="color:#94a3b8;font-family:monospace">{ts}</span>
      {job_badge}
    </span>
    <span style="color:#f8fafc;font-weight:700;font-family:monospace">
      {icon} {send_status.upper()}{escalation_badge}
    </span>
    <span style="background:{tone_color}25;color:{tone_color};padding:1px 9px;
                 border-radius:99px;font-size:0.73rem;font-weight:600">{tone}</span>
  </div>
  <div style="padding:10px 14px;background:#0f172a;color:#e2e8f0;
              font-family:monospace;line-height:1.9">
    <div><b style="color:#64748b;display:inline-block;width:75px">To</b>{recipient}</div>
    <div><b style="color:#64748b;display:inline-block;width:75px">Subject</b>{subject}</div>
    <div><b style="color:#64748b;display:inline-block;width:75px">Invoice</b>
         {invoice_no}&nbsp;&nbsp;{client}&nbsp;&nbsp;{amount_str}&nbsp;&nbsp;{overdue}d overdue</div>
    <div><b style="color:#64748b;display:inline-block;width:75px">Stage</b>{stage}</div>
    {error_html}
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def page_email_logs() -> None:
    st.title("📧 Email Logs")
    st.caption(
        "Terminal-style log of every email and escalation dispatched by the agent."
    )

    # ── Load jobs for the job filter ──────────────────────────────────────
    try:
        all_jobs = _list_jobs(limit=100)
    except Exception:
        all_jobs = []

    job_options: dict[str, int | None] = {"All Jobs": None}
    for j in all_jobs:
        jid   = int(j.get("id", j.get("job_id", 0)))
        label = (
            f"Job #{jid}  —  "
            f"{str(j.get('status', '')).upper()}  "
            f"({str(j.get('created_at', ''))[:16]})"
        )
        job_options[label] = jid

    # ── Filter row ────────────────────────────────────────────────────────
    col_f0, col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 3, 1])
    filter_job    = col_f0.selectbox("Job", list(job_options.keys()))
    filter_status = col_f1.selectbox("Status", ["All", "sent", "failed", "not_sent"])
    filter_type   = col_f2.selectbox("Type",   ["All", "Client emails", "Escalations", "No Overdue"])
    filter_search = col_f3.text_input(
        "Invoice / Client", placeholder="INV-001  or  Acme Corp"
    )
    if col_f4.button("🔄", help="Refresh"):
        st.rerun()

    selected_job_id = job_options[filter_job]

    try:
        logs = _get_all_audit_logs(limit=300, job_id=selected_job_id)
    except Exception as exc:
        st.error(f"Could not load email logs: {exc}")
        return

    if not logs:
        st.info("No email activity recorded yet.")
        return

    def _matches(log: dict) -> bool:
        if filter_status != "All" and log.get("send_status") != filter_status:
            return False
        if filter_type == "Client emails" and log.get("stage_key") in ["Escalation Flag", "No_overdue"]:
            return False
        if filter_type == "Escalations" and not log.get("stage_key") == "Escalation Flag":
            return False
        if filter_type == "No Overdue" and not log.get("stage_key") == "No_overdue":
            return False
        if filter_search.strip():
            needle   = filter_search.strip().lower()
            haystack = (
                str(log.get("invoice_no", "")) + str(log.get("client", ""))
            ).lower()
            if needle not in haystack:
                return False
        return True

    filtered = [l for l in logs if _matches(l)]

    n_sent     = sum(1 for l in filtered if l.get("send_status") == "sent")
    n_failed   = sum(1 for l in filtered if l.get("send_status") == "failed")
    n_escalate = sum(1 for l in filtered if l.get("escalation_required"))

    cs1, cs2, cs3, cs4 = st.columns(4)
    cs1.metric("Showing",      len(filtered))
    cs2.metric("✅ Sent",       n_sent)
    cs3.metric("❌ Failed",     n_failed)
    cs4.metric("🚨 Escalated", n_escalate)

    if not filtered:
        st.info("No records match the current filters.")
        return

    st.markdown("---")

    escalations   = [l for l in filtered if     l.get("escalation_required")]
    client_emails = [l for l in filtered if not l.get("escalation_required")]

    if escalations:
        st.markdown("#### 🚨 Escalation Emails")
        for log in escalations:
            _email_card(log)
        if client_emails:
            st.markdown("---")

    if client_emails:
        st.markdown("#### 📨 Client Follow-Up Emails")
        for log in client_emails:
            _email_card(log)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Failed Invoices
# ══════════════════════════════════════════════════════════════════════════════
def page_failed_invoices() -> None:
    st.title("⚠️ Failed Invoices")
    st.caption("Invoices that failed processing and are eligible for retry.")

    col_ref, _ = st.columns([1, 8])
    if col_ref.button("🔄 Refresh"):
        st.rerun()

    try:
        failed = _get_retryable()   # returns all rows via list_all()
    except Exception as exc:
        st.error(f"Could not load failed invoices: {exc}")
        return

    if not failed:
        st.success("🎉 No failed invoices recorded.")
        return

    df = _to_df(failed)

    # Count by status
    pending_count = sum(
        1 for row in failed
        if str(row.get("status", "")).lower() == "pending"
    )
    resolved_count = sum(
        1 for row in failed
        if str(row.get("status", "")).lower() == "resolved"
    )
    permanent_count = sum(
        1 for row in failed
        if str(row.get("status", "")).lower() == "permanent_failure"
    )

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(failed))
    c2.metric("⏳ Pending", pending_count)
    c3.metric("✅ Resolved", resolved_count)
    c4.metric("❌ Permanent", permanent_count)

    # Informational banner
    if pending_count > 0:
        st.info(f"{pending_count} invoice(s) pending retry.")
    else:
        st.success("🎉 No invoices are currently pending retry.")

    # Format timestamps for display
    for col in (
        "next_retry_at",
        "created_at",
        "updated_at",
        "last_attempted_at",
    ):
        if col in df.columns:
            df[col] = df[col].astype(str).str[:19]

    _dataframe(df)

    st.markdown("---")
    st.caption(
        "APScheduler retries eligible invoices automatically every "
        f"**{FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES} minutes**. Use the button below to trigger an immediate "
        "retry cycle."
    )

    # Only show manual retry button if something is actually pending
    if pending_count > 0:
        if st.button("⟳ Retry All Now", type="primary"):
            with st.spinner("Running retry cycle…"):
                try:
                    from scheduler.retry_scheduler import (
                        retry_failed_invoices,
                    )

                    retry_failed_invoices()
                    st.success(
                        "Retry cycle completed. Click Refresh to "
                        "see updated statuses."
                    )
                except Exception as exc:
                    st.error(f"Retry cycle error: {exc}")

# ══════════════════════════════════════════════════════════════════════════════
# Router
# ══════════════════════════════════════════════════════════════════════════════
_PAGES = {
    "📤 Upload CSV":      page_upload,
    "📋 Jobs":            page_jobs,
    "🔍 Audit Logs":      page_audit_logs,
    "📧 Email Logs":      page_email_logs,
    "⚠️ Failed Invoices": page_failed_invoices,
}

_PAGES[page]()


# ══════════════════════════════════════════════════════════════════════════════
# run_ui() — entry point for main.py
# ══════════════════════════════════════════════════════════════════════════════
def run_ui() -> None:
    this_file = os.path.abspath(__file__)
    cmd = [
        sys.executable, "-m", "streamlit", "run", this_file,
        "--server.headless", "true",
    ]
    logger.info("Launching Streamlit UI: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        logger.info("Streamlit UI shut down by user.")