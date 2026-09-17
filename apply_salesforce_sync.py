"""Write a completed Salesforce sync (Stage/ARR) into the DB and clear the
pending request.

Not run by the app itself. A Claude session with a Salesforce connector
reads pending requests (db.list_pending_salesforce_syncs()), looks up the
account/opportunity itself, then runs this to persist the result:

  echo '{"stage": "POC", "arr": "$300,000"}' \
    | python apply_salesforce_sync.py <account_id>
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

    fields = {k: v for k, v in result.items() if k in ("stage", "arr", "salesforce_url") and v}
    if fields:
        db.update_account(account_id, **fields)
    db.add_child(
        "notes", account_id, note_date=dt.date.today().isoformat(),
        summary=f"Synced from Salesforce via Claude: stage={result.get('stage', '—')}, ARR={result.get('arr', '—')}",
    )
    db.clear_salesforce_sync_request(account_id)
    print(f"Updated account {account_id} ({acc['name']}) and cleared the pending Salesforce sync request.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", type=int)
    parser.add_argument("--json-file", help="Path to result JSON; reads stdin if omitted.")
    args = parser.parse_args()

    raw = open(args.json_file).read() if args.json_file else sys.stdin.read()
    apply(args.account_id, json.loads(raw))
