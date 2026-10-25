# Garage

A private vehicle-maintenance tracker built with Django 5.2, Python 3.13,
PostgreSQL 17, and locally served HTMX. Google is the only account signup and
login method. The same Google account opens the same garage on every device
that can reach the application’s local network or VPN.

Supports US-market 2010 Ford F-150 King Ranch, 2012 Nissan Altima 3.5 SR,
2021 Subaru Crosstrek Limited, and 2026 Subaru Ascent Limited. The Ascent's
reviewed 2.4L turbo/CVT/AWD schedule covers normal use only; the other models
retain their existing configuration and driving-condition choices.

## What ships

- Manufacturer schedules, required-first Upcoming filtering, first/subsequent
  intervals, driving conditions, and explicit setup assumptions.
- A default mileage timeline with exact service targets, calendar warnings, and
  single/batch completion after one mileage confirmation.
- Multiple vehicles, mileage history, completed service, appointments, CSV
  history, and ICS calendar downloads.
- Google-only signup/login with verified identity, server-side sessions, and
  explicit migration of browser-only garages into account ownership.
- A prefilled Google Calendar event editor; the user must save the event.
  No Calendar permission, automatic synchronization, or duplicate-save detection.
- Vehicle-specific YouTube search links; optional video cards with a server-side
  YouTube Data API key. No access to a user’s YouTube account.

## Google sign-in and local-network access

The existing namespace Secret `google-oauth` supplies `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET`, plus the optional `YOUTUBE_API_KEY`. The chart injects
them only into the web container with
explicit Secret references. Do not put values in Git, Helm values, logs, or chat.
There is no SMTP dependency and Google access/refresh tokens are not retained.

Register exactly this authorized redirect URI for the existing web OAuth client:

`https://garage.apps.sno.batchelor.live/accounts/google/login/callback/`

Only `openid email profile` scopes are requested. Google redirects the browser
back to this local URL; Google does not need inbound access to the cluster.
Browsers need both Google internet access and local DNS/network reachability.
Web pods need outbound HTTPS/DNS to Google’s OAuth token and identity endpoints.
Keep the configured Google consent audience/publishing state; do not classify
an app as Workspace “Internal” merely because it is on a LAN. If production
branding requires public informational pages, host those separately; do not
expose the cluster to satisfy it.

### Safe rollout

`googleAuthRequired` defaults to `true`. For the first live callback check only,
deploy with `googleAuthRequired: false`: old unclaimed garages continue to work
and show a Connect with Google banner. Already claimed garages always require
their Google owner, even in this transition mode. After a real Google login is
verified, set the value to `true`, upgrade, and verify guest access is denied.
Never return to an old guest-only image after any ownership claims. Roll back
only to an account-aware image, or forward-fix while preserving ownership.

Each first sign-in offers a confirmation for this browser’s existing garage.
“Not now” preserves an import option in account settings. Recovery codes can be
used only after Google sign-in to locate an unclaimed garage and confirm import.
A successful claim invalidates the old code and browser-only access. Imports
into an existing account preserve its name/timezone, keep vehicle IDs/history,
and enforce the 30-vehicle limit atomically. Similar vehicles are not deduplicated.
Unclaimed data is retained; without a valid old session or recovery code,
ownership is not guessed. Recovery-code generation ends after required login.

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
more distant maintenance, with required items first and optional recommendations
afterward. Within each group, due-soon items precede more distant work.

## Updating current mileage

Every vehicle page has a **Current odometer (miles)** field and **Save mileage**
button in both Timeline and Detailed list. It starts with the latest recorded
mileage, including completed service. Saving records today's date in your
garage's timezone and refreshes the same maintenance view, its attention counts,
remaining mileage, and timeline marker. Dashboard counts refresh on your next visit.

Mileage updates do not log completed service, advance the setup assumption,
or move missed deadlines forward. Duplicate same-day submissions do not add
duplicate readings. A lower current mileage is rejected; use **Correct reading**
or **Correct record** to repair a mistaken entry. **Other date or engine hours**
opens the full reading form. Quick mileage updates never carry an older
engine-hour measurement forward as a new observation.

For a new Ascent, add a separate vehicle, choose **Subaru → Ascent → 2026 →
Limited**, and enter its actual odometer and original in-service date. Retain
the disclosed maintenance assumption for a new, normally used vehicle. No
completed service history is generated by setup, and deleted vehicles are not
recreated by catalog imports.

Run the disposable-data browser acceptance with:

```sh
uv run python scripts/check_ascent_mileage.py
```

This covers Ascent selection, current mileage updates, validation, both views,
mobile/keyboard/no-JavaScript use, vehicle isolation, and video search fallback.

## Maintenance timeline and quick completion

Vehicle pages open on **Timeline**. Each applicable service appears once at its
next exact mileage target, with required services before optional recommendations
at the same milestone. The current-mileage marker includes the observation date.
Calendar-overdue services stay at their mileage target with a date warning;
**Needs attention** links to approaching or overdue limits. Date/hour-only,
unknown-history, and as-needed work appear in separate sections. **Detailed list**
retains the existing filters. No driving rate or later recurring visits are projected.

Tap **Complete** or select several items and choose **Complete selected**. Confirm
or update the prefilled mileage, then save once. The service date defaults to today
in the garage timezone; **More options** allows backdating. Engine hours are optional
when relevant and are not guessed. Each selected item becomes an ordinary service
record; costs, provider and notes stay empty until edited in Service history.
The saved records update mileage and service targets without a duplicate odometer
reading. Setup assumptions stay fixed, and appointments are not marked complete.

A transaction saves the whole batch or nothing. Durable submission receipts make
retries safe, including after records are edited or deleted. Reusing a receipt with
changed values is rejected; start a new completion instead. This release includes
an additive database migration for receipts and their service-record links.

## Local development

Agents making changes can use the repository's
[`vehicle-maintenance` skill](skills/vehicle-maintenance/SKILL.md), also linked
from `AGENTS.md`. It covers the source map, domain rules, test selection and
deployment procedure. When installed locally, invoke it with `$vehicle-maintenance`.

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
uv run python scripts/check_timeline.py
GARAGE_LOCAL_TEST_ACCOUNT=1 GARAGE_URL=http://127.0.0.1:8000 uv run python scripts/browser_check.py
helm lint charts/garage
```

The browser check creates a disposable garage, exercises all three vehicle
flows, desktop/mobile layouts, records, calendar/video links, account sessions, and
isolation. It removes the vehicles afterward. Screenshots go to
`BROWSER_ARTIFACTS` (default `/private/tmp/garage-browser-check`). It does not
send data to Google or YouTube. Its local test-account fixture is restricted to
loopback addresses and adds no server-side login bypass. For live browser tests,
supply `GARAGE_STORAGE_STATE` for a dedicated Google test account; protect that
file as a credential and never commit it. Real Google login must be verified
interactively; mocked OAuth tests do not establish production consent. External API behavior is covered with mocks;
live video-card checks require an actual API key. See [video relevance testing](docs/video-discovery.md)
for the fixed benchmark, release gates, and isolated browser check.

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
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Existing `google-oauth` Secret, web container only |
| `GOOGLE_AUTH_REQUIRED` | `true` by default; temporarily `false` only for initial callback verification |
| `YOUTUBE_API_KEY` | Optional `google-oauth` Secret key; server-side YouTube Data API v3 access |
| `YOUTUBE_SEARCH_BUDGET` | Application search-request cap per Pacific day; default 80 |

Set `YOUTUBE_API_KEY` in the existing `google-oauth` Secret (selected by Helm
value `googleOAuthSecret`), then restart the web Deployment after future key
changes. The key reference is optional so installations without it retain search
links. Expanding **How-to videos** searches for up to three close vehicle-and-service
matches, with shared caching; no OAuth permission from the user is needed. The key is never sent to
the browser or logged. Public vehicle descriptors and task phrases are the only
search data sent. No per-user YouTube authorization is needed. Titles and narrative
descriptions must identify the service, action, model, year
or stated year range, and relevant engine/transmission/drivetrain. Unrelated and
insufficiently documented results are omitted; panels can contain fewer than three
cards or no cards. Results remain candidates, not verified mechanical instructions.
Request cache: seven days for
results, one day for empty searches, five minutes for API errors; a daily cleanup
removes metadata older than 30 days. Validate actual project quota before changing
the cap. Existing schedules/records keep working during API outages.

The Django admin uses Google sign-in and requires staff permission. There is no
password login or automatic promotion by email. After the intended administrator
has signed in, an operator can grant privileges using the local Django user ID:

```sh
oc -n vehicle-maintenance exec deploy/garage-web -- python manage.py grant_google_admin USER_ID
```

Catalog imports are preferable to editing a reviewed rule in place.

## Persistence and recovery

Account sessions renew on use and expire after one year of inactivity. Clearing
cookies or signing out does not delete the garage; sign in with the same Google
account to return. Signing out affects only that browser. Maintenance filters
are not synchronized and start at All maintenance. Account switching is done by
signing out and choosing a different Google account; provider unlinking and
email/password recovery are not available.

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
need reviewed search vocabulary and configuration
matching support as well as their schedule import. Unknown maintenance items keep
the search link without automatically displaying unfiltered video cards.

## Operations

`/health/live` checks the web process; `/health/ready` checks database availability.
Inspect failed Jobs, non-ready pods, PostgreSQL volume usage and HTTP 5xx logs.
YouTube failures emit `youtube_lookup_failed` without URLs/keys. The chart limits
resources and isolates database ingress to this namespace. One web replica and
one database instance are intended for this cluster; this is not HA PostgreSQL.
No browser analytics are installed. User content is escaped and CSV cells are
protected against spreadsheet formula injection. HTMX is vendored with its license.

## Release verification

- Ascent and inline mileage release, October 25, 2026 (Helm revision 10):
  186 tests passed locally; five PostgreSQL-only tests were skipped there.
  The four targeted PostgreSQL mileage, completion, and video-cache concurrency
  tests passed against an isolated temporary database. The unchanged account
  concurrency test was not rerun on PostgreSQL for this release.
- `scripts/check_ascent_mileage.py` and `scripts/check_timeline.py` passed:
  desktop/mobile, keyboard entry, same-view recalculation, invalid/duplicate
  mileage, service completion, vehicle isolation, and JavaScript-disabled use.
  Django checks, no-pending-model-change check, Helm lint, and server dry run passed.
- Pre-release backup `garage-backup-ascent-20261025224246` completed and verified
  its archive. Build `garage-13` produced pinned image
  `sha256:3eaddf70b2bc7ef325bf6542a122e6730cf97e405be45daea33bf6926550c367`.
  `garage-migrate-10` imported four schedules/six configurations without schema
  changes; rollout completed and HTTPS readiness passed. Vehicle creation
  still redirects unauthenticated clients to sign-in.
- The deployed image passed an isolated temporary-database smoke test for
  Ascent setup, inline mileage rendering/recalculation, lower-reading rejection,
  and duplicate-save handling. No production vehicle/service records were
  created or changed by these tests. Enter the owner's actual Ascent mileage
  and in-service date through the normal signed-in setup flow. Live Google
  consent and Ascent YouTube tutorial suitability were not retested.
- The prior revision 9 and its image remain available for a schema-compatible
  rollback. The temporary PostgreSQL test namespace and port-forward were removed.

Verified on OpenShift 4.22.4 with PostgreSQL 17:

- Timeline release (Helm revision 9): 152 local tests and all three PostgreSQL
  concurrency checks passed. Browser checks covered desktop/mobile timeline,
  batch completion, keyboard interaction, validation recovery, no-JavaScript
  saving, and the existing three-vehicle workflows. The pre-release backup was
  verified, migration `0004_completion_submission` completed, and deployed
  timeline/completion/CSV checks passed using a fully rolled-back test fixture.

- Automated coverage includes Google OAuth callbacks with mocked provider
  responses, verified identity, ownership, legacy claims, imports, disabled
  password routes, and existing maintenance calculation/workflows. Concurrent
  claims are tested against a disposable PostgreSQL database.
- Live desktop/mobile browser checks cover all three vehicles, service logging,
  appointments, ICS and Google event links, tutorial search links, and isolation between browser sessions. Google-account
  browser tests run locally with separate server-side sessions for the same user.
- Header, content, and footer alignment checked at 390, 768, 960, 1440, and
  1920 pixel viewport widths without horizontal overflow.
- A completed service record and its browser session survived both web and
  PostgreSQL pod restarts.
- A logical backup was restored into an isolated, disposable PostgreSQL
  instance; all five configurations and 108 maintenance rules were restored.
- Live YouTube oil-change searches returned three video cards for each supported
  vehicle. Rendered cards and cache reuse were checked without exposing the key;
  mocked tests cover missing credentials, failures, quota limits, and removals.
- The user confirmed real Google sign-in succeeded. Required login is enabled;
  anonymous vehicle setup and legacy recovery redirect to Google sign-in.
