"""Acknowledgement for an Executive Partnership Request.

Sent to the requester the moment the form is submitted. It is a receipt for
the request, not an acceptance: engagements are accepted on fit, capacity,
timing, sponsorship, and decision readiness, and this email must not read as
though a place has been reserved. It also avoids any claim about revenue,
savings, or EBITDA — the same restraint the advisory pricing copy uses.
"""

from html import escape

SUBJECT = "We received your Executive Partnership Request"
PREVIEW_TEXT = "Here is what you sent and what happens next."

INTRO_COPY = "Thank you for your interest in Jaspen Executive Partnerships."
REVIEW_COPY = (
    "We review every request personally to ensure the engagement is the right fit for both your "
    "organization and Jaspen."
)
NEXT_STEP_COPY = (
    "If your request aligns with our current capacity and expertise, we'll contact you to "
    "schedule an executive consultation."
)
DELIVERY_COPY = (
    "Advisory engagements are delivered through structured virtual working sessions. You execute "
    "within Jaspen while your advisor guides the decision process."
)
REPLY_COPY = (
    "If anything has changed, or you would like to add context before we speak, simply reply to "
    "this email."
)

ENGAGEMENT_LABELS = {
    "executive_decision_intensive": "Executive Decision Intensive ($25,000)",
    "strategic_advisor_partnership": "Strategic Advisor Partnership ($100,000)",
    "undecided": "Not sure yet — open to guidance",
}

TIMELINE_LABELS = {
    "within_30_days": "Within 30 days",
    "1_3_months": "1–3 months",
    "3_6_months": "3–6 months",
    "6_months_plus": "More than 6 months",
}

# Stored values are machine-readable; a receipt should read the way the form
# read, not "ceo, cfo".
PARTICIPANT_LABELS = {
    "ceo": "CEO",
    "founder": "Founder",
    "coo": "COO",
    "cfo": "CFO",
    "cio": "CIO",
    "business_unit_leader": "Business Unit Leader",
    "pmo": "PMO",
    "strategy_team": "Strategy Team",
    "other": "Other",
}


def _p(text):
    return escape(str(text or ""))


def _greeting(recipient_name):
    """First name only — "Hi Dr. Jane Smith," reads like a form letter."""
    first = str(recipient_name or "").strip().split(" ")[0].strip()
    return f"Hi {escape(first)}," if first else "Hi there,"


def _summary_rows(engagement_label, timeline_label, participants):
    rows = [("Engagement", engagement_label), ("Decision timing", timeline_label)]
    if participants:
        rows.append(("Participants", ", ".join(participants)))
    return rows


def render_advisory_request_received_email(
    *,
    recipient_name="",
    engagement="undecided",
    decision_timeline="",
    participants=(),
    advisory_email="partnerships@jaspen.ai",
):
    """Returns {subject, preview_text, body, html} for the acknowledgement."""
    greeting = _greeting(recipient_name)
    engagement_label = ENGAGEMENT_LABELS.get(str(engagement), ENGAGEMENT_LABELS["undecided"])
    timeline_label = TIMELINE_LABELS.get(str(decision_timeline), "Not specified")
    participant_list = [
        PARTICIPANT_LABELS.get(str(item), str(item).replace("_", " ").title())
        for item in (participants or [])
        if str(item).strip()
    ]
    rows = _summary_rows(engagement_label, timeline_label, participant_list)

    text_rows = "\n".join(f"{label}: {value}" for label, value in rows)
    text = f"""We received your Executive Partnership Request

{greeting}

{INTRO_COPY}

{REVIEW_COPY}

{text_rows}

What happens next: {NEXT_STEP_COPY}

{DELIVERY_COPY}

{REPLY_COPY}

Kind regards,
Lydia
Jaspen Advisory
{advisory_email}
"""

    rows_html = "".join(
        f"""<tr>
                      <td style="padding:6px 0; font-size:14px; line-height:1.6; color:#4f5d75; width:38%; vertical-align:top;">{_p(label)}</td>
                      <td style="padding:6px 0; font-size:15px; line-height:1.6; color:#07112f; font-weight:600;">{_p(value)}</td>
                    </tr>"""
        for label, value in rows
    )

    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>We received your Executive Partnership Request</title>
  </head>
  <body style="margin:0; padding:0; background:#eff9fc; font-family:Arial, Helvetica, sans-serif; color:#172033;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">{_p(PREVIEW_TEXT)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eff9fc; padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px; background:#ffffff; border:1px solid #cde7f0; border-radius:18px; overflow:hidden;">
            <tr>
              <td style="padding:24px 28px; background:#161f3b;">
                <div style="font-size:24px; line-height:1; color:#ffffff; font-weight:700;">Jaspen</div>
              </td>
            </tr>
            <tr>
              <td style="padding:34px 28px 26px; background:#161f3b;">
                <p style="margin:0 0 10px; font-size:13px; line-height:1.4; letter-spacing:.08em; text-transform:uppercase; color:#f0a6d4; font-weight:700;">Request received</p>
                <h1 style="margin:0; font-size:28px; line-height:1.18; color:#ffffff;">We have your Executive Partnership Request</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 28px 2px;">
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#172033;">{greeting}</p>
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(INTRO_COPY)}</p>
                <p style="margin:0; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(REVIEW_COPY)}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px 6px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eff9fc; border:1px solid #cde7f0; border-radius:14px;">
                  <tr>
                    <td style="padding:20px;">
                      <h2 style="margin:0 0 10px; font-size:16px; line-height:1.3; color:#07112f;">What you sent</h2>
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                        {rows_html}
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px 6px;">
                <h2 style="margin:0 0 8px; font-size:16px; line-height:1.3; color:#07112f;">What happens next</h2>
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(NEXT_STEP_COPY)}</p>
                <p style="margin:0; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(DELIVERY_COPY)}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px 34px;">
                <p style="margin:0 0 18px; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(REPLY_COPY)}</p>
                <p style="margin:0 0 4px; font-size:15px; line-height:1.65; color:#4f5d75;">Kind regards,</p>
                <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">Lydia</p>
                <p style="margin:2px 0 0; font-size:15px; line-height:1.65; color:#4f5d75;">Jaspen Advisory</p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px; background:#161f3b;">
                <p style="margin:0; font-size:13px; line-height:1.5; color:#d9deec;">You received this because you submitted an Executive Partnership Request at jaspen.ai. This is a confirmation of that request, not a marketing email.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    return {"subject": SUBJECT, "preview_text": PREVIEW_TEXT, "body": text, "html": html}
