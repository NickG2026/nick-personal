"""Bulk create/update accounts from Salesforce records pulled by Claude.

Not run by the app directly, but the Dashboard has a "Request Salesforce
import" button (db.request_salesforce_import()) that flags this as wanted.
When asked to "import my Salesforce accounts," Claude queries Salesforce
(via its own connector) for opportunities/accounts where the user is listed
as SE, builds a JSON array of records, and pipes it in:

  echo '[{"name": "Acme Corp", "ae_assigned": "...", "se_assigned": "...",
          "stage": "POC", "arr": "$300,000", "salesforce_url": "..."}]' \
    | python import_salesforce_accounts.py

Matches existing accounts by name (case-insensitive); creates new ones for
anything not already tracked. Every record leaves a Timeline note either
way, and this clears the pending import request when done.
"""
import datetime as dt
import json
import sys

import db

UPDATABLE_FIELDS = ("ae_assigned", "se_assigned", "stage", "arr", "close_date", "salesforce_url")


def apply(records):
    created, updated = 0, 0
    for rec in records:
        name = rec["name"].strip()
        if not name:
            continue
        acc = db.find_account_by_name(name)
        fields = {k: rec[k] for k in UPDATABLE_FIELDS if rec.get(k)}

        if acc is None:
            account_id = db.create_account(name, rec.get("ae_assigned", ""))
            created += 1
        else:
            account_id = acc["id"]
            updated += 1

        if fields:
            db.update_account(account_id, **fields)

        db.add_child(
            "notes", account_id, note_date=dt.date.today().isoformat(),
            summary=f"Imported/updated from Salesforce via Claude (Stage: {rec.get('stage', '—')}, "
                    f"ARR: {rec.get('arr', '—')})",
        )

    db.clear_salesforce_import_request()
    print(f"Created {created}, updated {updated} account(s) from Salesforce.")


if __name__ == "__main__":
    db.init_db()
    raw = sys.stdin.read()
    apply(json.loads(raw))
