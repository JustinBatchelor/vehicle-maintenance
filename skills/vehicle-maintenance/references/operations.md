# Verification and existing deployment

## Local work and checks

Run from the repository root. `README.md` has the development commands:

```sh
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py import_schedules
DEBUG=true uv run python manage.py runserver
```

SQLite is convenient locally; `podman compose up --build` runs PostgreSQL.
Choose focused pytest files from the skill's change map, then broaden when a
shared change warrants it. Model changes need a migration and
`uv run python manage.py makemigrations --check --dry-run`. Use
`uv run python manage.py check` for configuration and `helm lint charts/garage`
for chart changes. Refresh both `uv.lock` and hashed runtime `requirements.lock`
when dependencies change, using the README commands.

Concurrency claims need real PostgreSQL: SQLite skips the locking test.
`tests/postgres.yaml` provides a disposable database in
`vehicle-maintenance-test`. Point test `DATABASE_URL` only at an isolated
database, never the live garage database. Remove only resources created for
that test after it finishes.

For UI changes, run the local server and:

```sh
uv run playwright install chromium
GARAGE_LOCAL_TEST_ACCOUNT=1 GARAGE_URL=http://127.0.0.1:8000 uv run python scripts/browser_check.py
```

The loopback-only fixture creates disposable Google-linked test users and
independent sessions; it is not a production login bypass. Check desktop and
mobile widths for overflow and relevant interaction changes. Live browser tests
need `GARAGE_STORAGE_STATE` from an authorized, dedicated Google test account.
Treat that file as a credential, never commit it or reuse another user's cookies.
Mocked OAuth callbacks do not verify a real consent screen or callback registration.
Missing local Google credentials is not a reason to disable required production login.

Video relevance checks have an additional local runner:

```sh
uv run python scripts/check_video_panels.py
```

It creates a temporary SQLite database and loopback server, uses ordinary Google-
linked test sessions, and checks real HTMX loading/matched/empty/unavailable panels
at desktop and mobile widths with synthetic provider responses. It never contacts
Google/YouTube. Set `PLAYWRIGHT_BROWSERS_PATH` if browsers are installed elsewhere.
For live relevance evaluation, follow `docs/video-discovery.md`; preserve the daily
project cap and keep metadata artifacts outside the checkout.

## Deployment map

Use `oc` with the existing kubeconfig. Confirm the active context/namespace
before changes. The live release is Helm `garage` in namespace
`vehicle-maintenance`, with chart `charts/garage` and deployment overrides in
`charts/garage/values-deployed.yaml`. Read that file for current image digests;
do not copy a historical digest or Helm revision from an old conversation.

Resources: Deployment `garage-web`, StatefulSet `garage-db`, Services of those
names, Route `garage`, migration Job `garage-migrate-<release revision>`.
The image is built for amd64 using the existing binary Docker BuildConfig
`garage`. Preserve restricted-SCC/arbitrary-UID compatibility, read-only web
root, writable `/tmp`, probes and resource limits. PostgreSQL is internal only.
Storage is `truenas-nfs`; data and backups occupy separate retained volumes.

| Secret | Referenced keys |
| --- | --- |
| `garage-app` | `DATABASE_URL`, `DJANGO_SECRET_KEY` |
| `garage-db` | `password` |
| `google-oauth` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `YOUTUBE_API_KEY` |

`googleOAuthSecret` selects the existing Secret; do not recreate or overwrite it
on upgrades. OAuth key references are required; YouTube is optional so keyless
installations retain fallback links. Only web containers receive these provider
credentials. Environment-injected Secret changes require a web rollout to take
effect. The chart and Django default to required Google authentication; the live
initial consent check is already complete. Keep `googleAuthRequired: true`.

The callback is
`https://garage.apps.sno.batchelor.live/accounts/google/login/callback/`.
LAN/VPN clients need local DNS, trusted HTTPS, and internet access to Google;
web pods need outbound Google DNS/HTTPS. There is no need to open inbound access
from Google to this private cluster. Retain identity-only OAuth scopes.

## Authorized release procedure

Deploy only within the user's authorized task. Documentation-only changes do
not require a release; chart/environment-only changes can reuse the pinned
image when application code is unchanged.

1. Complete relevant checks and inspect the diff. Before an upgrade, create a
   uniquely named Job from `cronjob/garage-backup` and wait for successful
   completion. Stop on backup, build, or migration failure and diagnose it;
   do not repeatedly redeploy or delete data to force readiness.
2. For runtime source changes, use
   `python scripts/build_archive.py /tmp/garage-build.tar.gz`, then
   `oc -n vehicle-maintenance start-build garage --from-archive=/tmp/garage-build.tar.gz`.
   This helper excludes local data and avoids macOS archive metadata. Wait for
   the returned Build to complete. Inspect that exact Build's
   `status.outputDockerImageReference` and `status.output.to.imageDigest`, and
   record its immutable registry repository plus `@sha256:...` in
   `values-deployed.yaml`. Avoid a mutable `latest` lookup racing another build.
3. For chart changes, render and inspect the Helm manifests; a server dry-run
   can check admission compatibility. Upgrade with
   `helm upgrade --install garage charts/garage -n vehicle-maintenance -f charts/garage/values-deployed.yaml --wait --timeout=5m`.
4. Verify the new revision's migration/import Job completes and
   `oc -n vehicle-maintenance rollout status deployment/garage-web --timeout=5m`
   succeeds. The web init container waits for the image's exact catalog version
   and all migrations. Readiness alone is not full feature acceptance.
5. Check HTTPS, health endpoints and the relevant authenticated workflow. Report
   any part that still needs real user/provider interaction. When pushing is
   authorized, commit the intended source/configuration changes to the existing
   GitHub remote; check the branch and remote first and preserve unrelated work.

## Recovery and operational tests

Nightly logical backups retain 14 days on a separate volume in the same TrueNAS
failure domain. `scripts/verify_restore.py` checks a real restore into an
isolated disposable database. Inspect it before running; never test restoration
over the live database. `scripts/persistence_check.py` restarts app/database pods
and requires authorized test authentication; use it for requested operational
verification, not routine UI or documentation checks.

Rollback must preserve account-based authorization after ownership claims. Use
an account-aware image and schema-compatible release; otherwise plan a forward
fix or deliberate restore with the user. Do not delete namespaces/PVCs to repair
an application rollout. Preserve the Django secret when restoring sessions.
