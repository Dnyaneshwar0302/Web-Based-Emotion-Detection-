from datetime import datetime, timedelta, timezone
from collections import Counter
from io import BytesIO
import matplotlib
matplotlib.use("Agg")

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    HRFlowable
)

import matplotlib.pyplot as plt
import numpy as np


def generate_weekly_report_pdf(user, logs, week_start, week_end, goal=None, recommendation=None):

    from flask import session

    # Retrieve dashboard summary saved from frontend
    summary = session.get("latest_dashboard_summary")

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # ---------------------- BEAUTIFUL STYLES ----------------------
    title_style = ParagraphStyle(
        "Title",
        fontSize=26,
        leading=30,
        alignment=1,
        textColor=colors.HexColor("#f8170b"),
        spaceAfter=20,
        fontName="Helvetica-Bold"
    )

    section_header = ParagraphStyle(
        "SectionHeader",
        fontSize=17,
        leading=22,
        textColor=colors.HexColor("#c2185b"),
        spaceBefore=20,
        spaceAfter=10,
        fontName="Helvetica-Bold"
    )

    normal = ParagraphStyle(
        "Normal",
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#4a4a4a")
    )

    small = ParagraphStyle(
        "Small",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#777")
    )

    # ---------------------- PDF FLOW ----------------------
    flow = []

    # 🌸 TITLE
    flow.append(Paragraph("🌸 Emotion Detection Report ", title_style))

    flow.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor("#ff9ecd"),
            spaceBefore=10,
            spaceAfter=20
        )
    )

    # 🌸 Meta Info
    meta = (
        f"<b>User:</b> {user.username}<br/>"
        f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    flow.append(Paragraph(meta, normal))
    flow.append(Spacer(1, 12))

    # 🎀 SECTION: Summary
    flow.append(Paragraph("💖 Emotion Summary", section_header))

    # If no summary exists
    if not summary:
        flow.append(Paragraph("No dashboard summary available.", normal))

    else:
        # Build table from summary
        table_data = [["Emotion", "Count", "Percentage"]]
        for item in summary:
            table_data.append([
                item["emotion"].capitalize(),
                str(item["count"]),
                f"{item['percentage']:.1f}%"
            ])

        table = Table(
            table_data,
            colWidths=[2.2 * inch, 1 * inch, 1 * inch]
        )

        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ff77c9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#f8c4e4")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ffe6f3")),
        ]))
        flow.append(table)
        flow.append(Spacer(1, 20))

        # PIE CHART
        labels = [item["emotion"].capitalize() for item in summary]
        sizes = [item["count"] for item in summary]

        cute_colors = [
            "#ff6b6b", "#feca57", "#54a0ff",
            "#5f27cd", "#1dd1a1", "#ff9ff3"
        ]

        fig, ax = plt.subplots(figsize=(4, 4))
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", colors=cute_colors)
        ax.set_title("Emotion Distribution (Dashboard Summary)")

        img_buf = BytesIO()
        plt.savefig(img_buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        img_buf.seek(0)

        flow.append(Image(img_buf, width=300, height=300))
        flow.append(Spacer(1, 20))

    # 🎯 GOAL SECTION — ALWAYS SHOW HAPPY
    flow.append(Paragraph("🎯 Your Current Goal", section_header))

    flow.append(Paragraph("<b>Target Emotion:</b> happy", normal))

    flow.append(Spacer(1, 20))

    # 💡 RECOMMENDATION SECTION
    flow.append(Paragraph("💡 Personalized Recommendation", section_header))

    if recommendation:
        flow.append(Paragraph(recommendation, normal))
    else:
        flow.append(Paragraph("Not enough data for a recommendation.", normal))

    flow.append(Spacer(1, 20))

    # ⏳ TIMELINE SECTION
    flow.append(Paragraph("⏳ Recent Emotion Timeline", section_header))

    emotions = [log.emotion for log in logs]
    total = len(emotions)

    if total == 0:
        flow.append(Paragraph("No timeline available.", normal))
    else:
        timeline_data = [["Timestamp", "Emotion", "Confidence"]]
        for log in sorted(logs, key=lambda x: x.timestamp, reverse=True)[:20]:
            timeline_data.append([
                log.timestamp.strftime("%H:%M:%S"),
                log.emotion.capitalize(),
                f"{(log.confidence or 0) * 100:.1f}%"
            ])

        timeline_table = Table(
            timeline_data,
            colWidths=[1.5 * inch, 1.3 * inch, 1.3 * inch]
        )

        timeline_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#060204")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#f3cfe8")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ffeef9")),
        ]))

        flow.append(timeline_table)

    # Build PDF
    doc.build(flow)
    buffer.seek(0)
    return buffer
