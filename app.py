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
import streamlit.components.v1 as components
from st_aggrid import AgGrid, GridOptionsBuilder, StAggridTheme

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


def quarter_offset(quarter_str, offset):
    """'2026-Q3' + 1 -> '2026-Q4'; handles year rollover in either direction."""
    year_str, q_str = quarter_str.split("-Q")
    year, q = int(year_str), int(q_str) + offset
    while q > 4:
        q -= 4
        year += 1
    while q < 1:
        q += 4
        year -= 1
    return f"{year}-Q{q}"


# ------------------------------------------------------------------ sidebar --
with st.sidebar:
    st.markdown("### 🗂️ SE Account Manager")
    st.button("Dashboard", use_container_width=True, on_click=goto, args=("Dashboard",))
    st.button("＋ Add Account", use_container_width=True, on_click=goto, args=("Add Account",))
    st.divider()
    st.caption("Accounts by Quarter Close")

    _accounts = db.list_accounts()
    _current_q = quarter_label(dt.date.today().isoformat())
    _next_q = quarter_offset(_current_q, 1)

    _buckets = {}
    for _acc in _accounts:
        _q = quarter_label(_acc["close_date"])
        if _q is None:
            _key = "No Close Date"
        elif _q == _current_q:
            _key = "Closing This Quarter"
        elif _q == _next_q:
            _key = "Closing Next Quarter"
        else:
            _key = f"Closing in {_q}"
        _buckets.setdefault(_key, []).append(_acc)

    _order = ["Closing This Quarter", "Closing Next Quarter"]
    _order += sorted(k for k in _buckets if k not in _order and k != "No Close Date")
    if "No Close Date" in _buckets:
        _order.append("No Close Date")

    for _key in _order:
        _group = sorted(_buckets[_key], key=lambda a: a["name"])
        with st.expander(f"{_key} ({len(_group)})", expanded=(_key == "Closing This Quarter")):
            for _acc in _group:
                _dot = HEALTH_COLOR.get(_acc["health"], "#8180AC")
                if st.button(f"● {_acc['name']}", key=f"nav_{_acc['id']}", use_container_width=True):
                    goto("Account", _acc["id"])
    st.divider()
    st.caption(f"v{APP_VERSION}")


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
    total_arr = sum(parse_arr(a["arr"]) for a in accounts)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total accounts", len(accounts))
    c2.metric("Healthy", counts_by_health.get("Healthy", 0))
    c3.metric("Customer meetings this week", len(db.list_calendar_events_this_week()))
    c4.metric("At Risk", counts_by_health.get("At Risk", 0))
    c5.metric("Total ARR", f"${total_arr:,.0f}")

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

    render_calendar_card()
    render_pipeline_table(accounts)

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


def render_pipeline_table(accounts):
    st.subheader("Pipeline overview")
    with st.container(border=True):
        if not accounts:
            st.caption("No accounts yet.")
            return

        rows = [
            {
                "Name": a["name"],
                "Stage": a["stage"] or "—",
                "Quarter Close": quarter_label(a["close_date"]) or "—",
                "ARR": parse_arr(a["arr"]),
                "AE": a["ae_assigned"] or "—",
                "SE": a["se_assigned"] or "—",
                "Health": a["health"],
            }
            for a in accounts
        ]
        df = pd.DataFrame(rows)

        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_default_column(
            filter=True, sortable=True, resizable=True,
            filterParams={"buttons": ["apply", "reset"], "closeOnApply": True},
        )
        gb.configure_column("ARR", type=["numericColumn"], valueFormatter="'$' + value.toLocaleString()")

        grid_theme = StAggridTheme(base="alpine").withParams(
            backgroundColor="#100A2C",
            foregroundColor="#F4F4FF",
            headerBackgroundColor="#1B1A6A",
            headerTextColor="#F4F4FF",
            oddRowBackgroundColor="#160F3D",
            rowHoverColor="#241660",
            selectedRowBackgroundColor="#2A1B75",
            accentColor="#5050EE",
            borderColor="#1B1A6A",
            fontSize=15,
            headerFontSize=15,
        )

        AgGrid(
            df, gridOptions=gb.build(), height=380, fit_columns_on_grid_load=True,
            theme=grid_theme, allow_unsafe_jscode=True,
        )


def render_calendar_card():
    with st.container(border=True):
        h1, h2 = st.columns([5, 1.6])
        h1.subheader("Customer Meetings — Next 4 Weeks")

        pending = db.get_calendar_sync_request()
        if pending:
            st.info(f'Calendar sync requested at {pending} — ask Claude to "sync my calendar" to complete it.')
            if st.button("Cancel calendar sync request"):
                db.clear_calendar_sync_request()
                st.rerun()
        elif h2.button("🔔 Sync calendar"):
            db.request_calendar_sync()
            st.success('Requested — ask Claude to "sync my calendar."')
            st.rerun()

        events = db.list_calendar_events_four_weeks()
        html = _build_calendar_html(events, num_weeks=4)
        components.html(html, height=650, scrolling=True)


def _fmt_hour_label(hour):
    period = "AM" if hour % 24 < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    return f"{h12} {period}"


def _fmt_clock(t):
    period = "AM" if t.hour < 12 else "PM"
    h12 = t.hour % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{t.minute:02d} {period}"


def _build_calendar_html(events, num_weeks=4, day_start_hour=8, day_end_hour=19):
    """Google-Calendar-style week grid: hour rows down the side, Mon-Fri
    columns, events as time-positioned blocks — stacked for `num_weeks`."""
    row_h = 44  # px per hour
    gutter_w = 50
    total_hours = day_end_hour - day_start_hour
    grid_h = total_hours * row_h

    by_date = {}
    for e in events:
        by_date.setdefault(e["start_time"][:10], []).append(e)

    monday = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    today = dt.date.today()
    now = dt.datetime.now()
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    gridlines_bg = (
        f"repeating-linear-gradient(to bottom, #1B1A6A 0, #1B1A6A 1px, transparent 1px, transparent {row_h}px)"
    )

    weeks_html = []
    for week in range(num_weeks):
        week_monday = monday + dt.timedelta(days=7 * week)

        day_headers = []
        for i in range(5):
            day = week_monday + dt.timedelta(days=i)
            if day == today:
                date_badge = f"<span style='background:#E0433C;color:#fff;border-radius:50%;padding:1px 7px;'>{day.day}</span>"
            else:
                date_badge = f"<span style='color:#F4F4FF;'>{day.day}</span>"
            day_headers.append(
                f"<div style='flex:1;text-align:center;font-size:12.5px;color:#8180AC;padding-bottom:4px;'>"
                f"{weekday_names[i]} {date_badge}</div>"
            )
        header_html = f"<div style='display:flex;'><div style='width:{gutter_w}px;'></div>{''.join(day_headers)}</div>"

        hour_labels = "".join(
            f"<div style='position:absolute;top:{(h - day_start_hour) * row_h - 7}px;left:0;width:{gutter_w - 8}px;"
            f"text-align:right;font-size:10.5px;color:#8180AC;'>{_fmt_hour_label(h)}</div>"
            for h in range(day_start_hour, day_end_hour + 1)
        )

        day_cols = []
        for i in range(5):
            day = week_monday + dt.timedelta(days=i)
            day_events = by_date.get(day.isoformat(), [])

            parsed = []
            for e in day_events:
                s = dt.datetime.fromisoformat(e["start_time"])
                en = dt.datetime.fromisoformat(e["end_time"]) if e["end_time"] else s + dt.timedelta(hours=1)
                parsed.append({"e": e, "s": s, "en": en})
            parsed.sort(key=lambda p: p["s"])

            lane_end_times = []
            assignments = []
            for p in parsed:
                placed = False
                for lane, end in enumerate(lane_end_times):
                    if p["s"] >= end:
                        lane_end_times[lane] = p["en"]
                        assignments.append((p, lane))
                        placed = True
                        break
                if not placed:
                    lane_end_times.append(p["en"])
                    assignments.append((p, len(lane_end_times) - 1))
            total_lanes = max(1, len(lane_end_times))

            blocks = []
            for p, lane in assignments:
                s_h = max(p["s"].hour + p["s"].minute / 60, day_start_hour)
                en_h = min(max(p["en"].hour + p["en"].minute / 60, s_h + 0.25), day_end_hour)
                top = (s_h - day_start_hour) * row_h
                height = max((en_h - s_h) * row_h, 18)
                lane_w = 100 / total_lanes
                left = lane * lane_w
                tag = f" · {p['e']['account_name']}" if p["e"]["account_name"] else ""
                inner = f"<b>{_fmt_clock(p['s'])}</b> {p['e']['title']}{tag}"
                link = p["e"]["link"]
                content = (
                    f"<a href='{link}' target='_blank' style='color:#F4F4FF;text-decoration:none;'>{inner}</a>"
                    if link else inner
                )
                blocks.append(
                    f"<div style='position:absolute;top:{top}px;height:{height}px;"
                    f"left:calc({left}% + 2px);width:calc({lane_w}% - 4px);"
                    f"background:#2A1B75;border-left:3px solid #5050EE;border-radius:4px;"
                    f"padding:2px 5px;font-size:11px;line-height:1.25;color:#F4F4FF;overflow:hidden;'>{content}</div>"
                )

            now_line = ""
            if day == today and day_start_hour <= now.hour < day_end_hour:
                now_top = (now.hour + now.minute / 60 - day_start_hour) * row_h
                now_line = (
                    f"<div style='position:absolute;top:{now_top}px;left:-4px;width:8px;height:8px;"
                    f"border-radius:50%;background:#E0433C;'></div>"
                    f"<div style='position:absolute;top:{now_top + 3}px;left:0;right:0;height:2px;background:#E0433C;'></div>"
                )

            day_cols.append(
                f"<div style='position:relative;flex:1;border-left:1px solid #1B1A6A;height:{grid_h}px;"
                f"background-image:{gridlines_bg};background-size:100% {row_h}px;background-repeat:repeat-y;'>"
                f"{''.join(blocks)}{now_line}</div>"
            )

        body_html = (
            f"<div style='position:relative;height:{grid_h}px;display:flex;'>"
            f"<div style='position:relative;width:{gutter_w}px;'>{hour_labels}</div>"
            f"{''.join(day_cols)}</div>"
        )

        weeks_html.append(
            f"<div style='margin-bottom:18px;'>"
            f"<div style='font-size:11.5px;color:#8180AC;margin-bottom:4px;'>Week of {week_monday.month}/{week_monday.day}</div>"
            f"{header_html}{body_html}</div>"
        )

    return (
        "<style>body{margin:0;background:#100A2C;}</style>"
        "<div style='font-family:\"Open Sans\",system-ui,sans-serif;background:#100A2C;padding:6px 10px;'>"
        + "".join(weeks_html) + "</div>"
    )


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

    slack_link = (
        f"https://slack.com/app_redirect?channel={acc['slack_channel_id']}" if acc["slack_channel_id"] else acc["slack_url"]
    )
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if acc["salesforce_url"]:
            st.link_button("🔗 Open in Salesforce", acc["salesforce_url"])
    with a2:
        if slack_link:
            st.link_button("💬 Open in Slack", slack_link)
    with a3:
        render_sync_request(
            acc, kind="slack", requested_at_field="slack_sync_requested_at",
            request_fn=db.request_slack_sync, clear_fn=db.clear_slack_sync_request,
            label="Request Claude Slack sync", verb="run pending Slack syncs",
            guard=(not acc["slack_channel_id"], "Set a Slack Channel ID on this account first."),
        )
    with a4:
        render_sync_request(
            acc, kind="salesforce", requested_at_field="salesforce_sync_requested_at",
            request_fn=db.request_salesforce_sync, clear_fn=db.clear_salesforce_sync_request,
            label="Request Salesforce sync (Stage/ARR)", verb="run pending Salesforce syncs",
        )

    st.divider()
    tabs = st.tabs(["Deliverables & Tasks", "Timeline", "Account Stakeholders", "Blockers", "Full History"])
    with tabs[0]:
        h1, h2 = st.columns([5, 1.6])
        h1.subheader("Deliverables & Tasks")
        if h2.button("➕ Add Deliverable/Task", key=f"open_add_workitem_{acc['id']}"):
            render_add_workitem_dialog(acc["id"])
        render_work_items(acc["id"])
    with tabs[1]:
        h1, h2 = st.columns([5, 1.6])
        h1.subheader("Timeline")
        if h2.button("📝 Add update", key=f"open_update_{acc['id']}"):
            render_add_update_dialog(acc["id"])
        render_timeline(acc["id"])
    with tabs[2]:
        render_child_section("stakeholders", acc["id"], ["name", "role", "email", "notes"])
    with tabs[3]:
        render_child_section("blockers", acc["id"], ["description", "link", "status"], statuses=["Open", "Resolved"])
    with tabs[4]:
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
    c1, c2, c3, c4, c5, c6 = st.columns(6, gap="small")
    c1.markdown(f"<span class='se-muted'>AE</span><br>{acc['ae_assigned'] or '—'}", unsafe_allow_html=True)
    c2.markdown(f"<span class='se-muted'>SE</span><br>{acc['se_assigned'] or '—'}", unsafe_allow_html=True)
    c3.markdown(f"<span class='se-muted'>Stage</span><br>{acc['stage'] or '—'}", unsafe_allow_html=True)
    c4.markdown(f"<span class='se-muted'>ARR</span><br>{acc['arr'] or '—'}", unsafe_allow_html=True)
    dot = HEALTH_COLOR.get(acc["health"], "#8180AC")
    c5.markdown(
        f"<span class='se-muted'>Health</span><br>"
        f"<span class='se-dot' style='background:{dot}'></span>{acc['health']}",
        unsafe_allow_html=True,
    )
    c6.markdown(f"<span class='se-muted'>Close Date</span><br>{acc['close_date'] or '—'}", unsafe_allow_html=True)

    st.markdown("**Where we stand today**")
    st.write(acc["status_summary"] or "—")

    if acc["grafana_url"]:
        st.markdown(f"[Grafana]({acc['grafana_url']})")


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
                status_summary=status_summary,
                grafana_url=grafana_url, salesforce_url=salesforce_url, slack_url=slack_url,
                slack_channel_id=slack_channel_id,
            )
            db.log_history(
                acc["id"], source="manual", status_summary=status_summary,
                last_call_date=acc["last_call_date"], last_call_summary=acc["last_call_summary"],
                next_call_date=acc["next_call_date"], next_call_time=acc["next_call_time"],
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


@st.dialog("Add Deliverable/Task")
def render_add_workitem_dialog(account_id):
    item_type = st.selectbox("Type", ["Deliverable", "Task"], key=f"dialog_wi_type_{account_id}")
    description = st.text_input("Description", key=f"dialog_wi_desc_{account_id}")
    due_date = st.text_input("Due Date (YYYY-MM-DD)", key=f"dialog_wi_due_{account_id}")
    status = st.selectbox("Status", ["Open", "Done"], key=f"dialog_wi_status_{account_id}")
    if st.button("Save", key=f"dialog_wi_save_{account_id}"):
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


@st.dialog("Add update")
def render_add_update_dialog(account_id):
    note_date = st.text_input("Date (YYYY-MM-DD)", value=dt.date.today().isoformat(), key=f"update_date_{account_id}")
    summary = st.text_area("Update", key=f"update_text_{account_id}")
    if st.button("Save", key=f"save_update_{account_id}"):
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
