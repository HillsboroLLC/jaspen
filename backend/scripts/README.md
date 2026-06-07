# Backend Maintenance Scripts

## Monthly credit renewal

Use the Flask CLI command (preferred):

```bash
cd ~/sekki-platform/backend
set -a
[ -f .env ] && source .env
set +a
export FLASK_APP=wsgi:app
./venv/bin/flask credits reset-monthly
```

Dry-run:

```bash
./venv/bin/flask credits reset-monthly --dry-run
```

Equivalent direct script:

```bash
./venv/bin/python scripts/reset_monthly_credits.py
```

## Monthly feedback digest

Set the recipient in production `.env`:

```bash
FEEDBACK_DIGEST_RECIPIENTS=you@example.com
```

The digest uses Anthropic synthesis when `ANTHROPIC_API_KEY` is available. To force the fallback structured summary:

```bash
FEEDBACK_DIGEST_USE_AI=false
```

Run a dry-run preview:

```bash
cd ~/sekki-platform/backend
set -a
[ -f .env ] && source .env
set +a
export FLASK_APP=wsgi:app
./venv/bin/flask feedback digest-monthly --dry-run
```

Send immediately:

```bash
./venv/bin/flask feedback digest-monthly
```

## Production scheduler (recommended): systemd timer on DigitalOcean

Install timer/service files:

```bash
cd ~/sekki-platform/backend
sudo cp scripts/systemd/jaspen-credit-reset.service /etc/systemd/system/
sudo cp scripts/systemd/jaspen-credit-reset.timer /etc/systemd/system/
sudo chmod +x /home/sekki/sekki-platform/backend/scripts/run_monthly_credit_reset.sh
sudo systemctl daemon-reload
sudo systemctl enable --now jaspen-credit-reset.timer
```

Install the monthly feedback digest timer/service files:

```bash
cd ~/sekki-platform/backend
sudo cp scripts/systemd/jaspen-feedback-digest.service /etc/systemd/system/
sudo cp scripts/systemd/jaspen-feedback-digest.timer /etc/systemd/system/
sudo chmod +x /home/sekki/sekki-platform/backend/scripts/run_monthly_feedback_digest.sh
sudo systemctl daemon-reload
sudo systemctl enable --now jaspen-feedback-digest.timer
```

Run one immediate verification pass:

```bash
cd ~/sekki-platform/backend
set -a
[ -f .env ] && source .env
set +a
export FLASK_APP=wsgi:app
./venv/bin/flask credits reset-monthly --dry-run
sudo systemctl start jaspen-credit-reset.service
sudo journalctl -u jaspen-credit-reset.service -n 50 --no-pager
```

Run one immediate feedback digest verification pass:

```bash
cd ~/sekki-platform/backend
set -a
[ -f .env ] && source .env
set +a
export FLASK_APP=wsgi:app
./venv/bin/flask feedback digest-monthly --dry-run
sudo systemctl start jaspen-feedback-digest.service
sudo journalctl -u jaspen-feedback-digest.service -n 50 --no-pager
```

Verify timer schedule:

```bash
systemctl list-timers --all | grep jaspen-credit-reset
systemctl list-timers --all | grep jaspen-feedback-digest
```

## Required schema

This workflow requires `users.credits_reset_at`. If missing, run:

```bash
cd ~/sekki-platform/backend
set -a
[ -f .env ] && source .env
set +a
export FLASK_APP=wsgi:app
./venv/bin/flask db upgrade
```

## Fallback scheduler: cron

If systemd timers are not available in your environment, use cron:

```cron
10 0 1 * * cd /home/sekki/sekki-platform/backend && set -a && . ./.env && set +a && export FLASK_APP=wsgi:app && ./venv/bin/flask credits reset-monthly >> /var/log/jaspen/monthly-credit-reset.log 2>&1
10 1 1 * * cd /home/sekki/sekki-platform/backend && set -a && . ./.env && set +a && export FLASK_APP=wsgi:app && ./venv/bin/flask feedback digest-monthly >> /var/log/jaspen/monthly-feedback-digest.log 2>&1
```
