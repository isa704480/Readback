"""The artefact.

Everything else in this codebase exists to fill a ServiceReport in; this module
is where that report leaves the building. It is what the office emails to the
customer and staples to a warranty claim, so it is held to a different standard
than a screen: nobody can hover a tooltip on a printout, and nobody will ring
the technician back to ask what "partial" meant.

Two decisions worth naming.

First, the completeness footer is rendered from ``evaluate()``, never from a
second copy of the rules. A PDF that said a report was fine while the office
screen said it was blocked would be worse than no PDF at all -- the whole
product is the claim that one engine decides what "billable" means.

Second, a draft prints. It would be easy, and wrong, to refuse: technicians and
office staff pass drafts around while a job is still open, and a draft that
silently looks like a finished report is exactly how an unbillable job reaches
a customer. So the draft prints with a red banner across it naming the blocking
gaps in the same words the agent used on the phone.

reportlab is deliberate: pure Python, no system libraries. weasyprint would need
GTK on Windows and the export would be undeployable on half the machines that
have to run it.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .completeness import evaluate
from .models import Organization, ReportStatus, ServiceReport

# --------------------------------------------------------------------------
# palette -- the office half of the design language, measured on paper
#
# Every pair below is the same one the office screen uses, so a printout and
# the dispatcher's monitor cannot disagree about what red means.
#   ink 16.9:1  ink-2 7.0:1  ledger 9.5:1  amber 4.6:1  block 6.1:1 on paper
# --------------------------------------------------------------------------

RAISED = colors.HexColor("#fbfaf8")
INK = colors.HexColor("#16150f")
INK_2 = colors.HexColor("#57544b")
LINE = colors.HexColor("#e4e1d9")
LINE_STRONG = colors.HexColor("#d3cfc4")
LEDGER = colors.HexColor("#14493c")
LEDGER_SOFT = colors.HexColor("#e7f0ec")
AMBER = colors.HexColor("#9c6500")
AMBER_SOFT = colors.HexColor("#fdf0d8")
BLOCK = colors.HexColor("#b4231c")
BLOCK_SOFT = colors.HexColor("#fbeae9")
DONE = colors.HexColor("#1f7a5c")

# Calistoga / Inter / IBM Plex Mono are web fonts. Embedding three TTF files to
# reproduce them exactly would add megabytes to every export for a difference
# nobody notices on paper, so the roles carry over instead of the faces:
# a serif display for the masthead, a grotesque for body, mono for data.
DISPLAY = "Times-Bold"
BODY = "Helvetica"
BODY_BOLD = "Helvetica-Bold"
MONO = "Courier"
MONO_BOLD = "Courier-Bold"

PAGE = A4
MARGIN = 16 * mm
CONTENT_WIDTH = PAGE[0] - 2 * MARGIN

RESOLUTION_LABELS = {
    "resolved": "Resolved",
    "partial": "Partially resolved",
    "return_visit": "Return visit required",
    "quote_required": "Quote required",
}

SEVERITY_LABELS = {"info": "Info", "monitor": "Monitor", "urgent": "Urgent"}
SEVERITY_COLOURS = {"info": INK_2, "monitor": AMBER, "urgent": BLOCK}

DASH = "—"


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body",
        fontName=BODY,
        fontSize=9.6,
        leading=14,
        textColor=INK,
    )
    return {
        "body": base,
        "company": ParagraphStyle(
            "company", parent=base, fontName=DISPLAY, fontSize=17, leading=20,
            textColor=LEDGER,
        ),
        "title": ParagraphStyle(
            "title", parent=base, fontName=BODY_BOLD, fontSize=9,
            textColor=INK_2, alignment=2, leading=12,
        ),
        "titleNo": ParagraphStyle(
            "titleNo", parent=base, fontName=MONO_BOLD, fontSize=12,
            textColor=INK, alignment=2, leading=15,
        ),
        "section": ParagraphStyle(
            "section", parent=base, fontName=BODY_BOLD, fontSize=8.4,
            textColor=LEDGER, leading=11, spaceAfter=0,
        ),
        "label": ParagraphStyle(
            "label", parent=base, fontName=BODY_BOLD, fontSize=7.8,
            textColor=INK_2, leading=11,
        ),
        "value": ParagraphStyle("value", parent=base, fontSize=9.6, leading=13),
        "mono": ParagraphStyle(
            "mono", parent=base, fontName=MONO, fontSize=8.6, leading=12,
        ),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.8, leading=11.6),
        "cellMono": ParagraphStyle(
            "cellMono", parent=base, fontName=MONO, fontSize=8.2, leading=11.6,
        ),
        "th": ParagraphStyle(
            "th", parent=base, fontName=BODY_BOLD, fontSize=7.6, leading=10,
            textColor=INK_2,
        ),
        "gap": ParagraphStyle(
            "gap", parent=base, fontSize=9, leading=12.4, textColor=INK,
            leftIndent=10, bulletIndent=0,
        ),
        "note": ParagraphStyle(
            "note", parent=base, fontSize=8.4, leading=11.6, textColor=INK_2,
        ),
        "bannerTitle": ParagraphStyle(
            "bannerTitle", parent=base, fontName=BODY_BOLD, fontSize=11.5,
            leading=15, textColor=BLOCK,
        ),
        "caption": ParagraphStyle(
            "caption", parent=base, fontSize=7.8, leading=10.5, textColor=INK_2,
        ),
    }


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _txt(value: str | None) -> str:
    return escape((value or "").strip())


def _or_dash(value: str | None) -> str:
    cleaned = (value or "").strip()
    return escape(cleaned) if cleaned else DASH


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return DASH
    # SQLite hands back naive datetimes even for DateTime(timezone=True).
    # Everything written here is UTC, so say so rather than printing a bare
    # time that a reader in another country will silently misread.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _fmt_qty(value: float | None) -> str:
    if value is None:
        return DASH
    return f"{value:g}"


def _clean_safety_note(report: ServiceReport) -> str:
    """Strip the [no-findings] marker the completeness engine parks in here."""
    return (report.safety_note or "").replace("[no-findings]", "").strip()


def pdf_filename(report: ServiceReport) -> str:
    """A filename an email client and a Windows share will both accept.

    Content-Disposition is a header: a work order number carrying a quote or a
    newline would let the value break out of it, so the alphabet is closed
    rather than filtered.
    """
    wo = report.work_order
    number = (wo.number if wo else "") or "service-report"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", number).strip("-.") or "service-report"
    state = "final" if report.status is ReportStatus.final else "draft"
    return f"{safe[:60]}-{state}.pdf"


# --------------------------------------------------------------------------
# flowables
# --------------------------------------------------------------------------

class _Rule(Flowable):
    """A hairline. Cheaper than a table and it never invents padding."""

    def __init__(self, width: float, colour=LINE, thickness: float = 0.6):
        super().__init__()
        self.width = width
        self.height = thickness
        self._colour = colour
        self._thickness = thickness

    def draw(self) -> None:
        self.canv.setStrokeColor(self._colour)
        self.canv.setLineWidth(self._thickness)
        self.canv.line(0, 0, self.width, 0)


class _ScoreBar(Flowable):
    """The completeness score as a bar, because a number alone gets skimmed.

    Colour follows the same rule as the office screen: green only when the
    report can actually be billed, amber when it is merely tidy.
    """

    def __init__(self, width: float, score: int, billable: bool):
        super().__init__()
        self.width = width
        self.height = 7
        self._score = max(0, min(100, int(score)))
        self._billable = billable

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(LINE)
        c.roundRect(0, 0, self.width, self.height, 3.5, stroke=0, fill=1)
        filled = self.width * self._score / 100.0
        if filled > 0.5:
            c.setFillColor(DONE if self._billable else AMBER)
            c.roundRect(0, 0, max(filled, 7), self.height, 3.5, stroke=0, fill=1)


# --------------------------------------------------------------------------
# photos
# --------------------------------------------------------------------------

_DATA_URI = re.compile(
    r"^data:image/[a-zA-Z0-9.+-]+\s*;\s*base64\s*,(?P<payload>.+)$", re.DOTALL
)

MAX_PHOTOS = 2
MAX_PHOTO_BYTES = 12 * 1024 * 1024


def _photo_flowable(data_url: str, max_w: float, max_h: float) -> Image | None:
    """One photo, scaled to fit, or None.

    Everything in here is somebody else's bytes: a data URI assembled by a
    phone browser, stored months ago, possibly truncated in transit. A photo is
    the least important thing on this page and the most likely to be malformed,
    so it is never allowed to be the reason a warranty claim cannot be printed.
    """
    match = _DATA_URI.match((data_url or "").strip())
    if match is None:
        return None
    payload = re.sub(r"\s+", "", match.group("payload"))
    if len(payload) > MAX_PHOTO_BYTES:
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    try:
        width, height = ImageReader(io.BytesIO(raw)).getSize()
        if not width or not height:
            return None
        scale = min(max_w / width, max_h / height)
        # A fresh stream, and lazy=0 so the bytes are decoded here inside the
        # try rather than at build time, where a failure would take the whole
        # document down instead of one photo.
        return Image(
            io.BytesIO(raw),
            width=width * scale,
            height=height * scale,
            lazy=0,
        )
    except Exception:
        # Pillow raises a wide and undocumented family of errors on corrupt
        # image data. There is no useful distinction between them here.
        return None


def _photo_block(report: ServiceReport, st: dict) -> list:
    cell_w = (CONTENT_WIDTH - 10) / 2
    cells: list[list] = []
    for photo in report.photos[:MAX_PHOTOS]:
        try:
            image = _photo_flowable(photo.data_url, cell_w - 8, 118)
        except Exception:
            image = None
        if image is None:
            continue
        caption = _txt(photo.caption) or "Site photograph"
        cells.append([image, Spacer(1, 4), Paragraph(caption, st["caption"])])

    if not cells:
        return []

    while len(cells) < 2:
        cells.append([Spacer(1, 1)])

    grid = Table([cells], colWidths=[cell_w, cell_w])
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [*_heading("Photographs", st), grid, Spacer(1, 14)]


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _heading(text: str, st: dict) -> list:
    """A section rule, returned flat.

    Every piece carries keepWithNext, so reportlab pulls the section's first
    content flowable up with it rather than leaving "PARTS FITTED" stranded at
    the foot of a page with the parts on the next one.

    Flat on purpose. A KeepTogether nested inside another KeepTogether measures
    as 0xffffff high -- reportlab's outer wrap() reads the inner one's forced
    split height as its real height -- and the enclosing block then breaks to a
    new page every time, however much room is left. That cost the completeness
    footer a page of its own before it was noticed.
    """
    block = [
        Paragraph(escape(text.upper()), st["section"]),
        Spacer(1, 3),
        _Rule(CONTENT_WIDTH, LINE_STRONG),
        Spacer(1, 7),
    ]
    for flowable in block:
        flowable.keepWithNext = 1
    return block


def _masthead(report: ServiceReport, organization: Organization | None, st: dict) -> list:
    wo = report.work_order
    company = (organization.name if organization else "") or "Service Report"
    final = report.status is ReportStatus.final

    filed_label = "Date filed" if final else "Draft opened"
    filed_value = _fmt_dt(report.finalized_at if final else report.created_at)

    # The verdict belongs beside the work order number, not only in the footer.
    # A dispatcher who prints this and hands page one across a desk has to see
    # that it cannot be billed without turning to the last page for the reasons.
    chip_text = (
        ("FILED " + DASH + " BILLABLE")
        if final
        else ("DRAFT " + DASH + " NOT BILLABLE")
    )
    # Measured, not guessed: a table with no colWidths eats the whole column,
    # and a full-width chip reads as a banner rather than a status.
    chip_width = stringWidth(chip_text, BODY_BOLD, 8) + 16
    chip = Table(
        [
            [
                Paragraph(
                    chip_text,
                    ParagraphStyle(
                        "chip",
                        parent=st["note"],
                        fontName=BODY_BOLD,
                        fontSize=8,
                        leading=11,
                        textColor=LEDGER if final else BLOCK,
                    ),
                )
            ]
        ],
        colWidths=[chip_width],
    )
    chip.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LEDGER_SOFT if final else BLOCK_SOFT),
                ("BOX", (0, 0), (-1, -1), 0.7, LEDGER if final else BLOCK),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    chip.hAlign = "LEFT"

    left = [
        Paragraph(escape(company), st["company"]),
        Spacer(1, 2),
        Paragraph("Field service report", st["note"]),
        Spacer(1, 9),
        chip,
    ]
    right = [
        Paragraph("WORK ORDER", st["title"]),
        Paragraph(_or_dash(wo.number if wo else ""), st["titleNo"]),
        Spacer(1, 3),
        Paragraph(
            f"{escape(filed_label)}: {escape(filed_value)}",
            ParagraphStyle("filed", parent=st["note"], alignment=2),
        ),
    ]

    head = Table([[left, right]], colWidths=[CONTENT_WIDTH * 0.56, CONTENT_WIDTH * 0.44])
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [head, Spacer(1, 10), _Rule(CONTENT_WIDTH, LEDGER, 1.6), Spacer(1, 14)]


def _facts_table(rows: list[tuple[str, str, bool]], st: dict) -> Table:
    """Label/value pairs. `mono` marks the fields somebody will type into a form."""
    data = [
        [
            Paragraph(escape(label.upper()), st["label"]),
            Paragraph(value, st["cellMono"] if mono else st["value"]),
        ]
        for label, value, mono in rows
    ]
    table = Table(data, colWidths=[CONTENT_WIDTH * 0.26, CONTENT_WIDTH * 0.74])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _job_section(report: ServiceReport, st: dict) -> list:
    wo = report.work_order
    site = wo.site if wo else None
    asset = wo.asset if wo else None

    asset_line = DASH
    if asset is not None:
        make_model = " ".join(p for p in [asset.make, asset.model] if p and p.strip())
        parts = [asset.label or DASH]
        if make_model:
            parts.append(make_model)
        asset_line = escape(" · ".join(parts))

    warranty = "Yes" if wo and wo.under_warranty else "No"
    warranty_cell = (
        f'<font color="#9c6500"><b>{warranty}</b></font>'
        if wo and wo.under_warranty
        else warranty
    )

    rows = [
        ("Site", _or_dash(site.label if site else ""), False),
        ("Address", _or_dash(site.address if site else ""), False),
        ("Job type", _or_dash((wo.job_type if wo else "").replace("_", " ").title()), False),
        ("Reported fault", _or_dash(wo.complaint if wo else ""), False),
        ("Asset", asset_line, False),
        ("Asset serial", _or_dash(asset.serial if asset else ""), True),
        ("Under warranty", warranty_cell, False),
    ]
    return [*_heading("Job", st), _facts_table(rows, st), Spacer(1, 14)]


def _work_section(report: ServiceReport, st: dict) -> list:
    resolution = (
        RESOLUTION_LABELS.get(report.resolution.value, report.resolution.value)
        if report.resolution
        else ""
    )
    if report.resolution and report.resolution.value != "resolved":
        resolution = f'<font color="#9c6500"><b>{escape(resolution)}</b></font>'
    elif resolution:
        resolution = f'<font color="#14493c"><b>{escape(resolution)}</b></font>'
    else:
        resolution = '<font color="#b4231c"><b>Not recorded</b></font>'

    hours = report.labor_hours
    labour = (
        f"{_fmt_qty(hours)} h"
        if hours
        else '<font color="#b4231c">Not recorded</font>'
    )
    travel = (
        f"{report.travel_minutes} min" if report.travel_minutes is not None else DASH
    )

    rows = [
        ("Work performed", _or_dash(report.work_summary), False),
        ("Cause", _or_dash(report.cause), False),
        ("Resolution", resolution, False),
        ("Labour on site", labour, True),
        ("Travel", travel, True),
    ]
    return [*_heading("Work performed", st), _facts_table(rows, st), Spacer(1, 14)]


def _data_table(header: list[str], body: list[list], widths: list[float], st: dict) -> Table:
    data = [[Paragraph(escape(h.upper()), st["th"]) for h in header]] + body
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), RAISED),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE_STRONG),
                ("LINEBELOW", (0, 1), (-1, -2), 0.4, LINE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _parts_section(report: ServiceReport, st: dict) -> list:
    if not report.parts:
        return [
            *_heading("Parts fitted", st),
            Paragraph("No parts recorded on this job.", st["note"]),
            Spacer(1, 14),
        ]

    body = []
    for part in report.parts:
        # A missing serial on a warranty-bearing part is the single most
        # expensive omission in this document, so it is called out in red on
        # the line itself, not only in the footer.
        serial = (part.serial or "").strip()
        if serial:
            serial_cell = Paragraph(escape(serial), st["cellMono"])
        elif part.warranty_bearing:
            serial_cell = Paragraph(
                '<font color="#b4231c"><b>MISSING</b></font>', st["cellMono"]
            )
        else:
            serial_cell = Paragraph(DASH, st["cellMono"])

        body.append(
            [
                Paragraph(_or_dash(part.part_number), st["cellMono"]),
                Paragraph(_or_dash(part.description), st["cell"]),
                Paragraph(_fmt_qty(part.quantity), st["cellMono"]),
                serial_cell,
                Paragraph("Yes" if part.warranty_bearing else "No", st["cell"]),
            ]
        )

    widths = [
        CONTENT_WIDTH * 0.17,
        CONTENT_WIDTH * 0.36,
        CONTENT_WIDTH * 0.08,
        CONTENT_WIDTH * 0.25,
        CONTENT_WIDTH * 0.14,
    ]
    table = _data_table(
        ["Part no.", "Description", "Qty", "Serial", "Warranty"], body, widths, st
    )
    return [*_heading("Parts fitted", st), table, Spacer(1, 14)]


def _findings_section(report: ServiceReport, st: dict) -> list:
    if not report.findings:
        return [
            *_heading("Findings", st),
            Paragraph(
                "Nothing outstanding was reported on this visit.", st["note"]
            ),
            Spacer(1, 14),
        ]

    body = []
    for finding in report.findings:
        key = finding.severity.value
        colour = SEVERITY_COLOURS.get(key, INK_2).hexval()[2:]
        label = SEVERITY_LABELS.get(key, key.title())
        body.append(
            [
                Paragraph(f'<font color="#{colour}"><b>{escape(label)}</b></font>', st["cell"]),
                Paragraph(_or_dash(finding.description), st["cell"]),
                Paragraph(_or_dash(finding.recommended_work), st["cell"]),
            ]
        )

    widths = [CONTENT_WIDTH * 0.14, CONTENT_WIDTH * 0.47, CONTENT_WIDTH * 0.39]
    table = _data_table(
        ["Severity", "Finding", "Recommended work"], body, widths, st
    )
    return [
        *_heading("Findings not addressed today", st),
        table,
        Spacer(1, 6),
        Paragraph(
            "Findings are work identified but not carried out on this visit. "
            "They are quotable.",
            st["note"],
        ),
        Spacer(1, 14),
    ]


def _safety_section(report: ServiceReport, st: dict) -> list:
    note = _clean_safety_note(report)
    if not note:
        return []

    cell = Table(
        [[Paragraph(escape(note), st["value"])]],
        colWidths=[CONTENT_WIDTH],
    )
    cell.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), AMBER_SOFT),
                ("BOX", (0, 0), (-1, -1), 0.6, AMBER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [*_heading("Safety note", st), cell, Spacer(1, 14)]


def _completeness_section(report: ServiceReport, st: dict) -> list:
    """The footer that decides whether this page is an invoice or a warning.

    Sourced entirely from evaluate(). If the rules change, this changes with
    them; there is no second opinion encoded here.
    """
    result = evaluate(report)
    final = report.status is ReportStatus.final
    billable = final and result.can_finalize

    checked = len(result.satisfied) + len(result.gaps)
    summary = (
        f"{result.score}% complete "
        f"{DASH} {len(result.satisfied)} of {checked} checks satisfied"
    )

    flow: list = [
        *_heading("Completeness", st),
        _ScoreBar(CONTENT_WIDTH, result.score, billable),
        Spacer(1, 6),
        Paragraph(escape(summary), st["value"]),
        Spacer(1, 10),
    ]

    if not final:
        banner_rows = [
            [Paragraph("DRAFT " + DASH + " NOT BILLABLE", st["bannerTitle"])],
            [
                Paragraph(
                    "This report has not been filed. Do not invoice from it and "
                    "do not submit it with a warranty claim.",
                    ParagraphStyle("bannerBody", parent=st["value"], textColor=INK),
                )
            ],
        ]
        if result.blockers:
            banner_rows.append(
                [
                    Paragraph(
                        "Still required before this job can be closed:",
                        ParagraphStyle(
                            "bannerLead", parent=st["value"], fontName=BODY_BOLD
                        ),
                    )
                ]
            )
            for gap in sorted(result.blockers, key=lambda g: g.cost_rank):
                banner_rows.append(
                    [Paragraph(escape(gap.prompt), st["gap"], bulletText="•")]
                )
        else:
            banner_rows.append(
                [
                    Paragraph(
                        "Nothing is blocking it. The technician has not filed it yet.",
                        st["value"],
                    )
                ]
            )

        banner = Table(banner_rows, colWidths=[CONTENT_WIDTH])
        banner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BLOCK_SOFT),
                    ("BOX", (0, 0), (-1, -1), 1.2, BLOCK),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (0, 0), 10),
                    ("TOPPADDING", (0, 1), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -2), 4),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
                ]
            )
        )
        flow.append(banner)
    else:
        filed = Table(
            [
                [
                    Paragraph(
                        "FILED " + DASH + " BILLABLE",
                        ParagraphStyle(
                            "filedTitle", parent=st["bannerTitle"], textColor=LEDGER
                        ),
                    )
                ],
                [
                    Paragraph(
                        "Filed "
                        + escape(_fmt_dt(report.finalized_at))
                        + ". Every blocking check passed at the time of filing.",
                        st["value"],
                    )
                ],
            ],
            colWidths=[CONTENT_WIDTH],
        )
        filed.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), LEDGER_SOFT),
                    ("BOX", (0, 0), (-1, -1), 1.2, LEDGER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (0, 0), 10),
                    ("TOPPADDING", (0, 1), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (0, 0), 4),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
                ]
            )
        )
        flow.append(filed)

        if result.gaps:
            flow.append(Spacer(1, 8))
            skipped = ", ".join(g.key.replace("_", " ") for g in result.gaps)
            flow.append(
                Paragraph(
                    "Optional items left out: " + escape(skipped) + ".", st["note"]
                )
            )

    # One unit. A verdict split across a page break -- the score at the bottom
    # of one page and the reason it is not billable at the top of the next --
    # is how somebody bills a draft.
    return [KeepTogether(flow)]


# --------------------------------------------------------------------------
# page furniture
# --------------------------------------------------------------------------

def _page_furniture(report: ServiceReport, organization: Organization | None):
    wo = report.work_order
    number = (wo.number if wo else "") or "service report"
    company = (organization.name if organization else "") or ""
    draft = report.status is not ReportStatus.final

    def draw(canvas, doc) -> None:
        canvas.saveState()

        # A draft that reaches a printer must still read as a draft from across
        # a desk, on any page, even if the footer is what got photocopied.
        if draft:
            canvas.saveState()
            canvas.setFont(BODY_BOLD, 68)
            canvas.setFillColor(BLOCK)
            canvas.setFillAlpha(0.06)
            canvas.translate(PAGE[0] / 2, PAGE[1] / 2)
            canvas.rotate(52)
            canvas.drawCentredString(0, 0, "DRAFT")
            canvas.restoreState()

        y = MARGIN - 5
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, y + 12, PAGE[0] - MARGIN, y + 12)

        canvas.setFont(MONO, 7.4)
        canvas.setFillColor(INK_2)
        left = f"{number}" + (f"  ·  {company}" if company else "")
        canvas.drawString(MARGIN, y, left[:110])
        canvas.drawRightString(PAGE[0] - MARGIN, y, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return draw


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def render_report_pdf(
    report: ServiceReport, organization: Organization | None = None
) -> bytes:
    """Render one service report. Returns PDF bytes; never writes to disk."""
    st = _styles()

    story: list = []
    story += _masthead(report, organization, st)
    story += _job_section(report, st)
    story += _work_section(report, st)
    story += _parts_section(report, st)
    story += _findings_section(report, st)
    story += _safety_section(report, st)
    story += _photo_block(report, st)
    story += _completeness_section(report, st)

    wo = report.work_order
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 6,
        title=f"Service report {wo.number if wo else ''}".strip(),
        author=(organization.name if organization else "Closeout"),
        subject="Field service report",
        creator="Closeout",
    )
    furniture = _page_furniture(report, organization)
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return buffer.getvalue()
