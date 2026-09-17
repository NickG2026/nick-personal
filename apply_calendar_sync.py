"""Write this week's synced Google Calendar customer meetings into the DB
and clear the pending request.

Not run by the app. The Dashboard's "Request Calendar sync" button just
timestamps a request (db.request_calendar_sync()). When asked to "sync my
calendar," Claude queries its own Google Calendar connector for this week's
events, matches each one to a tracked account by name where possible, and
pipes a JSON array in:

  echo '[{"title": "Candescent | Proposal Review", "start_time": "2026-09-18T14:00:00",
          "end_time": "2026-09-18T15:00:00", "account_name": "Candescent",
          "link": "https://meet.google.com/..."}]' \
    | python apply_calendar_sync.py

Replaces whatever was previously synced for the current week (so re-running
doesn't duplicate), then clears the pending request.
"""
import json
import sys

import db


def apply(records):
    db.clear_calendar_events_this_week()
    for rec in records:
        name = rec.get("account_name")
        account_id = None
        if name:
            acc = db.find_account_by_name(name)
            if acc:
                account_id = acc["id"]
        db.add_calendar_event(
            title=rec["title"], start_time=rec["start_time"], end_time=rec.get("end_time"),
            account_name=name, account_id=account_id, link=rec.get("link"),
        )
    db.clear_calendar_sync_request()
    print(f"Synced {len(records)} calendar event(s) for this week.")


if __name__ == "__main__":
    db.init_db()
    apply(json.loads(sys.stdin.read()))
