---
name: vehicle-maintenance
description: Implement, review, or troubleshoot changes in JustinBatchelor/vehicle-maintenance (Garage), including Django features, manufacturer schedules, Google accounts, YouTube discovery, tests, and its existing OpenShift deployment. Use for this repository rather than unrelated vehicle or website projects.
---

# Vehicle Maintenance

Work on the existing Garage application. The usual checkout is
`/Users/jbatchel/codex/vehicle-maintenance`; its remote is
`git@github.com:JustinBatchelor/vehicle-maintenance.git`. Use the active checkout
when working elsewhere. Paths below are relative to the repository unless
they link to this skill's references.

## Orient before changing behavior

Read `README.md`, inspect `git status --short`, then read the relevant source.
Treat this guide as a map, not a replacement for the current implementation.
Earlier feature plans include functionality that was subsequently changed;
preserve current behavior unless the user's request changes it.

- Python 3.13, Django 5.2, PostgreSQL 17, server-rendered templates and vendored
  HTMX; SQLite is for local convenience. No separate frontend build or public API.
- Google is the only signup/login method. Account ownership persists across
  devices. No email/password registration, SMTP requirement, or email allowlist.
- New vehicles default to a disclosed maintenance assumption, separate from
  real service records. Upcoming shows required before optional work. Filters
  are temporary and start at All maintenance.
- Google Calendar uses a prefilled event-editor link. It does not use a Calendar
  API, retain Google tokens, synchronize events, or prevent repeated manual saves.
- YouTube discovery uses the server-side API key in the existing `google-oauth`
  Secret. Search links remain available when cards cannot load.
- Maintenance coverage is reviewed and finite: 2010 Ford F-150 King Ranch,
  2012 Nissan Altima 3.5 SR, and 2021 Subaru Crosstrek Limited. Dynamic videos
  do not establish manufacturer schedule coverage for other vehicles.

## Find the change surface

| Change | Start here |
| --- | --- |
| Page layout, mobile behavior, filters | `templates/`, `static/app.css`, `static/app.js` |
| Vehicle setup, history, appointments, exports | `garage/forms.py`, `garage/views.py`, `garage/urls.py` |
| Models, ownership, observations | `garage/models.py`, `garage/migrations/`, `garage/middleware.py` |
| Due calculations and applicability | `garage/calculator.py`, `garage/services.py`, `tests/test_calculator.py`, `tests/test_assumptions.py` |
| Manufacturer coverage and provenance | `data/REVIEW.md`, `data/schedules.json`, `scripts/build_catalog.py`, `garage/management/commands/import_schedules.py` |
| Google identity and legacy imports | `garage/accounts.py`, `config/urls.py`, `config/settings.py`, `tests/test_accounts.py` |
| Video discovery, quotas and caching | `garage/videos.py`, `garage/limits.py`, `templates/garage/videos.html`, `tests/test_videos.py` |
| Containers, Secrets, releases and backups | `Containerfile`, `charts/garage/`, `scripts/`, `README.md` |

Read [domain rules](references/domain.md) for changes to schedules, history,
ownership, exports, or videos. Read [verification and deployment](references/operations.md)
for environment setup, test selection, or live operations. Documentation-only
changes need no image build or deployment.

## Boundaries to preserve

Check ownership on every garage operation, export, and tutorial endpoint.
Keep the pure calculator independent of Django and external services. Preserve
manufacturer provenance, conditional requirements, and inspection/replacement
distinctions; never invent intervals to fill a gap.

The live app is LAN/VPN-only at `https://garage.apps.sno.batchelor.live`.
Required Google login has been verified and enabled. Do not disable it to test
a feature or roll back to guest-only authorization after ownership claims.
Do not expose the cluster or change OAuth publishing settings as a workaround.

Read Secret names/keys or boolean presence checks when diagnosing credentials;
do not dump values, full environment variables, OAuth queries, or API-key URLs.
Never commit databases, browser authentication state, or credentials.

Choose checks proportional to the change; distinguish mocked provider tests
from real Google consent or live YouTube checks. Source changes do not by
themselves authorize deployment, privilege grants, destructive data operations,
or publishing. Use the user's current request and established authorization.
When pushing is authorized, use the existing remote without force-pushing.
Report what changed, checks performed, and whether it was pushed/deployed.
