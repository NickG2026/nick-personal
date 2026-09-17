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

## Slack + Claude sync

Each account has a "Slack Channel ID" field. The "🔄 Sync status from Slack +
Claude" button on the account page reads that channel's recent messages and
asks Claude to rewrite the status summary and flag any new deliverables/
blockers, which get added automatically.

Setup:
1. Create a Slack app (api.slack.com/apps) with bot scopes
   `channels:history`, `groups:history`, `users:read`; install it to your
   workspace; invite the bot to each account's channel; copy the bot token
   (`xoxb-...`).
2. Get an Anthropic API key (console.anthropic.com).
3. Set both as env vars wherever the app runs:
   - **Docker**: `docker run ... -e SLACK_BOT_TOKEN=xoxb-... -e ANTHROPIC_API_KEY=sk-ant-...`
   - **Kubernetes**: `cp k8s/secret.example.yaml k8s/secret.yaml`, fill in
     the real values, `kubectl apply -f k8s/secret.yaml`, then restart the
     deployment.
4. On each account, paste its Slack channel ID (right-click the channel
   name in Slack → View channel details → bottom of the panel).

## Adding a field or feature

- New column on an account: add it to `SCHEMA` in `db.py` (the `accounts`
  table), then add a matching widget in `render_account()` in `app.py`.
- New account-level list (e.g. "risks"): copy the `deliverables` table
  pattern in `db.py` and add a `render_child_section(...)` call + tab in
  `app.py`.
- Existing SQLite files aren't auto-migrated — for a new column on an
  existing DB, either delete `data/se_accounts.db` (loses data) or run a
  one-off `ALTER TABLE accounts ADD COLUMN ...` against it.
