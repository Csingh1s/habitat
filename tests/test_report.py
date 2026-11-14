from horizon_explorer.models import Control, Evidence, PageEvidence
from horizon_explorer.report import markdown_report


def test_report_marks_inventory_read_only() -> None:
    evidence = Evidence(pages=[PageEvidence(
        url="https://www.discoverhorizon.com/authenticated/schedule/ScheduleDayViewX.aspx",
        title="Schedule Day View", headings=["Schedule"], tabs=["Day"],
        links=[], controls=[Control("button", "Save", None, None, "risky")], forms=[],
    )])
    report = markdown_report(evidence)
    assert "read-only UI inventory" in report
    assert "Save (risky)" in report
