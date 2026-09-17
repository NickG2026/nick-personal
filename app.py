"""SE Account Manager — personal daily-driver for SE account status.

Run locally:  streamlit run app.py
Or via the provided Dockerfile.

Everything lives in three files: app.py (UI), db.py (SQLite), data/ (the DB
file). Add a field: add a column in db.py's SCHEMA + a widget below.
"""
import datetime as dt
import re

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="SE Account Manager", layout="wide", page_icon="🗂️")
db.init_db()

APP_VERSION = "2026-09-17 (Claude-driven Slack sync requests)"

# ---------------------------------------------------------------- styling --
HEALTH_COLOR = {"Healthy": "#1DDB8C", "Attention": "#5050EE", "At Risk": "#FF4689"}

st.markdown(
    """
    <style>
      html, body, [class*="css"]  { font-family: "Open Sans", system-ui, sans-serif; }
      #MainMenu, footer, header {visibility: hidden;}
      .block-container {padding-top: 1.5rem; max-width: 1400px;}
      .se-card {
        background: #100A2C; border: 1px solid #1B1A6A; border-radius: 8px;
        padding: 8px 14px; margin-bottom: 4px; line-height: 1.25;
      }
      .se-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; }
      .se-muted { color:#8180AC; font-size:0.85rem; }
      .se-title { font-size:1.05rem; font-weight:600; color:#F4F4FF; }
      .se-card p { margin-bottom: 0; }
      div[data-testid="stMetricValue"] { color:#F4F4FF; }
      a { color:#B6B6FD; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"
if "selected_account" not in st.session_state:
    st.session_state.selected_account = None


def goto(page, account_id=None):
    st.session_state.page = page
    if account_id is not None:
        st.session_state.selected_account = account_id


# ------------------------------------------------------------------ sidebar --
with st.sidebar:
    st.markdown("### 🗂️ SE Account Manager")
    st.button("Dashboard", use_container_width=True, on_click=goto, args=("Dashboard",))
    st.button("＋ Add Account", use_container_width=True, on_click=goto, args=("Add Account",))
    st.divider()
    st.caption("Accounts")
    for acc in db.list_accounts():
        dot = HEALTH_COLOR.get(acc["health"], "#8180AC")
        if st.button(f"● {acc['name']}", key=f"nav_{acc['id']}", use_container_width=True):
            goto("Account", acc["id"])
    st.divider()
    st.caption(f"v{APP_VERSION}")


def days_until(date_str):
    if not date_str:
        return None
    try:
        d = dt.date.fromisoformat(date_str)
        return (d - dt.date.today()).days
    except ValueError:
        return None


def quarter_label(date_str):
    """'2026-09-30' -> '2026-Q3' (sorts correctly as a plain string)."""
    if not date_str:
        return None
    try:
        d = dt.date.fromisoformat(date_str)
    except ValueError:
        return None
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def parse_arr(value):
    """'$300,000' -> 300000.0; blank/unparseable -> 0.0"""
    if not value:
        return 0.0
    digits = re.sub(r"[^0-9.]", "", value)
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- dashboard --
def render_dashboard():
    accounts = db.list_accounts()
    st.title("Dashboard")

    counts_by_health = {h: 0 for h in db.HEALTH_LEVELS}
    for a in accounts:
        counts_by_health[a["health"]] = counts_by_health.get(a["health"], 0) + 1

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total accounts", len(accounts))
    c2.metric("Healthy", counts_by_health.get("Healthy", 0))
    c3.metric("Attention", counts_by_health.get("Attention", 0))
    c4.metric("At Risk", counts_by_health.get("At Risk", 0))
    c5.metric("Pending Slack syncs", len(db.list_pending_slack_syncs()))

    pending_import = db.get_salesforce_import_request()
    if pending_import:
        st.info(f'Salesforce import requested at {pending_import} — ask Claude to "import my Salesforce accounts" to complete it.')
        if st.button("Cancel Salesforce import request"):
            db.clear_salesforce_import_request()
            st.rerun()
    elif st.button("🔔 Request Salesforce import (all accounts where I'm SE)"):
        db.request_salesforce_import()
        st.success('Requested — ask Claude to "import my Salesforce accounts."')
        st.rerun()

    render_pipeline_tables(accounts)

    st.subheader("Upcoming this week")
    upcoming = []
    for a in accounts:
        d = days_until(a["next_call_date"])
        if d is not None and 0 <= d <= 7:
            upcoming.append((d, a))
        for row in db.list_children("deliverables", a["id"]):
            dd = days_until(row["due_date"])
            if dd is not None and 0 <= dd <= 7 and row["status"] != "Done":
                upcoming.append((dd, a, row["description"]))
    upcoming.sort(key=lambda x: x[0])
    if not upcoming:
        st.caption("Nothing due in the next 7 days.")
    for item in upcoming:
        if len(item) == 2:
            d, a = item
            st.markdown(f"- **{a['name']}** — next call in {d}d ({a['next_call_date']} {a['next_call_time'] or ''})")
        else:
            d, a, desc = item
            st.markdown(f"- **{a['name']}** — deliverable due in {d}d: {desc}")

    st.subheader("Accounts")
    if not accounts:
        st.info("No accounts yet — add one from the sidebar.")
        return

    f1, f2, f3, f4 = st.columns(4)
    sort_choice = f1.selectbox("Sort by", ["Name", "Health", "Next call date"])
    quarter_options = sorted({quarter_label(a["close_date"]) for a in accounts if a["close_date"]})
    stage_options = sorted({a["stage"] for a in accounts if a["stage"]})
    ae_options = sorted({a["ae_assigned"] for a in accounts if a["ae_assigned"]})
    quarter_filter = f2.multiselect("Quarter Close", quarter_options)
    stage_filter = f3.multiselect("Stage", stage_options)
    ae_filter = f4.multiselect("AE", ae_options)

    if quarter_filter:
        accounts = [a for a in accounts if quarter_label(a["close_date"]) in quarter_filter]
    if stage_filter:
        accounts = [a for a in accounts if a["stage"] in stage_filter]
    if ae_filter:
        accounts = [a for a in accounts if a["ae_assigned"] in ae_filter]

    if sort_choice == "Health":
        order = {"At Risk": 0, "Attention": 1, "Healthy": 2}
        accounts = sorted(accounts, key=lambda a: order.get(a["health"], 3))
    elif sort_choice == "Next call date":
        accounts = sorted(accounts, key=lambda a: a["next_call_date"] or "9999-99-99")

    if not accounts:
        st.caption("No accounts match these filters.")

    for a in accounts:
        counts = db.open_counts(a["id"])
        dot = HEALTH_COLOR.get(a["health"], "#8180AC")
        with st.container():
            st.markdown('<div class="se-card">', unsafe_allow_html=True)
            cols = st.columns([2.6, 1.4, 1.6, 1.6, 2, 2, 1])
            cols[0].markdown(
                f"<span class='se-dot' style='background:{dot}'></span>"
                f"<span class='se-title'>{a['name']}</span><br>"
                f"<span class='se-muted'>AE: {a['ae_assigned'] or '—'}</span>",
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f"<span class='se-muted'>Stage</span><br>{a['stage'] or '—'}",
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                f"<span class='se-muted'>Last call</span><br>{a['last_call_date'] or '—'}",
                unsafe_allow_html=True,
            )
            cols[3].markdown(
                f"<span class='se-muted'>Next call</span><br>{a['next_call_date'] or '—'} {a['next_call_time'] or ''}",
                unsafe_allow_html=True,
            )
            cols[4].markdown(
                f"<span class='se-muted'>Open items</span><br>"
                f"{counts['deliverables']} deliverables · {counts['tasks']} tasks · {counts['blockers']} blockers",
                unsafe_allow_html=True,
            )
            cols[5].markdown(
                f"<span class='se-muted'>Status</span><br>{(a['status_summary'] or '—')[:80]}",
                unsafe_allow_html=True,
            )
            cols[6].button("Open →", key=f"open_{a['id']}", on_click=goto, args=("Account", a["id"]))
            st.markdown("</div>", unsafe_allow_html=True)


def render_pipeline_tables(accounts):
    st.subheader("Pipeline overview")
    if not accounts:
        st.caption("No accounts yet.")
        return

    by_stage = {}
    by_quarter = {}
    for a in accounts:
        stage = a["stage"] or "—"
        row = by_stage.setdefault(stage, {"Accounts": 0, "ARR": 0.0})
        row["Accounts"] += 1
        row["ARR"] += parse_arr(a["arr"])

        quarter = quarter_label(a["close_date"]) or "—"
        row = by_quarter.setdefault(quarter, {"Accounts": 0, "ARR": 0.0})
        row["Accounts"] += 1
        row["ARR"] += parse_arr(a["arr"])

    stage_df = pd.DataFrame(
        [{"Stage": k, "Accounts": v["Accounts"], "Total ARR": f"${v['ARR']:,.0f}"} for k, v in by_stage.items()]
    ).sort_values("Stage")
    quarter_df = pd.DataFrame(
        [{"Quarter Close": k, "Accounts": v["Accounts"], "Total ARR": f"${v['ARR']:,.0f}"} for k, v in by_quarter.items()]
    ).sort_values("Quarter Close")

    t1, t2 = st.columns(2)
    with t1:
        st.caption("By Stage")
        st.dataframe(stage_df, use_container_width=True, hide_index=True)
    with t2:
        st.caption("By Quarter Close")
        st.dataframe(quarter_df, use_container_width=True, hide_index=True)


# ------------------------------------------------------------- add account --
def render_add_account():
    st.title("Add Account")
    with st.form("add_account_form"):
        name = st.text_input("Account name")
        ae = st.text_input("AE assigned")
        submitted = st.form_submit_button("Create account")
        if submitted and name.strip():
            new_id = db.create_account(name.strip(), ae.strip())
            goto("Account", new_id)
            st.rerun()


# ------------------------------------------------------------ account detail --
def render_account():
    acc = db.get_account(st.session_state.selected_account)
    if acc is None:
        st.warning("Account not found.")
        return

    edit_key = f"editing_{acc['id']}"
    st.session_state.setdefault(edit_key, False)

    top = st.columns([6, 1.4, 1])
    top[0].title(acc["name"])
    if not st.session_state[edit_key]:
        if top[1].button("✏️ Edit details"):
            st.session_state[edit_key] = True
            st.rerun()
    if top[2].button("Delete account"):
        db.delete_account(acc["id"])
        goto("Dashboard")
        st.rerun()

    if st.session_state[edit_key]:
        render_account_edit_form(acc, edit_key)
    else:
        render_account_report(acc)

    render_sync_request(
        acc, kind="slack", requested_at_field="slack_sync_requested_at",
        request_fn=db.request_slack_sync, clear_fn=db.clear_slack_sync_request,
        label="Request Claude Slack sync", verb="run pending Slack syncs",
        guard=(not acc["slack_channel_id"], "Set a Slack Channel ID on this account first."),
    )
    render_sync_request(
        acc, kind="salesforce", requested_at_field="salesforce_sync_requested_at",
        request_fn=db.request_salesforce_sync, clear_fn=db.clear_salesforce_sync_request,
        label="Request Salesforce sync (Stage/ARR)", verb="run pending Salesforce syncs",
    )

    st.divider()
    st.subheader("Deliverables & Tasks")
    render_work_items(acc["id"])

    st.divider()
    st.subheader("Timeline")
    render_timeline(acc["id"])
    render_add_update(acc["id"])

    st.divider()
    tabs = st.tabs(["Blockers", "Stakeholders", "Full History"])
    with tabs[0]:
        render_child_section("blockers", acc["id"], ["description", "link", "status"], statuses=["Open", "Resolved"])
    with tabs[1]:
        render_child_section("stakeholders", acc["id"], ["name", "role", "email", "notes"])
    with tabs[2]:
        history = db.list_history(acc["id"])
        if not history:
            st.caption("No history yet — saved changes will show up here.")
        for h in history:
            with st.container():
                st.markdown(
                    f"**{h['changed_at']}** · _{h['source']}_  \n"
                    f"Status: {h['status_summary'] or '—'}  \n"
                    f"Last call: {h['last_call_date'] or '—'} — {h['last_call_summary'] or '—'}  \n"
                    f"Next call: {h['next_call_date'] or '—'} {h['next_call_time'] or ''}"
                )
                st.divider()


def render_account_report(acc):
    """Read-only, report-style view of the account header — static until
    'Edit details' is pressed."""
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("AE", acc["ae_assigned"] or "—")
    c2.metric("SE", acc["se_assigned"] or "—")
    c3.metric("Stage", acc["stage"] or "—")
    c4.metric("ARR", acc["arr"] or "—")
    c5.metric("Health", acc["health"])
    if acc["close_date"]:
        st.caption(f"Close date: {acc['close_date']} ({quarter_label(acc['close_date'])})")

    c6, c7 = st.columns(2)
    with c6:
        st.markdown(f"**Last call** — {acc['last_call_date'] or '—'}")
        st.caption(acc["last_call_summary"] or "—")
    with c7:
        st.markdown(f"**Next call** — {acc['next_call_date'] or '—'} {acc['next_call_time'] or ''}")

    st.markdown("**Where we stand today**")
    st.write(acc["status_summary"] or "—")

    links = [(l, u) for l, u in [("Grafana", acc["grafana_url"]), ("Salesforce", acc["salesforce_url"]), ("Slack", acc["slack_url"])] if u]
    if links:
        st.markdown(" · ".join(f"[{l}]({u})" for l, u in links))
    if acc["slack_channel_id"]:
        st.caption(f"Slack channel ID: {acc['slack_channel_id']}")


def render_account_edit_form(acc, edit_key):
    with st.form("account_meta_form"):
        c1, c2, c3 = st.columns(3)
        ae = c1.text_input("AE assigned", value=acc["ae_assigned"] or "")
        se = c2.text_input("SE assigned", value=acc["se_assigned"] or "")
        health = c3.selectbox("Health", db.HEALTH_LEVELS, index=db.HEALTH_LEVELS.index(acc["health"]) if acc["health"] in db.HEALTH_LEVELS else 0)

        c4, c5, c4b = st.columns(3)
        stage = c4.text_input("Stage", value=acc["stage"] or "")
        arr = c5.text_input("ARR", value=acc["arr"] or "")
        close_date = c4b.text_input("Close Date (YYYY-MM-DD)", value=acc["close_date"] or "")

        c6, c7 = st.columns(2)
        last_call_date = c6.text_input("Last call date (YYYY-MM-DD)", value=acc["last_call_date"] or "")
        last_call_summary = c7.text_area("Last call summary", value=acc["last_call_summary"] or "", height=80)

        c8, c9 = st.columns(2)
        next_call_date = c8.text_input("Next call date (YYYY-MM-DD)", value=acc["next_call_date"] or "")
        next_call_time = c9.text_input("Next call time", value=acc["next_call_time"] or "")

        status_summary = st.text_area("Where we stand today (update daily)", value=acc["status_summary"] or "", height=100)

        st.caption("Quick links")
        l1, l2, l3 = st.columns(3)
        grafana_url = l1.text_input("Grafana URL", value=acc["grafana_url"] or "")
        salesforce_url = l2.text_input("Salesforce URL", value=acc["salesforce_url"] or "")
        slack_url = l3.text_input("Slack URL", value=acc["slack_url"] or "")
        slack_channel_id = st.text_input("Slack Channel ID (for Claude sync, e.g. C0123ABCDEF)", value=acc["slack_channel_id"] or "")

        save_col, cancel_col = st.columns([1, 1])
        saved = save_col.form_submit_button("Save")
        cancelled = cancel_col.form_submit_button("Cancel")

        if saved:
            db.update_account(
                acc["id"], ae_assigned=ae, se_assigned=se, stage=stage, arr=arr, close_date=close_date, health=health,
                last_call_date=last_call_date, last_call_summary=last_call_summary,
                next_call_date=next_call_date, next_call_time=next_call_time, status_summary=status_summary,
                grafana_url=grafana_url, salesforce_url=salesforce_url, slack_url=slack_url,
                slack_channel_id=slack_channel_id,
            )
            db.log_history(
                acc["id"], source="manual", status_summary=status_summary, last_call_date=last_call_date,
                last_call_summary=last_call_summary, next_call_date=next_call_date, next_call_time=next_call_time,
            )
            st.session_state[edit_key] = False
            st.success("Saved.")
            st.rerun()
        if cancelled:
            st.session_state[edit_key] = False
            st.rerun()


def render_sync_request(acc, kind, requested_at_field, request_fn, clear_fn, label, verb, guard=None):
    requested_at = acc[requested_at_field]
    if requested_at:
        st.info(f'{kind.capitalize()} sync requested at {requested_at} — ask Claude, in a chat session, to "{verb}" to complete it.')
        if st.button(f"Cancel {kind} sync request", key=f"cancel_{kind}_{acc['id']}"):
            clear_fn(acc["id"])
            st.rerun()
    elif st.button(f"🔔 {label}", key=f"req_{kind}_{acc['id']}"):
        if guard and guard[0]:
            st.error(guard[1])
        else:
            request_fn(acc["id"])
            st.success(f'Requested — ask Claude, in a chat session, to "{verb}."')
            st.rerun()


def render_work_items(account_id):
    """Deliverables and Tasks merged into one table (Type column), with an
    inline, immediately-applied status dropdown per row."""
    deliverables = [("Deliverable", "deliverables", r) for r in db.list_children("deliverables", account_id)]
    tasks = [("Task", "tasks", r) for r in db.list_children("tasks", account_id)]
    rows = sorted(deliverables + tasks, key=lambda t: t[2]["due_date"] or "9999-99-99")

    if not rows:
        st.caption("No deliverables or tasks yet.")
    else:
        header = st.columns([1.2, 3.3, 1.3, 1.4, 0.8])
        for h, label in zip(header, ["Type", "Description", "Due Date", "Status", ""]):
            h.caption(label)
        for item_type, table, row in rows:
            cols = st.columns([1.2, 3.3, 1.3, 1.4, 0.8])
            cols[0].write(item_type)
            cols[1].write(row["description"])
            cols[2].write(row["due_date"] or "—")
            statuses = ["Open", "Done"]
            current = row["status"] if row["status"] in statuses else "Open"
            new_status = cols[3].selectbox(
                "Status", statuses, index=statuses.index(current),
                key=f"status_{table}_{row['id']}", label_visibility="collapsed",
            )
            if new_status != row["status"]:
                if new_status == "Done":
                    db.delete_child(table, row["id"])
                    db.add_child(
                        "notes", account_id, note_date=dt.date.today().isoformat(),
                        summary=f"{item_type} complete: {row['description']}",
                    )
                else:
                    db.update_child(table, row["id"], status=new_status)
                st.rerun()
            if cols[4].button("Delete", key=f"del_{table}_{row['id']}"):
                db.delete_child(table, row["id"])
                st.rerun()

    with st.form(f"add_workitem_{account_id}", clear_on_submit=True):
        st.caption("Add deliverable/task")
        c1, c2, c3, c4 = st.columns([1.2, 3.3, 1.3, 1.4])
        item_type = c1.selectbox("Type", ["Deliverable", "Task"], key=f"new_wi_type_{account_id}")
        description = c2.text_input("Description", key=f"new_wi_desc_{account_id}")
        due_date = c3.text_input("Due Date", key=f"new_wi_due_{account_id}")
        status = c4.selectbox("Status", ["Open", "Done"], key=f"new_wi_status_{account_id}")
        if st.form_submit_button("Add"):
            if description.strip():
                table = "deliverables" if item_type == "Deliverable" else "tasks"
                db.add_child(table, account_id, description=description.strip(), due_date=due_date.strip(), status=status)
                st.rerun()


def render_timeline(account_id):
    """Most-recent-first log of updates — manual notes and anything Claude
    added (e.g. a completed Slack/Salesforce sync)."""
    notes = list(reversed(db.list_children("notes", account_id, order_by="created_at")))
    if not notes:
        st.caption("No updates yet.")
    for n in notes:
        with st.container():
            date_suffix = f" ({n['note_date']})" if n["note_date"] else ""
            st.markdown(f"**{n['created_at']}**{date_suffix}  \n{n['summary']}")
            st.divider()


def render_add_update(account_id):
    with st.expander("+ Add update"):
        with st.form(f"add_update_{account_id}", clear_on_submit=True):
            note_date = st.text_input("Date (YYYY-MM-DD)", value=dt.date.today().isoformat(), key=f"update_date_{account_id}")
            summary = st.text_area("Update", key=f"update_text_{account_id}")
            if st.form_submit_button("Add update"):
                if summary.strip():
                    db.add_child("notes", account_id, note_date=note_date.strip(), summary=summary.strip())
                    st.rerun()


def render_child_section(table, account_id, fields, statuses=None):
    rows = db.list_children(table, account_id)
    for row in rows:
        cols = st.columns(len(fields) + 1)
        for i, f in enumerate(fields):
            cols[i].caption(f.replace("_", " ").title())
            cols[i].write(row[f] or "—")
        if cols[-1].button("Delete", key=f"del_{table}_{row['id']}"):
            db.delete_child(table, row["id"])
            st.rerun()

    with st.form(f"add_{table}_{account_id}", clear_on_submit=True):
        st.caption(f"Add {table[:-1] if table.endswith('s') else table}")
        vals = {}
        cols = st.columns(len(fields))
        for i, f in enumerate(fields):
            if f == "status" and statuses:
                vals[f] = cols[i].selectbox(f.title(), statuses, key=f"new_{table}_{f}_{account_id}")
            else:
                vals[f] = cols[i].text_input(f.replace("_", " ").title(), key=f"new_{table}_{f}_{account_id}")
        if st.form_submit_button("Add"):
            if any(v.strip() for v in vals.values() if isinstance(v, str)):
                db.add_child(table, account_id, **vals)
                st.rerun()


# --------------------------------------------------------------------- root --
page = st.session_state.page
if page == "Dashboard":
    render_dashboard()
elif page == "Add Account":
    render_add_account()
elif page == "Account":
    render_account()
