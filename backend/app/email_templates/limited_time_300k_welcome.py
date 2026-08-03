"""Purchase receipt and welcome email for the 300K Limited-Time offer.

Sent once, when Stripe confirms the purchase and the credits are granted. It
doubles as the receipt, so it states what was paid and what arrived; Stripe's
own receipt covers the payment record.
"""

from html import escape

SUBJECT = "Your 300,000 Jaspen credits are ready"
PREVIEW_TEXT = "Your purchase is confirmed. Here is what you have and where to start."

INTRO_COPY = (
    "Your purchase is confirmed and your credits are already on your account. "
    "There is nothing else to set up."
)
CREDITS_COPY = (
    "These credits do not expire and do not reset monthly. They stay until you use them, "
    "whether that takes a month or a year."
)
PERSONAL_COPY = (
    "They are personal to your account. If you later join a Team or Business plan, your credits "
    "stay yours rather than joining the shared pool, and your account signs in on one device at a "
    "time to keep them that way."
)
START_COPY = (
    "The best first step is a decision you are actually facing. Frame it, build the rubric, "
    "weigh the evidence, and keep the reasoning where you can find it later."
)
SUPPORT_COPY = (
    "If something does not work the way it should, reply to this email. We resolve the issue, "
    "or we refund it."
)


def _p(text):
    return escape(text or "")


def _greeting(recipient_name):
    """First name only - a receipt that says "Hi Dr. Jane Smith," reads like a form."""
    first = str(recipient_name or "").strip().split(" ")[0].strip()
    return f"Hi {escape(first)}," if first else "Hi there,"


def render_limited_time_300k_welcome_email(
    *,
    recipient_name="",
    credits_label="300,000",
    amount_label="$999",
    workspace_url="https://www.jaspen.ai",
    receipt_reference="",
):
    """Returns {subject, preview_text, body, html} for the purchase email."""
    greeting = _greeting(recipient_name)
    credits_label = _p(str(credits_label))
    amount_label = _p(str(amount_label))
    reference_line = (
        f"Reference: {_p(receipt_reference)}" if receipt_reference else ""
    )
    reference_html = (
        f'<p style="margin:10px 0 0; font-size:13px; line-height:1.5; color:#4f5d75;">{reference_line}</p>'
        if reference_line
        else ""
    )

    text = f"""Your {credits_label} Jaspen credits are ready

{greeting}

{INTRO_COPY}

What you bought: {credits_label} usage credits for {amount_label}, one time. No subscription was started.

{CREDITS_COPY}

{PERSONAL_COPY}

Where to start: {START_COPY}

Open Jaspen: {workspace_url}

{SUPPORT_COPY}

Kind regards,
Lydia
{reference_line}
"""

    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Your Jaspen credits are ready</title>
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
                <p style="margin:0 0 10px; font-size:13px; line-height:1.4; letter-spacing:.08em; text-transform:uppercase; color:#f0a6d4; font-weight:700;">Purchase confirmed</p>
                <h1 style="margin:0 0 14px; font-size:28px; line-height:1.18; color:#ffffff;">Your {credits_label} credits are ready</h1>
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;">{greeting}</p>
                <p style="margin:0; font-size:16px; line-height:1.65; color:#d9deec;">{_p(INTRO_COPY)}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px 6px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eff9fc; border:1px solid #cde7f0; border-radius:14px;">
                  <tr>
                    <td style="padding:20px;">
                      <h2 style="margin:0 0 8px; font-size:16px; line-height:1.3; color:#07112f;">What you bought</h2>
                      <p style="margin:0 0 10px; font-size:22px; line-height:1.3; color:#07112f; font-weight:700;">{credits_label} usage credits</p>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">{amount_label}, one time. No subscription was started, and nothing renews.</p>
                      {reference_html}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px 6px;">
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(CREDITS_COPY)}</p>
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(PERSONAL_COPY)}</p>
                <p style="margin:0; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(START_COPY)}</p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:18px 28px 18px;">
                <a href="{workspace_url}" style="display:inline-block; padding:13px 18px; background:#a0036c; color:#ffffff; text-decoration:none; border-radius:8px; font-size:15px; font-weight:700;">Open Jaspen</a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 34px;">
                <p style="margin:0 0 18px; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(SUPPORT_COPY)}</p>
                <p style="margin:0 0 4px; font-size:15px; line-height:1.65; color:#4f5d75;">Kind regards,</p>
                <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">Lydia</p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px; background:#161f3b;">
                <p style="margin:0; font-size:13px; line-height:1.5; color:#d9deec;">You received this because you purchased Jaspen credits. This is a receipt for that purchase, not a marketing email.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    return {"subject": SUBJECT, "preview_text": PREVIEW_TEXT, "body": text, "html": html}
