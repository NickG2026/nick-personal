"""Pull an account's Slack channel activity and have Claude turn it into an
updated status summary + any new deliverables/blockers it spots.

Needs two env vars set wherever the app runs:
  SLACK_BOT_TOKEN     - bot token with channels:history, groups:history,
                        users:read scopes; bot must be invited to the channel
  ANTHROPIC_API_KEY   - Claude API key
"""
import json
import os
from datetime import datetime


def _slack_client():
    from slack_sdk import WebClient

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set.")
    return WebClient(token=token)


def fetch_recent_messages(channel_id, limit=100):
    client = _slack_client()
    resp = client.conversations_history(channel=channel_id, limit=limit)
    messages = resp.get("messages", [])

    user_cache = {}

    def user_name(uid):
        if uid not in user_cache:
            try:
                info = client.users_info(user=uid)
                user_cache[uid] = info["user"].get("real_name") or info["user"].get("name", uid)
            except Exception:
                user_cache[uid] = uid
        return user_cache[uid]

    lines = []
    for m in reversed(messages):  # oldest first
        if m.get("subtype"):  # skip joins/leaves/topic changes/etc
            continue
        text = (m.get("text") or "").strip()
        if not text:
            continue
        ts = datetime.fromtimestamp(float(m["ts"])).strftime("%Y-%m-%d %H:%M")
        lines.append(f"[{ts}] {user_name(m.get('user', 'unknown'))}: {text}")
    return "\n".join(lines)


def summarize_with_claude(account_name, existing_summary, transcript):
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    client = Anthropic(api_key=api_key)

    prompt = f"""You maintain the status summary for the account "{account_name}".

Current status summary:
{existing_summary or "(none yet)"}

Recent Slack channel activity for this account:
{transcript or "(no messages)"}

Write an updated one-paragraph status summary reflecting the latest activity.
Also extract any NEW action items and NEW blockers mentioned that aren't
already reflected in the current summary.

Respond with ONLY valid JSON, no markdown fences, in this shape:
{{"status_summary": "...", "new_deliverables": ["...", ...], "new_blockers": ["...", ...]}}
Use empty arrays if there's nothing new."""

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    return json.loads(raw)


def sync_account_from_slack(account):
    if not account["slack_channel_id"]:
        raise RuntimeError("Set a Slack Channel ID on this account first.")
    transcript = fetch_recent_messages(account["slack_channel_id"])
    return summarize_with_claude(account["name"], account["status_summary"], transcript)
