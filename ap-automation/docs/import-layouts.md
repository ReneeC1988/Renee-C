# Import file layouts (fictional)

> The layouts below are illustrative. Column order and template settings are **[GUESS]** representations of how a Vista-style Import Manager (IM) template is set up, written for a fictional company. Confirm against your own templates before relying on them.

## 1. Inputs (normalized)

### Scale ticket (`data/scale_tickets_oct2026.csv`)
Normalized from the third-party ticketing provider's feed after code mapping (see `api-integration.md`).

| Field | Example | Notes |
|---|---|---|
| ticket | 880101 | Unique per scale |
| date | 2026-10-01 | Weigh date |
| material | AGBM-34 | Material code |
| supplier / hauler | 41035 / 41210 | Vendor numbers (hauler blank for delivered binder) |
| tons | 24.26 | Net tons |
| sys_price / haul_rate | 13.40 / 6.50 | Price in the system at the time of the weigh |
| matl_accrual / haul_accrual | 325.08 / 157.69 | What was accrued to `2015.` |

### Vendor invoice line (`data/vendor_invoice_lines_oct2026.csv`)
One row per ticket billed: `invoice, vendor, ticket, material, tons, unit_price, amount`. Material `HAUL` marks a hauling line. PDFs, vendor CSVs and API payloads are all converted to this shape before matching.

## 2. Output: AP Entry import (`output/AP_Entry_Import_Oct2026.csv`)

No header row, CRLF line endings, amounts with two decimals and no thousands separators. Record type in column 1 lets one file feed both the header and line sides of the template.

| Col | Header record (H) | Line record (L) |
|---|---|---|
| 1 | `H` | `L` |
| 2 | Co | Co |
| 3 | Mth (`M/D/YYYY`, 1st of month) | Mth |
| 4 | Batch seq (links lines to header) | Batch seq |
| 5 | Vendor | Vendor |
| 6 | APRef (vendor invoice #) | APRef |
| 7 | Description | Line description |
| 8 | Invoice date | – |
| 9 | Due date (invoice date + terms) | – |
| 10 | Invoice total | Line amount |
| 11 | – | Line # |
| 12 | – | GL account (`2015.` AP Accrued clearing) |
| 13 | – | Units (tons) |

Example:

```
H,1,10/1/2026,1,41020,020-4221,Incoming Rock wk ending 10/17/2026,10/19/2026,11/18/2026,8544.46,,,
L,1,10/1/2026,1,41020,020-4221,#57 Washed Stone,,,5208.83,1,2015.,365.53
L,1,10/1/2026,1,41020,020-4221,Screenings / Rock Dust,,,3335.63,2,2015.,340.37
```

**Design choice:** lines are summarized to one per material per invoice so the AP batch stays readable. Ticket-level proof lives in the matching log, which is what an auditor asks for.

## 3. Template defaults **[GUESS]**

| Field | Source | Value |
|---|---|---|
| Co | Record col 2 | |
| Mth | Record col 3 | |
| BatchId / BatchSeq | ERP default | |
| VendorGroup | User default | 1 |
| Vendor | Record col 5 | |
| APRef | Record col 6 | |
| InvDate / DueDate | Record cols 8 / 9 | |
| PayMethod | User default | Check |
| LineType | User default | GL (expense to clearing account) |
| GLAcct | Record col 12 | |
| Units / UM | Record col 13 / default `TON` | |
| GrossAmt | Record col 10 | |

## 4. Import run steps

1. Clear the IM work file for old import IDs.
2. Import the CSV with the AP template, spot-check one header and one line in Work Edit.
3. Upload to an AP batch. Confirm the batch count and total equal `run_summary.imported_total`.
4. Validate and post. Clear any empty batches left by failed runs.

**Gotcha that cost real time:** never open the CSV in Excel before importing. Excel rewrites `10/1/2026` dates, and the ERP then reads the batch month as null.

## 5. Common import errors

| Message | Cause | Fix |
|---|---|---|
| Batch month was null | Dates reformatted by Excel, or leftover work-file records | Regenerate the file, clear the work file |
| Vendor invalid | Vendor # not in vendor master | Fix the mapping table |
| Cannot insert NULL into column X | Required field has no record column or default | Add a default for X, clear the work file, re-import |
| Duplicate APRef for vendor | Invoice already entered | Matching engine already holds duplicates; check for manual entry |
