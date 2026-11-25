# Path to production: taking the demo into a real ERP

The demo uses mock servers. This page covers what the same design looks like against three real ERPs, and how I'd roll it out safely.

> Based on publicly documented features as of late 2026. ERP capabilities vary by version, hosting and licensing, so confirm each item with the ERP admin and vendor before planning around it.

## The design stays the same

Whatever the ERP, the pieces do not change:

1. **Ticket feed** from the third-party ticketing provider (API or scheduled export).
2. **Integration service** that maps codes, matches invoices to tickets, and holds exceptions.
3. **ERP entry point** that creates AP invoices in an unposted state.
4. **Human approval and posting** inside the ERP.
5. **Tie-out and audit log** on every run.

Only step 3 changes from one ERP to the next.

## Trimble Viewpoint Vista (construction)

| Approach | How it works | When to use it |
|---|---|---|
| **Import Manager (IM)** | Integration writes the AP Entry file; IM template maps columns to AP header and line fields; Import → Work Edit → Upload → validate and post the batch. | Starting point. No new licensing, uses templates AP already maintains. |
| **AP Unapproved Invoices** | Invoices land in Unapproved with reviewer groups (e.g., buyer approves price variances), then move to AP Entry. | When approvals should live inside Vista instead of in email. |
| **Trimble App Xchange / Vista APIs** | REST calls to create AP records and read back errors, through Trimble's integration platform. | Fully hands-off runs. Requires Trimble licensing and a developer or partner. |

Notes:
- **Tickets.** If the ticketing provider feeds Vista's **Material Sales (MS)** module, the "MS Tickets" accruals already exist in Vista, and matching can read them from there.
- **Avoid direct SQL writes** into Vista tables. They bypass validation, are not supported, and are not possible on cloud-hosted Vista.
- **Security:** a dedicated integration user in a security group that can create and validate batches but not post.
- **Testing:** use a test company or a test copy of the database.

## Oracle NetSuite

| Approach | How it works | When to use it |
|---|---|---|
| **CSV Import Assistant** | Saved import map for Vendor Bills; can be run on a schedule from SuiteScript (a CSV import task). | Quick start, close to the Vista IM pattern. |
| **SuiteTalk REST** | `POST /services/rest/record/v1/vendorBill` with header and expense/item lines; SuiteQL to read tickets, vendors and open bills. | Standard API path; no custom code inside NetSuite. |
| **RESTlet (SuiteScript)** | A custom endpoint inside NetSuite that takes our payload and does the matching-aware create in one call. | When business rules need to run inside NetSuite. |

Notes:
- **Auth:** OAuth 2.0 (machine-to-machine) or token-based auth, tied to a dedicated integration role with only the permissions it needs.
- **Matching:** NetSuite has native 3-way match (PO → Item Receipt → Vendor Bill). Scale tickets can become **Item Receipts** against a blanket PO, and NetSuite then flags bill variances itself.
- **Approvals:** Vendor Bill approval routing (SuiteFlow workflow) keeps bills in "Pending Approval" until a person approves them. This is the "integration can't post" control.
- **Limits:** API concurrency and script governance limits apply, so batch calls and handle retries.
- **Testing:** use a sandbox account, which is a copy of production.

## Deltek

Deltek sells several ERPs, and the approach depends on which one:

| Product | Typical users | AP entry point |
|---|---|---|
| **Costpoint** | Government contractors | AP voucher import (preprocessor file import) or Costpoint web services/APIs; vouchers then go through approval and posting in Costpoint. |
| **Vantagepoint** | Architecture, engineering, professional services | REST API (OAuth) and Transaction Center imports for AP vouchers, posted by a user. |
| **ComputerEase** | Construction contractors | File imports for AP invoices; API options are more limited, so a file-drop design fits best. |

Notes:
- **Project costing is central** in Deltek. Every AP line usually needs a project, task and labor/expense code, so the code map needs project fields as well as GL accounts.
- **Costpoint** is audited heavily (DCAA), so the audit log and tie-out matter even more.

## Rollout plan (any ERP)

1. **Discovery (2–3 weeks):** map the current process, volumes, exception types and approvers; confirm the ticket provider's API or export; pick the ERP entry point.
2. **Build in test (4–6 weeks):** integration user and role, code maps, matching rules, file or API connector, alerts.
3. **Parallel run (1–2 closes):** run automation alongside the manual process and compare batches line by line.
4. **Go live by vendor:** start with one clean, high-volume vendor; add the rest once exceptions are understood.
5. **Operate:** daily exception queue, monthly accrual tie-out, quarterly review of tolerances and access.

**People involved:** ERP admin or IT, the ticketing vendor, the ERP vendor or a partner (for API licensing), and the AP lead and controller to sign off on matching rules and controls.
