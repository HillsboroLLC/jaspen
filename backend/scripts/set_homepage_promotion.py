"""Turn the RANK THEM homepage promotion on or off.

The admin API does this too, but that needs a token and a hand-built request.
This is the same write, as one command:

    PYTHONPATH=. ./venv/bin/python scripts/set_homepage_promotion.py on
    PYTHONPATH=. ./venv/bin/python scripts/set_homepage_promotion.py off
    PYTHONPATH=. ./venv/bin/python scripts/set_homepage_promotion.py status

Takes effect for visitors within one cache TTL. No restart.
"""
import sys

from app import create_app, db
from app.homepage_promotion import (
    get_promotion_config,
    promotion_is_live,
    public_promotion_state,
    save_promotion_config,
    _read_live_state,
)


def _report():
    config = get_promotion_config()
    state = _read_live_state()
    sales = state["sales_count"]
    live = promotion_is_live(config, sales)
    cap = int(config.get("sales_cap") or 0)

    print(f'switch:      {"on" if config.get("active") else "off"}')
    print(f'showing:     {"yes" if live else "no"}')
    print(f'sales:       {sales}{f" of {cap}" if cap else ""}')
    if cap and sales >= cap:
        print('             (stopped itself: the sales cap is reached)')
    print(f'links to:    {config.get("campaign_path")}')
    print(f'public says: active={public_promotion_state().get("active")}')
    return 0


def main():
    args = [a.strip().lower() for a in sys.argv[1:] if a.strip()]
    if not args or args[0] not in {"on", "off", "status"}:
        print(__doc__)
        return 2

    app = create_app()
    with app.app_context():
        if args[0] == "status":
            return _report()

        save_promotion_config({"active": args[0] == "on"})
        db.session.commit()
        print(f'Promotion switched {args[0]}.\n')
        return _report()


if __name__ == "__main__":
    raise SystemExit(main())
