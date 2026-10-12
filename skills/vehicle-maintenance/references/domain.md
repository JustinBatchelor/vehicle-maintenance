# Domain rules and implementation traps

## Maintenance and observations

`VehicleConfiguration` selects a reviewed `ScheduleVersion`, its source, and
applicable `MaintenanceRule` rows. Rules point to `MaintenanceItem` types.
`garage/services.py` selects rules by conditions, equipment, transmission,
drivetrain and priority before calling the pure `garage/calculator.py` module.
Read both when changing applicability: similarly named normal/severe rules are
alternatives, not necessarily separate tasks to display.

- Evaluate miles, calendar time, and engine hours independently. Apply whichever
  occurs first, preserving distinct first/subsequent intervals.
- `service` rules use qualifying service; `milestone` rules stay anchored to
  original vehicle age/mileage; `conditional` rules remain as-needed. Completing
  an item must not reset unrelated items or every original milestone.
- Missing history or a missing required dimension stays unknown unless a known
  dimension already establishes due/overdue status. Due-soon defaults are 30 days
  or 500 miles. Inject dates into calculator tests; do not rely on today's date.
- `Vehicle.latest_reading` considers observed odometer readings and completed
  service records. Keep its observation date visible; never substitute estimated
  mileage. Backdated edits/deletions must trigger correct recalculation.

`assume_maintained` defaults to true at setup. Store a frozen
`assumed_through_date/miles/hours` baseline, not synthetic `ServiceRecord` rows.
For history-free items, choose the next manufacturer mileage milestone beyond
that baseline. A normal-use Altima entered at 133,600 miles targets its next
7,500-mile oil milestone at 135,000, not 141,100. With an in-service date, time
uses vehicle-age milestones; otherwise the recurring interval starts at the
assumption date, with that assumption explained in the UI.

Actual service history takes precedence per item, even when backdated.
`original_items` explicitly means never serviced and uses initial requirements;
`unknown_items` disables the baseline for those items. “Use setup assumption”
clears those overrides. Mileage updates and ordinary edits do not advance the
baseline. Disabling it clears it; re-enabling uses the latest observation.

The server orders recommendations by status, then name. `static/app.js` makes
Upcoming include both `due-soon` and `upcoming`, orders required before optional,
and preserves the server order within each group. Other filters restore the
original order. Do not persist filters across pages/devices.

## Catalog changes

Use `data/REVIEW.md` for source tables, footnotes and applicability decisions.
The Ford source is the general `10frdmg2e.pdf`, not the Raptor supplement.
There are multiple mechanical configurations within the three supported models;
do not reduce coverage to trim names alone.

Change the generator `scripts/build_catalog.py` and regenerate
`data/schedules.json`; keep them consistent. Review changed tables/footnotes
against the official publication. Preserve source URL, publication identity,
SHA-256, page references, review metadata and optional-vs-required distinctions.
Increment the dataset version instead of mutating an already published version.
`import_schedules` validates and imports transactionally and idempotently;
normal page requests read PostgreSQL, not manufacturer websites. New coverage
must pass the same review process; search/video results are not schedule sources.

## Accounts and legacy ownership

`Garage.owner` is a nullable, unique relationship to the Django user. Null exists
for historical browser garages, not a new anonymous-access feature. Middleware
resolves access through the authenticated Google owner. All private child objects
must be fetched through that garage, even when their UUID is known.

`garage/accounts.py` and the explicit routes in `config/urls.py` deliberately
expose only the supported account operations; including all allauth URLs would
reintroduce unwanted signup/password/provider-management endpoints. Require a
verified Google email and stable Google provider UID. Never merge accounts by
email or retain Google access/refresh tokens. Login initiation and logout are
CSRF-protected POSTs; limits use shared database storage.

Legacy migration requires authenticated, explicit confirmation and proof from
the old server-side session or a recovery code. Lock the user and source garage
inside a transaction. If a destination garage exists, move vehicles preserving
IDs and all attached readings, assumptions, history and appointments; retain the
destination name/timezone. Reject imports exceeding 30 vehicles atomically;
do not deduplicate similar vehicles. Invalidate recovery codes after success.
An already owned garage cannot be claimed with an old cookie/code. Do not infer
ownership from a matching email or manually assign a user's legacy data without
valid evidence and authorization.

Django admin also requires Google authentication and staff status. Privilege
assignment is an explicit operator action using `grant_google_admin USER_ID`,
not an automatic consequence of signup or a feature-testing workaround.

## Service records and exports

Appointments contain one or more maintenance items but never satisfy a service
requirement. Completed records contain actual date, mileage, optional hours,
cost, provider and notes; preserve editing, deletion and backdating validation.
CSV exports escape spreadsheet formulas and contain actual history, not setup
assumptions. ICS events are all-day, have an exclusive end date and stable UID,
and exclude private costs/notes. Calendar links require the user to save in Google;
later edits do not synchronize previously exported events.

## YouTube discovery

Expansion loads an authenticated HTMX fragment; external calls do not block
page rendering. `garage/video_profiles.py` contains task phrases, component/action
synonyms, conflicts and required mechanical dimensions, separately from schedules.
`queries()` uses the public year/make/model and only procedure-relevant details.
Unknown item profiles fail closed to a vehicle/task search link.

At most two vehicle-context searches retrieve up to 15 candidates each. Keep
inspection and replacement separate; reject wrong models, explicit configuration
conflicts and missing critical details. Titles must identify the component;
only short procedural narrative can add positive description evidence. Keyword
lists alone cannot establish a match. A stated year/range must include the target;
no neighboring-year compatibility is currently inferred or approved.

`search.list` candidates are checked with batched `videos.list`. Preserve provider
ordering among accepted candidates, deduplicate IDs and filter unavailable/private/
live/region-blocked results. Display zero to three linked cards, labeled possible
matches, with attribution and a search fallback. No embeds or user YouTube OAuth.
Never send identity, VIN, mileage, nickname or private notes to the provider.

Cache keys include search/profile versions and mechanical context, never owner.
The existing JSON field stores an envelope with videos and outcome (matches,
no_matches, unavailable). Empty and failure notices survive cache hits. Results
last seven days, empty results one day, failures/partial failures five minutes.
The atomic lease AND expiry check prevent duplicate requests. Cleanup deletes
metadata older than 30 days. Per-user throttling and the shared project search cap
are separate; daily counters use Pacific time. Never raise the cap to run tests.
Failures preserve maintenance operations. Logs include outcome, candidate/card
counts and elapsed time, never HTTP exception text, URLs or keys.

`scripts/evaluate_videos.py` defines 20 development, 10 held-out and 10 targeted
cases, reproduces the old search behavior, and applies the new matcher to fresh
provider results. Live mode is explicit and quota-bounded. `--cluster` keeps the
key inside the existing web pod and reserves searches through its existing shared
limiter; it does not deploy code or write garage/service data. Evaluation artifacts
must stay outside Git and expire after 29 days. Permanent fixtures are synthetic.
Do not confuse mocked tests or metadata review with watching instructional content.
A benchmark without independent human labels/availability checks cannot pass.
See `docs/video-discovery.md` for commands, gates and the latest evaluation status.
