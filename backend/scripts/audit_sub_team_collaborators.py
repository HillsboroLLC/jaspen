"""Find organizations holding collaborators without a Team-or-higher plan.

Read-only. Nothing is created, changed, or removed.

    PYTHONPATH=. ./venv/bin/python scripts/audit_sub_team_collaborators.py
    PYTHONPATH=. ./venv/bin/python scripts/audit_sub_team_collaborators.py --detail

Collaboration is a Team-or-higher entitlement, but the invite path did not
enforce a plan check, so sub-Team orgs could accumulate members. This reports
whether any such orgs exist before that gate starts refusing them.

Exit status: 0 when nothing is affected, 1 when at least one org is. Members
found here are NOT auto-grandfathered -- the entitlement stays Team+ only, so
anything reported needs a migration/communication decision before the gate
ships.
"""
import argparse
import sys

from app import create_app, db
from app.models import Organization, OrganizationInvitation, OrganizationMember, User
from app.orgs import plan_allows_collaboration

# Owners are not collaborators; they hold their own org.
COLLABORATION_ROLES = ("admin", "creator", "collaborator", "viewer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--detail",
        action="store_true",
        help="list each affected organization and member email",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        orgs = Organization.query.all()
        affected = []

        for org in orgs:
            if plan_allows_collaboration(org.plan_key):
                continue

            members = (
                OrganizationMember.query
                .filter(
                    OrganizationMember.organization_id == org.id,
                    OrganizationMember.status == "active",
                    OrganizationMember.role.in_(COLLABORATION_ROLES),
                )
                .all()
            )
            pending = (
                OrganizationInvitation.query
                .filter_by(organization_id=org.id, status="pending")
                .count()
            )
            if members or pending:
                affected.append((org, members, pending))

        if not affected:
            print("No sub-Team organizations hold collaborators or pending invites.")
            print("The Team+ gate can be enforced with no customer impact.")
            return 0

        member_total = sum(len(m) for _, m, _ in affected)
        invite_total = sum(p for _, _, p in affected)

        print(f"Affected organizations: {len(affected)}")
        print(f"Active sub-Team collaborators: {member_total}")
        print(f"Pending sub-Team invitations: {invite_total}")
        print()

        by_plan = {}
        for org, members, pending in affected:
            key = str(org.plan_key or "unknown")
            entry = by_plan.setdefault(key, {"orgs": 0, "members": 0, "pending": 0})
            entry["orgs"] += 1
            entry["members"] += len(members)
            entry["pending"] += pending

        print(f"{'plan':<20} {'orgs':>6} {'members':>9} {'pending':>9}")
        for plan in sorted(by_plan):
            row = by_plan[plan]
            print(f"{plan:<20} {row['orgs']:>6} {row['members']:>9} {row['pending']:>9}")

        if args.detail:
            print()
            for org, members, pending in affected:
                owner = User.query.filter_by(id=org.owner_user_id).first()
                owner_email = owner.email if owner else "(no owner)"
                print(f"- {org.name} [{org.id}] plan={org.plan_key} owner={owner_email}")
                for member in members:
                    user = User.query.filter_by(id=member.user_id).first()
                    print(f"    {member.role:<14} {user.email if user else member.user_id}")
                if pending:
                    print(f"    {'pending':<14} {pending} invitation(s)")

        print()
        print("These members would lose access when the Team+ gate is enforced.")
        print("Decide on migration and customer communication before merging.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
