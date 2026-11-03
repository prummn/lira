"""Knowledge jobs remain visible without loading source text into the monitor."""
import json
from datetime import datetime, timedelta, timezone

from app.models import Collection, KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun, Paper


def test_monitor_keeps_all_active_batches_and_reports_paper_checkpoints(client):
    client.app.state.research_worker.stop()
    now = datetime.now(timezone.utc)
    with client.app.state.database.sessions() as db:
        db.add(Collection(id='topic', name='Agents'))
        db.add(Paper(id='p', title='ReAct'))
        db.flush()
        db.add(KnowledgeMaintenanceRun(id='old', scope_type='collection', scope_id='topic', status='running',
            source_fingerprint='old', created_at=now-timedelta(days=7), usage_json=json.dumps({
                'paper_count': 8, 'audit_issue_ids': ['done', 'active', 'retry'],
                'processed_issue_ids': ['done'], 'active_issue_id': 'active',
                'paper_audits': [{'private_source': 'x'*100000}]})))
        db.add(KnowledgeMaintenanceRun(id='queued', scope_type='library', status='queued', source_fingerprint='queued'))
        db.add_all([KnowledgeMaintenanceRun(id=f'recent-{i}', scope_type='library', status='complete',
            source_fingerprint=str(i), created_at=now+timedelta(seconds=i)) for i in range(15)])
        db.flush()
        for iid, status in [('done', 'accepted'), ('active', 'proposed'), ('retry', 'proposed')]:
            db.add(KnowledgeMaintenanceIssue(id=iid, run_id='old', kind='coverage', severity='info', status=status,
                confidence=0, auto_eligible=False, summary='Source check', reasoning='', source_fingerprint='x',
                proposed_action_json=json.dumps({'type':'curate_paper','paper_id':'p'})))
        db.commit()
    state = client.get('/api/research/status').json()
    jobs = state['maintenance_tasks']
    assert {job['id'] for job in jobs if job['status'] in ('queued', 'running')} == {'old', 'queued'}
    run = next(job for job in jobs if job['id'] == 'old')
    assert run['scope_title'] == 'Agents'
    assert (run['completed'], run['total'], run['paper_count']) == (1, 3, 8)
    assert run['active_paper_id'] == 'p' and run['active_paper_title'] == 'ReAct'
    assert 'usage' not in run and 'paper_audits' not in run
    assert len([job for job in jobs if job['status'] == 'complete']) <= 10


def test_monitor_distinguishes_waiting_from_finished_partial_runs(client):
    client.app.state.research_worker.stop()
    worker = client.app.state.research_worker
    worker.settings(worker.settings().model_copy(update={'enabled':True,'maintenance_enabled':True}))
    with client.app.state.database.sessions() as db:
        db.add(KnowledgeMaintenanceRun(id='waiting', scope_type='library', status='partial', source_fingerprint='w',
            usage_json=json.dumps({'audit_issue_ids':['pending'], 'retry_at':{'pending': 9999999999}})))
        db.add(KnowledgeMaintenanceRun(id='review', scope_type='library', status='partial', source_fingerprint='r',
            usage_json=json.dumps({'audit_issue_ids':['failed'], 'processed_issue_ids':['failed']})))
        db.flush()
        for iid, rid, status in [('pending','waiting','proposed'), ('failed','review','needs_review')]:
            db.add(KnowledgeMaintenanceIssue(id=iid,run_id=rid,kind='coverage',severity='info',status=status,
                confidence=0,auto_eligible=False,summary='Check',reasoning='',source_fingerprint='x'))
        db.commit()
    jobs = client.get('/api/research/status').json()['maintenance_tasks']
    waiting = next(job for job in jobs if job['id']=='waiting')
    reviewed = next(job for job in jobs if job['id']=='review')
    assert waiting['pending'] == 1 and waiting['reason'] == 'retry_wait'
    assert reviewed['pending'] == 0 and reviewed['failed'] == 1


def test_single_paper_jobs_show_the_paper_name_instead_of_identical_generic_titles(client):
    client.app.state.research_worker.stop()
    with client.app.state.database.sessions() as db:
        db.add(Paper(id='p',title='ReAct'))
        db.commit()
    created=client.post('/api/knowledge/maintenance/runs',json={'scope_type':'papers','paper_ids':['p']})
    assert created.status_code == 200
    task=next(t for t in client.get('/api/research/status').json()['maintenance_tasks'] if t['id']==created.json()['id'])
    assert task['scope_title'] == 'ReAct'
