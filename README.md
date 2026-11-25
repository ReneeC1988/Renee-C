# Finance & ERP Automation Portfolio

Projects that show how I automate accounting work in a construction and materials business: AP, imports into the ERP, API integrations, and month-end reconciliations.

> **All companies, vendors, people and figures in this repository are fictional.** Each project is modeled on the kind of work I do, but uses invented data and mock systems. No employer data is included.

## Projects

| Project | What it shows | Tools |
|---|---|---|
| [AP automation: tickets to ERP](ap-automation/) | Third-party scale tickets matched to vendor invoices, AP Entry import file, and an API integration that builds and posts an AP batch with segregation of duties and tie-outs | Python, REST APIs, ERP Import Manager, CSV |

More projects coming soon.

## Running the demos

Python 3.9+ with the standard library only, nothing to install.

```bash
cd ap-automation/scripts
python ap_pipeline.py     # matching + AP import file
python api_demo.py        # mock ticketing + ERP APIs, full run log
python build_replay.py    # rebuilds site/index.html replay page
```
