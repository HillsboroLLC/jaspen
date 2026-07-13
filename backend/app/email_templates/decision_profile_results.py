"""Decision Profile result email template."""

from html import escape

SUBJECT = "Your Jaspen Decision Profile"
PREVIEW_TEXT = "A closer look at how you naturally approach important decisions."
JASPEN_BRIDGE_HEADLINE = "You've started thinking it through. Now let Jaspen help you work through it."
JASPEN_BRIDGE_COPY = (
    "You can start with Jaspen for free and use it on a real decision. "
    "When the decision has real consequences for your life, your work, a business, "
    "your finances, or the people affected by it, Essential gives you more room to "
    "explore the evidence, test assumptions, compare tradeoffs, and preserve why you made the choice."
)

STYLE_PROFILES = {
    "evidence_builder": {
        "explanation": "You tend to feel most confident when a decision can be explained with clear information and a visible line of reasoning.",
        "shows_up": "You often pause long enough to gather facts, compare signals, and make the case for why a path makes sense.",
        "strength": "Your natural strength is traceability. Other people can usually see how you got from the situation to the choice.",
        "watch": "A useful pattern to watch is waiting for one more piece of information when the decision already has enough shape to move.",
        "jaspen": "Jaspen can help you organize evidence, capture tradeoffs, and turn your reasoning into a decision record without slowing the work down.",
    },
    "fast_mover": {
        "explanation": "You tend to read the situation quickly, form a direction, and keep momentum instead of circling the same choice for too long.",
        "shows_up": "You often know what feels workable early and prefer to test the decision through action.",
        "strength": "Your natural strength is movement. You help decisions leave the conversation stage and become real progress.",
        "watch": "A useful pattern to watch is moving before the key assumptions have been named clearly enough for others to follow.",
        "jaspen": "Jaspen can help you preserve speed while adding a quick check on assumptions, risks, and what would change your mind.",
    },
    "thoughtful_explorer": {
        "explanation": "You tend to open up possibilities before settling, giving several options a genuine look.",
        "shows_up": "You often want to understand the shape of the decision space instead of rushing to the first workable answer.",
        "strength": "Your natural strength is breadth. You notice options and angles that may otherwise be skipped.",
        "watch": "A useful pattern to watch is keeping too many options alive after the strongest few have emerged.",
        "jaspen": "Jaspen can help you compare alternatives cleanly, narrow the field, and keep the reasons visible as you choose.",
    },
    "consensus_seeker": {
        "explanation": "You tend to decide with the people affected by the choice in mind, weighing how a decision will hold up across perspectives.",
        "shows_up": "You often look for alignment, shared understanding, and a path that others can support after the meeting ends.",
        "strength": "Your natural strength is durability. Your decisions are more likely to travel well because people understand the reasoning.",
        "watch": "A useful pattern to watch is waiting for complete agreement when clear ownership would be more helpful.",
        "jaspen": "Jaspen can help you capture stakeholder input, separate preferences from decision criteria, and clarify who needs to weigh in.",
    },
    "practical_optimizer": {
        "explanation": "You tend to balance instinct and information, looking for the path that works in the real constraints in front of you.",
        "shows_up": "You often compare effort, usefulness, timing, and tradeoffs without needing the decision to be perfect.",
        "strength": "Your natural strength is fit. You are tuned to what can actually work, not just what looks best in theory.",
        "watch": "A useful pattern to watch is optimizing around immediate constraints before checking whether the goal has shifted.",
        "jaspen": "Jaspen can help you make the practical tradeoffs explicit, preserve the why, and revisit the decision when conditions change.",
    },
    "reflective_analyzer": {
        "explanation": "You tend to think decisions through carefully and learn from how they turn out over time.",
        "shows_up": "You often revisit the reasoning, notice what changed, and look for patterns you can apply next time.",
        "strength": "Your natural strength is learning. Your decisions can improve because you pay attention after the choice is made.",
        "watch": "A useful pattern to watch is replaying a decision longer than the next action requires.",
        "jaspen": "Jaspen can help you capture the original context, track what changed, and turn reflection into useful decision memory.",
    },
}


def _p(text):
    return escape(text or "")


def render_decision_profile_email(style, *, workspace_url, unsubscribe_url):
    key = style["key"]
    profile = STYLE_PROFILES[key]
    style_name = _p(style["name"])
    preview = _p(PREVIEW_TEXT)
    cta_url = _p(workspace_url)
    unsubscribe = _p(unsubscribe_url)

    text = f"""{SUBJECT}

{PREVIEW_TEXT}

Your decision style: {style["name"]}

{profile["explanation"]}

How this style tends to show up:
{profile["shows_up"]}

Natural strength:
{profile["strength"]}

A useful pattern to watch:
{profile["watch"]}

How Jaspen can help:
{profile["jaspen"]}

{JASPEN_BRIDGE_HEADLINE}

{JASPEN_BRIDGE_COPY}

Start with Jaspen:
{workspace_url}

You received this because you requested your Jaspen Decision Profile. You can unsubscribe from Jaspen updates here:
{unsubscribe_url}

Jaspen
"""

    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{_p(SUBJECT)}</title>
  </head>
  <body style="margin:0; padding:0; background:#f6f7fb; font-family:Arial, Helvetica, sans-serif; color:#172033;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">{preview}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f7fb; padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px; background:#ffffff; border:1px solid #e7eaf3; border-radius:18px; overflow:hidden;">
            <tr>
              <td style="padding:24px 28px; border-bottom:1px solid #eef1f7;">
                <div style="font-size:24px; line-height:1; color:#161f3b; font-weight:700;">Jaspen</div>
              </td>
            </tr>
            <tr>
              <td style="padding:30px 28px 10px;">
                <p style="margin:0 0 10px; font-size:13px; line-height:1.4; letter-spacing:.08em; text-transform:uppercase; color:#a0036c; font-weight:700;">Decision Profile</p>
                <h1 style="margin:0 0 12px; font-size:28px; line-height:1.18; color:#07112f;">Your decision style: {style_name}</h1>
                <p style="margin:0; font-size:16px; line-height:1.65; color:#4f5d75;">{_p(profile["explanation"])}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 28px 4px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #e7eaf3; border-radius:14px;">
                  <tr>
                    <td style="padding:20px;">
                      <h2 style="margin:0 0 8px; font-size:16px; line-height:1.3; color:#07112f;">How this style tends to show up</h2>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(profile["shows_up"])}</p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 20px 20px;">
                      <h2 style="margin:0 0 8px; font-size:16px; line-height:1.3; color:#07112f;">Natural strength</h2>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(profile["strength"])}</p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 20px 20px;">
                      <h2 style="margin:0 0 8px; font-size:16px; line-height:1.3; color:#07112f;">A useful pattern to watch</h2>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(profile["watch"])}</p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 20px 20px;">
                      <h2 style="margin:0 0 8px; font-size:16px; line-height:1.3; color:#07112f;">How Jaspen can help</h2>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(profile["jaspen"])}</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px 6px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eff9fc; border:1px solid #d8edf4; border-radius:14px;">
                  <tr>
                    <td style="padding:20px;">
                      <h2 style="margin:0 0 8px; font-size:18px; line-height:1.35; color:#07112f;">{_p(JASPEN_BRIDGE_HEADLINE)}</h2>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">{_p(JASPEN_BRIDGE_COPY)}</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 28px 34px;">
                <a href="{cta_url}" style="display:inline-block; padding:13px 18px; background:#a0036c; color:#ffffff; text-decoration:none; border-radius:8px; font-size:15px; font-weight:700;">Start with Jaspen</a>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px; background:#f8f9fc; border-top:1px solid #eef1f7;">
                <p style="margin:0 0 8px; font-size:13px; line-height:1.5; color:#667085;">You received this because you requested your Jaspen Decision Profile.</p>
                <p style="margin:0; font-size:13px; line-height:1.5; color:#667085;">You can unsubscribe from Jaspen updates <a href="{unsubscribe}" style="color:#a0036c;">here</a>.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    return {"subject": SUBJECT, "preview_text": PREVIEW_TEXT, "body": text, "html": html}
