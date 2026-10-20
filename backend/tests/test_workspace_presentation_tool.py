from werkzeug.security import generate_password_hash

from app import db as app_db
from app.models import User
from app.scorecards import upsert_scorecard


THREAD_ID = 'workspace-presentation-thread'


def _card(card_id, name='Workspace option'):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'thread_id': THREAD_ID,
        'project_name': name,
        'jaspen_score': 64,
        'dimensions': {'fit': {'label': 'Fit', 'score': 64, 'confidence': 'medium'}},
        'metrics': {'value': 123},
        'gates': [{'key': 'approval', 'status': 'pass'}],
    }


def _save_card(user_id, card_id):
    upsert_scorecard(
        user_id=user_id,
        thread_id=THREAD_ID,
        payload=_card(card_id),
    )
    app_db.session.commit()


def _run_tool(user, card_id, changes):
    from app.routes.ai_agent import _execute_mutation_tool

    return _execute_mutation_tool(
        'update_workspace_presentation',
        {'scorecard_id': card_id, 'changes': changes},
        user=user,
        user_id=user.id,
        thread_id=THREAD_ID,
        view_context={'current_view': 'scorecard', 'active_scorecard_id': card_id},
    )


def test_tool_and_patch_route_share_validated_override_result(
    app, db, client, test_user, auth_headers,
):
    route_card = 'presentation-route-card'
    tool_card = 'presentation-tool-card'
    _save_card(test_user.id, route_card)
    _save_card(test_user.id, tool_card)
    changes = {
        'section_layout': [
            {'key': 'score', 'x': 0, 'y': 0, 'w': 4, 'h': 3},
            {'key': 'executive', 'x': 4, 'y': 0, 'w': 8, 'h': 3},
        ],
        'custom_blocks': [
            {'id': 'market-note', 'type': 'callout', 'heading': 'Market note',
             'body': 'Keep this visible.', 'x': 0, 'y': 4, 'w': 6, 'h': 3},
        ],
        'report_presentation': {
            'colors': {'accent': '#0f6e77', 'tint': '#eef5f7'},
            'text': {'headline': 'A clearer decision brief'},
            'layout': {'hidden': ['financials'], 'evidence_variant': 'compact'},
        },
    }

    route = client.patch(
        f'/api/v1/strategy/threads/{THREAD_ID}/scorecards/{route_card}/overrides',
        json=changes,
        headers=auth_headers,
    )
    assert route.status_code == 200, route.get_json()

    tool = _run_tool(test_user, tool_card, changes)
    assert tool['ok'] is True, tool
    assert tool['display_overrides'] == route.get_json()['display_overrides']
    assert tool['updated_scorecard']['jaspen_score'] == 64
    assert tool['updated_scorecard']['dimensions']['fit']['score'] == 64
    assert tool['updated_scorecard']['metrics'] == {'value': 123}
    assert tool['updated_scorecard']['gates'] == [{'key': 'approval', 'status': 'pass'}]


def test_tool_rejects_unknown_section_low_contrast_and_analytical_fields(app, db, test_user):
    card_id = 'presentation-rejections-card'
    _save_card(test_user.id, card_id)

    unknown_section = _run_tool(
        test_user, card_id, {'section_layout': [{'key': 'secret_scores', 'x': 0}]}
    )
    assert unknown_section['ok'] is False
    assert unknown_section['code'] == 'unknown_section'
    assert 'secret_scores' in unknown_section['error']

    low_contrast = _run_tool(
        test_user, card_id, {'report_presentation': {'colors': {'accent': '#FFFFFF'}}}
    )
    assert low_contrast['ok'] is False
    assert low_contrast['code'] == 'low_contrast'

    analytical = _run_tool(test_user, card_id, {'jaspen_score': 99})
    assert analytical['ok'] is False
    assert analytical['code'] == 'unsupported_override_key'
    assert 'jaspen_score' in analytical['error']


def test_tool_refuses_a_scorecard_owned_by_another_user(app, db, test_user):
    other = User(
        email='workspace-owner@example.com',
        name='Other Owner',
        password_hash=generate_password_hash('ValidPass1', method='pbkdf2:sha256'),
        subscription_plan='free',
        credits_remaining=300,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(other)
    db.session.commit()
    _save_card(other.id, 'other-owner-card')

    result = _run_tool(test_user, 'other-owner-card', {'subtitle': 'Not allowed'})
    assert result['ok'] is False
    assert result['code'] == 'scorecard_not_editable'


def test_tool_schema_allows_only_presentation_change_keys(app):
    from app.routes.ai_agent import _anthropic_tool_definitions
    from app.routes.strategy import _ALLOWED_OVERRIDE_KEYS

    tools = {
        item['name']: item
        for item in _anthropic_tool_definitions(enable_mutation_tools=True)
    }
    schema = tools['update_workspace_presentation']['input_schema']
    changes = schema['properties']['changes']
    assert set(changes['properties']) == _ALLOWED_OVERRIDE_KEYS
    assert changes['additionalProperties'] is False
    assert 'changes' in schema['required']


def test_tool_schema_targets_one_pager_text_colors_and_decision_title(app):
    from app.routes.ai_agent import _anthropic_tool_definitions

    tools = {
        item['name']: item
        for item in _anthropic_tool_definitions(enable_mutation_tools=True)
    }
    tool = tools['update_workspace_presentation']
    changes = tool['input_schema']['properties']['changes']['properties']

    assert 'report_presentation.text' in tool['description']
    assert 'report_presentation.colors' in tool['description']
    assert 'title field renames the decision itself' in tool['description']
    report_description = changes['report_presentation']['description']
    for slot in ('headline', 'summary', 'accent', 'ink', 'tint'):
        assert slot in report_description
    assert 'Do not use for a one-pager headline' in changes['title']['description']
