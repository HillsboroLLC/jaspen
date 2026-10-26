from flask_jwt_extended import create_access_token

from app.models import AdminAuditEvent, UserSession


def test_admin_feedback_view_is_audited_without_customer_content(client, app, db, admin_user, test_user):
    customer_text = 'confidential customer decision text'
    row = UserSession(
        user_id=test_user.id,
        session_id='feedback-thread',
        name='Feedback project',
        payload={'chat_history': [{
            'role': 'assistant',
            'content': customer_text,
            'feedback': {'value': 'down', 'note': 'Needs work'},
        }]},
    )
    db.session.add(row)
    db.session.commit()
    with app.app_context():
        token = create_access_token(identity=str(admin_user.id))

    response = client.get(
        '/api/v1/admin/message-feedback?value=down',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    event = AdminAuditEvent.query.filter_by(action='message_feedback.view').one()
    assert event.actor_user_id == admin_user.id
    assert event.details == {
        'user_id_filter': None,
        'value_filter': 'down',
        'query_used': False,
        'result_count': 1,
    }
    assert customer_text not in str(event.details)
