# File layouts

All files are fictional samples. Field names follow the shape of a construction ERP's equipment (EM) module and are illustrative.

## Inputs

### Telematics daily summary (`data/telematics_daily_oct2026.csv`)

One row per unit per day, pulled nightly from the telematics provider. Most OEM and aftermarket providers can deliver this through an AEMP 2.0 / ISO 15143-3 style API (cumulative operating hours, location) or a scheduled export.

| Field | Meaning |
|---|---|
| unit | Equipment number, matched to the ERP equipment master |
| date | Calendar day |
| geofence | Primary geofence for the day (most engine hours); mapped to a job in `data/jobs.csv` |
| engine_hours | Engine-on hours for the day |
| meter_start / meter_end | Hour meter readings; also feed EM meter readings for preventive maintenance |
| idle_pct | Share of engine hours at idle |

**[GUESS]** A unit that works two jobs in one day is assigned to the geofence with the most hours. Production should split by geofence time.

### HeavyJob field timecards (`data/heavyjob_timecards_oct2026.csv`)

Where hours are born. One timecard per foreman per job per day, one row per operator, as exported from HeavyJob (HCSS).

| Field | Meaning |
|---|---|
| hj_row, hj_timecard | Row and timecard IDs (illustrative format) |
| date, foreman, job, cost_code | Work date, foreman, job and HeavyJob cost code (maps to the ERP phase) |
| employee, labor_hours | Operator and hours worked |
| equipment, equip_hours | Machine and hours used; blank = no equipment entered in the field |
| status | Approved - exported to payroll, or Approved - export failed |

### Payroll timecards (`data/pr_timecards_oct2026.csv`)

One line per operator per day, imported from approved HeavyJob timecards. The equipment columns are what the payroll ledger update posts to EM usage.

| Field | Meaning |
|---|---|
| tc_line, hj_row | ERP timecard line ID and the HeavyJob row it was imported from |
| pr_co, pr_batch, pr_end_date | Payroll company (the company that owns the job [GUESS]), weekly batch, period ending Friday |
| employee, date, job, phase | Operator, work date, job and phase for the labor |
| labor_hours | Operator's hours (shift) |
| equipment, equip_hours, equip_rate | Equipment columns: unit, hours the machine was used, rate. Blank equipment = no usage posted |

### Posted EM usage (`data/em_usage_posted_oct2026.csv`)

What the ERP already holds: usage posted by the payroll ledger update. Ties back to the timecard by `tc_line`.

| Field | Meaning |
|---|---|
| trans | EM transaction number |
| em_co | Company that owns the unit (receives the revenue) |
| jc_co | Company that owns the job (pays the cost) |
| pr_batch, tc_line, employee | Payroll batch and timecard line the usage came from |
| unit, date | Equipment and actual date |
| job, phase, cost_type | JC posting (JC company 2) |
| rev_code | 1 = hourly operating |
| hours, rate, amount | Time units, rate and dollars |
| source, foreman | Where the line came from |

## Output: EM usage import (`output/EM_Usage_Import_Oct2026.csv`)

Uploaded through the ERP's Import Manager into an **EM usage posting batch**, one batch per owning EM company. Header row included here for readability; strip it if the template is set to "no header".

| Column | Example | Notes |
|---|---|---|
| Co | 2 | EM company that owns the unit |
| Mth | 10/1/2026 | Batch month |
| BatchSeq | 14 | Sequence within the batch |
| Equipment | R-305 | |
| RevCode | 1 | |
| ActualDate | 10/21/2026 | The day the machine worked, so the rate in effect that day applies |
| JCCo / Job / Phase / JCCostType | 2 / 26-1118 / 20-200 / 3 | Where the cost lands; JCCo ≠ Co means intercompany |
| WorkUM / TimeUnits | HRS / -8.00 | Negative hours reverse an original line |
| Rate / Dollars | 72.00 / -576.00 | |
| Description | `F016 WRONG_JOB: Reverse EM-70301 ...` | Finding ID ties every line back to the rec |

### Import template settings [GUESS]

- Form: EM usage posting (revenue breakdown follows the revenue code)
- Record type: single record per line, comma delimited
- Defaults: GL accounts from the equipment's department and revenue code (not overridden in the file)
- Intercompany: allowed both ways (Co 1 loaders on Co 2 jobs, Co 2 trucks on the Co 1 plant job); the ERP creates the due-to/due-from on posting
- After upload: validate the batch, review the batch total against `correction_total` in the run summary, then post

## Output: labor reclass for payroll (`output/labor_reclass_for_payroll_oct2026.csv`)

Operator hours that payroll charged to the crew's job while the machine (and operator) worked another. Booked as a JC labor cost transfer; gross pay doesn't change. `cross_company = Y` lines also need the intercompany labor entry.

## Output: missing from payroll (`output/missing_from_payroll_oct2026.csv`)

Rows approved in HeavyJob that never reached ERP payroll. The operator is owed the labor hours on the next payroll; the equipment hours are posted through the correction batch.
