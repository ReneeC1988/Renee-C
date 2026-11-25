"""
End-to-end API demo (FICTIONAL): third-party tickets -> matching -> ERP AP API.

  python api_demo.py

Starts the mock servers locally, then acts as the integration service:
  1. Authenticates to the ticketing provider and pages through October tickets
  2. Maps provider codes to ERP materials/vendors; holds voids and unmapped codes
  3. Matches vendor invoices to tickets (same rules as ap_pipeline.py)
  4. Authenticates to the ERP, opens an AP batch, sends each approved invoice
  5. Simulates a network timeout + retry to show duplicate protection
  6. Validates and posts the batch, then ties the ERP batch back to the approved total
Every call is written to output/api_run_log.json, which the replay page reads.
"""
import json, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta
from collections import defaultdict

import ap_pipeline as ap
import mock_servers

BASE = "http://127.0.0.1:8765"
LOG, CLOCK = [], [datetime(2026, 11, 2, 2, 0, 0)]       # simulated run at 2:00 AM

# Provider-side codes (what the third party calls things) -> ours
PRODUCT_MAP = {"57STONE": "AGGB-57", "DUST": "AGGB-DUST", "34BASE": "AGBM-34",
               "MSAND": "AGBM-SAND", "PG6422": "LIQ-6422"}
SITE_MAP = {"GRANITE-BEND-Q1": 41020, "BLUE-MESA-PIT2": 41035, "CASCADE-TERM": 41300}
CARRIER_MAP = {"REDLINE": 41210, "TWORIVERS": 41225}
REV = lambda d: {v: k for k, v in d.items()}


def call(method, path, body=None, token=None, step="", note=""):
    CLOCK[0] += timedelta(milliseconds=180)
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req) as r: status, resp = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        status, resp = e.code, json.loads(e.read())
    shown = body
    if body and "lines" in body and len(body["lines"]) > 3:
        shown = dict(body, lines=body["lines"][:3] + [f"... {len(body['lines']) - 3} more"])
    shown_resp = resp
    if isinstance(resp, dict) and isinstance(resp.get("data"), list) and len(resp["data"]) > 2:
        shown_resp = dict(resp, data=resp["data"][:2] + [f"... {len(resp['data']) - 2} more"])
    LOG.append(dict(t=CLOCK[0].isoformat(timespec="milliseconds"), step=step, method=method,
                    path=path, status=status,
                    request=shown, response=shown_resp, note=note))
    return status, resp


def provider_tickets(tickets):
    """Render our fake tickets the way the third-party provider would send them."""
    prod, site, carr = REV(PRODUCT_MAP), REV(SITE_MAP), REV(CARRIER_MAP)
    out = []
    for t in tickets:
        ts = datetime.fromisoformat(t["date"]) + timedelta(hours=6, minutes=t["ticket"] % 600)
        out.append(dict(ticket_id=f"TT-{t['ticket']}", status="complete",
                        weighed_at=ts.isoformat() + "-05:00", origin_site=site[t["supplier"]],
                        product_code=prod[t["material"]], carrier=carr.get(t["hauler"], ""),
                        truck=t["truck"], net_tons=t["tons"],
                        updated_at=(ts + timedelta(minutes=1)).isoformat()))
    # Things a real feed throws at you:
    out.append(dict(out[10], ticket_id="TT-890001", status="void"))            # voided load
    out.append(dict(out[20], ticket_id="TT-890002", carrier="SUMMITHAUL"))     # unmapped carrier
    return out


def map_ticket(p):
    """Provider record -> our ticket dict, or (None, reason)."""
    if p["status"] == "void": return None, "voided at the scale"
    mat = PRODUCT_MAP.get(p["product_code"]); sup = SITE_MAP.get(p["origin_site"])
    hauler = CARRIER_MAP.get(p["carrier"]) if p["carrier"] else None
    if not mat or not sup: return None, f"unmapped product/site {p['product_code']}/{p['origin_site']}"
    if p["carrier"] and not hauler: return None, f"unmapped carrier {p['carrier']}"
    _, price, desc = ap.MATERIALS[mat]
    rate = ap.HAUL_RATE.get(hauler, 0.0)
    return dict(ticket=int(p["ticket_id"].split("-")[1]), date=p["weighed_at"][:10],
                material=mat, description=desc, supplier=sup, hauler=hauler or "",
                tons=p["net_tons"], sys_price=price, matl_accrual=ap.money(p["net_tons"] * price),
                haul_rate=rate, haul_accrual=ap.money(p["net_tons"] * rate), truck=p["truck"]), None


def run():
    tickets, invoices, inv_lines = ap.generate()
    srv = mock_servers.start(tickets=provider_tickets(tickets), vendors=ap.VENDORS.keys())

    # 1. Pull tickets from the third party
    _, tok = call("POST", "/tickettrail/v1/oauth/token",
                  {"client_id": "copperhollow-int", "client_secret": "demo-secret"},
                  step="Ticketing provider", note="Authenticate to the third-party ticketing API")
    feed, page = [], 1
    while page:
        _, r = call("GET", f"/tickettrail/v1/tickets?updated_since=2026-10-01&page={page}&page_size=100",
                    token=tok["access_token"], step="Ticketing provider",
                    note=f"Pull tickets, page {page}")
        feed += r["data"]; page = r["next_page"]

    # 2. Map codes; hold what can't be mapped
    staged, held = [], []
    for p in feed:
        t, why = map_ticket(p)
        (staged.append(t) if t else held.append(dict(ticket_id=p["ticket_id"], reason=why)))
    assert {t["ticket"] for t in staged} == {t["ticket"] for t in tickets}
    LOG.append(dict(t=CLOCK[0].isoformat(timespec="milliseconds"), step="Staging", method="LOCAL",
                    path="map + stage tickets", status=200, request=None,
                    response={"received": len(feed), "staged": len(staged), "held": held},
                    note="Map provider codes to ERP materials and vendors"))

    # 3. Match invoices to staged tickets
    results, inv_status = ap.match(staged, invoices, inv_lines)
    counts = defaultdict(int)
    for s in inv_status.values(): counts[s] += 1
    LOG.append(dict(t=CLOCK[0].isoformat(timespec="milliseconds"), step="Matching", method="LOCAL",
                    path="match invoices to tickets", status=200, request=None,
                    response=dict(invoices=len(invoices), **counts,
                                  held=[k for k, v in inv_status.items() if v == "HOLD"]),
                    note="Ticket, tons (±0.05) and price (±2%) checks"))

    # 4. Send approved invoices to the ERP
    _, etok = call("POST", "/erp/v1/oauth/token",
                   {"client_id": "copperhollow-ap-int", "client_secret": "demo-secret"},
                   step="ERP", note="Authenticate to the ERP API (integration user)")
    T = etok["access_token"]
    _, batch = call("POST", "/erp/v1/ap/batches", {"co": ap.CO, "mth": ap.MONTH.isoformat()},
                    token=T, step="ERP", note="Open an AP batch for October")
    bid = batch["batch_id"]

    approved = [i for i in invoices if inv_status[i["invoice"]] != "HOLD"]
    sent_total = 0.0
    for n, i in enumerate(approved):
        agg = defaultdict(lambda: [0.0, 0.0])
        for r in results:
            if r["invoice"] == i["invoice"]:
                agg[r["material"]][0] += r["tons"]; agg[r["material"]][1] += r["amount"]
        inv_d = date.fromisoformat(i["invoice_date"])
        body = dict(header=dict(vendor=i["vendor"], ap_ref=i["invoice"], gross_amt=i["total"],
                                inv_date=inv_d.isoformat(),
                                due_date=(inv_d + timedelta(days=ap.VENDORS[i["vendor"]]["terms_days"])).isoformat(),
                                description=f"{ap.VENDORS[i['vendor']]['kind']} {i['invoice']}"),
                    lines=[dict(line=k + 1, material=m, gl_acct=ap.GL["accrual"], units=round(t, 2),
                                um="TON", amount=round(a, 2))
                           for k, (m, (t, a)) in enumerate(sorted(agg.items()))])
        s, r = call("POST", f"/erp/v1/ap/batches/{bid}/invoices", body, token=T, step="ERP",
                    note=f"Add invoice {i['invoice']} ({inv_status[i['invoice']].replace('_', ' ').lower()})")
        if s == 201: sent_total += i["total"]
        if n == 6:   # simulate: response lost to a timeout, client retries the same invoice
            s2, r2 = call("POST", f"/erp/v1/ap/batches/{bid}/invoices", body, token=T, step="ERP",
                          note="Retry after a simulated timeout: ERP refuses the duplicate, "
                               "client confirms it already exists and moves on")
            assert s2 == 409

    # 5. Validate, post, and tie out
    call("POST", f"/erp/v1/ap/batches/{bid}/validate", {}, token=T, step="ERP", note="Validate batch")
    call("POST", f"/erp/v1/ap/batches/{bid}/post", {}, token=T, step="ERP",
         note="Integration user tries to post (ERP blocks it: segregation of duties)")
    CLOCK[0] = datetime(2026, 11, 2, 8, 15, 0)            # AP supervisor reviews in the morning
    _, stok = call("POST", "/erp/v1/oauth/token", {"client_id": "ap-supervisor", "client_secret": "demo-secret"},
                   step="AP review", note="AP supervisor signs in after reviewing the batch")
    _, posted = call("POST", f"/erp/v1/ap/batches/{bid}/post", {}, token=stok["access_token"],
                     step="AP review", note="AP supervisor posts the batch")
    tie = abs(posted["total"] - round(sent_total, 2)) < 0.005 and posted["invoice_count"] == len(approved)
    LOG.append(dict(t=CLOCK[0].isoformat(timespec="milliseconds"), step="Tie-out", method="LOCAL",
                    path="ERP batch vs approved invoices", status=200 if tie else 500, request=None,
                    response=dict(erp_batch_total=posted["total"], approved_total=round(sent_total, 2),
                                  erp_invoices=posted["invoice_count"], approved_invoices=len(approved),
                                  tie_out="PASS" if tie else "FAIL"),
                    note="ERP batch must equal what we approved"))
    srv.shutdown()
    (ap.OUT / "api_run_log.json").write_text(json.dumps(LOG, indent=2))
    assert tie
    return LOG


if __name__ == "__main__":
    log = run()
    for e in log:
        print(f"{e['t'][11:23]}  {e['method']:6} {e['status']}  {e['path'][:60]:60}  {e['note']}")
