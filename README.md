# SE Account Manager

Personal daily-driver for tracking your accounts: health, last/next call,
deliverables, tasks, blockers, stakeholders, and quick links (Grafana,
Salesforce, Slack). Python + SQLite + Streamlit, three files, runs in a
container on your workstation.

## Run with Docker (recommended)

```bash
cd se-account-manager
docker build -t se-account-manager .
docker run -d --name se-accounts \
  -p 8501:8501 \
  -v se_accounts_data:/data \
  se-account-manager
```

Open **http://localhost:8501** in any browser. The `-v se_accounts_data:/data`
volume keeps your SQLite file across container rebuilds — don't skip it.

To update the app after editing code: `docker build -t se-account-manager .`
then recreate the container (same run command); your data survives because
it's in the named volume, not the image.

## Run on Kubernetes (inside Docker Desktop)

Build the image into Docker Desktop's local image store, then apply the
manifests in `k8s/`:

```bash
cd se-account-manager
docker build -t se-account-manager:latest .

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml

kubectl -n se-account-manager port-forward svc/se-account-manager 8501:8501
```

Open **http://localhost:8501** in any browser (leave `port-forward` running
in that terminal, or run it with `&`/in a background terminal). Data
persists in a 1Gi PersistentVolumeClaim (`se-accounts-data`) independent of
the pod, so redeploys don't lose your DB.

To redeploy after code changes:

```bash
docker build -t se-account-manager:latest .
kubectl -n se-account-manager rollout restart deployment/se-account-manager
```

Runs as a single replica (`Recreate` strategy) — SQLite is a single file and
can't be shared across pods.

### `ErrImagePull` after applying

This means your cluster's container runtime can't see the image you built
with `docker build` — it's trying to pull `se-account-manager:latest` from a
registry instead of using the local one. Which fix applies depends on how
your Kubernetes is set up:

- **Docker Desktop's built-in Kubernetes**: it shares the Docker daemon, so
  a plain `docker build` should already be visible. Confirm you're on that
  context (`kubectl config current-context` → `docker-desktop`), then
  `kubectl -n se-account-manager describe pod <pod>` to see the exact image
  name it's trying to pull — a typo or extra registry prefix is the usual
  cause.
- **kind**: `docker build` images aren't visible to the kind cluster
  automatically — load it explicitly: `kind load docker-image
  se-account-manager:latest --name <your-cluster-name>`, then `kubectl -n
  se-account-manager rollout restart deployment/se-account-manager`.
- **minikube**: either build against minikube's own daemon
  (`eval $(minikube docker-env) && docker build -t se-account-manager:latest
  .`) or load the image you already built: `minikube image load
  se-account-manager:latest`.
- **k3d/other**: load the image into the cluster's node the same way (e.g.
  `k3d image import se-account-manager:latest`).

## Run without Docker

```bash
cd se-account-manager
pip install -r requirements.txt
streamlit run app.py
```

Data is written to `se-account-manager/data/se_accounts.db`.

## Slack sync (via Claude, not a bot token)

The app itself holds no Slack or Anthropic credentials — it never talks to
either API directly. Instead:

1. Each account has a "Slack Channel ID" field (paste it from Slack:
   right-click the channel → View channel details → bottom of the panel).
2. On the account page, click "🔔 Request Claude Slack sync." This just
   timestamps a `slack_sync_requested_at` flag on that account — nothing is
   fetched yet. The Dashboard's "Pending Slack syncs" counter shows how many
   accounts are waiting.
3. Next time you're in a Claude Code / chat session in this repo with a
   Slack connector available, ask it to **"run pending Slack syncs."**
   Claude will: read `db.list_pending_slack_syncs()`, use its own Slack
   connector to fetch each account's channel history, write an updated
   status summary + any new deliverables/blockers itself, and persist the
   result by running `apply_slack_sync.py <account_id>` (piping in
   `{"status_summary": ..., "new_deliverables": [...], "new_blockers": [...]}`
   as JSON), which also clears the pending flag.

This only completes when a Claude session with Slack access actually runs
the request — the deployed app can't trigger it on its own.

## Salesforce sync (also via Claude)

Same pattern as Slack, for the Stage and ARR fields shown on the account
report:

1. On the account page, click "🔔 Request Salesforce sync (Stage/ARR)" —
   timestamps `salesforce_sync_requested_at` on that account.
2. Ask Claude to **"run pending Salesforce syncs."** It reads
   `db.list_pending_salesforce_syncs()`, looks up each account/opportunity
   via its own Salesforce connector, and persists the result by running
   `apply_salesforce_sync.py <account_id>` (piping in `{"stage": ...,
   "arr": ...}` as JSON), which also clears the pending flag and drops a
   Timeline note.

### Importing all your Salesforce accounts

Ask Claude to **"import my Salesforce accounts."** It queries Salesforce
for opportunities/accounts where you're listed as SE, and for each one
pipes a JSON record into `import_salesforce_accounts.py`:

```bash
echo '[{"name": "Acme Corp", "ae_assigned": "...", "se_assigned": "...",
        "stage": "POC", "arr": "$300,000", "salesforce_url": "..."}]' \
  | python import_salesforce_accounts.py
```

It matches existing accounts by name (case-insensitive) and updates them,
or creates a new account for anything not already tracked — either way it
leaves a Timeline note recording the import.

## Calendar sync (also via Claude)

Same request/fulfill pattern again, for the Dashboard's "This Week's
Customer Meetings" card:

1. Click "🔔 Sync calendar" on that card — timestamps
   `calendar_sync_requested_at` in `app_settings`.
2. Ask Claude to **"sync my calendar."** It reads this week's events via
   its own Google Calendar connector, filters down to genuine
   customer-facing meetings (external attendees, not internal prep/syncs),
   matches each to a tracked account by name where possible, and persists
   the result by piping JSON into `apply_calendar_sync.py`:

```bash
echo '[{"title": "Acme Corp | QBR", "start_time": "2026-09-18T14:00:00",
        "end_time": "2026-09-18T15:00:00", "account_name": "Acme Corp",
        "link": "https://meet.google.com/..."}]' \
  | python apply_calendar_sync.py
```

This replaces whatever was previously synced for the current week (so
re-running doesn't duplicate) and clears the pending request. The
Dashboard's "Customer meetings this week" metric and calendar card both
read from this table.

## Adding a field or feature

- New column on an account: add it to `SCHEMA` in `db.py` (the `accounts`
  table), then add a matching widget in `render_account()` in `app.py`.
- New account-level list (e.g. "risks"): copy the `deliverables` table
  pattern in `db.py` and add a `render_child_section(...)` call + tab in
  `app.py`.
- Existing SQLite files aren't auto-migrated — for a new column on an
  existing DB, either delete `data/se_accounts.db` (loses data) or run a
  one-off `ALTER TABLE accounts ADD COLUMN ...` against it.
