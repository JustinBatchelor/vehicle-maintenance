# Garage

An account-free, private vehicle-maintenance tracker built with Django 5.2,
Python 3.13, PostgreSQL 17, and locally served HTMX. Supports US-market 2010
Ford F-150 King Ranch, 2012 Nissan Altima 3.5 SR, and 2021 Subaru Crosstrek
Limited, including relevant configuration/operating-condition differences.

## What ships

- Manufacturer schedule references, due/overdue/upcoming/unknown states,
  first/subsequent intervals, and condition-specific rules.
- Multiple vehicles per private garage, mileage history, completed service
  records, multi-item appointments, CSV export, and calendar downloads.
- No signup, email service, or Google OAuth credentials required. A server-side
  Django session identifies a garage; a secure browser cookie is its key.
- Optional recovery codes are generated from 32 random bytes, stored only as
  SHA-256 hashes, and shown once. They restore the same garage on another device.
- "Add to Google Calendar" opens a prefilled event that the user must save.
  It does not call Google APIs, confirm a save, prevent repeated saves in Google,
  or synchronize updates. `.ics` is an independent optional alternative.
- Every maintenance item has a dynamic vehicle-specific YouTube search link.
  Video cards are optional: configure `YOUTUBE_API_KEY` to enable official API
  discovery with labeled broader matches, caching, and quota controls.

This release uses session-based access. Public account registration, email
verification, Google sign-in, and direct Calendar API writes are outside its
scope. No external credentials are needed for the core maintenance workflow.

## Starting maintenance assumptions

New vehicle forms default to **Assume scheduled maintenance is up to date**.
This stores a fixed mileage/date starting point, separate from completed service
records and CSV exports. Uncheck it to start with unknown history. Existing
vehicles retain their current behavior until the option is enabled in **Edit
details**, using their latest observed mileage and date.

Without actual history, the next mileage target is the next manufacturer
milestone after the starting point, preserving different first and recurring
intervals. For example, a normal-use Altima entered at 133,600 miles has its next
7,500-mile oil milestone at 135,000 miles. It is not treated as freshly serviced
at 133,600 miles. With an original in-service date, time targets use vehicle-age
milestones; without one, the recurring time interval starts at the assumption
date and this is explained on each task. As-needed rules stay conditional, and
missing engine-hour readings stay unknown where required.

Actual service history, including backdated entries, takes precedence per item.
Each item also allows **Confirm never serviced**, **Mark history unknown**, or
**Use setup assumption**. Updating mileage or editing details does not advance
the starting point. Disable the assumption to remove it; re-enabling starts from
the latest observation. The Upcoming filter includes due-soon work as well as
more distant maintenance.

## Local development

With Python 3.13 and uv:

```sh
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py import_schedules
DEBUG=true uv run python manage.py runserver
```

SQLite is a local convenience only. Production uses PostgreSQL. Alternatively:

```sh
podman compose up --build
```

Open `http://localhost:8080`. Compose uses a named PostgreSQL volume and test-only
credentials. Never use its credentials in production.

## Tests

```sh
uv run pytest -q
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run playwright install chromium
GARAGE_URL=http://127.0.0.1:8000 uv run python scripts/browser_check.py
helm lint charts/garage
```

The browser check creates a disposable garage, exercises all three vehicle
flows, desktop/mobile layouts, records, calendar/video links, recovery, and
isolation. It removes the vehicles afterward. Screenshots go to
`BROWSER_ARTIFACTS` (default `/private/tmp/garage-browser-check`). It does not
send data to Google or YouTube. External API behavior is covered with mocks;
live video-card checks require an actual API key.

Dependency locks: `uv.lock` includes development tools; `requirements.lock`
contains hashed runtime dependencies for the container. Refresh both together:

```sh
uv lock
uv export --frozen --no-dev --format requirements-txt --output-file requirements.lock
```

## OpenShift

Namespace: `vehicle-maintenance`. Route: `https://garage.apps.sno.batchelor.live`.
The chart runs under restricted SCC with arbitrary user IDs. Application
containers have read-only root filesystems; `/tmp` is an ephemeral volume.
PostgreSQL data and backups use separate retained `truenas-nfs` volumes.

Initial setup (idempotently provision secrets; do not regenerate them on upgrades):

```sh
oc create namespace vehicle-maintenance
python scripts/provision_secrets.py
oc -n vehicle-maintenance new-build --name=garage --binary --strategy=docker --to=garage:latest
oc -n vehicle-maintenance patch bc garage --type=merge \
  -p '{"spec":{"strategy":{"dockerStrategy":{"dockerfilePath":"Containerfile"}}}}'
```

Build from the current checkout without local databases, virtualenvs, or macOS
archive metadata:

```sh
python scripts/build_archive.py /tmp/garage-build.tar.gz
oc -n vehicle-maintenance start-build garage --from-archive=/tmp/garage-build.tar.gz --follow
oc -n vehicle-maintenance get istag garage:latest -o jsonpath='{.image.dockerImageReference}'
```

Use the immutable image reference from that final command as `image` in
`charts/garage/values-deployed.yaml`. Keep the database image pinned too.

```sh
helm template garage charts/garage -f charts/garage/values-deployed.yaml > /tmp/garage-rendered.yaml
oc apply --dry-run=server -n vehicle-maintenance -f /tmp/garage-rendered.yaml
helm upgrade --install garage charts/garage -n vehicle-maintenance -f charts/garage/values-deployed.yaml
oc -n vehicle-maintenance get jobs
oc -n vehicle-maintenance wait job/garage-migrate-RELEASE_REVISION --for=condition=complete --timeout=5m
oc -n vehicle-maintenance rollout status deployment/garage-web --timeout=5m
```

Each release creates a migration/import Job. The web init container waits for
the image's exact catalog version and all migrations. Do not expose a release
as ready while migration/import has failed. Back up the database before upgrades.
Rollback is `helm rollback` only when schema-compatible; otherwise restore a
compatible backup and image together. Do not delete the namespace or PVCs to
roll back an application release.

## Runtime configuration

| Setting | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string; required in deployment |
| `DJANGO_SECRET_KEY` | Stable, random server secret; created by provisioner |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Exact route/host values supplied by chart |
| `COOKIE_SECURE` | `true` in OpenShift; HTTPS-only cookies |
| `YOUTUBE_API_KEY` | Optional server-side key restricted to YouTube Data API v3 |
| `YOUTUBE_SEARCH_BUDGET` | Application search-request cap per Pacific day; default 80 |

Add a YouTube key to the existing `garage-app` Secret using your normal secret
management workflow, then restart the web Deployment. The key is never sent to
the browser or logged. Public vehicle descriptors and task phrases are the only
search data sent. No per-user YouTube authorization is needed. Results remain
candidates, not verified mechanical instructions. Request cache: seven days for
results, one day for empty searches, five minutes for API errors; a daily cleanup
removes metadata older than 30 days. Validate actual project quota before changing
the cap. Existing schedules/records keep working during API outages.

The operational Django admin has no pre-created login. If needed, provision an
administrator interactively:

```sh
oc -n vehicle-maintenance exec -it deploy/garage-web -- python manage.py createsuperuser
```

End users never need these credentials. Catalog imports are preferable to editing
a reviewed rule in place.

## Persistence and recovery

Cookies renew on use, expiring after one year of inactivity. Garages are not
automatically deleted when sessions expire. Clearing a browser's cookie without
a recovery code loses access; CSV is a history export, not a full garage backup.
Save the optional recovery code before switching devices. Anyone holding it can
access the garage. Rotating it invalidates the old code but leaves connected
browsers connected. Disconnecting a browser flushes its session.

Nightly PostgreSQL custom-format backups run at 03:00 America/New_York, retain
14 days, and first verify the archive can be listed. Cache/session cleanup runs
at 03:20. The backup volume shares the TrueNAS failure domain; it is not an
off-site copy. Protect Secret backups separately: restoring database sessions
requires the original Django secret.

Trigger and inspect a backup:

```sh
oc -n vehicle-maintenance create job --from=cronjob/garage-backup garage-backup-manual
oc -n vehicle-maintenance logs job/garage-backup-manual
```

Restore with `pg_restore --no-owner --no-acl --exit-on-error` into a separate
empty PostgreSQL database first. Verify schema, configurations, garages and
record counts before any planned production cutover. Do not use `--clean` on the
live database as a test. See `scripts/verify_restore.py` for the disposable
restore check used during release acceptance.

## Maintenance data

See [the review record](data/REVIEW.md) and `data/schedules.json` for provenance,
configuration decisions and documented conditional cases. `python
scripts/build_catalog.py` reproduces the reviewed dataset. Increment its version
when changing intervals, test, then import atomically. New vehicle configurations
automatically participate in tutorial searches once their reviewed schedule is
imported; no hard-coded video list is required.

## Operations

`/health/live` checks the web process; `/health/ready` checks database availability.
Inspect failed Jobs, non-ready pods, PostgreSQL volume usage and HTTP 5xx logs.
YouTube failures emit `youtube_lookup_failed` without URLs/keys. The chart limits
resources and isolates database ingress to this namespace. One web replica and
one database instance are intended for this cluster; this is not HA PostgreSQL.
No browser analytics are installed. User content is escaped and CSV cells are
protected against spreadsheet formula injection. HTMX is vendored with its license.

## Release verification

Verified on OpenShift 4.22.4 with PostgreSQL 17:

- 53 automated tests pass locally, including setup assumptions, milestone
  boundaries, fixed starting points, history overrides, opt-out, and ownership.
  The initial PostgreSQL release also passed its full 38-test suite plus three
  relevant form tests after its final validation change.
- Live desktop/mobile browser checks cover all three vehicles, service logging,
  appointments, ICS and Google event links, tutorial search links, garage
  recovery, and isolation between browser sessions.
- Header, content, and footer alignment checked at 390, 768, 960, 1440, and
  1920 pixel viewport widths without horizontal overflow.
- A completed service record and its browser session survived both web and
  PostgreSQL pod restarts.
- A logical backup was restored into an isolated, disposable PostgreSQL
  instance; all five configurations and 108 maintenance rules were restored.
- Live YouTube API results remain unverified without an API key; mock-based
  coverage exercises discovery, caching, and failures.
