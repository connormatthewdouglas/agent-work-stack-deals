"""Data license for the published price and deal feeds (code is MIT, see LICENSE; data is CC BY 4.0, see LICENSE-DATA)."""

DATA_LICENSE = {
    "data": "CC-BY-4.0",
    "data_license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "Lantern Works (https://thelanternworks.com)",
    "code": "MIT",
    "details": "https://thelanternworks.com/methodology/#license",
}

# T40: where to report a wrong price (public form + GitHub issue form; humans stay in the loop).
REPORT_ISSUE = {
    "url": "https://thelanternworks.com/report-price/",
    "issue_form": "https://github.com/connormatthewdouglas/agent-work-stack-deals/issues/new?template=wrong-price.yml",
    "docs": "https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/docs/REPORT-WRONG-PRICE.md",
}
REPORT_ISSUE_NOTE = ("Report a wrong price: https://thelanternworks.com/report-price/ (or the GitHub issue form in report_issue.issue_form; "
                     "agents see report_issue.docs). MCP results carry a prefilled report_issue_url per row.")
