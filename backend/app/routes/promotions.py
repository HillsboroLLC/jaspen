# backend/app/routes/promotions.py
#
# The public read side of the homepage promotion (app/homepage_promotion.py).
# One unauthenticated GET, called on homepage load.
#
# The JWT is optional and read only to answer one question: does this visitor
# already own the 300K offer? If so the response says so and the modal never
# appears, which is what keeps a buyer from being sold the thing they bought
# even on a browser with no local history. An expired or malformed token is
# treated as "signed out" — a public page must never fail on a stale cookie.

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.homepage_promotion import public_promotion_state
from app.models import User

promotions_bp = Blueprint("promotions", __name__)


def _current_user_or_none():
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
    except Exception:  # noqa: BLE001 - any token problem means "signed out" here
        return None
    if not identity:
        return None
    try:
        return User.query.filter_by(id=str(identity)).first()
    except Exception:  # noqa: BLE001 - the promotion must not break on a DB hiccup
        return None


@promotions_bp.route("/homepage", methods=["GET"])
def get_homepage_promotion():
    return jsonify({"promotion": public_promotion_state(_current_user_or_none())}), 200
