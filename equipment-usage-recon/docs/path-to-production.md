# Path to production: equipment usage reconciliation in a real ERP

The demo uses simulated feeds. This page covers what the same design looks like against three ERPs, and how I'd roll it out.

> Based on publicly documented features as of late 2026. Modules and options vary by version, hosting and licensing; confirm each item with the ERP admin and vendor.

## The design stays the same

1. **Field time:** HeavyJob (or another field time-tracking app) timecards, read through its API or export, tied row by row to ERP payroll.
2. **Telematics feed:** daily engine hours, hour meter and geofence per unit (provider API or export).
3. **Posted usage:** read from the ERP, never re-keyed.
4. **Rec engine:** unit-by-day classification, auto-fix the objective errors, route the rest.
5. **Corrections post through the ERP's own usage transaction,** not a journal entry, so job cost, equipment revenue, meters and intercompany stay consistent.
6. **Tie-out and audit log** on every run.

## Trimble Viewpoint Vista

| Piece | How |
|---|---|
| Read posted usage | SQL views over EM cost detail and JC cost detail (read-only reporting access), or a saved report export |
| Rates | EM revenue rates by category, with equipment-level overrides and job revenue templates where used |
| Post corrections | **Import Manager** into an EM usage posting batch (this demo's file), then validate and post |
| Usage source | HeavyJob timecards exported into PR timecard entry with equipment columns; the PR ledger update posts usage to EM and JC. Read PR timecard detail to tie usage back to its timecard line |
| Labor follow-up | Wrong-job operator hours fixed with a JC cost adjustment (labor) or a PR timecard correction before the batch closes |
| Meters | The same telematics feed can post EM meter readings so preventive maintenance runs on real hours |
| Intercompany | Cross-company usage (EM Co ≠ JC Co) books the due-to/due-from automatically on post |

Notes:
- **No direct SQL writes.** Reads only; every change goes through a batch.
- **Run weekly after each payroll batch posts,** and once more before JC close, so foremen fix timecards while they remember the day and corrected job cost flows to the WIP schedule.
- Trimble offers equipment and telematics integrations through its own platform; worth checking before building a custom feed.

## HeavyJob (HCSS) as the field source

- HCSS offers APIs and payroll export integrations for HeavyJob timecards; read approved timecards (labor, equipment, cost codes, approval status) for the month.
- Tie every exported row to an ERP payroll line and flag anything approved but not exported before the payroll batch closes. That one check protects paychecks, job cost and equipment revenue at once.
- Keep the HeavyJob cost code to ERP phase map, and employee and equipment IDs, in one maintained cross-reference.
- HCSS also sells telematics; if the fleet reports there, engine hours and geofences can come from the same vendor.

## Oracle NetSuite

NetSuite has no native construction equipment-rate module, so the design adds one:

| Piece | How |
|---|---|
| Equipment and rates | Custom records (Equipment, Rate by category with effective dates), or a construction SuiteApp that provides them |
| Usage | Custom transaction or time-based charges on the project (SuiteProjects), posting job cost and internal equipment revenue |
| Corrections | SuiteTalk REST or CSV import of reversing/reposting usage records; SuiteQL to read posted usage |
| Intercompany | NetSuite OneWorld intercompany journals or advanced intercompany auto-elimination between subsidiaries |

## Deltek

| Product | Approach |
|---|---|
| **ComputerEase** (construction) | Equipment costing module charges jobs at equipment rates; corrections by its file import; rec engine reads exports |
| **Costpoint** | Equipment usage typically charged as project costs at standard rates (e.g., via timesheets or a non-labor usage import) against project/task; confirm the module in use |
| **Vantagepoint** | Equipment charged as project expenses via Transaction Center imports or the REST API |

## Rollout plan

1. **Discovery (2 weeks):** how HeavyJob exports to payroll, rate structure (hourly on actual hours used), which units have telematics, who approves.
2. **Map geofences to jobs (1 week):** with the equipment manager; set a standard for naming new job geofences at mobilization.
3. **Parallel run (1 close):** run the rec but post nothing; review every finding with two superintendents to tune the hours tolerance.
4. **Go live:** auto-fix duplicates and rates first, add approved categories once supers trust the evidence.
5. **Operate:** weekly run during the month (not just month-end) so foremen fix timecards while they remember the day.

**People involved:** equipment manager (telematics and geofences), superintendents (approvals), payroll (timecard fixes), ERP admin (import template, read access), controller (tolerances and sign-off).
