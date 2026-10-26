"""Customer data-sharing choices. Everything is OFF unless an owner/admin
turns it on, and every change is audited.

- improve_jaspen: the organization allows de-identified, aggregated decision
  scores, outcomes and patterns to improve Jaspen's methodology. Never project
  names, raw conversations, files or connector data.
- decision_sharing_allowed: members may use "Share this decision with Jaspen"
  (each share still needs an explicit action and a preview).

Nothing in Jaspen reads customer content across organizations today; this is
the consent record any future use must check first.
"""

DEFAULTS = {"improve_jaspen": False, "decision_sharing_allowed": False}


def data_sharing_choices(org):
    settings = org.settings if org is not None and isinstance(org.settings, dict) else {}
    stored = settings.get("data_sharing") if isinstance(settings.get("data_sharing"), dict) else {}
    choices = dict(DEFAULTS)
    for key in DEFAULTS:
        if isinstance(stored.get(key), bool):
            choices[key] = stored[key]
    choices["updated_at"] = stored.get("updated_at")
    choices["updated_by"] = stored.get("updated_by")
    return choices


def improve_jaspen_opted_in(org):
    return data_sharing_choices(org)["improve_jaspen"] is True


def decision_sharing_allowed(org):
    return data_sharing_choices(org)["decision_sharing_allowed"] is True
