# Video discovery and relevance evaluation

Garage shows possible matches only when public metadata supports the requested
service and vehicle. It can return zero cards. This is metadata filtering, not
verification of mechanical instructions or manufacturer compatibility.

## Matching and runtime behavior

`garage/video_profiles.py` maps all 54 maintenance items to two natural search
phrases, component/action synonyms, conflicts and necessary configuration fields.
The manufacturer catalog and service calculations are unchanged. Missing profiles
keep a vehicle/task search link and never trigger unfiltered discovery.

Each uncached lookup makes at most two searches of 15 candidates, stopping after
three qualifying cards. Searches retain year/make/model and only task-relevant
engine/transmission/drivetrain details. Batched video details preserve search
ordering; duplicates, deleted/private/live/region-blocked videos are excluded.

Titles must name the component. Short narrative description sentences can supply
supporting procedure and vehicle evidence; hashtags, keyword lists, links and
unrelated advice cannot. The target year must appear explicitly or fall inside an
explicitly stated range. This is an uploader claim, not independently verified
compatibility. Adjacent years are never inferred from a vehicle generation. Wrong
models, explicit mechanical conflicts, missing critical details, advertising-only
content and wrong actions are rejected. Combined differential work requires both
axles, and automatic transmission fluid-and-filter service requires filter content.
Inspection panels do not accept replacement-only instructions.

The authenticated HTMX endpoint is unchanged. Its internal result includes an
`outcome`: `matches`, `no_matches`, `unavailable`, or `refreshing`. Cards are labeled
“Possible vehicle and service match.” Provider outages and partial failures retain
qualifying cards and an unavailable notice. Empty and failure notices survive
cache hits. The existing JSON cache field now stores `{videos, outcome}`; versioned
keys isolate older cached lists without a database migration. Changes to query,
filter or profile semantics must change `SEARCH_VERSION` or `PROFILE_VERSION`.

The shared daily search cap remains 80 (Pacific day), with the existing per-garage
throttle, 90-second lease, seven-day successful cache, one-day empty cache and
five-minute failure cache. Cleanup removes metadata older than 30 days. Diagnostic
logs record outcome, candidate/accepted counts and elapsed time, never identity,
private vehicle data, API URLs or key-bearing exception text.

## Automated checks

```sh
uv run pytest -q
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python scripts/check_video_panels.py
```

The panel check uses a temporary database, an ordinary authenticated local test
session, a loopback server, and synthetic provider responses. It tests real HTMX
loading, matches, empty results and outages at 1440px and 390px. Screenshots default
to `/private/tmp/garage-video-panels`; set `BROWSER_ARTIFACTS` to change that location.
Use `PLAYWRIGHT_BROWSERS_PATH` for a nonstandard Chromium installation.

Concurrency tests require disposable PostgreSQL. Point `DATABASE_URL` at an
isolated test instance, never the live database. The suite checks concurrent cache
claims as well as account ownership. SQLite deliberately skips those locking tests.

## Live benchmark and review

The manifest in `scripts/evaluate_videos.py` has 40 fixed cases:

- 20 development cases: oil, engine filter, spark plugs and brake inspection for
  all five configurations.
- 10 held-out cases: coolant replacement and the applicable transmission-fluid
  service for all five configurations.
- 10 targeted cases: front/rear differentials, filter inspection/replacement,
  CVT inspection and brake-fluid inspection.

The evaluator reproduces the original algorithm (up to three progressively broader
searches, five candidates each, first three available cards) and runs the new
algorithm separately. Query responses are reused within the temporary artifact;
filter changes can be replayed without more API searches. The fixed held-out set
is useful for regression but must not be described as unseen after its results
have been inspected or used to fix bugs.

```sh
# Explicit live access, at most 20 search attempts this invocation.
uv run python scripts/evaluate_videos.py \
  --artifact /private/tmp/garage-video-evaluation.json \
  --live --cluster --split dev --max-searches 20

# Repeat for holdout/targeted; resumption reuses completed requests.
uv run python scripts/evaluate_videos.py \
  --artifact /private/tmp/garage-video-evaluation.json \
  --live --cluster --split holdout --max-searches 20

# Offline replay with the current matching version.
uv run python scripts/evaluate_videos.py \
  --artifact /private/tmp/garage-video-evaluation.json --split all

# Read review metrics without provider calls.
uv run python scripts/evaluate_videos.py \
  --artifact /private/tmp/garage-video-evaluation.json --report
```

`--cluster` keeps the credential in the existing web pod and reserves every search
through the deployed shared quota counter. It does not deploy code or modify
vehicles, records or video caches. Without `--cluster`, use a locally configured
key/database and its shared limiter. Never raise the daily cap for evaluation.
The artifact must be outside the checkout. It has restrictive file permissions
and expires after 29 days; the next invocation deletes expired artifacts. Delete
abandoned artifacts by that deadline too; the tool cannot clean files while idle.
Permanent regression fixtures contain synthetic data only.

Review the videos themselves, independently of the matcher. Within each case,
set `known_available` to true/false only after an independent availability search
and explain the evidence in `availability_notes`. For each displayed card set:

- `review`: `relevant`, `irrelevant`, or `uncertain`.
- `contradiction`: whether vehicle/configuration or service/action explicitly conflicts.
- `review_notes`: observations about the actual content and applicability.

Metadata review or sampled frames alone cannot establish a complete procedural
review. Uncertain counts as unsuitable; unreviewed results leave precision
unscored. Passing requires every held-out case and its reviews to be complete,
at least 90% displayed-card relevance, zero contradictions, and at least 80%
coverage among cases independently confirmed to have a suitable video. Empty
results never count as a quality success. Review baseline results alongside the
proposed results rather than treating fewer cards as proof of improvement.

## Evaluation status — October 11, 2026

Final automated verification: **132 tests passed against disposable PostgreSQL**,
including concurrent cache claims and ownership checks. Django system checks and
migration drift checks passed. The real HTMX panel browser check passed at both
viewport sizes with synthetic responses. No schema migration is required.

A quota-bounded run captured 80 successful search batches using the deployed key
and shared limiter, then replayed the final matcher offline. All 30 core paired
cases were collected. The targeted set remains partially collected because the
80-search daily allowance was reached.

| Set | Completed old/new cases | Old/new cards | New empty cases |
| --- | --- | --- | --- |
| Development | 20 / 20 | 60 / 17 | 11 / 20 |
| Held out | 10 / 10 | 30 / 4 | 6 / 10 |
| Targeted | 6 / 4 | 18 / 4 | 2 / 4 |

These are retrieval counts, **not relevance or coverage scores**. Metadata review
reproduced wrong-service, wrong-engine and inspection/replacement failures in the
old results. It also exposed vocabulary gaps and generic-advice false positives;
those now have synthetic regression tests. The new strict matcher leaves many
services empty, especially on Nissan and Subaru, when explicit fit evidence is
missing. Do not weaken the evidence rules simply to fill three cards.

An isolated browser could open a candidate watch page, but attempts to play and
seek three sampled videos did not produce reviewable frames in this environment.
No videos were marked relevant on the strength of metadata alone.

**Release gate: not passed.** Full independent video-content review and availability
labels are still outstanding, and the remaining targeted searches need a later
quota window. The evaluation itself did not change production code, settings or deployment;
it consumed normal shared YouTube search counters only. The temporary artifact
is `/private/tmp/garage-video-evaluation-20261011.json`; do not commit it.


## Release — October 11, 2026

The user subsequently requested release of this implementation with the disclosed
review and coverage limitations. The relevance gate above remains unpassed; this
release is not evidence that the 90% relevance / 80% coverage targets were met.

- Helm release `garage`, namespace `vehicle-maintenance`, revision **8**.
- OpenShift build `garage-11`, immutable image digest
  `sha256:bb4329cf7af57012b918a14141c0b1eae99b26c67acdc78bbba473aa9341e6c0`.
- Pre-release backup `garage-backup-video-release-20261011-2155` completed and
  verified its archive. Migration/import job `garage-migrate-8` completed; no
  schema migrations were needed. Web rollout completed successfully.
- HTTPS liveness/readiness and login page returned 200. Anonymous vehicle setup
  redirected to Google login. Deployed-code checks accepted a synthetic matching
  oil tutorial, rejected wrong-engine/wrong-action candidates, and rendered the
  expected empty-result panel. These checks did not consume provider quota.
- Google login remains required and the shared daily search cap remains 80.
  All 80 searches were already used at release time. New lookups therefore use
  search-link fallback until the next Pacific-day budget window; cached failures
  can persist for five minutes after that reset.
- No authenticated live browser session was available for an end-to-end owner
  check. Desktop/mobile HTMX behavior was verified locally with synthetic data.
