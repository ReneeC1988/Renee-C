# Renee Campbell · Finance & ERP Automation Portfolio

Projects that show how I automate accounting work in a construction and materials business: AP, imports into the ERP, API integrations, and month-end reconciliations.

> **All companies, vendors, people and figures in this repository are fictional.** Each project is modeled on the kind of work I do, but uses invented data and mock systems. No employer data is included.

## About

I'm a Financial Controller (MBA, MSE, CPA Candidate) for a dual-entity construction and manufacturing business who automates the work accounting teams do by hand: SQL queries, ERP imports (Vista), API integrations and AI-assisted (Claude) workflows that cut keying, catch errors before they post, and tie out to the cent.

**Live portfolio:** https://reneec1988.github.io/Renee-C/

## Projects

| Project | What it shows | Tools |
|---|---|---|
| [AP automation: tickets to ERP](ap-automation/) | Third-party scale tickets matched to vendor invoices, AP Entry import file, and an API integration that builds and posts an AP batch with segregation of duties and tie-outs | Python, REST APIs, ERP Import Manager, CSV |
| [Equipment usage reconciliation](equipment-usage-recon/) | Posted equipment usage checked against telematics unit by unit, day by day; auto-fixes, approval routing, an EM usage correction batch and an intercompany tie-out | Python, telematics data, ERP Import Manager, CSV |

More projects coming soon.

## Running the demos

Python 3.9+ with the standard library only, nothing to install.

```bash
cd ap-automation/scripts
python ap_pipeline.py     # matching + AP import file
python api_demo.py        # mock ticketing + ERP APIs, full run log
python build_replay.py    # rebuilds site/index.html replay page

cd ../../equipment-usage-recon/scripts
python em_usage_recon.py  # reconciliation + EM usage correction file
python build_site.py      # rebuilds site/index.html
```
