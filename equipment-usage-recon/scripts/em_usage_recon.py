"""
Copperhollow Paving & Grading -- equipment usage reconciliation (FICTIONAL DATA ONLY)

Crews enter labor and equipment hours in the field in HeavyJob (HCSS). Approved
HeavyJob timecards are exported to ERP payroll timecards, and the payroll ledger
update posts the equipment hours to EM (revenue for the owning company) and JC
(equipment cost on the job). Usage is billed on ACTUAL hours used.

This script compares what the telematics devices say each machine did (engine
hours and the job-site geofence it worked in) with the usage payroll posted, then:

  1. classifies every unit-day and every posted usage line exactly once
  2. proposes the correcting EM usage lines (reversal + repost) for each fixable item
  3. holds judgment calls for the superintendent with the dollars at stake
  4. writes an EM Usage import file, a review queue, a labor reclass list for
     payroll, the GL effect by company (intercompany both ways) and a tie-out

Run:  python em_usage_recon.py            (writes to ../data and ../output)
Every company, job, unit, person and dollar amount here is invented.
"""
import csv, json, random
from collections import defaultdict, Counter
from datetime import date, timedelta
from pathlib import Path

random.seed(1031)
ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "output"
DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)

MONTH = date(2026, 10, 1)
MONTH_END = date(2026, 10, 31)
HOURS_TOLERANCE = 1.0        # posted vs engine hours per unit-day before it is corrected to actual [GUESS]
MIN_UNPOSTED_HOURS = 1.0     # engine hours on a job site with no usage posted -> propose usage
RATE_CHANGE = date(2026, 10, 16)

COMPANIES = {1: "Copperhollow Materials Co.", 2: "Copperhollow Paving & Grading"}

# Revenue code 1 = hourly operating rate. Rates by category, with effective dates.
# category -> (description, [(effective date, $/hr)], job phase)
CATEGORIES = {
    "PAV": ("Asphalt Paver",          [(MONTH, 185.00), (RATE_CHANGE, 195.00)], "20-200"),
    "ROL": ("Roller",                 [(MONTH, 68.00), (RATE_CHANGE, 72.00)],   "20-200"),
    "MIL": ("Cold Planer (Milling)",  [(MONTH, 410.00)],                        "20-100"),
    "TKT": ("Tack Distributor Truck", [(MONTH, 75.00)],                         "20-200"),
    "SKD": ("Skid Steer",             [(MONTH, 48.00)],                         "10-300"),
    "EXC": ("Excavator",              [(MONTH, 120.00)],                        "10-300"),
    "DTK": ("Tandem Dump Truck",      [(MONTH, 82.00)],                         "20-150"),
    "LDR": ("Wheel Loader",           [(MONTH, 95.00)],                         "10-300"),
}
PHASES = {"20-100": "Milling", "20-200": "Paving", "20-150": "Hauling", "10-300": "Earthwork / Base"}
COST_TYPE = 3                # JC cost type 3 = Equipment [GUESS]
REV_CODE = "1"

# Fleet: unit -> (category, owning EM company, telematics device fitted?)
FLEET = {}
def _units(prefix, cat, n, start, co=2, no_tel=()):
    for i in range(n):
        u = f"{prefix}-{start + i}"
        FLEET[u] = dict(category=cat, em_co=co, telematics=u not in no_tel)
_units("P", "PAV", 4, 201)
_units("R", "ROL", 8, 301)
_units("M", "MIL", 2, 401)
_units("K", "TKT", 2, 451)
_units("S", "SKD", 4, 501, no_tel=("S-504",))
_units("X", "EXC", 2, 551)
_units("T", "DTK", 8, 601, no_tel=("T-607", "T-608"))
_units("L", "LDR", 2, 901, co=1)              # owned by the materials company; also loaned to paving jobs
PAVING_ONLY = ("PAV", "ROL", "MIL", "TKT")       # never work at the plant

JOBS = {   # jc_co: the company that owns the job (and whose payroll the crew is on) [GUESS]
    "26-1104": dict(jc_co=2, desc="Hwy 9 Mill & Overlay",           geofence="GF-1104"),
    "26-1112": dict(jc_co=2, desc="Cedar Ridge Subdivision Ph 2",   geofence="GF-1112"),
    "26-1118": dict(jc_co=2, desc="County Rd 41 Widening",          geofence="GF-1118"),
    "26-1125": dict(jc_co=2, desc="Riverside Commons Parking Lot",  geofence="GF-1125"),
    "26-1131": dict(jc_co=2, desc="Airport Taxiway C Rehab",        geofence="GF-1131"),
    "26-9010": dict(jc_co=1, desc="Plant 1 Stockpile & Yard Work",  geofence="GF-PLANT1"),
}
PAVING_JOBS = [j for j, v in JOBS.items() if v["jc_co"] == 2]
GEOFENCES = {j["geofence"]: job for job, j in JOBS.items()}
GEOFENCES["GF-YARD"] = None                    # equipment yard, not a job

# Fictional GL accounts (same chart in both companies)
SHORT = {1: "Copperhollow Materials", 2: "Copperhollow Paving"}
def gl(co, kind, other=None):
    return {"jc":     ("5410.", "Job Cost - Equipment"),
            "rev":    ("4610.", "Equipment Revenue - Internal"),
            "icrev":  ("4615.", "Equipment Revenue - Intercompany"),
            "duefrom": ("1450.", f"Due from {SHORT.get(other, '')}"),
            "dueto":  ("2450.", f"Due to {SHORT.get(other, '')}")}[kind]


def money(x): return round(x + 1e-9, 2)
def half(x): return max(0.5, round(x * 2) / 2)
def mdy(d): return f"{d.month}/{d.day}/{d.year}"


def rate_for(unit, d):
    rate = None
    for eff, r in CATEGORIES[FLEET[unit]["category"]][1]:
        if d >= eff: rate = r
    return rate


def workdays():
    d = MONTH
    while d <= MONTH_END:
        if d.weekday() < 5: yield d
        d += timedelta(days=1)


# --------------------------------------------------------------------------- generate
def generate():
    """What really happened (telematics) and what got posted (timecards)."""
    days = list(workdays())
    tel, usage = [], []
    meter = {u: random.randint(1800, 9400) + random.random() for u in FLEET}
    job_list = list(PAVING_JOBS)

    for u, f in FLEET.items():
        # equipment moves between jobs in stretches of a few days
        pool = (PAVING_JOBS if f["category"] in PAVING_ONLY
                else ["26-9010"] * 4 + PAVING_JOBS if f["em_co"] == 1
                else PAVING_JOBS + ["26-9010"] if f["category"] in ("DTK", "SKD") else PAVING_JOBS)
        cur, left = random.choice(pool), 0
        for d in days:
            if left <= 0:
                cur = random.choice(pool + [None]) if random.random() < 0.85 else None
                left = random.randint(2, 6)
            left -= 1
            if cur is None:
                site, hrs = "GF-YARD", round(random.uniform(0, 1.2), 1)
            else:
                site, hrs = JOBS[cur]["geofence"], round(min(11.0, max(2.5, random.gauss(7.4, 1.3))), 1)
            start = meter[u]; meter[u] += hrs
            if f["telematics"]:
                tel.append(dict(unit=u, date=d.isoformat(), geofence=site, engine_hours=hrs,
                                meter_start=round(start, 1), meter_end=round(meter[u], 1),
                                idle_pct=random.randint(8, 31)))
            if cur is not None:
                posted = half(hrs + random.uniform(-0.45, 0.55))
                usage.append(dict(unit=u, date=d.isoformat(), job=cur, hours=posted,
                                  rate=rate_for(u, d), source="PR timecard",
                                  foreman=random.choice(["Foreman 12", "Foreman 18", "Foreman 23", "Foreman 31"])))

    # ---- scenario knobs: the mistakes a real month produces ----
    tel_by = {(t["unit"], t["date"]): t for t in tel}
    def on_job(u):  # posted lines for unit u that sit on a telematics job day
        return [x for x in usage if x["unit"] == u and (u, x["date"]) in tel_by]

    # 1) Milling machine ran 3 days but the crew's timecards never carried it
    drop = [x for x in usage if x["unit"] == "M-402"][3:6]
    # plus scattered missed units (crew forgot to add the machine to the timecard)
    for u in ("R-306", "T-603", "S-502", "X-552", "L-902"):
        drop.append(random.choice(on_job(u)))
    # intercompany both ways: a materials-company loader on a paving job, and a
    # paving-company truck and skid steer hauling at the plant, all left off timecards
    ic1 = [x for x in on_job("L-901") if JOBS[x["job"]]["jc_co"] == 2]
    ic2 = [x for x in usage if FLEET[x["unit"]]["em_co"] == 2 and FLEET[x["unit"]]["telematics"]
           and x["job"] == "26-9010" and x["unit"] not in ("S-502", "T-603")]
    drop += ic1[len(ic1) // 2: len(ic1) // 2 + 2] + ic2[:2]
    labor_only = []                    # operator still on the timecard, equipment column blank
    for x in drop:
        if x in usage: usage.remove(x); labor_only.append(x)

    # 2) Rate table changed 10/16 for pavers and rollers, but Foreman 23's
    #    timecard template still carried the old rates through 10/23
    for x in usage:
        if (FLEET[x["unit"]]["category"] in ("PAV", "ROL") and x["foreman"] == "Foreman 23"
                and RATE_CHANGE.isoformat() <= x["date"] <= "2026-10-23"):
            x["rate"] = CATEGORIES[FLEET[x["unit"]]["category"]][1][0][1]

    # 3) Roller and excavator charged to the job the crew was on, not where the machine was
    for u, n in (("R-305", 3), ("X-551", 2), ("T-602", 1)):
        c = on_job(u)
        for x in c[len(c) // 2: len(c) // 2 + n]:
            others = [j for j in PAVING_JOBS if j != x["job"]]
            x["job"] = others[n % len(others)]
            x["foreman"] = "Foreman 18"

    plant = [x for x in on_job("T-606") if x["job"] == "26-9010"]
    for x in plant[:2]:
        x["job"], x["foreman"] = "26-1118", "Foreman 12"

    # 4) Same timecard line keyed twice
    for u in ("P-202", "T-605", "S-501"):
        c = on_job(u); x = c[len(c) // 2]
        usage.append(dict(x))

    # 5) Hours on the timecard far above the machine's actual hours (shift hours keyed)
    for u, h in (("P-204", 10.0), ("R-302", 9.5), ("T-601", 10.0), ("X-552", 11.0), ("K-452", 9.0)):
        cand = [x for x in on_job(u) if tel_by[(u, x["date"])]["engine_hours"] < 6.0] or on_job(u)
        cand[0]["hours"] = h

    # 6) Usage posted on a day the machine never left the yard
    yard_units = [u for u in ("S-503", "R-308", "T-604", "R-307", "T-606", "S-502")
                  if any(t["unit"] == u and GEOFENCES[t["geofence"]] is None for t in tel)][:3]
    for u in yard_units:
        yard = [t for t in tel if t["unit"] == u and GEOFENCES[t["geofence"]] is None]
        t = yard[len(yard) // 2]
        usage.append(dict(unit=u, date=t["date"], job=random.choice(job_list), hours=8.0,
                          rate=rate_for(u, date.fromisoformat(t["date"])),
                          source="PR timecard", foreman="Foreman 31"))

    operator = {u: f"E{1100 + i}" for i, u in enumerate(FLEET)}
    lo_ids = {id(x) for x in labor_only}
    for x in usage + labor_only:
        x["labor"] = x["hours"] if x["hours"] >= 9.0 else half(x["hours"] + random.uniform(0.2, 1.4))

    # ---- HeavyJob (field): one timecard per foreman per job per day, one row per operator
    heavyjob = []
    for x in sorted(usage + labor_only, key=lambda x: (x["date"], x["foreman"], x["job"], x["unit"])):
        has_eq = id(x) not in lo_ids
        hj_tc = f"HJ-{date.fromisoformat(x['date']):%m%d}-{x['foreman'].split()[-1]}-{x['job'][-4:]}"
        x["hj_row"] = f"{hj_tc}-{sum(1 for h in heavyjob if h['hj_timecard'] == hj_tc) + 1:02d}"
        heavyjob.append(dict(hj_row=x["hj_row"], hj_timecard=hj_tc, date=x["date"], foreman=x["foreman"], job=x["job"],
                             cost_code=CATEGORIES[FLEET[x["unit"]]["category"]][2].replace("-", ""),
                             employee=operator[x["unit"]], labor_hours=x["labor"],
                             equipment=x["unit"] if has_eq else "", equip_hours=x["hours"] if has_eq else 0.0,
                             status="Approved - exported to payroll"))
    # One foreman's approved timecard never made it into ERP payroll (export error)
    touched = {"M-402", "R-306", "T-603", "S-502", "X-552", "L-902", "L-901", "R-305", "X-551", "T-602", "T-606",
               "P-202", "T-605", "S-501", "P-204", "R-302", "T-601", "K-452", "S-503", "R-308", "T-604", "R-307"}
    groups = defaultdict(list)
    for h in heavyjob: groups[h["hj_timecard"]].append(h)
    eligible = [k for k, g in sorted(groups.items()) if g[0]["date"] >= "2026-10-19"
                and all(h["equipment"] and h["equipment"] not in touched and FLEET[h["equipment"]]["telematics"] for h in g)]
    failed = max(eligible, key=lambda k: len(groups[k]))
    failed_rows = set()
    for h in groups[failed]:
        h["status"] = "Approved - export failed"; failed_rows.add(h["hj_row"])
    usage[:] = [x for x in usage if x["hj_row"] not in failed_rows]

    # ---- ERP payroll timecards (imported from HeavyJob); the equipment columns
    #      are what the payroll ledger update posts to EM and JC
    def week_end(iso):
        d = date.fromisoformat(iso); return d + timedelta(days=(4 - d.weekday()))
    timecards = []
    for x in sorted(usage + labor_only, key=lambda x: (x["date"], x["unit"])):
        co = JOBS[x["job"]]["jc_co"]
        has_eq = id(x) not in lo_ids
        lab = x["labor"]
        tc = dict(hj_row=x["hj_row"], tc_line=f"TC-{len(timecards) + 1:05d}", pr_co=co, pr_batch=f"PR{co}-{week_end(x['date']):%m%d}",
                  pr_end_date=week_end(x["date"]).isoformat(), employee=operator[x["unit"]], date=x["date"],
                  job=x["job"], phase=CATEGORIES[FLEET[x["unit"]]["category"]][2], labor_hours=lab,
                  equipment=x["unit"] if has_eq else "", equip_hours=x["hours"] if has_eq else 0.0,
                  equip_rate=x["rate"] if has_eq else 0.0, foreman=x["foreman"])
        timecards.append(tc)
        if has_eq: x["tc"] = tc

    # Number the posted lines the way the ERP would and price them
    usage.sort(key=lambda x: (x["date"], x["unit"]))
    for i, x in enumerate(usage, start=1):
        f = FLEET[x["unit"]]; tc = x.pop("tc")
        x.update(em_co=f["em_co"], jc_co=JOBS[x["job"]]["jc_co"], batch_seq=i, trans=f"EM-{70000 + i}",
                 phase=CATEGORIES[f["category"]][2], cost_type=COST_TYPE, rev_code=REV_CODE,
                 amount=money(x["hours"] * x["rate"]), source="PR ledger update",
                 pr_batch=tc["pr_batch"], tc_line=tc["tc_line"], employee=tc["employee"], labor_hours=tc["labor_hours"],
                 hj_row=x["hj_row"])
    return tel, usage, timecards, heavyjob


# --------------------------------------------------------------------------- reconcile
def reconcile(tel, usage, timecards, heavyjob):
    tel_by = {(t["unit"], t["date"]): t for t in tel}
    lines_by = defaultdict(list)
    for x in usage: lines_by[(x["unit"], x["date"])].append(x)

    findings, status = [], {}          # status: trans -> category for every posted line
    tel_status = {}                    # (unit,date) -> category for every telematics day
    labor_reclass = []                 # operator hours payroll charged to the wrong job
    missing_payroll = []               # approved HeavyJob time that never reached payroll
    hj_failed = {(h["equipment"], h["date"]): h for h in heavyjob if h["status"].endswith("failed") and h["equipment"]}
    hj_blank = {(h["employee"], h["date"]): h for h in heavyjob if not h["equipment"]}
    blank_tc = {(t["employee"], t["date"]): t for t in timecards if not t["equipment"]}
    operator = {}
    for t in timecards:
        if t["equipment"]: operator[t["equipment"]] = t["employee"]
    fid = 0

    def add(cat, unit, d, action, lines=(), corr=(), **kw):
        nonlocal fid; fid += 1
        f = dict(id=f"F{fid:03d}", category=cat, unit=unit, date=d, action=action,
                 lines=[l["trans"] for l in lines], corrections=list(corr), **kw)
        f["net_amount"] = money(sum(c["amount"] for c in corr))
        findings.append(f)
        for l in lines: status[l["trans"]] = cat
        return f

    def rev(l, why):    # reversal of a posted line (negative hours at the posted rate)
        return dict(unit=l["unit"], date=l["date"], job=l["job"], hours=-l["hours"], rate=l["rate"],
                    amount=money(-l["hours"] * l["rate"]), memo=f"Reverse {l['trans']} - {why}")

    def post(unit, d, job, hours, why):
        r = rate_for(unit, date.fromisoformat(d))
        return dict(unit=unit, date=d, job=job, hours=hours, rate=r, amount=money(hours * r), memo=why)
    def jc(job): return JOBS[job]["jc_co"]

    for key in sorted(set(tel_by) | set(lines_by)):
        unit, d = key
        t = tel_by.get(key)
        lines = list(lines_by.get(key, []))

        # A) duplicates: identical line keyed twice -> reverse the extra copy (auto)
        seen = {}
        for l in list(lines):
            k = (l["job"], l["hours"], l["rate"])
            if k in seen:
                add("DUPLICATE", unit, d, "auto", [l], [rev(l, "duplicate of " + seen[k]["trans"])],
                    detail=f"Same {l['hours']} hrs on {l['job']} already posted as {seen[k]['trans']}. "
                           f"Timecard {l['tc_line']} for {l['employee']} was keyed twice, so payroll should check the labor hours too",
                    payroll=f"Duplicate timecard {l['tc_line']} ({l['employee']}, {l['labor_hours']} labor hrs)")
                lines.remove(l)
            else:
                seen[k] = l

        if not FLEET[unit]["telematics"]:
            for l in lines: status[l["trans"]] = "UNVERIFIED"
            continue

        tel_job = GEOFENCES[t["geofence"]] if t else None
        eng = t["engine_hours"] if t else 0.0

        if not lines and key in hj_failed:
            h = hj_failed[key]
            missing_payroll.append(dict(hj_row=h["hj_row"], hj_timecard=h["hj_timecard"], foreman=h["foreman"],
                                        employee=h["employee"], date=d, job=h["job"], labor_hours=h["labor_hours"],
                                        equipment=unit, equip_hours=h["equip_hours"]))
            add("NOT_TRANSFERRED", unit, d, "auto", [], [post(unit, d, h["job"], h["equip_hours"], f"From approved HeavyJob {h['hj_timecard']}")],
                detail=f"HeavyJob timecard {h['hj_timecard']} ({h['foreman']}) is approved with {h['equip_hours']} equipment hrs, "
                       f"but the export to payroll failed, so nothing reached the ERP. Telematics agrees: {eng} engine hrs in {t['geofence']}. "
                       f"Operator {h['employee']}'s {h['labor_hours']} labor hrs are missing from payroll too",
                tel_hours=eng, posted_hours=0.0, payroll=f"Unpaid: {h['employee']} {h['labor_hours']} hrs ({h['hj_timecard']})")
            tel_status[key] = "NOT_TRANSFERRED"; continue

        if not lines:
            if tel_job and eng >= MIN_UNPOSTED_HOURS:
                hrs = half(eng)
                tc = blank_tc.get((operator.get(unit), d))
                hb = hj_blank.get((operator.get(unit), d))
                note = (f" Operator {tc['employee']} is on HeavyJob timecard {hb['hj_timecard'] if hb else '?'} and payroll line "
                        f"{tc['tc_line']} ({tc['pr_batch']}) for {tc['job']}, {tc['labor_hours']} hrs, with no equipment entered. "
                        f"The miss started in the field.") if tc else ""
                add("UNPOSTED", unit, d, "approve", [], [post(unit, d, tel_job, hrs, "Actual hours, not on timecard")],
                    detail=f"{eng} engine hrs in {t['geofence']} ({tel_job}); no usage posted by payroll.{note}",
                    tel_hours=eng, posted_hours=0.0, payroll=f"{tc['tc_line']} equipment column blank" if tc else "")
                tel_status[key] = "UNPOSTED"
            else:
                tel_status[key] = "IDLE_NO_USAGE"
            continue

        posted_hrs = sum(l["hours"] for l in lines)
        if tel_job is None:
            f = add("NO_ACTIVITY", unit, d, "review", lines, [],
                    detail=f"{posted_hrs} hrs posted to {lines[0]['job']}, but unit sat in {t['geofence']} ({eng} engine hrs)",
                    tel_hours=eng, posted_hours=posted_hrs)
            f["at_stake"] = money(-sum(l["amount"] for l in lines))
            tel_status[key] = "NO_ACTIVITY"; continue

        if abs(posted_hrs - eng) > HOURS_TOLERANCE:
            corr = [rev(l, "not actual hours") for l in lines] + [post(unit, d, tel_job, half(eng), f"Actual hours used ({eng} engine hrs)")]
            l0 = lines[0]
            add("HOURS_VARIANCE", unit, d, "approve", lines, corr,
                detail=f"{posted_hrs} hrs posted vs {eng} actual engine hrs. Timecard {l0['tc_line']} shows "
                       f"{l0['labor_hours']} labor hrs for {l0['employee']}: shift hours were keyed as machine hours",
                tel_hours=eng, posted_hours=posted_hrs, payroll=f"{l0['tc_line']} equipment hrs = shift hrs")
            tel_status[key] = "HOURS_VARIANCE"; continue

        if any(l["job"] != tel_job for l in lines):
            corr = []
            for l in lines:
                corr += [rev(l, f"machine was on {tel_job}"),
                         post(unit, d, tel_job, l["hours"], f"Moved from {l['job']} per geofence")]
            for l in lines:
                labor_reclass.append(dict(employee=l["employee"], date=d, tc_line=l["tc_line"], pr_batch=l["pr_batch"],
                                          labor_hours=l["labor_hours"], from_job=l["job"], to_job=tel_job,
                                          from_co=jc(l["job"]), to_co=jc(tel_job),
                                          cross_company="Y" if jc(l["job"]) != jc(tel_job) else "N",
                                          reason=f"Operated {unit} on {tel_job} per telematics"))
            add("WRONG_JOB", unit, d, "approve", lines, corr,
                detail=f"Payroll posted it to {lines[0]['job']} (the crew's job); telematics puts the unit in "
                       f"{t['geofence']} ({tel_job}). Operator {lines[0]['employee']}'s labor is listed for a JC labor reclass",
                tel_hours=eng, posted_hours=posted_hrs, payroll=f"Labor reclass {lines[0]['tc_line']}")
            tel_status[key] = "WRONG_JOB"; continue

        bad_rate = [l for l in lines if abs(l["rate"] - rate_for(unit, date.fromisoformat(d))) > 0.004]
        if bad_rate:
            corr = []
            for l in bad_rate:
                corr += [rev(l, "old rate"), post(unit, d, l["job"], l["hours"], "Repost at current rate table")]
            add("RATE", unit, d, "auto", bad_rate, corr,
                detail=f"Posted at ${bad_rate[0]['rate']:.2f}/hr; rate table says ${rate_for(unit, date.fromisoformat(d)):.2f} from {mdy(RATE_CHANGE)}",
                tel_hours=eng, posted_hours=posted_hrs)
        for l in lines: status.setdefault(l["trans"], "MATCHED")
        tel_status[key] = "MATCHED" if not bad_rate else "RATE"
    return findings, status, tel_status, labor_reclass, missing_payroll


# --------------------------------------------------------------------------- export
def write_csv(path, rows, header=True, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        if header: w.writerow(fields)
        for r in rows: w.writerow([r[k] for k in fields] if isinstance(r, dict) else r)


def export(tel, usage, timecards, heavyjob, findings, status, tel_status, labor_reclass, missing_payroll):
    write_csv(DATA / "telematics_daily_oct2026.csv", tel)
    write_csv(DATA / "heavyjob_timecards_oct2026.csv", heavyjob)
    write_csv(DATA / "pr_timecards_oct2026.csv", timecards)
    write_csv(DATA / "em_usage_posted_oct2026.csv", usage,
              fields=["trans", "batch_seq", "em_co", "unit", "date", "jc_co", "job", "phase", "cost_type",
                      "rev_code", "hours", "rate", "amount", "source", "pr_batch", "tc_line", "employee"])
    write_csv(DATA / "equipment_master.csv",
              [dict(unit=u, em_co=f["em_co"], category=f["category"],
                    description=CATEGORIES[f["category"]][0], telematics="Y" if f["telematics"] else "N")
               for u, f in FLEET.items()])
    write_csv(DATA / "revenue_rates.csv",
              [dict(category=c, description=v[0], rev_code=REV_CODE, effective=mdy(eff), rate=r, um="HRS")
               for c, v in CATEGORIES.items() for eff, r in v[1]])
    write_csv(DATA / "jobs.csv", [dict(jc_co=v["jc_co"], job=j, description=v["desc"], geofence=v["geofence"])
                                  for j, v in JOBS.items()])

    # ---- EM Usage import (corrections only), one batch per owning EM company
    imported = [f for f in findings if f["action"] in ("auto", "approve")]
    held = [f for f in findings if f["action"] == "review"]
    rows, seq = [], defaultdict(int)
    for f in imported:
        for c in f["corrections"]:
            co = FLEET[c["unit"]]["em_co"]; seq[co] += 1
            cat = FLEET[c["unit"]]["category"]
            rows.append(dict(Co=co, Mth=mdy(MONTH), BatchSeq=seq[co], Equipment=c["unit"], RevCode=REV_CODE,
                             ActualDate=mdy(date.fromisoformat(c["date"])), JCCo=JOBS[c["job"]]["jc_co"], Job=c["job"],
                             Phase=CATEGORIES[cat][2], JCCostType=COST_TYPE, WorkUM="HRS",
                             TimeUnits=f"{c['hours']:.2f}", Rate=f"{c['rate']:.2f}", Dollars=f"{c['amount']:.2f}",
                             Description=f"{f['id']} {f['category']}: {c['memo']}"[:60]))
    rows.sort(key=lambda r: (r["Co"], r["BatchSeq"]))
    write_csv(OUT / "EM_Usage_Import_Oct2026.csv", rows)

    write_csv(OUT / "review_queue_oct2026.csv",
              [dict(id=f["id"], category=f["category"], unit=f["unit"], date=f["date"],
                    posted_lines=" ".join(f["lines"]), posted_hours=f.get("posted_hours", ""),
                    engine_hours=f.get("tel_hours", ""), dollars_at_stake=f.get("at_stake", 0.0),
                    detail=f["detail"]) for f in held])
    write_csv(OUT / "findings_oct2026.csv",
              [dict(id=f["id"], category=f["category"], action=f["action"], unit=f["unit"], date=f["date"],
                    posted_lines=" ".join(f["lines"]), net_amount=f["net_amount"],
                    at_stake=f.get("at_stake", ""), payroll=f.get("payroll", ""), detail=f["detail"]) for f in findings])
    write_csv(OUT / "labor_reclass_for_payroll_oct2026.csv", labor_reclass)
    write_csv(OUT / "missing_from_payroll_oct2026.csv", missing_payroll)

    # ---- GL effect by company (what the ERP books when the correction batch posts)
    posted_by_co = defaultdict(float)
    for x in usage: posted_by_co[x["em_co"]] += x["amount"]
    flows = defaultdict(float)                      # (em_co, jc_co) -> net dollars
    for r in rows: flows[(int(r["Co"]), int(r["JCCo"]))] += float(r["Dollars"])
    lines = defaultdict(float)                      # (co, acct, desc) -> debit(+)/credit(-)
    for (em_co, jc_co), amt in flows.items():
        lines[(jc_co, *gl(jc_co, "jc"))] += amt
        if em_co == jc_co:
            lines[(em_co, *gl(em_co, "rev"))] -= amt
        else:
            lines[(jc_co, *gl(jc_co, "dueto", em_co))] -= amt
            lines[(em_co, *gl(em_co, "duefrom", jc_co))] += amt
            lines[(em_co, *gl(em_co, "icrev"))] -= amt
    correcting_entry = []
    for (co, acct, desc), v in sorted(lines.items(), key=lambda kv: (kv[0][0] != 2, kv[0][1])):
        v = money(v)
        if v == 0: continue
        correcting_entry.append(dict(co=co, acct=acct, desc=desc, **({"debit": v} if v > 0 else {"credit": -v})))
    def bal(co, acct):
        return money(sum(e.get("debit", 0) - e.get("credit", 0) for e in correcting_entry if e["co"] == co and e["acct"] == acct))
    intercompany = dict(
        materials_units_on_paving_jobs=money(flows.get((1, 2), 0.0)),
        paving_units_on_materials_jobs=money(flows.get((2, 1), 0.0)),
        due_from_paving_on_materials_books=bal(1, "1450."), due_to_materials_on_paving_books=-bal(2, "2450."),
        due_from_materials_on_paving_books=bal(2, "1450."), due_to_paving_on_materials_books=-bal(1, "2450."))
    posted_ic = defaultdict(float)
    for x in usage:
        if x["em_co"] != x["jc_co"]: posted_ic[f"Co {x['em_co']} units on Co {x['jc_co']} jobs"] += x["amount"]

    # ---- bridge
    cats = ["NOT_TRANSFERRED", "UNPOSTED", "HOURS_VARIANCE", "WRONG_JOB", "RATE", "DUPLICATE"]
    by_cat = {c: dict(count=sum(1 for f in findings if f["category"] == c),
                      net=money(sum(f["net_amount"] for f in findings if f["category"] == c))) for c in cats}
    held_cat = {"NO_ACTIVITY": dict(count=len(held), at_stake=money(sum(f["at_stake"] for f in held)))}
    posted_total = money(sum(posted_by_co.values()))
    corr_total = money(sum(float(r["Dollars"]) for r in rows))
    corrected = money(posted_total + corr_total)

    job_before, job_after = defaultdict(float), defaultdict(float)
    for x in usage: job_before[x["job"]] += x["amount"]; job_after[x["job"]] += x["amount"]
    for r in rows: job_after[r["Job"]] += float(r["Dollars"])

    tel_job_hours = sum(t["engine_hours"] for t in tel if GEOFENCES[t["geofence"]])
    posted_tel_hours = sum(x["hours"] for x in usage if FLEET[x["unit"]]["telematics"])

    # ---- payroll side: PR timecard equipment columns -> EM usage (ledger update)
    tc_eq = [t for t in timecards if t["equipment"]]
    pr_hours, pr_dollars = sum(t["equip_hours"] for t in tc_eq), money(sum(t["equip_hours"] * t["equip_rate"] for t in tc_eq))
    em_hours = sum(x["hours"] for x in usage)

    # ---- tie-outs
    dr = sum(e.get("debit", 0) for e in correcting_entry); cr = sum(e.get("credit", 0) for e in correcting_entry)
    hj_ok = [h for h in heavyjob if not h["status"].endswith("failed")]
    hj_bad = [h for h in heavyjob if h["status"].endswith("failed")]
    checks = {
        "HeavyJob exported timecards = ERP payroll timecards (rows and hours)":
            {h["hj_row"] for h in hj_ok} == {t["hj_row"] for t in timecards}
            and abs(sum(h["equip_hours"] for h in hj_ok) - sum(t["equip_hours"] for t in timecards)) < 0.005
            and abs(sum(h["labor_hours"] for h in hj_ok) - sum(t["labor_hours"] for t in timecards)) < 0.005,
        "every failed HeavyJob export is caught and corrected":
            {h["hj_row"] for h in hj_bad} == {m["hj_row"] for m in missing_payroll},
        "PR timecard equipment hours and dollars = EM usage posted":
            abs(pr_hours - em_hours) < 0.005 and abs(pr_dollars - posted_total) < 0.005
            and {t["tc_line"] for t in tc_eq} == {x["tc_line"] for x in usage},
        "every posted usage line classified once":
            len(status) == len(usage) and set(status) == {x["trans"] for x in usage},
        "every telematics unit-day classified once": len(tel_status) == len(tel),
        "import total = sum of approved corrections":
            abs(corr_total - sum(f["net_amount"] for f in imported)) < 0.005,
        "posted + corrections = corrected usage by job":
            abs(sum(job_after.values()) - corrected) < 0.005,
        "correcting entry balances (Dr = Cr)": abs(dr - cr) < 0.005,
        "intercompany due-to = due-from, both directions":
            abs(intercompany["due_from_paving_on_materials_books"] - intercompany["due_to_materials_on_paving_books"]) < 0.005
            and abs(intercompany["due_from_materials_on_paving_books"] - intercompany["due_to_paving_on_materials_books"]) < 0.005,
    }
    summary = dict(
        posting_month=mdy(MONTH),
        fleet_units=len(FLEET), units_with_telematics=sum(f["telematics"] for f in FLEET.values()),
        telematics_unit_days=len(tel),
        heavyjob=dict(rows=len(heavyjob), timecards=len({h["hj_timecard"] for h in heavyjob}),
                      exported_rows=len(hj_ok), failed_rows=len(hj_bad),
                      failed_timecards=sorted({h["hj_timecard"] for h in hj_bad}),
                      failed_equip_hours=sum(h["equip_hours"] for h in hj_bad),
                      failed_labor_hours=sum(h["labor_hours"] for h in hj_bad)),
        payroll=dict(timecard_lines=len(timecards), lines_with_equipment=len(tc_eq),
                     lines_equipment_blank=len(timecards) - len(tc_eq),
                     pr_batches=sorted({t["pr_batch"] for t in timecards}),
                     equipment_hours=round(pr_hours, 2), equipment_dollars=pr_dollars,
                     labor_reclass_lines=len(labor_reclass),
                     labor_reclass_hours=round(sum(r["labor_hours"] for r in labor_reclass), 2)),
        posted_usage_lines=len(usage),
        telematics_job_site_hours=round(tel_job_hours, 1), posted_hours_telematics_units=round(posted_tel_hours, 1),
        posted_usage_total=posted_total,
        posted_by_em_company={COMPANIES[k]: money(v) for k, v in sorted(posted_by_co.items())},
        posted_intercompany={k: money(v) for k, v in sorted(posted_ic.items())},
        line_status=dict(Counter(status.values())),
        corrections_by_category=by_cat,
        held_for_review=held_cat,
        findings=len(findings), findings_auto=sum(f["action"] == "auto" for f in findings),
        findings_approved=sum(f["action"] == "approve" for f in findings), findings_held=len(held),
        correction_lines=len(rows), correction_total=corr_total,
        corrected_usage_total=corrected,
        intercompany_corrections=intercompany,
        correcting_entry=correcting_entry,
        jobs=[dict(job=j, jc_co=JOBS[j]["jc_co"], desc=JOBS[j]["desc"], before=money(job_before[j]),
                   after=money(job_after[j]), change=money(job_after[j] - job_before[j])) for j in JOBS],
        tie_out_checks=checks,
    )
    (OUT / "recon_summary_oct2026.json").write_text(json.dumps(summary, indent=2))
    assert all(checks.values()), checks
    return summary, rows


def run():
    tel, usage, timecards, heavyjob = generate()
    findings, status, tel_status, labor_reclass, missing = reconcile(tel, usage, timecards, heavyjob)
    summary, rows = export(tel, usage, timecards, heavyjob, findings, status, tel_status, labor_reclass, missing)
    return dict(tel=tel, usage=usage, timecards=timecards, heavyjob=heavyjob, findings=findings, status=status,
                tel_status=tel_status, labor_reclass=labor_reclass, missing_payroll=missing, summary=summary, rows=rows)


if __name__ == "__main__":
    print(json.dumps(run()["summary"], indent=2))
