# API integration flow (fictional)

> Architecture for Copperhollow Materials Co. (fictional). Endpoint names and payloads are illustrative **[GUESS]**; the real shape depends on which ERP API or integration platform is in use.

## Goal

Move invoices and tickets into the ERP without anyone downloading, retyping or re-saving files, while keeping the same controls as the file import (matching, approvals, tie-outs).

## Flow

```mermaid
sequenceDiagram
  participant Scale as Ticketing provider (3rd party)
  participant Vendor as Vendor portal / EDI
  participant Mid as Integration service
  participant Stage as Staging DB
  participant ERP as ERP (AP + Import Manager)
  Mid->>Scale: GET /tickets?updated_since=last_run (OAuth token)
  Scale-->>Mid: Tickets incl. voids and edits
  Mid->>Stage: Map codes, upsert tickets (key = provider ticket id)
  Vendor->>Mid: POST /invoices (webhook) or nightly pull
  Mid->>Stage: Normalize to invoice-line layout
  Mid->>Mid: Match, apply tolerances, route exceptions
  Mid->>ERP: Push approved invoices (API or IM file drop)
  ERP-->>Mid: Batch id, status, errors
  Mid->>Stage: Log result; alert AP on any failure
```

## Pieces

| Piece | Job | Notes |
|---|---|---|
| Ticketing-provider connector | Pull new and changed tickets from the third party's API since the last run | Idempotent; handles voids and re-weighs; a code map turns their material/vendor codes into ours |
| Vendor connector | Receive invoice JSON/EDI, or extract from emailed PDFs | Each source maps to the one invoice-line layout |
| Staging DB | Holds tickets, invoice lines, match results, run logs | The audit trail lives here |
| Matching service | Same rules as `scripts/ap_pipeline.py` | Tolerances kept in config, not code |
| ERP push | Create AP transactions | Two options below |
| Alerts | Email/Teams message for holds and failed posts | One daily digest, plus instant alerts for failures |

### ERP push options

1. **File drop into Import Manager (lowest risk).** The service writes the same CSV as the manual process to a watched folder, and a scheduled IM job imports and uploads it. Uses the templates already in place.
2. **Direct API.** The service calls the ERP's API (or an integration platform in front of it) to create AP header and line records in an open batch, then reads back the batch status. Faster, but needs API licensing and closer error handling.

## Third-party ticket feed

Tickets don't originate in our systems, so the connector has to treat the provider as the source of truth and guard against its quirks: **[GUESS: field names]**

```json
{
  "ticket_id": "TT-880101",
  "status": "complete",
  "weighed_at": "2026-10-01T07:42:10-05:00",
  "origin_site": "BLUE-MESA-PIT2",
  "product_code": "34BASE",
  "carrier": "REDLINE",
  "net_tons": 24.26,
  "updated_at": "2026-10-01T07:43:02-05:00"
}
```

- **Code mapping:** provider `product_code` + `origin_site` → our material code and supplier vendor; `carrier` → hauler vendor. Unmapped codes stop the ticket in staging with an alert, so nothing accrues to the wrong vendor.
- **Changes after the fact:** pull by `updated_at`, not weigh date, so voids and corrected weights reach us. A voided ticket reverses its accrual.
- **Completeness check:** each run compares ticket counts and tons per site per day with the provider's daily summary.

## Example payload (vendor → integration service)

```json
{
  "vendor": 41035,
  "invoice": "035-4033",
  "invoice_date": "2026-10-05",
  "lines": [
    {"ticket": 880101, "material": "AGBM-34", "tons": 24.26, "unit_price": 14.338, "amount": 347.84}
  ]
}
```

## Controls kept from the manual process

- No invoice posts without every line matched to a ticket, or a person approving the variance.
- Duplicate protection on ticket number *and* on vendor + invoice number.
- Every run writes counts and totals, and stops if lines, headers and approved totals do not tie.
- Credentials sit in a secrets vault, and the integration user can create AP batches but not post them. **[GUESS: who posts]**
