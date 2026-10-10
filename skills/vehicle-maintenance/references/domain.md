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
dashboard rendering. `queries()` uses public vehicle configuration and procedure
search phrases, progressing from vehicle-specific to model to general. Keep
inspection and replacement phrases distinct. Never send identity, VIN, mileage
or private notes. Label broader results and state that applicability is unverified.

`search.list` candidates are checked with `videos.list`: preserve ordering,
deduplicate IDs, filter unavailable/private/live/region-blocked results, show at
most three linked cards with attribution, and retain the YouTube search fallback.
No embeds or user YouTube OAuth are used.

Cache by query context, not owner. Results last seven days, empty results one
day, failures five minutes; the database lease prevents simultaneous duplicate
requests. Cleanup deletes metadata older than 30 days. Per-user throttling and
the project search-request budget are separate; the daily budget uses Pacific
time. Do not confuse the app's search count with Google's quota units. Changes
to API requests or storage policy warrant checking current official documentation.
API failures must preserve maintenance operations. HTTP client debug logging
can disclose API-key query strings; retain the existing sanitized logging.
