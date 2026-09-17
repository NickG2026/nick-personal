"""Write a completed Slack sync into the DB and clear the pending request.

Not run by the app itself. A Claude session with a Slack connector reads
pending requests (db.list_pending_slack_syncs()), fetches + summarizes each
account's channel itself, then runs this to persist the result:

  echo '{"status_summary": "...", "new_deliverables": ["..."], "new_blockers": []}' \
    | python apply_slack_sync.py <account_id>
"""
import argparse
import datetime as dt
import json
import sys

import db


def apply(account_id, result):
    acc = db.get_account(account_id)
    if acc is None:
        sys.exit(f"No account with id {account_id}")

    db.update_account(account_id, status_summary=result["status_summary"])
    for desc in result.get("new_deliverables", []):
        db.add_child("deliverables", account_id, description=desc, status="Open")
    for desc in result.get("new_blockers", []):
        db.add_child("blockers", account_id, description=desc, status="Open")
    db.add_child(
        "notes", account_id, note_date=dt.date.today().isoformat(),
        summary=f"Synced from Slack via Claude: {result['status_summary'][:300]}",
    )
    db.log_history(
        account_id, source="slack_sync", status_summary=result["status_summary"],
        last_call_date=acc["last_call_date"], last_call_summary=acc["last_call_summary"],
        next_call_date=acc["next_call_date"], next_call_time=acc["next_call_time"],
    )
    db.clear_slack_sync_request(account_id)
    print(f"Updated account {account_id} ({acc['name']}) and cleared the pending sync request.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", type=int)
    parser.add_argument("--json-file", help="Path to result JSON; reads stdin if omitted.")
    args = parser.parse_args()

    raw = open(args.json_file).read() if args.json_file else sys.stdin.read()
    apply(args.account_id, json.loads(raw))
