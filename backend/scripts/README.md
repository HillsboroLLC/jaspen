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

Verify timer schedule:

```bash
systemctl list-timers --all | grep jaspen-credit-reset
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
```
