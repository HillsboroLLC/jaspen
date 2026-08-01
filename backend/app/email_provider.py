"""Small transactional-email provider boundary.

The application currently delivers mail through Flask-Mail/SMTP.  Keeping the
provider behind this interface makes the decision-asset workflow testable and
allows a future provider swap without changing authorization or artifact code.
"""

from dataclasses import dataclass
from email.utils import formataddr, parseaddr

from flask import current_app
from flask_mail import Message

from app import mail


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class EmailProviderResult:
    provider: str
    response_category: str


class TransactionalEmailProvider:
    name = "smtp"

    def send(
        self,
        *,
        subject,
        recipient,
        text_body,
        html_body,
        attachments=(),
    ):
        configured_sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        sender_name = str(current_app.config.get("DECISION_ASSET_EMAIL_SENDER_NAME") or "Jaspen").strip()
        _existing_name, sender_address = parseaddr(str(configured_sender or ""))
        if not sender_address:
            raise RuntimeError("transactional_email_not_configured")

        message = Message(
            subject=subject,
            recipients=[recipient],
            sender=formataddr((sender_name, sender_address)),
            reply_to=current_app.config.get("DECISION_ASSET_EMAIL_REPLY_TO") or None,
        )
        message.body = text_body
        message.html = html_body
        for attachment in attachments:
            message.attach(
                attachment.filename,
                attachment.content_type,
                attachment.data,
            )
        mail.send(message)
        return EmailProviderResult(provider=self.name, response_category="accepted")


def get_transactional_email_provider():
    return TransactionalEmailProvider()
