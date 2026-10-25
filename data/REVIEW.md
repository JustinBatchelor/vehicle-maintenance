# Manufacturer dataset review

Schedule versions: `2026.10.09.2` for existing vehicles; `2026.10.25.1` for the
2026 Ascent Limited. Market: United States. Ascent reviewed October 25, 2026;
existing schedules retain their October 9 review and unchanged rules.

The catalog contains factual intervals and paraphrased applicability notes, not
copies of the manuals. Source PDFs are downloaded for review outside the repo.
Their SHA-256 checksums and publication URLs are in `schedules.json`. `page`
means PDF page number (one-based); Nissan's printed page numbers are two lower.

## Ford

Source: 2010 Model Year Scheduled Maintenance Guide, second printing,
`10frdmg2e.pdf`. Reviewed truck tables on PDF pages 14–27, general limits on
page 5, owner checks on page 8, special conditions on pages 41–45, and axle
exceptions on page 47. The original planning link `10f12rp1e.pdf` is an SVT
Raptor supplement and is deliberately **not** used for the King Ranch.

Key applicability decisions:

- King Ranch configurations use the 5.4L V8 and 6R80 automatic, with 4x2/4x4 choices.
- The 6R80 is explicitly excluded from severe-use 30,000-mile ATF changes.
- Spark plugs appear at 90,000 miles in the normal truck table, 60,000 for extensive idling.
- F-150 is excluded from the generic scheduled fuel-filter replacement.
- Cabin/seat filters and transmission dipstick inspections require explicit equipment confirmation.
- Front differential and transfer-case work is restricted to 4x4.
- Rear axle replacement is conditional: the page-47 Ford-design/synthetic-axle exception overrides the generic page-27 row.
- Belt replacement at 150,000 miles depends on whether it was replaced within 100,000 miles. It is shown as conditional, not an invented unconditional interval.
- Oil under extensive idling also has a 200-engine-hour limit. Missing hour readings are shown as an incomplete baseline, not ignored.

## Nissan

Source: 2012 Nissan Service and Maintenance Guide. Reviewed schedule selection
on PDF page 11; explanations on pages 12–14; schedule tables including pages
17, 19, 23, 28, 33, 38, and 51.

- Separate Schedule 1/2 oil and inspection intervals; conditions apply only to matching work.
- Altima has no separately scheduled differential or transfer-case service in this guide.
- CVT and manual coupe configurations are separate. The specific CVT deterioration-check/replacement alternative on printed page 12 is presented as conditional work at 60,000 miles under the listed conditions, not generic 30,000-mile ATF replacement.
- Brake fluid: 30,000 miles/24 months normal; 15,000 miles/12 months Schedule 1.
- Drive-belt inspection starts at 60,000 miles/48 months, then follows the 15,000-mile/12-month inspection entries.
- Blue factory coolant: first 105,000 miles/84 months, subsequent 75,000/60.
- Premium upgrade items are explicitly optional and excluded from dashboard required-maintenance counts.

## Subaru

Source: 2021 Warranty and Maintenance Booklet, MSA5M2101W. Visually checked
the page-28 table and read page-29 notes and page-27 continuation guidance.

- Limited uses the 2.5L CVT AWD configuration. STI timing belt, BRZ, hybrid and manual-only rows are excluded.
- Oil/filter and tire rotation: 6,000 miles/6 months. Spark plugs and wheel-bearing inspections: 60,000/60. Cabin filter: 12,000/12.
- Air filter and relevant fluid/system inspections use 30,000/30; fuel filter 72,000/72.
- Factory coolant: first 137,500/132; subsequent 75,000/72.
- Severe conditions are mapped by the item numbers in the notes. Repeated towing brings CVT replacement to 24,855 miles and differential replacement to 15,000/15.
- Brake-fluid replacement remains distinct from the additional severe-use fluid inspection; high humidity/mountainous operation shortens replacement to 15,000/15.

## Subaru Ascent — 2026, normal use

Source: US 2026 Warranty and Maintenance Booklet,
`6680519_26a_Subaru_Warranty_and_Maintenance_TEXT_HR_051925.pdf`.
SHA-256: `efefdeb029aa8310e2a5626c0a2eb018136681e3b8b6044ae38ba6a0d9e00e82`.
The stable source link is Subaru's 2026 Ascent Limited vehicle-resources page;
its public `/services/documentation/trim/TCL` listing supplies the booklet's
temporary download URL. Do not store signed download parameters in the catalog.
Visually reviewed PDF page 28 and read pages 27 (continuation) and 29 (notes).

- Configuration: Limited, 2.4L turbo flat-four, CVT, AWD. Seating does not change
  the reviewed maintenance table. Manual/clutch and BRZ-only rows are excluded.
- Oil/filter and tire rotation: 6,000 miles/6 months. Cabin filter, brake-system,
  pad/disc, axle-boot/joint, and steering/suspension inspections: 12,000/12.
- Air filter and brake-fluid replacement, drive belts, fuel lines, cooling system,
  and differential inspections: 30,000/30. CVT **inspection**: 36,000/36; do not
  copy the existing Crosstrek catalog's 30,000/30 interval or label it replacement.
- Spark plugs and wheel-bearing inspection: 60,000/60. Fuel filter: 72,000/72.
- Factory coolant: first 137,500 miles/132 months, then 75,000/72. Preserve
  page-29 note 10's conditioner instruction and distinguish first/subsequent work.
- Tire wear, filter contamination/dust, and warranty-related footnotes remain
  notes, not invented extra replacement deadlines. Inspection includes correcting
  or replacing components when necessary.
- Normal use is the reviewed scope. The page-29 severe-condition item numbers
  do not consistently align with the renumbered page-28 table. No severe-use
  toggles or inferred remapping are published for this configuration. Drivers
  with those conditions need additional source review before relying on this
  normal-use schedule alone.

The new schedule reuses existing maintenance item types without changing their
meaning. All earlier source, item, schedule, and configuration entries are kept
unchanged; the catalog regression test verifies that published snapshot.

## Calculation interpretation and limits

`milestone` rules follow original odometer/vehicle-age columns. `service` rules
follow elapsed limits since actual service, including oil and subsequent coolant
replacement. `conditional` rules retain source notes without turning alternatives
or condition checks into a fabricated fixed deadline. Confirming an item has
never been serviced applies its initial limits; absence of a record alone is
not that confirmation.

The optional setup assumption uses the next original mileage/age milestone
after the entered starting point, including first/subsequent limits, until
actual history is available. Without an in-service date, assumed time cycles
start at the entered date using recurring intervals. This planning assumption
is labeled in the UI and creates no completed service records. It does not
change the reviewed manufacturer intervals in this dataset.

The latest recorded service establishes the known baseline, but does not prove
that earlier work occurred. Backdated work cannot replace a later recorded
service; actual work does override a setup assumption for that item.
Source references and notes remain visible so users can check applicability,
especially for modified vehicles or non-original fluid types. These datasets
cover scheduled maintenance in the cited publications, not diagnostics, recalls,
repairs, or every daily-use instruction in the separate owner's manuals.

## Updating

Edit `scripts/build_catalog.py`, increment the dataset version, regenerate with
`python scripts/build_catalog.py`, review source tables/footnotes, add or change
independent regression cases, then run `python manage.py import_schedules`.
Rules within a published version are immutable; a new version keeps old rule
rows for provenance while configurations move to the reviewed replacement.
Import is transactional and idempotent. Document metadata can be refreshed, but
the checksum must remain the exact reviewed document's checksum.
