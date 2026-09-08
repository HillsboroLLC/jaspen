# backend/scripts/seed_impact_demo.py
#
# Three demo decisions that exercise the Decision Impact Report end-to-end in
# the real workspace UI. Idempotent — safe to re-run; it deletes and rebuilds
# only the three threads it owns.
#
#   impact-demo-thin      a thin brief Jaspen materially develops
#   impact-demo-strong    a well-prepared brief whose structure and
#                         recommendation hold, where Jaspen strengthens the
#                         evidentiary basis instead
#   impact-demo-quiet     a strong brief Jaspen legitimately adds little to
#
# The third one matters most. It is the case the whole methodology has to be
# able to report honestly, and it is the one that would quietly disappear if
# the demo data were written to flatter the product.
#
# SAFETY. Same guard as init_dev_db.py: SQLite only unless explicitly
# overridden, and never a remote host. This writes user-visible rows, so it
# must never be pointed at production.
#
# Run from backend/ with the venv active:
#   python scripts/seed_impact_demo.py
#   python scripts/seed_impact_demo.py --email someone@else.local
#
# Then log in as dev@jaspen.local (password jaspen-dev-password), open each
# thread, and look at the Decision Impact card on the scorecard dashboard.

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402
from app import models_challenge_event, models_decision_baseline  # noqa: E402,F401
from app.decision_impact import capture_or_update_draft, seal_baseline  # noqa: E402
from app.models import Scorecard, User, UserSession  # noqa: E402
from app.models_challenge_event import ChallengeEvent  # noqa: E402
from app.models_decision_baseline import DecisionBaseline  # noqa: E402
from app.scorecards import upsert_scorecard  # noqa: E402
from scripts.init_dev_db import assert_local_database  # noqa: E402

DEFAULT_EMAIL = 'dev@jaspen.local'

THREADS = ('impact-demo-thin', 'impact-demo-strong', 'impact-demo-quiet')


def _dim(label, score, confidence, ask=None):
    return {
        'label': label,
        'score': score,
        'raw_score': score,
        'confidence': confidence,
        'what_would_improve': ask,
        'rationale': f'Assessment of {label.lower()} against the brief.',
        'source': 'conversation',
    }


def _rubric(*criteria):
    return {'criteria': [
        {'key': key, 'label': label, 'weight': weight}
        for key, label, weight in criteria
    ]}


def _session(user, thread_id, name, turns, rubric=None, objective='balanced'):
    payload = {
        'session_id': thread_id,
        'name': name,
        'strategy_objective': objective,
        'chat_history': [{'role': 'user', 'content': text} for text in turns],
    }
    if rubric:
        payload['scoring_rubric'] = rubric
    db.session.add(UserSession(
        user_id=user.id,
        session_id=thread_id,
        name=name,
        created_by_user_id=user.id,
        payload=payload,
        scenarios_json={},
    ))
    db.session.commit()


def _score(user, thread_id, card_id, project_name, score, dimensions, weights, run, rubric):
    upsert_scorecard(
        user_id=user.id,
        thread_id=thread_id,
        payload={
            'id': card_id,
            'project_name': project_name,
            'evaluation_id': run,
            'jaspen_score': score,
            'score_category': 'Good' if score >= 60 else 'Fair',
            'executive_summary': f'{project_name} assessed against the thread rubric.',
            'dimensions': dimensions,
            'scoring_weights': weights,
            # REQUIRED, not decoration. renderScorecardCard reads
            # result.rubric.criteria to know which dimensions this card actually
            # has. Without it the chat card falls back to Jaspen's six built-in
            # dimension keys, finds none of them in `dimensions`, and renders
            # every bar at 0.0/10 — real analysis displayed as if nothing scored.
            'rubric': rubric,
            'top_risks': [],
            'assumptions': [],
        },
        evaluation_id=run,
        analysis_pass=True,
    )
    db.session.commit()


def _wipe(user):
    for thread_id in THREADS:
        Scorecard.query.filter_by(user_id=user.id, thread_id=thread_id).delete()
        UserSession.query.filter_by(user_id=user.id, session_id=thread_id).delete()
        DecisionBaseline.query.filter_by(user_id=user.id, thread_id=thread_id).delete()
        ChallengeEvent.query.filter_by(user_id=user.id, thread_id=thread_id).delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# 1. Thin brief, materially developed
# ---------------------------------------------------------------------------

def seed_thin(user):
    thread_id = 'impact-demo-thin'
    weights = {'cost': 0.3, 'risk': 0.25, 'speed': 0.25, 'capability': 0.2}
    rubric = _rubric(
        ('cost', 'Total cost of ownership', 0.30),
        ('risk', 'Delivery risk', 0.25),
        ('speed', 'Time to benefit', 0.25),
        ('capability', 'Operational capability', 0.20),
    )
    _session(
        user, thread_id, 'Warehouse automation — thin brief',
        [
            'We are thinking about automating the Dayton warehouse. Labour costs '
            'keep climbing and I think automation is the answer. Budget is '
            'roughly 2.4M. I want to move this year.',
        ],
        rubric=rubric,
        objective='cost',
    )

    # Baseline captured and sealed BEFORE analysis: one option, two criteria,
    # nothing quantified. A genuinely thin starting point.
    capture_or_update_draft(user, thread_id, structure={
        'alternatives': ['Full automation'],
        'criteria': [
            {'key': 'c1', 'label': 'Cost', 'backed_by_source': True,
             'quantified': False, 'weight': None},
            {'key': 'c2', 'label': 'Speed', 'backed_by_source': False,
             'quantified': False, 'weight': None},
        ],
        'assumptions': ['Labour costs keep rising', 'Automation is the answer'],
        'risks': [],
        'dependencies': [],
        'sources': ['FY25 labour cost summary'],
        'confirmed': True,
    })
    seal_baseline(user, thread_id)

    first = {
        'cost': _dim('Total cost of ownership', 88, 'assumed',
                     'Share the vendor quotes and the FY25 labour baseline.'),
        'risk': _dim('Delivery risk', 74, 'assumed',
                     'Provide the integrator reference checks.'),
        'speed': _dim('Time to benefit', 70, 'low',
                      'Share the phased rollout timeline.'),
        'capability': _dim('Operational capability', 66, 'assumed',
                           'Provide the current pick-rate data.'),
    }
    _score(user, thread_id, 'demo-thin-a', 'Full automation', 74, first, weights, 'run-1', rubric)
    _score(user, thread_id, 'demo-thin-b', 'Phased automation', 71, {
        'cost': _dim('Total cost of ownership', 79, 'low', 'Share the phase-one quote.'),
        'risk': _dim('Delivery risk', 82, 'medium'),
        'speed': _dim('Time to benefit', 64, 'assumed', 'Confirm the phase-one date.'),
        'capability': _dim('Operational capability', 70, 'low', 'Provide pick-rate data.'),
    }, weights, 'run-1', rubric)
    _score(user, thread_id, 'demo-thin-c', 'Status quo with overtime', 58, {
        'cost': _dim('Total cost of ownership', 55, 'high'),
        'risk': _dim('Delivery risk', 90, 'high'),
        'speed': _dim('Time to benefit', 40, 'medium'),
        'capability': _dim('Operational capability', 45, 'medium'),
    }, weights, 'run-1', rubric)

    # A second pass after the user supplies evidence.
    _score(user, thread_id, 'demo-thin-a', 'Full automation', 77, {
        'cost': _dim('Total cost of ownership', 88, 'high'),
        'risk': _dim('Delivery risk', 74, 'medium'),
        'speed': _dim('Time to benefit', 70, 'medium'),
        'capability': _dim('Operational capability', 66, 'assumed',
                           'Still need the current pick-rate data.'),
    }, weights, 'run-2', rubric)

    _add_plan(user, thread_id, 'demo-thin-a')
    return thread_id


# ---------------------------------------------------------------------------
# 2. Strong brief, basis strengthened, recommendation holds
# ---------------------------------------------------------------------------

def seed_strong(user):
    thread_id = 'impact-demo-strong'
    weights = {'cost': 0.2, 'risk': 0.2, 'fit': 0.2, 'speed': 0.2, 'support': 0.2}
    rubric = _rubric(
        ('cost', 'Landed cost', 0.20),
        ('risk', 'Delivery risk', 0.20),
        ('fit', 'Network fit', 0.20),
        ('speed', 'Transition speed', 0.20),
        ('support', 'Support model', 0.20),
    )
    _session(
        user, thread_id, 'Vendor consolidation — prepared brief',
        [
            'We are consolidating from three logistics vendors to one. Options are '
            'Meridian, Alder and keeping the current split. Criteria: landed cost '
            '20%, delivery risk 20%, network fit 20%, transition speed 20%, '
            'support model 20%. Current spend is 8.1M across the three. Meridian '
            'quoted 7.3M, Alder 7.6M. I am leaning Meridian.',
        ],
        rubric=rubric,
        objective='cost',
    )

    capture_or_update_draft(user, thread_id, structure={
        'alternatives': ['Meridian', 'Alder', 'Keep current split'],
        'criteria': [
            {'key': 'c1', 'label': 'Landed cost', 'backed_by_source': True,
             'quantified': True, 'weight': 0.2},
            {'key': 'c2', 'label': 'Delivery risk', 'backed_by_source': False,
             'quantified': False, 'weight': 0.2},
            {'key': 'c3', 'label': 'Network fit', 'backed_by_source': False,
             'quantified': False, 'weight': 0.2},
            {'key': 'c4', 'label': 'Transition speed', 'backed_by_source': False,
             'quantified': False, 'weight': 0.2},
            {'key': 'c5', 'label': 'Support model', 'backed_by_source': True,
             'quantified': False, 'weight': 0.2},
        ],
        'assumptions': ['Volumes hold at FY25 levels'],
        'risks': ['Single-vendor concentration'],
        'dependencies': ['TMS integration'],
        'sources': ['FY25 spend export', 'Meridian quote', 'Alder quote'],
        'confirmed': True,
    })
    seal_baseline(user, thread_id)

    first = {
        'cost': _dim('Landed cost', 84, 'high'),
        'risk': _dim('Delivery risk', 70, 'assumed',
                     'Share the carrier on-time performance history.'),
        'fit': _dim('Network fit', 76, 'assumed',
                    'Provide the lane-level coverage map.'),
        'speed': _dim('Transition speed', 68, 'low',
                      'Confirm the cutover window with operations.'),
        'support': _dim('Support model', 80, 'medium'),
    }
    _score(user, thread_id, 'demo-strong-a', 'Meridian', 76, first, weights, 'run-1', rubric)
    _score(user, thread_id, 'demo-strong-b', 'Alder', 71, {
        'cost': _dim('Landed cost', 78, 'high'),
        'risk': _dim('Delivery risk', 74, 'assumed', 'Share on-time history.'),
        'fit': _dim('Network fit', 66, 'assumed', 'Provide coverage map.'),
        'speed': _dim('Transition speed', 70, 'low', 'Confirm cutover window.'),
        'support': _dim('Support model', 68, 'medium'),
    }, weights, 'run-1', rubric)
    _score(user, thread_id, 'demo-strong-c', 'Keep current split', 61, {
        'cost': _dim('Landed cost', 50, 'high'),
        'risk': _dim('Delivery risk', 82, 'high'),
        'fit': _dim('Network fit', 70, 'medium'),
        'speed': _dim('Transition speed', 95, 'high'),
        'support': _dim('Support model', 55, 'medium'),
    }, weights, 'run-1', rubric)

    # Second pass: three assumptions become evidence-backed. Same options, same
    # criteria, same leader — a materially better-founded version of the same
    # recommendation.
    _score(user, thread_id, 'demo-strong-a', 'Meridian', 79, {
        'cost': _dim('Landed cost', 84, 'high'),
        'risk': _dim('Delivery risk', 70, 'high'),
        'fit': _dim('Network fit', 76, 'high'),
        'speed': _dim('Transition speed', 68, 'medium'),
        'support': _dim('Support model', 80, 'medium'),
    }, weights, 'run-2', rubric)

    _add_plan(user, thread_id, 'demo-strong-a')
    return thread_id


# ---------------------------------------------------------------------------
# 3. Strong brief, little added — the honest quiet case
# ---------------------------------------------------------------------------

def seed_quiet(user):
    thread_id = 'impact-demo-quiet'
    weights = {'cost': 0.34, 'risk': 0.33, 'speed': 0.33}
    rubric = _rubric(
        ('cost', 'Occupancy cost', 0.34),
        ('risk', 'Disruption risk', 0.33),
        ('speed', 'Time to occupy', 0.33),
    )
    _session(
        user, thread_id, 'Office lease renewal — well prepared',
        [
            'Renewing the Cincinnati office lease. Options: renew 5 years at 24/sqft, '
            'renew 3 years at 26/sqft, or relocate to the Norwood space at 21/sqft. '
            'Criteria are cost, disruption risk and speed, weighted evenly. I have '
            'the broker comparables, the fit-out quote and headcount plan.',
        ],
        rubric=rubric,
    )

    capture_or_update_draft(user, thread_id, structure={
        'alternatives': ['Renew 5 years', 'Renew 3 years', 'Relocate to Norwood'],
        'criteria': [
            {'key': 'c1', 'label': 'Occupancy cost', 'backed_by_source': True,
             'quantified': True, 'weight': 0.34},
            {'key': 'c2', 'label': 'Disruption risk', 'backed_by_source': True,
             'quantified': True, 'weight': 0.33},
            {'key': 'c3', 'label': 'Time to occupy', 'backed_by_source': True,
             'quantified': True, 'weight': 0.33},
        ],
        'assumptions': [],
        'risks': ['Fit-out overrun', 'Headcount growth above plan'],
        'dependencies': ['Fit-out contractor availability'],
        'sources': ['Broker comparables', 'Fit-out quote', 'Headcount plan'],
        'confirmed': True,
    })
    seal_baseline(user, thread_id)

    # One pass, everything already evidenced. Jaspen confirms rather than
    # changes: no asks, no resolutions, nothing left open.
    for card_id, name, score, cost, risk, speed in (
        ('demo-quiet-a', 'Renew 5 years', 74, 72, 88, 62),
        ('demo-quiet-b', 'Renew 3 years', 68, 64, 86, 60),
        ('demo-quiet-c', 'Relocate to Norwood', 71, 86, 58, 70),
    ):
        _score(user, thread_id, card_id, name, score, {
            'cost': _dim('Occupancy cost', cost, 'high'),
            'risk': _dim('Disruption risk', risk, 'high'),
            'speed': _dim('Time to occupy', speed, 'high'),
        }, weights, 'run-1', rubric)

    return thread_id


def _add_plan(user, thread_id, scorecard_id):
    """An AI-generated plan, so dependency_surfaced events exist."""
    from app.decision_ledger import record_generated_plan
    from app.routes.strategy import _load_scenarios, _save_scenarios, _store_thread_wbs

    plan = {
        'name': 'Execution plan',
        'start_date': datetime.utcnow().date().isoformat(),
        'tasks': [
            {'id': 'task-1', 'title': 'Confirm baseline figures', 'depends_on': []},
            {'id': 'task-2', 'title': 'Negotiate terms', 'depends_on': ['task-1']},
            {'id': 'task-3', 'title': 'Integration readiness', 'depends_on': ['task-1']},
            {'id': 'task-4', 'title': 'Cutover', 'depends_on': ['task-2', 'task-3']},
        ],
    }
    all_data = _load_scenarios(user.id) or {}
    thread_data = all_data.get(thread_id) or {}
    _store_thread_wbs(thread_data, scorecard_id, plan)
    all_data[thread_id] = thread_data
    _save_scenarios(user.id, all_data)
    record_generated_plan(user_id=user.id, thread_id=thread_id, plan=plan)
    db.session.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', default=DEFAULT_EMAIL)
    parser.add_argument('--allow-non-sqlite', action='store_true')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        assert_local_database(
            app.config['SQLALCHEMY_DATABASE_URI'],
            allow_non_sqlite=args.allow_non_sqlite,
        )

        user = User.query.filter_by(email=args.email).first()
        if not user:
            raise SystemExit(
                f'No user {args.email!r}. Run scripts/init_dev_db.py first.'
            )

        _wipe(user)
        for seed in (seed_thin, seed_strong, seed_quiet):
            thread_id = seed(user)
            print(f'  seeded {thread_id}')

        print('\nDecision Impact demo threads ready for', args.email)
        from app.decision_impact import build_impact_report
        for thread_id in THREADS:
            report = build_impact_report(user, thread_id)
            impact = report['impact']
            interventions = ', '.join(
                f"{i['label']} {i['count']}"
                for i in impact['interventions'] if i['qualifying']
            ) or 'none'
            print(
                f"  {thread_id:22s} verdict={impact['verdict']:20s} "
                f"routes={impact['routes_satisfied'] or '[]'} "
                f"moved={len(impact['moved'])} interventions=({interventions})"
            )


if __name__ == '__main__':
    main()
