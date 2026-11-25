"""Build site/index.html (the replay page) from output/api_run_log.json. FICTIONAL DATA."""
import json
import ap_pipeline as ap
import api_demo as demo

ROOT = ap.ROOT
log = json.loads((ap.OUT / "api_run_log.json").read_text())

setup = dict(
    users=[
        dict(login="copperhollow-ap-int", role="Integration (API)", create=True, add=True, validate=True, post=False),
        dict(login="ap-supervisor", role="AP Supervisor", create=True, add=True, validate=True, post=True),
        dict(login="ap-clerk", role="AP Clerk", create=True, add=True, validate=True, post=False),
    ],
    vendors=[dict(vendor=k, name=v["name"], kind=v["kind"], terms_days=v["terms_days"],
                  pay="ACH" if v["kind"] != "Material Hauling" else "Check") for k, v in ap.VENDORS.items()],
    gl=[
        dict(acct="2015.", desc="AP Accrued – Incoming Material", use="Credited by scale tickets, debited by vendor invoices"),
        dict(acct="1310.", desc="Inventory – Aggregates", use="Month-end true-up of rock price variance (and hauling-in)"),
        dict(acct="1320.", desc="Inventory – Liquid Asphalt", use="Month-end true-up of binder price variance"),
        dict(acct="2000.", desc="Accounts Payable – Trade", use="Credited when the AP batch posts"),
    ],
    codemap=[dict(field="product_code", code=k, erp=v, desc=ap.MATERIALS[v][2]) for k, v in demo.PRODUCT_MAP.items()]
          + [dict(field="origin_site", code=k, erp=str(v), desc=ap.VENDORS[v]["name"]) for k, v in demo.SITE_MAP.items()]
          + [dict(field="carrier", code=k, erp=str(v), desc=ap.VENDORS[v]["name"]) for k, v in demo.CARRIER_MAP.items()],
    materials=[dict(material=k, desc=d, supplier=ap.VENDORS[s]["name"], price=p) for k, (s, p, d) in ap.MATERIALS.items()],
    api=[
        dict(k="ERP base URL", v="https://erp.copperhollow.example/erp/v1"),
        dict(k="Ticketing provider base URL", v="https://api.tickettrail.example/v1"),
        dict(k="Auth", v="OAuth 2.0 client credentials; secrets in vault"),
        dict(k="Company / Batch month", v=f"Co {ap.CO} / first of month (e.g. {ap.MONTH.isoformat()})"),
        dict(k="Invoice line GL account", v=ap.GL["accrual"]),
        dict(k="Ticket pull", v="Nightly 2:00 AM, updated_since = last successful run"),
        dict(k="Match tolerances", v=f"Tons ±0.05 · Unit price ±{ap.PRICE_TOLERANCE:.0%}"),
        dict(k="Duplicate key", v="Vendor + APRef (invoice #), and ticket #"),
        dict(k="Posting", v="Human only (AP Supervisor)"),
    ],
)

tpl = (ROOT / "site" / "template.html").read_text()
html = tpl.replace("/*__LOG__*/[]", json.dumps(log)).replace("/*__SETUP__*/{}", json.dumps(setup))
(ROOT / "site" / "index.html").write_text(html)
print("wrote", ROOT / "site" / "index.html", len(html), "bytes")
