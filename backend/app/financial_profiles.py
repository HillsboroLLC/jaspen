# app/financial_profiles.py
"""
Lightweight business profiles and slot alias mapping.

Profile tuple format: (business_model, focus)
Current default: ("saas", "revenue")

Slots:
- revenue_run_rate: any-of ["MRR", "ARR", "Revenue"]
- profitability:    any-of ["Gross_Margin", "EBIT", "Operating_Cash_Flow"]
- plan_window:      any-of ["Plan_Months"]

Rationale: Keep minimal surface for gating while allowing flexible label inputs.
"""

from typing import Dict, List, Tuple, Optional, Any

Profile = Tuple[str, str]

DEFAULT_PROFILE: Profile = ("saas", "revenue")

# Mapping: profile -> slot -> accepted label aliases
PROFILE_SLOTS: Dict[Profile, Dict[str, List[str]]] = {
    DEFAULT_PROFILE: {
        "revenue_run_rate": ["MRR", "ARR", "Revenue"],
        "profitability": ["Gross_Margin", "EBIT", "Operating_Cash_Flow"],
        "plan_window": ["Plan_Months"],
    },
}

__all__ = [
    "Profile",
    "DEFAULT_PROFILE",
    "PROFILE_SLOTS",
    "detect_profile",
    "get_profile_slots",
    "get_slot_aliases",
]


def detect_profile(cum_text: Optional[str], parsed: Optional[Dict[str, Any]]) -> Profile:
    """
    Return a (business_model, focus) profile.
    Safe default is ("saas","revenue"). Heuristics are intentionally lightweight.

    Parameters
    ----------
    cum_text : Optional[str]
        Cumulative conversation text.
    parsed : Optional[Dict[str, Any]]
        Parsed labels extracted so far (unused for now).

    Returns
    -------
    Profile
        Selected profile tuple.
    """
    if not cum_text:
        return DEFAULT_PROFILE

    text = cum_text.lower()
    # Minimal hints for SaaS; default remains SaaS even if no hints found.
    if any(k in text for k in ("saas", "subscription", "subscribers", "monthly recurring", "mrr", "arr")):
        return DEFAULT_PROFILE

    return DEFAULT_PROFILE


def get_profile_slots(profile: Optional[Profile] = None) -> Dict[str, List[str]]:
    """
    Return slot->aliases mapping for the given profile; falls back to default.
    """
    p = profile or DEFAULT_PROFILE
    return PROFILE_SLOTS.get(p, PROFILE_SLOTS[DEFAULT_PROFILE])


def get_slot_aliases(slot: str, profile: Optional[Profile] = None) -> List[str]:
    """
    Return accepted label aliases for a specific slot under the given profile.
    """
    slots = get_profile_slots(profile)
    return slots.get(slot, [])
