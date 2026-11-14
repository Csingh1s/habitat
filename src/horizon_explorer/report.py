from __future__ import annotations

from collections import Counter

from .models import Evidence


def markdown_report(evidence: Evidence) -> str:
    lines = [
        "# Horizon Requirements Inventory",
        "",
        f"Generated: `{evidence.generated_at}`",
        "",
        "## Scope and safety",
        "",
        "This report is a read-only UI inventory. Controls and links are evidence of possible "
        "requirements, not proof that an action was executed. No forms were submitted and no "
        "buttons were clicked.",
        "",
        f"Pages inventoried: **{len(evidence.pages)}**  ",
        f"Blocked items requiring review: **{len(evidence.blocked_items)}**",
        "",
        "## Page requirements",
        "",
    ]
    for index, page in enumerate(evidence.pages, 1):
        lines.extend([f"### {index}. {page.title or 'Untitled page'}", "", f"- URL: `{page.url}`"])
        if page.headings:
            lines.append(f"- Areas/headings: {', '.join(page.headings)}")
        if page.tabs:
            lines.append(f"- Tabs/navigation: {', '.join(page.tabs)}")
        if page.forms:
            lines.append(f"- Forms present: {', '.join(page.forms)}")
        if page.controls:
            lines.append("- Fields and available actions:")
            lines.extend(
                f"  - `{control.kind}` — {control.label or control.name or 'unlabelled'} "
                f"({control.risk})" for control in page.controls
            )
        if page.links:
            safe = [link.text or link.url for link in page.links if link.risk == "safe"]
            if safe:
                lines.append(f"- Safe linked navigation: {', '.join(safe)}")
        lines.append("")
    counts = Counter(item["reason"] for item in evidence.blocked_items)
    lines.extend(["## Blocked or review-required items", ""])
    if counts:
        lines.extend(f"- {reason}: {count}" for reason, count in sorted(counts.items()))
    else:
        lines.append("- None.")
    lines.extend(["", "## Follow-up validation", "", "- Confirm role-based visibility with an authorized user.", "- Validate business rules and data requirements with the product owner."])
    return "\n".join(lines) + "\n"

