"""
Copperhollow Paving & Grading -- equipment usage reconciliation (FICTIONAL DATA ONLY)

Compares what the telematics devices say each machine did (engine hours and the
job-site geofence it worked in) with the equipment usage that was posted to jobs
from crew timecards, then:

  1. classifies every unit-day and every posted usage line exactly once
  2. proposes the correcting EM usage lines (reversal + repost) for each fixable item
  3. holds judgment calls for the superintendent with the dollars at stake
  4. writes an EM Usage import file, a review queue, the GL effect by company
     (including intercompany) and a tie-out that must pass

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
HOURS_TOLERANCE = 1.0        # posted vs engine hours per unit-day before it goes to review [GUESS]
MIN_UNPOSTED_HOURS = 1.0     # engine hours on a job site with no usage posted -> propose usage
RATE_CHANGE = date(2026, 10, 16)

COMPANIES = {1: "Copperhollow Materials Co.", 2: "Copperhollow Paving & Grading"}
JC_CO = 2                    # all jobs belong to the paving company

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
_units("L", "LDR", 2, 901, co=1)              # owned by the materials company, loaned to jobs

JOBS = {
    "26-1104": dict(desc="Hwy 9 Mill & Overlay",           geofence="GF-1104"),
    "26-1112": dict(desc="Cedar Ridge Subdivision Ph 2",   geofence="GF-1112"),
    "26-1118": dict(desc="County Rd 41 Widening",          geofence="GF-1118"),
    "26-1125": dict(desc="Riverside Commons Parking Lot",  geofence="GF-1125"),
    "26-1131": dict(desc="Airport Taxiway C Rehab",        geofence="GF-1131"),
}
GEOFENCES = {j["geofence"]: job for job, j in JOBS.items()}
GEOFENCES["GF-YARD"] = None                    # equipment yard, not a job
GEOFENCES["GF-PLANT1"] = None                  # asphalt plant 1 (materials company)

# Fictional GL accounts
GL = {
    (2, "rev"): ("4610.", "Equipment Revenue - Internal"),
    (2, "jc"):  ("5410.", "Job Cost - Equipment"),
    (2, "ic"):  ("2450.", "Due to Copperhollow Materials Co."),
    (1, "rev"): ("4615.", "Equipment Revenue - Intercompany"),
    (1, "ic"):  ("1450.", "Due from Copperhollow Paving & Grading"),
}


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
    job_list = list(JOBS)

    for u, f in FLEET.items():
        # equipment moves between jobs in stretches of a few days
        cur, left = random.choice(job_list), 0
        for d in days:
            if left <= 0:
                cur = random.choice(job_list + [None]) if random.random() < 0.85 else None
                left = random.randint(2, 6)
            left -= 1
            if cur is None:
                site, hrs = ("GF-PLANT1" if f["em_co"] == 1 else "GF-YARD"), round(random.uniform(0, 1.2), 1)
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

    # 1) Milling machine ran 3 days on Hwy 9 but the timecards never carried it
    drop = [x for x in usage if x["unit"] == "M-402"][3:6]
    # plus scattered missed units (crew forgot to add the machine to the timecard)
    for u in ("R-306", "T-603", "S-502", "X-552", "L-902"):
        drop.append(random.choice(on_job(u)))
    for x in drop:
        if x in usage: usage.remove(x)

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
            others = [j for j in JOBS if j != x["job"]]
            x["job"] = others[n % len(others)]
            x["foreman"] = "Foreman 18"

    # 4) Same timecard line keyed twice
    for u in ("P-202", "T-605", "S-501"):
        c = on_job(u); x = c[len(c) // 2]
        usage.append(dict(x))

    # 5) Hours that don't square with the engine (judgment call -> review)
    for u, h in (("P-204", 10.0), ("R-302", 9.5), ("T-601", 10.0), ("X-552", 11.0), ("K-452", 9.0)):
        cand = [x for x in on_job(u) if tel_by[(u, x["date"])]["engine_hours"] < 6.0] or on_job(u)
        cand[0]["hours"] = h

    # 6) Usage posted on a day the machine never left the yard
    for u in ("S-503", "R-308", "T-604"):
        yard = [t for t in tel if t["unit"] == u and GEOFENCES[t["geofence"]] is None]
        t = yard[2]
        usage.append(dict(unit=u, date=t["date"], job=random.choice(job_list), hours=8.0,
                          rate=rate_for(u, date.fromisoformat(t["date"])),
                          source="PR timecard", foreman="Foreman 31"))

    # Number the posted lines the way the ERP would (batch + seq) and price them
    usage.sort(key=lambda x: (x["date"], x["unit"]))
    for i, x in enumerate(usage, start=1):
        f = FLEET[x["unit"]]
        x.update(em_co=f["em_co"], batch_seq=i, trans=f"EM-{70000 + i}",
                 phase=CATEGORIES[f["category"]][2], cost_type=COST_TYPE, rev_code=REV_CODE,
                 amount=money(x["hours"] * x["rate"]))
    return tel, usage


# --------------------------------------------------------------------------- reconcile
def reconcile(tel, usage):
    tel_by = {(t["unit"], t["date"]): t for t in tel}
    lines_by = defaultdict(list)
    for x in usage: lines_by[(x["unit"], x["date"])].append(x)

    findings, status = [], {}          # status: trans -> category for every posted line
    tel_status = {}                    # (unit,date) -> category for every telematics day
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
                    detail=f"Same {l['hours']} hrs on {l['job']} already posted as {seen[k]['trans']}")
                lines.remove(l)
            else:
                seen[k] = l

        if not FLEET[unit]["telematics"]:
            for l in lines: status[l["trans"]] = "UNVERIFIED"
            continue

        tel_job = GEOFENCES[t["geofence"]] if t else None
        eng = t["engine_hours"] if t else 0.0

        if not lines:
            if tel_job and eng >= MIN_UNPOSTED_HOURS:
                hrs = half(eng)
                add("UNPOSTED", unit, d, "approve", [], [post(unit, d, tel_job, hrs, "Usage not on timecard (telematics)")],
                    detail=f"{eng} engine hrs in {t['geofence']} ({tel_job}); nothing posted",
                    tel_hours=eng, posted_hours=0.0)
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
            f = add("HOURS_VARIANCE", unit, d, "review", lines, [],
                    detail=f"{posted_hrs} hrs posted vs {eng} engine hrs (idle {t['idle_pct']}%)",
                    tel_hours=eng, posted_hours=posted_hrs)
            f["at_stake"] = money((half(eng) - posted_hrs) * rate_for(unit, date.fromisoformat(d)))
            tel_status[key] = "HOURS_VARIANCE"; continue

        if any(l["job"] != tel_job for l in lines):
            corr = []
            for l in lines:
                corr += [rev(l, f"machine was on {tel_job}"),
                         post(unit, d, tel_job, l["hours"], f"Moved from {l['job']} per geofence")]
            add("WRONG_JOB", unit, d, "approve", lines, corr,
                detail=f"Posted to {lines[0]['job']}; telematics puts the unit in {t['geofence']} ({tel_job})",
                tel_hours=eng, posted_hours=posted_hrs)
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
    return findings, status, tel_status


# --------------------------------------------------------------------------- export
def write_csv(path, rows, header=True, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        if header: w.writerow(fields)
        for r in rows: w.writerow([r[k] for k in fields] if isinstance(r, dict) else r)


def export(tel, usage, findings, status, tel_status):
    write_csv(DATA / "telematics_daily_oct2026.csv", tel)
    write_csv(DATA / "em_usage_posted_oct2026.csv", usage,
              fields=["trans", "batch_seq", "em_co", "unit", "date", "job", "phase", "cost_type",
                      "rev_code", "hours", "rate", "amount", "source", "foreman"])
    write_csv(DATA / "equipment_master.csv",
              [dict(unit=u, em_co=f["em_co"], category=f["category"],
                    description=CATEGORIES[f["category"]][0], telematics="Y" if f["telematics"] else "N")
               for u, f in FLEET.items()])
    write_csv(DATA / "revenue_rates.csv",
              [dict(category=c, description=v[0], rev_code=REV_CODE, effective=mdy(eff), rate=r, um="HRS")
               for c, v in CATEGORIES.items() for eff, r in v[1]])
    write_csv(DATA / "jobs.csv", [dict(jc_co=JC_CO, job=j, description=v["desc"], geofence=v["geofence"])
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
                             ActualDate=mdy(date.fromisoformat(c["date"])), JCCo=JC_CO, Job=c["job"],
                             Phase=CATEGORIES[cat][2], JCCostType=COST_TYPE, WorkUM="HRS",
                             TimeUnits=f"{c['hours']:.2f}", Rate=f"{c['rate']:.2f}", Dollars=f"{c['amount']:.2f}",
                             Description=f"{f['id']} {f['category']}: {c['memo']}"[:60]))
    write_csv(OUT / "EM_Usage_Import_Oct2026.csv", rows)

    write_csv(OUT / "review_queue_oct2026.csv",
              [dict(id=f["id"], category=f["category"], unit=f["unit"], date=f["date"],
                    posted_lines=" ".join(f["lines"]), posted_hours=f.get("posted_hours", ""),
                    engine_hours=f.get("tel_hours", ""), dollars_at_stake=f.get("at_stake", 0.0),
                    detail=f["detail"]) for f in held])
    write_csv(OUT / "findings_oct2026.csv",
              [dict(id=f["id"], category=f["category"], action=f["action"], unit=f["unit"], date=f["date"],
                    posted_lines=" ".join(f["lines"]), net_amount=f["net_amount"],
                    at_stake=f.get("at_stake", ""), detail=f["detail"]) for f in findings])

    # ---- GL effect by company (what the ERP books when the correction batch posts)
    posted_by_co = defaultdict(float); corr_by_co = defaultdict(float)
    for x in usage: posted_by_co[x["em_co"]] += x["amount"]
    for r in rows: corr_by_co[int(r["Co"])] += float(r["Dollars"])
    def je(co_amounts):
        e = []
        own, ic = co_amounts.get(2, 0.0), co_amounts.get(1, 0.0)
        e.append(dict(co=2, acct=GL[(2, "jc")][0], desc=GL[(2, "jc")][1], debit=money(own + ic)))
        e.append(dict(co=2, acct=GL[(2, "rev")][0], desc=GL[(2, "rev")][1], credit=money(own)))
        e.append(dict(co=2, acct=GL[(2, "ic")][0], desc=GL[(2, "ic")][1], credit=money(ic)))
        e.append(dict(co=1, acct=GL[(1, "ic")][0], desc=GL[(1, "ic")][1], debit=money(ic)))
        e.append(dict(co=1, acct=GL[(1, "rev")][0], desc=GL[(1, "rev")][1], credit=money(ic)))
        return e
    correcting_entry = je(corr_by_co)

    # ---- bridge
    cats = ["UNPOSTED", "WRONG_JOB", "RATE", "DUPLICATE"]
    by_cat = {c: dict(count=sum(1 for f in findings if f["category"] == c),
                      net=money(sum(f["net_amount"] for f in findings if f["category"] == c))) for c in cats}
    held_cat = {c: dict(count=sum(1 for f in held if f["category"] == c),
                        at_stake=money(sum(f["at_stake"] for f in held if f["category"] == c)))
                for c in ("HOURS_VARIANCE", "NO_ACTIVITY")}
    posted_total = money(sum(posted_by_co.values()))
    corr_total = money(sum(float(r["Dollars"]) for r in rows))
    corrected = money(posted_total + corr_total)

    # job-level before/after
    job_before, job_after = defaultdict(float), defaultdict(float)
    for x in usage: job_before[x["job"]] += x["amount"]; job_after[x["job"]] += x["amount"]
    for r in rows: job_after[r["Job"]] += float(r["Dollars"])

    tel_job_hours = sum(t["engine_hours"] for t in tel if GEOFENCES[t["geofence"]])
    posted_tel_hours = sum(x["hours"] for x in usage if FLEET[x["unit"]]["telematics"])

    # ---- tie-outs
    dr = sum(e.get("debit", 0) for e in correcting_entry); cr = sum(e.get("credit", 0) for e in correcting_entry)
    checks = {
        "every posted usage line classified once":
            len(status) == len(usage) and set(status) == {x["trans"] for x in usage},
        "every telematics unit-day classified once": len(tel_status) == len(tel),
        "import total = sum of approved corrections":
            abs(corr_total - sum(f["net_amount"] for f in imported)) < 0.005,
        "posted + corrections = corrected usage by job":
            abs(sum(job_after.values()) - corrected) < 0.005,
        "correcting entry balances (Dr = Cr)": abs(dr - cr) < 0.005,
        "intercompany due-to = due-from":
            abs(next(e["credit"] for e in correcting_entry if e["acct"] == "2450.")
                - next(e["debit"] for e in correcting_entry if e["acct"] == "1450.")) < 0.005,
    }
    summary = dict(
        posting_month=mdy(MONTH),
        fleet_units=len(FLEET), units_with_telematics=sum(f["telematics"] for f in FLEET.values()),
        telematics_unit_days=len(tel), posted_usage_lines=len(usage),
        telematics_job_site_hours=round(tel_job_hours, 1), posted_hours_telematics_units=round(posted_tel_hours, 1),
        posted_usage_total=posted_total,
        posted_by_em_company={COMPANIES[k]: money(v) for k, v in sorted(posted_by_co.items())},
        line_status=dict(Counter(status.values())),
        corrections_by_category=by_cat,
        held_for_review=held_cat,
        findings=len(findings), findings_auto=sum(f["action"] == "auto" for f in findings),
        findings_approved=sum(f["action"] == "approve" for f in findings), findings_held=len(held),
        correction_lines=len(rows), correction_total=corr_total,
        corrected_usage_total=corrected,
        correcting_entry=correcting_entry,
        jobs=[dict(job=j, desc=JOBS[j]["desc"], before=money(job_before[j]), after=money(job_after[j]),
                   change=money(job_after[j] - job_before[j])) for j in JOBS],
        tie_out_checks=checks,
    )
    (OUT / "recon_summary_oct2026.json").write_text(json.dumps(summary, indent=2))
    assert all(checks.values()), checks
    return summary, rows


def run():
    tel, usage = generate()
    findings, status, tel_status = reconcile(tel, usage)
    summary, rows = export(tel, usage, findings, status, tel_status)
    return tel, usage, findings, status, tel_status, summary, rows


if __name__ == "__main__":
    print(json.dumps(run()[5], indent=2))
