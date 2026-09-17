"""Write a completed Salesforce sync (Stage/ARR/AE/SE) into the DB and clear
the pending request.

Not run by the app itself. A Claude session with a Salesforce connector
reads pending requests (db.list_pending_salesforce_syncs()), looks up the
account/opportunity itself (Owner.Name = AE, Sales_Engineer__r.Name = SE),
then runs this to persist the result:

  echo '{"stage": "POC", "arr": "$300,000", "ae_assigned": "Andrew Broaddus",
         "se_assigned": "Nickolas Gann"}' \
    | python apply_salesforce_sync.py <account_id>
"""
import argparse
import datetime as dt
import json
import sys

import db

UPDATABLE_FIELDS = ("stage", "arr", "salesforce_url", "ae_assigned", "se_assigned", "close_date")


def apply(account_id, result):
    acc = db.get_account(account_id)
    if acc is None:
        sys.exit(f"No account with id {account_id}")

    fields = {k: v for k, v in result.items() if k in UPDATABLE_FIELDS and v}
    if fields:
        db.update_account(account_id, **fields)
    db.add_child(
        "notes", account_id, note_date=dt.date.today().isoformat(),
        summary=(
            f"Synced from Salesforce via Claude: stage={result.get('stage', '—')}, "
            f"ARR={result.get('arr', '—')}, AE={result.get('ae_assigned', '—')}, "
            f"SE={result.get('se_assigned', '—')}"
        ),
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
