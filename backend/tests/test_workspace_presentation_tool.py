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


def test_tool_merges_partial_one_pager_edits_and_clears_only_named_slots(
    app, db, client, test_user, auth_headers,
):
    card_id = 'presentation-partial-merge-card'
    _save_card(test_user.id, card_id)
    url = f'/api/v1/strategy/threads/{THREAD_ID}/scorecards/{card_id}/overrides'
    initial = client.patch(url, json={'report_presentation': {
        'colors': {'accent': '#0f6e77', 'ink': '#263238', 'tint': '#eef5f7'},
        'text': {
            'headline': 'Original headline',
            'summary': 'Keep this summary',
            'tagline': 'Clear this tagline',
        },
        'layout': {'hidden': ['financials'], 'evidence_variant': 'compact'},
    }}, headers=auth_headers)
    assert initial.status_code == 200, initial.get_json()

    headline = _run_tool(test_user, card_id, {
        'report_presentation': {'text': {'headline': 'Updated headline'}},
    })
    assert headline['ok'] is True, headline
    presentation = headline['display_overrides']['report_presentation']
    assert presentation['text'] == {
        'headline': 'Updated headline',
        'summary': 'Keep this summary',
        'tagline': 'Clear this tagline',
    }
    assert presentation['colors'] == {
        'accent': '#0F6E77', 'ink': '#263238', 'tint': '#EEF5F7',
    }
    assert presentation['layout'] == {
        'hidden': ['financials'], 'evidence_variant': 'compact',
    }

    accent = _run_tool(test_user, card_id, {
        'report_presentation': {'colors': {'accent': '#0A66C2', 'ink': None}},
    })
    assert accent['ok'] is True, accent
    presentation = accent['display_overrides']['report_presentation']
    assert presentation['colors']['accent'] == '#0A66C2'
    assert 'ink' not in presentation['colors']
    assert presentation['colors']['tint'] == '#EEF5F7'
    assert presentation['text']['headline'] == 'Updated headline'

    cleared = _run_tool(test_user, card_id, {
        'report_presentation': {'text': {'summary': None, 'tagline': ''}},
    })
    assert cleared['ok'] is True, cleared
    presentation = cleared['display_overrides']['report_presentation']
    assert presentation['text'] == {'headline': 'Updated headline'}
    assert presentation['colors']['accent'] == '#0A66C2'
    assert presentation['layout']['evidence_variant'] == 'compact'

    layout = _run_tool(test_user, card_id, {
        'report_presentation': {'layout': {'evidence_variant': 'detailed'}},
    })
    assert layout['ok'] is True, layout
    presentation = layout['display_overrides']['report_presentation']
    assert presentation['layout'] == {
        'hidden': ['financials'], 'evidence_variant': 'detailed',
    }
    assert presentation['text'] == {'headline': 'Updated headline'}
    assert presentation['colors'] == {'accent': '#0A66C2', 'tint': '#EEF5F7'}


def test_tool_can_clear_all_report_presentation_and_revalidates_merged_colors(
    app, db, client, test_user, auth_headers,
):
    card_id = 'presentation-clear-and-validate-card'
    _save_card(test_user.id, card_id)
    url = f'/api/v1/strategy/threads/{THREAD_ID}/scorecards/{card_id}/overrides'
    initial = client.patch(url, json={'report_presentation': {
        'colors': {'accent': '#0f6e77'},
        'text': {'headline': 'Keep unless the whole object is cleared'},
    }}, headers=auth_headers)
    assert initial.status_code == 200, initial.get_json()

    rejected = _run_tool(test_user, card_id, {
        'report_presentation': {'colors': {'accent': '#FFFFFF'}},
    })
    assert rejected['ok'] is False
    assert rejected['code'] == 'low_contrast'

    current = client.get(url, headers=auth_headers).get_json()['display_overrides']
    assert current['report_presentation']['colors']['accent'] == '#0F6E77'
    assert current['report_presentation']['text']['headline'] == 'Keep unless the whole object is cleared'

    cleared = _run_tool(test_user, card_id, {'report_presentation': None})
    assert cleared['ok'] is True, cleared
    assert 'report_presentation' not in cleared['display_overrides']


def test_owner_route_still_replaces_the_full_report_presentation(
    app, db, client, test_user, auth_headers,
):
    card_id = 'presentation-route-replace-card'
    _save_card(test_user.id, card_id)
    url = f'/api/v1/strategy/threads/{THREAD_ID}/scorecards/{card_id}/overrides'
    initial = client.patch(url, json={'report_presentation': {
        'colors': {'accent': '#0f6e77'},
        'text': {'headline': 'Original headline', 'summary': 'Original summary'},
    }}, headers=auth_headers)
    assert initial.status_code == 200, initial.get_json()

    replaced = client.patch(url, json={'report_presentation': {
        'text': {'headline': 'Editor sends the full object'},
    }}, headers=auth_headers)
    assert replaced.status_code == 200, replaced.get_json()
    assert replaced.get_json()['display_overrides']['report_presentation'] == {
        'text': {'headline': 'Editor sends the full object'},
    }


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


def test_overrides_endpoint_explains_a_color_that_is_too_light(app, db, client, test_user, auth_headers):
    card_id = 'presentation-low-contrast-card'
    _save_card(test_user.id, card_id)
    url = f'/api/v1/strategy/threads/{THREAD_ID}/scorecards/{card_id}/overrides'
    response = client.patch(url, json={'display_overrides': {
        'report_presentation': {'colors': {'accent': '#E8472C'}},
    }}, headers=auth_headers)
    assert response.status_code == 400
    body = response.get_json()
    assert body['code'] == 'low_contrast'
    assert body['error'] == 'That color is too light to read on white. Choose a darker shade.'
