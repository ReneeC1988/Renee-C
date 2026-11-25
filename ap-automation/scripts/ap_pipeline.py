"""
Copperhollow Materials Co. -- AP automation demo pipeline (FICTIONAL DATA ONLY)

Steps
  1. generate()  -> fake scale tickets (as received from a third-party ticketing
                    provider, already code-mapped) + fake vendor invoices
  2. match()     -> 3-way-style match: invoice line <-> scale tickets, price tolerance
  3. export()    -> ERP AP Entry import file (header/line records), exception queue,
                    accrual true-up summary, and a tie-out that must pass

Run:  python ap_pipeline.py            (writes to ../data and ../output)
Every company, vendor, person, ticket and dollar amount here is invented.
"""
import csv, random, json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

random.seed(2026)
ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "output"
DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)

MONTH = date(2026, 10, 1)            # posting month (Mth)
MONTH_END = date(2026, 10, 31)
PRICE_TOLERANCE = 0.02               # 2% unit price tolerance before exception
CO = 1                               # ERP company number

# --- Fictional vendor master ------------------------------------------------
VENDORS = {
    41020: dict(name="Granite Bend Quarry",       kind="Incoming Rock",    terms_days=30),
    41035: dict(name="Blue Mesa Aggregates",      kind="Incoming Rock",    terms_days=30),
    41210: dict(name="Redline Hauling LLC",       kind="Material Hauling", terms_days=15),
    41225: dict(name="Two Rivers Trucking",       kind="Material Hauling", terms_days=15),
    41300: dict(name="Cascade Bitumen Supply",    kind="Liquid Asphalt",   terms_days=20),
}
# material code -> (supplier vendor, system price/ton, description)
MATERIALS = {
    "AGGB-57":  (41020, 14.25, "#57 Washed Stone"),
    "AGGB-DUST":(41020,  9.80, "Screenings / Rock Dust"),
    "AGBM-34":  (41035, 13.40, "3/4in Crushed Base"),
    "AGBM-SAND":(41035, 11.10, "Manufactured Sand"),
    "LIQ-6422": (41300, 610.00,"PG 64-22 Binder"),
}
HAUL_RATE = {41210: 6.50, 41225: 7.10}     # hauling $/ton
GL = dict(accrual="2015.", inv_agg="1310.", inv_liq="1320.", haul_in="1310.")


def money(x): return round(x + 1e-9, 2)


def generate():
    tickets, t_no = [], 880100
    d = MONTH
    while d <= MONTH_END:
        if d.weekday() < 6:                                   # plant runs Mon-Sat
            for _ in range(random.randint(10, 18)):
                mat = random.choice(list(MATERIALS))
                vendor, price, desc = MATERIALS[mat]
                liquid = mat.startswith("LIQ")
                tons = round(random.uniform(22.5, 26.0) if not liquid else random.uniform(24.0, 27.5), 2)
                hauler = None if liquid else random.choice(list(HAUL_RATE))
                t_no += 1
                tickets.append(dict(
                    ticket=t_no, date=d.isoformat(), material=mat, description=desc,
                    supplier=vendor, hauler=hauler or "", tons=tons,
                    sys_price=price, matl_accrual=money(tons * price),
                    haul_rate=HAUL_RATE.get(hauler, 0.0),
                    haul_accrual=money(tons * HAUL_RATE.get(hauler, 0.0)),
                    truck=f"TRK-{random.randint(100, 199)}"))
        d += timedelta(days=1)

    # Vendors bill weekly; each invoice lists the tickets it covers.
    invoices, inv_lines = [], []
    by_week_vendor = defaultdict(list)
    for t in tickets:
        wk = date.fromisoformat(t["date"]).isocalendar()[1]
        by_week_vendor[(t["supplier"], wk, "matl")].append(t)
        if t["hauler"]:
            by_week_vendor[(t["hauler"], wk, "haul")].append(t)

    # Scenario knobs: one supplier raised price mid-month, a few ticket problems
    price_increase = {41035: 1.07}            # Blue Mesa billed +7% vs system price
    for (vendor, wk, kind), tix in sorted(by_week_vendor.items()):
        inv_no = f"{str(vendor)[-3:]}-{wk:02d}{random.randint(10, 99)}"
        inv_date = max(date.fromisoformat(t["date"]) for t in tix) + timedelta(days=2)
        lines = []
        for t in tix:
            if kind == "matl":
                p = t["sys_price"] * price_increase.get(vendor, 1.0)
                lines.append(dict(invoice=inv_no, vendor=vendor, ticket=t["ticket"],
                                  material=t["material"], tons=t["tons"],
                                  unit_price=round(p, 4), amount=money(t["tons"] * p)))
            else:
                lines.append(dict(invoice=inv_no, vendor=vendor, ticket=t["ticket"],
                                  material="HAUL", tons=t["tons"],
                                  unit_price=t["haul_rate"], amount=money(t["tons"] * t["haul_rate"])))
        invoices.append(dict(invoice=inv_no, vendor=vendor, vendor_name=VENDORS[vendor]["name"],
                             invoice_date=inv_date.isoformat(), kind=kind,
                             total=money(sum(l["amount"] for l in lines)), line_count=len(lines)))
        inv_lines.extend(lines)

    # Inject realistic exceptions
    inv_lines[5]["ticket"] = 999001                               # ticket not on file
    inv_lines[40]["tons"] = round(inv_lines[40]["tons"] + 3.0, 2)  # tonnage mismatch
    inv_lines[40]["amount"] = money(inv_lines[40]["tons"] * inv_lines[40]["unit_price"])
    dup = dict(inv_lines[77]); inv_lines.append(dup)               # same ticket billed twice
    # keep invoice totals honest after edits
    tot = defaultdict(float)
    for l in inv_lines: tot[l["invoice"]] += l["amount"]
    cnt = defaultdict(int)
    for l in inv_lines: cnt[l["invoice"]] += 1
    for i in invoices: i["total"], i["line_count"] = money(tot[i["invoice"]]), cnt[i["invoice"]]
    return tickets, invoices, inv_lines


def match(tickets, invoices, inv_lines):
    tk = {t["ticket"]: t for t in tickets}
    seen = set()
    results = []
    for l in inv_lines:
        t = tk.get(l["ticket"])
        kind = "haul" if l["material"] == "HAUL" else "matl"
        key = (l["ticket"], kind)
        r = dict(l, status="MATCHED", reason="", accrued=0.0, variance=0.0)
        if t is None:
            r.update(status="EXCEPTION", reason="Ticket not found in scale system")
        elif key in seen:
            r.update(status="EXCEPTION", reason="Ticket already billed (possible duplicate)")
        else:
            accrued = t["haul_accrual"] if kind == "haul" else t["matl_accrual"]
            sys_price = t["haul_rate"] if kind == "haul" else t["sys_price"]
            r["accrued"] = accrued
            r["variance"] = money(l["amount"] - accrued)
            if abs(l["tons"] - t["tons"]) > 0.05:
                r.update(status="EXCEPTION", reason=f"Tons billed {l['tons']} vs scale {t['tons']}")
            elif abs(l["unit_price"] - sys_price) / sys_price > PRICE_TOLERANCE:
                r.update(status="PRICE_VARIANCE",
                         reason=f"Unit price {l['unit_price']:.2f} vs system {sys_price:.2f}")
        seen.add(key)
        results.append(r)

    # An invoice is importable only if no line is a hard EXCEPTION.
    inv_status = {}
    for i in invoices:
        ls = [r for r in results if r["invoice"] == i["invoice"]]
        if any(r["status"] == "EXCEPTION" for r in ls):
            inv_status[i["invoice"]] = "HOLD"
        elif any(r["status"] == "PRICE_VARIANCE" for r in ls):
            inv_status[i["invoice"]] = "APPROVE_VARIANCE"   # routes to buyer, then imports
        else:
            inv_status[i["invoice"]] = "AUTO_IMPORT"
    return results, inv_status


def write_csv(path, rows, header=True, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        if header: w.writerow(fields)
        for r in rows: w.writerow([r[k] for k in fields] if isinstance(r, dict) else r)


def mdy(d): return f"{d.month}/{d.day}/{d.year}"


def export(tickets, invoices, inv_lines, results, inv_status):
    write_csv(DATA / "scale_tickets_oct2026.csv", tickets)
    write_csv(DATA / "vendor_invoices_oct2026.csv", invoices)
    write_csv(DATA / "vendor_invoice_lines_oct2026.csv", inv_lines)
    write_csv(DATA / "vendor_master.csv",
              [dict(vendor=k, **v) for k, v in VENDORS.items()])

    # --- ERP AP Entry import: H = header (one per invoice), L = line (one per GL distribution)
    # Each invoice is summarized to one line per material/GL so the AP batch stays readable;
    # ticket-level detail stays in the matching log for audit.
    rows, imported_total = [], 0.0
    importable = [i for i in invoices if inv_status[i["invoice"]] != "HOLD"]
    for seq, i in enumerate(importable, start=1):
        inv_d = date.fromisoformat(i["invoice_date"])
        due = inv_d + timedelta(days=VENDORS[i["vendor"]]["terms_days"])
        rows.append(["H", CO, mdy(MONTH), seq, i["vendor"], i["invoice"],
                     f"{VENDORS[i['vendor']]['kind']} wk ending {mdy(inv_d - timedelta(days=2))}",
                     mdy(inv_d), mdy(due), f"{i['total']:.2f}", "", "", ""])
        agg = defaultdict(lambda: [0.0, 0.0])
        for r in results:
            if r["invoice"] == i["invoice"]:
                agg[r["material"]][0] += r["tons"]; agg[r["material"]][1] += r["amount"]
        for ln, (mat, (tons, amt)) in enumerate(sorted(agg.items()), start=1):
            desc = "Hauling - incoming material" if mat == "HAUL" else MATERIALS[mat][2]
            rows.append(["L", CO, mdy(MONTH), seq, i["vendor"], i["invoice"], desc, "", "",
                         f"{amt:.2f}", ln, GL["accrual"], f"{tons:.2f}"])
        imported_total += i["total"]
    with open(OUT / "AP_Entry_Import_Oct2026.csv", "w", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerows(rows)   # no header row, CRLF

    # Exception queue
    exc = [r for r in results if r["status"] != "MATCHED"]
    write_csv(OUT / "exception_queue_oct2026.csv", exc,
              fields=["invoice", "vendor", "ticket", "material", "tons", "unit_price",
                      "amount", "accrued", "variance", "status", "reason"])

    # Accrual true-up (AP accrued clearing account)
    accrued_total = sum(t["matl_accrual"] + t["haul_accrual"] for t in tickets)
    cleared = sum(r["accrued"] for r in results
                  if inv_status[r["invoice"]] != "HOLD" and r["status"] != "EXCEPTION")
    variance = sum(r["variance"] for r in results
                   if inv_status[r["invoice"]] != "HOLD" and r["status"] != "EXCEPTION")
    by_kind = defaultdict(float)
    for r in results:
        if inv_status[r["invoice"]] != "HOLD" and r["status"] != "EXCEPTION":
            by_kind[VENDORS[r["vendor"]]["kind"]] += r["variance"]

    # Tie-outs: must all pass before anything is "delivered"
    line_sum = sum(float(r[9]) for r in rows if r[0] == "L")
    hdr_sum = sum(float(r[9]) for r in rows if r[0] == "H")
    checks = {
        "import lines = import headers": abs(line_sum - hdr_sum) < 0.005,
        "import headers = approved invoice totals": abs(hdr_sum - imported_total) < 0.005,
        "every invoice is imported or held": len(importable) + sum(
            1 for s in inv_status.values() if s == "HOLD") == len(invoices),
    }
    summary = dict(
        posting_month=mdy(MONTH),
        scale_tickets=len(tickets),
        accrued_at_scale=money(accrued_total),
        invoices_received=len(invoices),
        invoices_auto_import=sum(1 for s in inv_status.values() if s == "AUTO_IMPORT"),
        invoices_price_variance=sum(1 for s in inv_status.values() if s == "APPROVE_VARIANCE"),
        invoices_on_hold=sum(1 for s in inv_status.values() if s == "HOLD"),
        imported_total=money(imported_total),
        accrual_cleared=money(cleared),
        price_variance_total=money(variance),
        variance_by_category={k: money(v) for k, v in by_kind.items()},
        accrual_remaining_open=money(accrued_total - cleared),
        exception_lines=len(exc),
        tie_out_checks=checks,
    )
    (OUT / "run_summary_oct2026.json").write_text(json.dumps(summary, indent=2))
    assert all(checks.values()), checks
    return summary


if __name__ == "__main__":
    t, i, l = generate()
    res, st = match(t, i, l)
    print(json.dumps(export(t, i, l, res, st), indent=2))
