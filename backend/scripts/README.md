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

## Cron example (daily at 00:10 UTC)

```cron
10 0 * * * cd /home/sekki/sekki-platform/backend && set -a && . ./.env && set +a && export FLASK_APP=wsgi:app && ./venv/bin/flask credits reset-monthly >> /var/log/jaspen-credit-renewal.log 2>&1
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
