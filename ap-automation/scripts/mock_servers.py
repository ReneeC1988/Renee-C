"""
Mock servers for the Copperhollow AP demo (FICTIONAL).

  /tickettrail/v1/...  -> stand-in for the third-party e-ticketing provider
  /erp/v1/...          -> stand-in for the ERP's AP API

Endpoint names and payloads are illustrative, not any vendor's real API. The ERP mock
enforces the same rules a real AP batch would, so the client has to handle real-looking
failures: invalid vendor, duplicate invoice number, null batch month, lines not tying
to the header, posting without validating.

Standard library only. Start with start(port) from another script.
"""
import json, threading, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

STATE = dict(tickets=[], vendors=set(), gl_accounts={"2015.", "1310.", "1320."},
             batches={}, next_batch=101, ap_refs=set(), tokens={})
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _authed(self):
        tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        if tok not in STATE["tokens"]:
            self._send(401, {"error": "invalid_token"}); return False
        self.role = STATE["tokens"][tok]
        return True

    # ---------------- GET ----------------
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/tickettrail/v1/tickets":
            if not self._authed(): return
            page, size = int(q.get("page", ["1"])[0]), int(q.get("page_size", ["100"])[0])
            since = q.get("updated_since", [""])[0]
            rows = [t for t in STATE["tickets"] if t["updated_at"] >= since]
            chunk = rows[(page - 1) * size: page * size]
            return self._send(200, {"page": page, "total": len(rows), "data": chunk,
                                    "next_page": page + 1 if page * size < len(rows) else None})
        m = re.fullmatch(r"/erp/v1/ap/batches/(\d+)", u.path)
        if m:
            if not self._authed(): return
            b = STATE["batches"].get(int(m.group(1)))
            return self._send(200, _batch_view(b)) if b else self._send(404, {"error": "batch not found"})
        self._send(404, {"error": "not found"})

    # ---------------- POST ----------------
    def do_POST(self):
        u = urlparse(self.path)
        if u.path in ("/tickettrail/v1/oauth/token", "/erp/v1/oauth/token"):
            body = self._body()
            if body.get("client_secret") != "demo-secret":
                return self._send(401, {"error": "invalid_client"})
            role = "ap_poster" if body.get("client_id") == "ap-supervisor" else "integration"
            tok = f"tok-{len(STATE['tokens']) + 1:04d}"; STATE["tokens"][tok] = role
            return self._send(200, {"access_token": tok, "token_type": "Bearer",
                                    "expires_in": 3600, "role": role})

        if not self._authed(): return
        body = self._body()

        if u.path == "/erp/v1/ap/batches":
            mth = body.get("mth")
            if not mth or not re.fullmatch(r"\d{4}-\d{2}-01", mth):
                return self._send(422, {"error": "Batch month was null or not the 1st of a month."})
            with LOCK:
                bid = STATE["next_batch"]; STATE["next_batch"] += 1
                STATE["batches"][bid] = dict(batch_id=bid, co=body.get("co"), mth=mth,
                                             status="open", invoices=[])
            return self._send(201, _batch_view(STATE["batches"][bid]))

        m = re.fullmatch(r"/erp/v1/ap/batches/(\d+)/(invoices|validate|post)", u.path)
        if not m: return self._send(404, {"error": "not found"})
        b = STATE["batches"].get(int(m.group(1)))
        if not b: return self._send(404, {"error": "batch not found"})
        action = m.group(2)

        if action == "invoices":
            if b["status"] != "open":
                return self._send(409, {"error": f"Batch is {b['status']}; cannot add invoices."})
            h, lines = body.get("header", {}), body.get("lines", [])
            errs = []
            if h.get("vendor") not in STATE["vendors"]:
                errs.append(f"Vendor {h.get('vendor')} invalid!")
            key = (h.get("vendor"), h.get("ap_ref"))
            if key in STATE["ap_refs"]:
                return self._send(409, {"error": f"Duplicate APRef {h.get('ap_ref')} for vendor {h.get('vendor')}."})
            for ln in lines:
                if ln.get("gl_acct") not in STATE["gl_accounts"]:
                    errs.append(f"Line {ln.get('line')}: GL account {ln.get('gl_acct')} invalid.")
            if abs(sum(l.get("amount", 0) for l in lines) - h.get("gross_amt", 0)) > 0.005:
                errs.append("Invoice lines do not equal invoice total.")
            if errs:
                return self._send(422, {"errors": errs})
            with LOCK:
                seq = len(b["invoices"]) + 1
                b["invoices"].append(dict(batch_seq=seq, header=h, lines=lines))
                STATE["ap_refs"].add(key)
            return self._send(201, {"batch_id": b["batch_id"], "batch_seq": seq,
                                    "ap_ref": h["ap_ref"], "lines": len(lines)})

        if action == "validate":
            b["status"] = "validated"
            return self._send(200, _batch_view(b))

        if action == "post":
            if self.role != "ap_poster":
                return self._send(403, {"error": "Integration user may not post batches. "
                                                 "Posting requires an AP supervisor."})
            if b["status"] != "validated":
                return self._send(409, {"error": "Batch must be validated before posting."})
            b["status"] = "posted"
            return self._send(200, _batch_view(b))


def _batch_view(b):
    return dict(batch_id=b["batch_id"], co=b["co"], mth=b["mth"], status=b["status"],
                invoice_count=len(b["invoices"]),
                line_count=sum(len(i["lines"]) for i in b["invoices"]),
                total=round(sum(i["header"]["gross_amt"] for i in b["invoices"]), 2))


def start(port=8765, tickets=(), vendors=()):
    STATE["tickets"] = list(tickets); STATE["vendors"] = set(vendors)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
