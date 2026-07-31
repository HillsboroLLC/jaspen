#!/usr/bin/env python3
"""Print evaluation-level Thinking Power statistics as JSON."""

import json

from app import create_app
from app.evaluation_telemetry import build_evaluation_usage_report
from app.models import UsageEvent


def main():
    app = create_app()
    with app.app_context():
        events = UsageEvent.query.order_by(UsageEvent.created_at.asc()).all()
        print(json.dumps(build_evaluation_usage_report(events), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
