import copy

import pytest

from app import db as app_db
from app.models import UserSession
from app.scenarios_store import (
    ScenariosData,
    clear_all_scenarios_data,
    load_scenarios_data,
    save_project_scenarios_data,
)
from app.session_access import RevisionConflict
from app.routes.sessions import load_user_sessions, save_user_sessions


def _seed(user, *project_ids):
    assert save_user_sessions(user.id, {
        sid: {
            'session_id': sid,
            'name': sid,
            'chat_history': [],
            'visibility': 'private',
        }
        for sid in project_ids
    })
    for sid in project_ids:
        save_project_scenarios_data(user.id, sid, {'scenarios': {}})


def test_project_scoped_save_preserves_every_other_project(db, test_user):
    _seed(test_user, 'p-a', 'p-b', 'p-c')
    stale = load_scenarios_data(test_user.id)
    live = load_scenarios_data(test_user.id)
    live['p-b']['scenarios']['s1'] = {'name': 'user scenario'}
    save_project_scenarios_data(test_user.id, 'p-b', live['p-b'], source=live)
    current_c = load_scenarios_data(test_user.id)
    current_c['p-c']['scenarios']['s2'] = {'name': 'new project'}
    save_project_scenarios_data(test_user.id, 'p-c', current_c['p-c'], source=current_c)

    stale['p-a']['project_wbs'] = {'tasks': ['t']}
    save_project_scenarios_data(test_user.id, 'p-a', stale['p-a'], source=stale)

    rows = {
        row.session_id: row.scenarios_json
        for row in UserSession.query.filter(UserSession.session_id.in_(['p-a', 'p-b', 'p-c']))
    }
    assert rows['p-b']['scenarios']['s1']['name'] == 'user scenario'
    assert rows['p-c']['scenarios']['s2']['name'] == 'new project'


def test_alias_save_targets_canonical_row_and_never_creates_intake_row(db, test_user):
    _seed(test_user, 'db-key')
    row = UserSession.query.filter_by(session_id='db-key').one()
    row.payload = {**row.payload, 'session_id': 'payload-alias'}
    db.session.commit()

    loaded = load_scenarios_data(test_user.id)
    assert isinstance(loaded, ScenariosData)
    assert loaded.row_ids['payload-alias'] == row.id
    loaded['payload-alias']['scenarios']['s'] = {'label': 'Alias edit'}
    save_project_scenarios_data(
        test_user.id, 'payload-alias', loaded['payload-alias'], source=loaded,
    )
    assert UserSession.query.filter_by(session_id='payload-alias').count() == 0
    db.session.refresh(row)
    assert row.scenarios_json['scenarios']['s']['label'] == 'Alias edit'


def test_two_stale_request_snapshots_apply_their_own_changes(db, test_user):
    _seed(test_user, 'race')
    first = load_scenarios_data(test_user.id)
    second = load_scenarios_data(test_user.id)
    first['race']['first_change'] = True
    second['race']['second_change'] = True

    save_project_scenarios_data(
        test_user.id, 'race', first['race'], source=first,
    )
    save_project_scenarios_data(test_user.id, 'race', second['race'], source=second)

    row = UserSession.query.filter_by(session_id='race').one()
    assert row.scenarios_json['first_change'] is True
    assert row.scenarios_json['second_change'] is True


def test_rejected_write_is_atomic_for_all_projects(db, test_user):
    _seed(test_user, 'atomic-a', 'atomic-b')
    stale = load_scenarios_data(test_user.id)
    current = load_scenarios_data(test_user.id)
    current['atomic-a']['value'] = 'new'
    save_project_scenarios_data(test_user.id, 'atomic-a', current['atomic-a'], source=current)
    before = {
        row.session_id: (copy.deepcopy(row.scenarios_json), row.revision, copy.deepcopy(row.payload))
        for row in UserSession.query.filter(UserSession.session_id.in_(['atomic-a', 'atomic-b']))
    }
    stale['atomic-a']['value'] = 'stale'

    with pytest.raises(RevisionConflict):
        save_project_scenarios_data(
            test_user.id, 'atomic-a', stale['atomic-a'], source=stale,
            base_revision=stale.revisions['atomic-a'],
        )

    after = {
        row.session_id: (row.scenarios_json, row.revision, row.payload)
        for row in UserSession.query.filter(UserSession.session_id.in_(['atomic-a', 'atomic-b']))
    }
    assert after == before


def test_commit_failure_rolls_back_payload_and_revision(db, test_user, monkeypatch):
    _seed(test_user, 'commit-fail', 'untouched')
    loaded = load_scenarios_data(test_user.id)
    before = {
        row.session_id: (copy.deepcopy(row.scenarios_json), row.revision)
        for row in UserSession.query.filter(UserSession.session_id.in_(['commit-fail', 'untouched']))
    }
    loaded['commit-fail']['partial'] = True
    real_commit = app_db.session.commit
    monkeypatch.setattr(app_db.session, 'commit', lambda: (_ for _ in ()).throw(RuntimeError('commit failed')))
    with pytest.raises(RuntimeError, match='commit failed'):
        save_project_scenarios_data(
            test_user.id, 'commit-fail', loaded['commit-fail'], source=loaded,
        )
    monkeypatch.setattr(app_db.session, 'commit', real_commit)
    app_db.session.expire_all()
    after = {
        row.session_id: (row.scenarios_json, row.revision)
        for row in UserSession.query.filter(UserSession.session_id.in_(['commit-fail', 'untouched']))
    }
    assert after == before


def test_updater_retry_is_bounded(db, test_user, monkeypatch):
    import app.scenarios_store as store

    _seed(test_user, 'retry-bound')
    attempts = []
    monkeypatch.setattr(
        store, '_compare_and_swap',
        lambda *args, **kwargs: attempts.append(args[1]) or 0,
    )
    with pytest.raises(RevisionConflict):
        save_project_scenarios_data(
            test_user.id, 'retry-bound',
            updater=lambda current: {**current, 'value': 'never stored'},
            max_attempts=3,
        )
    assert len(attempts) == 3
    row = UserSession.query.filter_by(session_id='retry-bound').one()
    assert 'value' not in row.scenarios_json


def test_stale_session_snapshot_advances_from_the_database_counter(db, test_user):
    _seed(test_user, 'stale-counter')
    stale_sessions = load_user_sessions(test_user.id)
    before = UserSession.query.filter_by(session_id='stale-counter').one().revision

    loaded = load_scenarios_data(test_user.id)
    loaded['stale-counter']['scenario_change'] = True
    save_project_scenarios_data(
        test_user.id, 'stale-counter', loaded['stale-counter'], source=loaded,
    )
    after_scenario = UserSession.query.filter_by(session_id='stale-counter').one().revision

    stale_sessions['stale-counter']['name'] = 'Renamed from stale snapshot'
    assert save_user_sessions(test_user.id, stale_sessions)
    row = UserSession.query.filter_by(session_id='stale-counter').one()
    assert before < after_scenario < row.revision
    assert row.scenarios_json['scenario_change'] is True
    assert row.payload['name'] == 'Renamed from stale snapshot'


def test_explicit_clear_all_still_clears_every_project(db, test_user):
    _seed(test_user, 'reset-a', 'reset-b')
    for sid in ('reset-a', 'reset-b'):
        loaded = load_scenarios_data(test_user.id)
        loaded[sid]['scenarios']['x'] = {'label': sid}
        save_project_scenarios_data(test_user.id, sid, loaded[sid], source=loaded)

    assert clear_all_scenarios_data(test_user.id) is True
    assert all(
        row.scenarios_json == {}
        for row in UserSession.query.filter(UserSession.session_id.in_(['reset-a', 'reset-b']))
    )
