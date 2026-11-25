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

### Posted EM usage (`data/em_usage_posted_oct2026.csv`)

What the ERP already holds: usage posted from payroll timecards.

| Field | Meaning |
|---|---|
| trans | EM transaction number |
| em_co | Company that owns the unit (receives the revenue) |
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
| JCCo / Job / Phase / JCCostType | 2 / 26-1118 / 20-200 / 3 | Where the cost lands |
| WorkUM / TimeUnits | HRS / -8.00 | Negative hours reverse an original line |
| Rate / Dollars | 72.00 / -576.00 | |
| Description | `F016 WRONG_JOB: Reverse EM-70301 ...` | Finding ID ties every line back to the rec |

### Import template settings [GUESS]

- Form: EM usage posting (revenue breakdown follows the revenue code)
- Record type: single record per line, comma delimited
- Defaults: GL accounts from the equipment's department and revenue code (not overridden in the file)
- Intercompany: allowed, because Co 1 units post to Co 2 jobs; the ERP creates the due-to/due-from on posting
- After upload: validate the batch, review the batch total against `correction_total` in the run summary, then post
