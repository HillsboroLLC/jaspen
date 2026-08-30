# backend/app/decision_report_email.py
#
# The Decision Confidence report as emailed HTML and plain text.
#
# Document-shaped: the reader is scrolling, so this renders the whole report
# including every criterion. The deck renders a different subset at a
# different density, on purpose. See decision_report.build_report.
#
# Inline styles throughout, because email clients discard <style> blocks. No
# external assets, no web fonts, and a table-free layout except where a table
# is genuinely tabular, since that is what survives Outlook.
#
# Two limits travel with the content and are enforced here in markup:
#
#   Verified evidence and Jaspen's assessment are visually separate and
#   separately labelled. The assessment carries no source styling, because it
#   is reasoning rather than a citation.
#
#   Edited wording is marked. A narrative a person rewrote must not leave the
#   building looking like Jaspen's own finding.

import html

NAVY = "#161f3b"
SLATE = "#5a6585"
MUTED = "#8a93ad"
ROSE = "#a0036c"
LINE = "#dfe6ef"
GREEN = "#0e6b3f"
AMBER = "#8a5406"
BLUE = "#1f5f9e"


def _esc(value):
    return html.escape(str(value or ""))


def _label(text, color):
    return (
        f'<p style="margin:0 0 4px;font:700 10px/1.4 Arial,sans-serif;'
        f'letter-spacing:.09em;text-transform:uppercase;color:{color}">{_esc(text)}</p>'
    )


def _criterion_html(criterion):
    """One criterion, in the same order the workspace uses.

    Evidence first because it was verified, then the assessment, then what is
    still unsupported, then what would resolve it.
    """
    severity = criterion.get("severity")
    rule = {"reversing": "#dc2626", "material": "#f59e0b"}.get(severity, LINE)

    parts = [
        f'<tr><td style="padding:0 0 14px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid #e6eaf2;border-left:3px solid {rule};'
        f'background:#fcfdfe"><tr><td style="padding:13px 16px">'
    ]

    edited = (
        f'<span style="margin-left:8px;font:700 9px/1 Arial,sans-serif;'
        f'letter-spacing:.08em;text-transform:uppercase;color:{AMBER};'
        f'background:#fdf2dc;border:1px solid #f0c675;padding:2px 5px">Edited</span>'
        if criterion.get("edited") else ""
    )
    parts.append(
        f'<p style="margin:0 0 4px;font:600 15px/1.3 Arial,sans-serif;color:{NAVY}">'
        f'{_esc(criterion["label"])}'
        f'<span style="font:700 9px/1 Arial,sans-serif;letter-spacing:.07em;'
        f'text-transform:uppercase;color:{SLATE};margin-left:8px">'
        f'{_esc(criterion["grade_label"])}</span></p>'
    )

    meta = f'{criterion["weight_pct"]}% of the decision &middot; contributes {criterion["contributes"]}'
    if criterion.get("swing"):
        meta += f' &middot; {criterion["swing"]} points of exposure'
    parts.append(
        f'<p style="margin:0 0 10px;font:400 11px/1.4 Arial,sans-serif;color:{MUTED}">{meta}</p>'
    )

    if criterion.get("evidence"):
        parts.append(f'<div style="border-left:2px solid #10b981;padding-left:10px;margin:0 0 10px">')
        parts.append(_label("Evidence used", GREEN))
        for item in criterion["evidence"]:
            parts.append(
                f'<p style="margin:0 0 6px;font:400 13px/1.5 Arial,sans-serif;color:{NAVY}">'
                f'&ldquo;{_esc(item["excerpt"])}&rdquo;<br>'
                f'<span style="font:400 10px/1.4 Arial,sans-serif;color:{GREEN}">'
                f'{_esc(item["source"])}</span></p>'
            )
        parts.append("</div>")

    parts.append(f'<div style="border-left:2px solid #e6eaf2;padding-left:10px;margin:0 0 10px">')
    parts.append(_label("Jaspen's assessment", SLATE) if not edited
                 else f'<p style="margin:0 0 4px;font:700 10px/1.4 Arial,sans-serif;'
                      f'letter-spacing:.09em;text-transform:uppercase;color:{SLATE}">'
                      f"Jaspen's assessment{edited}</p>")
    parts.append(
        f'<p style="margin:0;font:400 13px/1.55 Arial,sans-serif;color:{SLATE}">'
        f'{_esc(criterion.get("assessment") or "No assessment was recorded for this criterion.")}</p>'
    )
    if criterion.get("assessment_basis"):
        parts.append(
            f'<p style="margin:3px 0 0;font:600 12px/1.4 Arial,sans-serif;color:{NAVY}">'
            f'{_esc(criterion["assessment_basis"])}</p>'
        )
    parts.append("</div>")

    if criterion.get("unsupported"):
        parts.append(
            f'<div style="border-left:2px solid #f5d9a4;padding-left:10px;margin:0 0 10px">'
            + _label("Still unsupported", AMBER)
            + f'<p style="margin:0;font:400 13px/1.55 Arial,sans-serif;color:{SLATE}">'
              f'{_esc(criterion["unsupported"])}</p></div>'
        )

    if criterion.get("evidence_needed"):
        parts.append(
            f'<div style="border-left:2px solid #9dc2e6;padding-left:10px">'
            + _label("How to improve this", BLUE)
            + f'<p style="margin:0;font:400 13px/1.55 Arial,sans-serif;color:{SLATE}">'
              f'{_esc(criterion["evidence_needed"])}</p></div>'
        )

    parts.append("</td></tr></table></td></tr>")
    return "".join(parts)


def render_report_html(report):
    """The full report as an HTML fragment, or an empty string."""
    if not report:
        return ""

    summary = report.get("summary") or {}
    backed = report.get("evidence_backed_pct")
    assumed = report.get("assumption_dependent_pct")

    sentences = [
        summary.get("verdict"), summary.get("standing"), summary.get("confidence"),
        summary.get("concentration"),
    ]
    briefing = " ".join(s for s in sentences if s)

    # The split bar, drawn as a two-cell table because a styled div with a
    # percentage width is unreliable in Outlook.
    bar = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:8px 0 4px"><tr>'
        f'<td width="{backed}%" style="background:{GREEN};height:8px;font-size:0;line-height:0">&nbsp;</td>'
        f'<td width="{assumed}%" style="background:#f59e0b;height:8px;font-size:0;line-height:0">&nbsp;</td>'
        f"</tr></table>"
    )

    out = [
        f'<h2 style="margin:28px 0 8px;font:700 15px/1.3 Arial,sans-serif;'
        f'letter-spacing:.06em;text-transform:uppercase;color:{ROSE}">Decision Confidence</h2>',
        f'<p style="margin:0;font:400 15px/1.4 Arial,sans-serif;color:{SLATE}">'
        f'<strong style="font-size:19px;color:{NAVY}">{backed}%</strong> evidence-backed'
        f' &middot; <strong style="font-size:19px;color:{NAVY}">{assumed}%</strong> assumption-dependent</p>',
        bar,
        f'<p style="margin:0 0 14px;font:400 11px/1.4 Arial,sans-serif;color:{MUTED}">'
        f'Evidence-backed share of the weighted decision</p>',
    ]

    if briefing or summary.get("sensitivity"):
        out.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:#f7fafc;border-left:3px solid {NAVY};margin:0 0 18px">'
            f'<tr><td style="padding:14px 16px">'
        )
        out.append(_label("Summary", MUTED))
        if briefing:
            out.append(
                f'<p style="margin:0 0 8px;font:400 14px/1.6 Arial,sans-serif;color:{NAVY}">'
                f'{_esc(briefing)}</p>'
            )
        if summary.get("sensitivity"):
            out.append(
                f'<p style="margin:0;font:600 14px/1.55 Arial,sans-serif;color:{NAVY}">'
                f'{_esc(summary["sensitivity"])}</p>'
            )
        if summary.get("next_step"):
            out.append(
                f'<p style="margin:10px 0 0;padding-top:10px;border-top:1px solid #dfe6ef;'
                f'font:400 14px/1.55 Arial,sans-serif;color:{NAVY}">'
                + _label("Do this next", ROSE)
                + _esc(summary["next_step"]) + "</p>"
            )
        out.append("</td></tr></table>")

    out.append(
        f'<h3 style="margin:0 0 10px;font:700 11px/1.3 Arial,sans-serif;'
        f'letter-spacing:.09em;text-transform:uppercase;color:{NAVY}">'
        f'Evidence and assumption detail</h3>'
    )
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0">')
    for criterion in report.get("criteria", []):
        out.append(_criterion_html(criterion))
    out.append("</table>")

    out.append(
        f'<p style="margin:6px 0 0;padding-top:10px;border-top:1px solid #eef1f6;'
        f'font:400 11px/1.5 Arial,sans-serif;color:{MUTED}">'
        f'{_esc(report["provenance_note"])}</p>'
    )
    return "".join(out)


def render_report_text(report):
    """Plain-text mirror, for clients that refuse HTML."""
    if not report:
        return ""

    summary = report.get("summary") or {}
    lines = [
        "DECISION CONFIDENCE",
        f'{report["evidence_backed_pct"]}% evidence-backed / '
        f'{report["assumption_dependent_pct"]}% assumption-dependent',
        "(Evidence-backed share of the weighted decision)",
        "",
    ]
    for key in ("verdict", "standing", "confidence", "concentration", "sensitivity"):
        if summary.get(key):
            lines.append(summary[key])
    if summary.get("next_step"):
        lines += ["", f'DO THIS NEXT: {summary["next_step"]}']

    lines += ["", "EVIDENCE AND ASSUMPTION DETAIL"]
    for criterion in report.get("criteria", []):
        lines.append("")
        edited = " [EDITED]" if criterion.get("edited") else ""
        lines.append(f'{criterion["label"]} - {criterion["grade_label"]}{edited}')
        meta = f'{criterion["weight_pct"]}% of the decision, contributes {criterion["contributes"]}'
        if criterion.get("swing"):
            meta += f', {criterion["swing"]} points of exposure'
        lines.append(meta)
        for item in criterion.get("evidence", []):
            lines.append(f'  Evidence used: "{item["excerpt"]}" ({item["source"]})')
        if criterion.get("assessment"):
            lines.append(f'  Jaspen\'s assessment: {criterion["assessment"]}')
        if criterion.get("unsupported"):
            lines.append(f'  Still unsupported: {criterion["unsupported"]}')
        if criterion.get("evidence_needed"):
            lines.append(f'  How to improve this: {criterion["evidence_needed"]}')

    lines += ["", report["provenance_note"]]
    return "\n".join(lines)
