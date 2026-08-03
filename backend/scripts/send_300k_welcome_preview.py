"""Preview the 300K purchase receipt: write it to a file, or send it to yourself.

Writing needs nothing configured and is the fast loop:

    PYTHONPATH=. ./venv/bin/python scripts/send_300k_welcome_preview.py --write /tmp/receipt.html

Sending needs real mail credentials, which live in the server's environment:

    cd ~/sekki-platform/backend
    eval export $(systemctl show gunicorn-sekki.service -p Environment --value)
    PYTHONPATH=. ./venv/bin/python scripts/send_300k_welcome_preview.py ldbailey303@gmail.com

Nothing is charged and no credits are granted - this only renders the template.
"""
import sys

from flask import current_app

from app import create_app, mail
from app.email_templates.limited_time_300k_welcome import (
    render_limited_time_300k_welcome_email,
)


def _render():
    return render_limited_time_300k_welcome_email(
        amount_label='$999',
        workspace_url=(current_app.config.get('FRONTEND_BASE_URL') or 'https://www.jaspen.ai'),
        receipt_reference='in_preview_example',
    )


def write(path):
    rendered = _render()
    with open(path, 'w') as handle:
        handle.write(rendered['html'])
    print(f'Wrote {path}')
    print(f'Subject: {rendered["subject"]}')
    print('Open it in a browser to check the layout. Send it to yourself to see how')
    print('a real mail client treats it - they are not the same thing.')
    return 0


def send(recipient):
    from flask_mail import Message

    server = current_app.config.get('MAIL_SERVER')
    if not server or server == 'smtp.example.com':
        print('FAIL  No mail server is configured in this environment, so nothing can be sent.')
        print('      Run this on the server, or use --write to preview the file instead.')
        return 1

    rendered = _render()
    message = Message(
        subject=f'[preview] {rendered["subject"]}',
        recipients=[recipient],
        sender='Jaspen <hello@jaspen.ai>',
        reply_to='hello@jaspen.ai',
    )
    message.body = rendered['body']
    message.html = rendered['html']
    mail.send(message)
    print(f'Sent to {recipient} via {server}.')
    print('Subject is prefixed [preview] so it cannot be mistaken for a real receipt.')
    return 0


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    if not args:
        print(__doc__)
        return 2
    app = create_app()
    with app.app_context():
        if args[0] == '--write':
            return write(args[1] if len(args) > 1 else 'limited-time-receipt.html')
        return send(args[0])


if __name__ == '__main__':
    raise SystemExit(main())
