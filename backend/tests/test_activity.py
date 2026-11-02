from datetime import date, timedelta


def _paper(client, paper_id='activity-paper'):
    from app.models import Paper

    with client.app.state.database.sessions() as session:
        session.add(Paper(id=paper_id, title='Activity paper'))
        session.commit()
    return paper_id


def test_activity_aggregates_kinds_and_deduplicates_paper_ids(client):
    paper_id = _paper(client)
    assert client.post('/api/activity', json={'kind': 'reading', 'paper_id': paper_id}).status_code == 201
    assert client.post('/api/activity', json={'kind': 'notes', 'paper_id': paper_id}).status_code == 201
    assert client.post('/api/activity', json={'kind': 'notes', 'paper_id': paper_id}).status_code == 201

    payload = client.get('/api/activity?days=7').json()
    assert payload['days'][-1]['reading'] == 1
    assert payload['days'][-1]['notes'] == 2
    assert payload['days'][-1]['total'] == 3
    assert payload['days'][-1]['paper_ids'] == [paper_id]
    assert payload['total'] == 3


def test_activity_zero_fills_range_and_calculates_streak(client):
    from app.models import ResearchActivity

    today = date.today()
    with client.app.state.database.sessions() as session:
        session.add_all([
            ResearchActivity(day=today, reading=1, notes=0, language=0, search=0, imports=0, paper_ids_json='[]'),
            ResearchActivity(day=today - timedelta(days=1), reading=0, notes=2, language=0, search=0, imports=0, paper_ids_json='[]'),
        ])
        session.commit()

    payload = client.get('/api/activity?days=5').json()
    assert len(payload['days']) == 5
    assert payload['days'][0]['total'] == 0
    assert payload['active_days_30'] == 2
    assert payload['streak'] == 2


def test_activity_rejects_unknown_kind_and_paper(client):
    assert client.post('/api/activity', json={'kind': 'scroll'}).status_code == 422
    assert client.post('/api/activity', json={'kind': 'reading', 'paper_id': 'missing'}).status_code == 404
