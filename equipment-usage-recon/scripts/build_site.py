"""Build site/index.html (the interactive reconciliation page) from the recon run. FICTIONAL DATA."""
import json
from datetime import date
import em_usage_recon as em

R = em.run()
tel, usage, findings, status, tel_status, summary, rows = (R[k] for k in ("tel", "usage", "findings", "status", "tel_status", "summary", "rows"))
ROOT = em.ROOT
days = [d.isoformat() for d in em.workdays()]

tel_by = {(t["unit"], t["date"]): t for t in tel}
lines_by = {}
for x in usage:
    lines_by.setdefault((x["unit"], x["date"]), []).append(
        dict(trans=x["trans"], job=x["job"], hours=x["hours"], rate=x["rate"], amount=x["amount"],
             foreman=x["foreman"], status=status[x["trans"]], tc=x["tc_line"], pr_batch=x["pr_batch"],
             employee=x["employee"], labor=x["labor_hours"]))
blank_tc = {}
for t in R["timecards"]:
    if not t["equipment"]:
        blank_tc[(t["employee"], t["date"])] = t
op = {x["unit"]: x["employee"] for x in usage}
find_by = {}
for f in findings:
    find_by.setdefault((f["unit"], f["date"]), []).append(f["id"])

fcat = {f["id"]: f["category"] for f in findings}
PRIORITY = ["NO_ACTIVITY", "HOURS_VARIANCE", "UNPOSTED", "WRONG_JOB", "DUPLICATE", "RATE", "MATCHED",
            "UNVERIFIED", "IDLE_NO_USAGE"]
units = []
for u, f in em.FLEET.items():
    cells = []
    for d in days:
        k = (u, d)
        st = []
        if k in tel_status: st.append(tel_status[k])
        st += [fcat[i] for i in find_by.get(k, [])]
        if not f["telematics"] and k in lines_by: st.append("UNVERIFIED")
        top = min(st, key=PRIORITY.index) if st else None
        t = tel_by.get(k)
        cells.append(dict(s=top, tel=dict(geofence=t["geofence"], job=em.GEOFENCES[t["geofence"]], hours=t["engine_hours"],
                                          meter=[t["meter_start"], t["meter_end"]], idle=t["idle_pct"]) if t else None,
                          lines=lines_by.get(k, []), f=find_by.get(k, []),
                          blank=(lambda b: dict(tc=b["tc_line"], pr_batch=b["pr_batch"], employee=b["employee"], job=b["job"], labor=b["labor_hours"]) if b else None)(blank_tc.get((op.get(u), d)))))
    units.append(dict(unit=u, category=f["category"], desc=em.CATEGORIES[f["category"]][0], em_co=f["em_co"],
                      telematics=f["telematics"], cells=cells))

setup = dict(
    equipment=[dict(unit=u["unit"], desc=u["desc"], category=u["category"],
                    owner=em.COMPANIES[u["em_co"]], co=u["em_co"], telematics=u["telematics"]) for u in units],
    rates=[dict(category=c, desc=v[0], rev_code=em.REV_CODE, eff=em.mdy(e), rate=r, phase=f"{v[2]} {em.PHASES[v[2]]}")
           for c, v in em.CATEGORIES.items() for e, r in v[1]],
    jobs=[dict(job=j, co=v["jc_co"], desc=v["desc"], geofence=v["geofence"]) for j, v in em.JOBS.items()]
         + [dict(job="(none)", co="", desc="Equipment yard", geofence="GF-YARD")],
    gl=[dict(co="1 and 2", acct=em.gl(1, k, 2)[0], desc=em.gl(1, k, 2)[1].replace(em.SHORT[2], "the other company"), use=u)
        for k, u in (("jc", "Debited on the job for every actual hour of equipment usage"),
                     ("rev", "Credited when a company's own unit works its own job"),
                     ("icrev", "Credited when a company's unit works the other company's job"),
                     ("duefrom", "Owner's side of cross-company usage"),
                     ("dueto", "Job's side of cross-company usage; must equal the other company's due-from"))],
    payroll=[
        dict(k="Usage source", v="PR timecard entry: each operator line carries Equipment, Rev code and equipment hours"),
        dict(k="Posting", v="PR ledger update posts labor to JC and equipment hours to EM usage (EM revenue + JC equipment cost)"),
        dict(k="PR company", v="The company that owns the job [GUESS]"),
        dict(k="Batches", v="Weekly, period ending Friday (PR1-mmdd, PR2-mmdd)"),
        dict(k="Billing basis", v="Actual hours the machine was used, not shift hours"),
        dict(k="Tie-out", v="Timecard equipment hours and dollars = EM usage posted from PR"),
    ],
    rules=[
        dict(k="Telematics feed", v="Nightly pull of daily engine hours, hour meter and primary geofence per unit (AEMP / ISO 15143-3 style)"),
        dict(k="Source of truth", v="Payroll timecard posts the usage; telematics verifies actual hours and job"),
        dict(k="Hours tolerance", v=f"±{em.HOURS_TOLERANCE:.1f} hr per unit-day, else correct to actual engine hours (after approval)"),
        dict(k="Unposted usage", v=f"≥{em.MIN_UNPOSTED_HOURS:.1f} engine hr inside a job geofence with nothing posted"),
        dict(k="Rate check", v="Posted rate vs EM revenue rate in effect on the actual date"),
        dict(k="Auto-correct", v="Duplicates and rate errors (objective, no judgment)"),
        dict(k="Approve, then correct", v="Unposted usage, wrong-job postings and hours off from actual (superintendent signs off)"),
        dict(k="Hold", v="Usage on days the unit never left the yard (could be a dead device)"),
        dict(k="Labor follow-up", v="Wrong-job operator hours listed for a JC labor reclass; duplicate timecards flagged to payroll"),
        dict(k="Corrections post as", v="EM usage batch: reverse the original line, repost the right one"),
    ],
)

payload = dict(days=days, units=units, findings=findings, summary=summary, setup=setup,
               labor_reclass=R["labor_reclass"],
               jobs={j: v["desc"] for j, v in em.JOBS.items()},
               import_rows=rows)
tpl = (ROOT / "site" / "template.html").read_text()
page = tpl.replace("/*__DATA__*/{}", json.dumps(payload, separators=(",", ":")))
(ROOT / "site" / "artifact.html").write_text(page)
# GitHub Pages copy: same page in a full document so it renders in standards mode
doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
       '<meta name="description" content="Equipment usage reconciliation demo: telematics vs posted EM usage, '
       'corrections and intercompany tie-out. All data fictional.">\n</head>\n<body>\n' + page + '\n</body>\n</html>\n')
(ROOT / "site" / "index.html").write_text(doc)
print("wrote site/index.html", len(doc), "bytes")
