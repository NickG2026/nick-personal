"""SE Account Manager — personal daily-driver for SE account status.

Run locally:  streamlit run app.py
Or via the provided Dockerfile.

Everything lives in three files: app.py (UI), db.py (SQLite), data/ (the DB
file). Add a field: add a column in db.py's SCHEMA + a widget below.
"""
import datetime as dt

import streamlit as st

import db
import slack_sync

st.set_page_config(page_title="SE Account Manager", layout="wide", page_icon="🗂️")
db.init_db()

# ---------------------------------------------------------------- styling --
HEALTH_COLOR = {"Healthy": "#1DDB8C", "Attention": "#5050EE", "At Risk": "#FF4689"}

st.markdown(
    """
    <style>
      html, body, [class*="css"]  { font-family: "Open Sans", system-ui, sans-serif; }
      #MainMenu, footer, header {visibility: hidden;}
      .block-container {padding-top: 1.5rem; max-width: 1400px;}
      .se-card {
        background: #100A2C; border: 1px solid #1B1A6A; border-radius: 10px;
        padding: 16px 18px; margin-bottom: 12px;
      }
      .se-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; }
      .se-muted { color:#8180AC; font-size:0.85rem; }
      .se-title { font-size:1.05rem; font-weight:600; color:#F4F4FF; }
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


def days_until(date_str):
    if not date_str:
        return None
    try:
        d = dt.date.fromisoformat(date_str)
        return (d - dt.date.today()).days
    except ValueError:
        return None


# ---------------------------------------------------------------- dashboard --
def render_dashboard():
    accounts = db.list_accounts()
    st.title("Dashboard")

    counts_by_health = {h: 0 for h in db.HEALTH_LEVELS}
    for a in accounts:
        counts_by_health[a["health"]] = counts_by_health.get(a["health"], 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total accounts", len(accounts))
    c2.metric("Healthy", counts_by_health.get("Healthy", 0))
    c3.metric("Attention", counts_by_health.get("Attention", 0))
    c4.metric("At Risk", counts_by_health.get("At Risk", 0))

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

    sort_choice = st.selectbox("Sort by", ["Name", "Health", "Next call date"], label_visibility="collapsed")
    if sort_choice == "Health":
        order = {"At Risk": 0, "Attention": 1, "Healthy": 2}
        accounts = sorted(accounts, key=lambda a: order.get(a["health"], 3))
    elif sort_choice == "Next call date":
        accounts = sorted(accounts, key=lambda a: a["next_call_date"] or "9999-99-99")

    for a in accounts:
        counts = db.open_counts(a["id"])
        dot = HEALTH_COLOR.get(a["health"], "#8180AC")
        with st.container():
            st.markdown('<div class="se-card">', unsafe_allow_html=True)
            cols = st.columns([3, 2, 2, 2, 2, 1])
            cols[0].markdown(
                f"<span class='se-dot' style='background:{dot}'></span>"
                f"<span class='se-title'>{a['name']}</span><br>"
                f"<span class='se-muted'>AE: {a['ae_assigned'] or '—'}</span>",
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f"<span class='se-muted'>Last call</span><br>{a['last_call_date'] or '—'}",
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                f"<span class='se-muted'>Next call</span><br>{a['next_call_date'] or '—'} {a['next_call_time'] or ''}",
                unsafe_allow_html=True,
            )
            cols[3].markdown(
                f"<span class='se-muted'>Open items</span><br>"
                f"{counts['deliverables']} deliverables · {counts['tasks']} tasks · {counts['blockers']} blockers",
                unsafe_allow_html=True,
            )
            cols[4].markdown(
                f"<span class='se-muted'>Status</span><br>{(a['status_summary'] or '—')[:80]}",
                unsafe_allow_html=True,
            )
            cols[5].button("Open →", key=f"open_{a['id']}", on_click=goto, args=("Account", a["id"]))
            st.markdown("</div>", unsafe_allow_html=True)


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

    top = st.columns([6, 1])
    top[0].title(acc["name"])
    if top[1].button("Delete account"):
        db.delete_account(acc["id"])
        goto("Dashboard")
        st.rerun()

    with st.form("account_meta_form"):
        c1, c2, c3 = st.columns(3)
        ae = c1.text_input("AE assigned", value=acc["ae_assigned"] or "")
        health = c2.selectbox("Health", db.HEALTH_LEVELS, index=db.HEALTH_LEVELS.index(acc["health"]) if acc["health"] in db.HEALTH_LEVELS else 0)
        c3.write("")

        c4, c5 = st.columns(2)
        last_call_date = c4.text_input("Last call date (YYYY-MM-DD)", value=acc["last_call_date"] or "")
        last_call_summary = c5.text_area("Last call summary", value=acc["last_call_summary"] or "", height=80)

        c6, c7 = st.columns(2)
        next_call_date = c6.text_input("Next call date (YYYY-MM-DD)", value=acc["next_call_date"] or "")
        next_call_time = c7.text_input("Next call time", value=acc["next_call_time"] or "")

        status_summary = st.text_area("Where we stand today (update daily)", value=acc["status_summary"] or "", height=100)

        st.caption("Quick links")
        l1, l2, l3 = st.columns(3)
        grafana_url = l1.text_input("Grafana URL", value=acc["grafana_url"] or "")
        salesforce_url = l2.text_input("Salesforce URL", value=acc["salesforce_url"] or "")
        slack_url = l3.text_input("Slack URL", value=acc["slack_url"] or "")
        slack_channel_id = st.text_input("Slack Channel ID (for Claude sync, e.g. C0123ABCDEF)", value=acc["slack_channel_id"] or "")

        if st.form_submit_button("Save"):
            db.update_account(
                acc["id"], ae_assigned=ae, health=health, last_call_date=last_call_date,
                last_call_summary=last_call_summary, next_call_date=next_call_date,
                next_call_time=next_call_time, status_summary=status_summary,
                grafana_url=grafana_url, salesforce_url=salesforce_url, slack_url=slack_url,
                slack_channel_id=slack_channel_id,
            )
            st.success("Saved.")
            st.rerun()

    links = [(l, u) for l, u in [("Grafana", acc["grafana_url"]), ("Salesforce", acc["salesforce_url"]), ("Slack", acc["slack_url"])] if u]
    if links:
        st.markdown(" · ".join(f"[{l}]({u})" for l, u in links))

    if st.button("🔄 Sync status from Slack + Claude"):
        try:
            with st.spinner("Reading Slack channel and asking Claude..."):
                result = slack_sync.sync_account_from_slack(acc)
            db.update_account(acc["id"], status_summary=result["status_summary"])
            for desc in result.get("new_deliverables", []):
                db.add_child("deliverables", acc["id"], description=desc, status="Open")
            for desc in result.get("new_blockers", []):
                db.add_child("blockers", acc["id"], description=desc, status="Open")
            db.add_child(
                "notes", acc["id"], note_date=dt.date.today().isoformat(),
                summary=f"Synced from Slack via Claude: {result['status_summary'][:300]}",
            )
            st.success("Synced from Slack.")
            st.rerun()
        except Exception as e:
            st.error(f"Sync failed: {e}")

    st.divider()
    tabs = st.tabs(["Deliverables", "Tasks", "Meeting Notes", "Blockers", "Stakeholders"])

    with tabs[0]:
        render_child_section("deliverables", acc["id"], ["description", "due_date", "status"], statuses=["Open", "Done"])
    with tabs[1]:
        render_child_section("tasks", acc["id"], ["description", "due_date", "status"], statuses=["Open", "Done"])
    with tabs[2]:
        render_child_section("notes", acc["id"], ["note_date", "summary"])
    with tabs[3]:
        render_child_section("blockers", acc["id"], ["description", "link", "status"], statuses=["Open", "Resolved"])
    with tabs[4]:
        render_child_section("stakeholders", acc["id"], ["name", "role", "email", "notes"])


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
