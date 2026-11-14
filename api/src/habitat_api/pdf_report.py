from collections.abc import Callable
from html import escape
from io import BytesIO
from uuid import UUID

from PIL import Image as PillowImage, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .models import ApprovedReport


def render_report(snapshot: ApprovedReport, load_photo: Callable[[UUID], bytes]) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=45, rightMargin=45, topMargin=45, bottomMargin=45,
                                  title=f"Inspection report {snapshot.id}", author=snapshot.approved_by)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=12)
    title = ParagraphStyle("title", parent=body, fontSize=22, leading=28, textColor=colors.HexColor("#18664f"), spaceAfter=20)
    heading = ParagraphStyle("heading", parent=body, fontSize=14, leading=20, spaceAfter=12)
    story = [Paragraph("Habitat Inspection Report", title), Paragraph(escape(snapshot.property_address), heading),
             Paragraph(f"Client: {escape(snapshot.client_name)}", body),
             Paragraph(f"Inspector approval: {escape(snapshot.approved_by)}<br/>{snapshot.approved_at.isoformat()}", body),
             Paragraph(f"Inspection: {snapshot.inspection_id}<br/>Approved report: {snapshot.id}", body),
             Paragraph(f"{len(snapshot.findings)} approved findings", heading)]
    for number, finding in enumerate(snapshot.findings, 1):
        story.append(PageBreak())
        story.append(Paragraph(f"{number:02d} / {escape(finding.category.value.title())}", title))
        story.append(Paragraph(escape(finding.location), heading))
        with PillowImage.open(BytesIO(load_photo(finding.media_asset_id))) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"} or original.width * original.height > 30_000_000:
                raise ValueError("Unsafe image dimensions or format.")
            oriented = ImageOps.exif_transpose(original)
            oriented.thumbnail((1600, 1200))
            image_bytes = BytesIO()
            oriented.convert("RGB").save(image_bytes, format="JPEG", quality=90)
            scale = min(document.width / oriented.width, 300 / oriented.height)
            story.append(Image(image_bytes, width=oriented.width * scale, height=oriented.height * scale))
        story.append(Spacer(1, 16))
        story.append(Paragraph(f"Photo {number:02d}: {escape(finding.caption)}", heading))
        story.append(Paragraph(escape(finding.observation).replace("\n", "<br/>"), body))
        story.append(Paragraph(f"Evidence ID: {finding.media_asset_id}<br/>Review ID: {finding.id}", body))
    def footer(canvas, _document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5f6863"))
        canvas.drawString(45, 25, f"Habitat / Inspector-approved report / {str(snapshot.id)[:8]}")
        canvas.drawRightString(A4[0] - 45, 25, str(canvas.getPageNumber()))
        canvas.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()