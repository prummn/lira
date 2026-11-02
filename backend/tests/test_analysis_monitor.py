"""Analysis progress in the global monitor uses isolated stores and no models."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pymupdf as fitz

from app.models import IntelligenceTask, Paper
from app.services.task_monitor import monitor_analysis_tasks


def test_opt_in_import_appears_in_monitor_and_tracks_progress_without_report(client, monkeypatch):
    client.app.state.intelligence_worker.stop()
    client.app.state.research_worker.stop()
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: SimpleNamespace(mode='remote', configured=True))
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((60, 65), 'Background Analysis Monitor', fontsize=18)
        page.insert_text((60, 110), 'Abstract', fontsize=14)
        page.insert_textbox(fitz.Rect(60, 145, 530, 290), 'We examine persistent research tasks and their visible progress in a local reading workspace.', fontsize=12)
        pdf = document.tobytes()
    imported = client.post('/api/papers/import', files={'file': ('monitor.pdf', pdf, 'application/pdf')}, data={'analyze': 'true'})
    assert imported.status_code == 201
    task_id = imported.json()['intelligence_task']['id']
    paper_id = imported.json()['id']
    state = client.get('/api/research/status').json()
    assert len(state['analysis_tasks']) == 1
    task = state['analysis_tasks'][0]
    assert (task['id'], task['paper_id'], task['status'], task['total_steps']) == (task_id, paper_id, 'queued', 0)
    assert task['paper_title'] == imported.json()['title']
    with client.app.state.database.sessions() as db:
        row = db.get(IntelligenceTask, task_id)
        row.status, row.phase, row.completed_steps, row.total_steps = 'running', 'extract', 2, 7
        row.report_json = json.dumps({'long_report': 'private source material' * 2000})
        db.commit()
    task = client.get('/api/research/status').json()['analysis_tasks'][0]
    assert (task['status'], task['phase'], task['completed_steps'], task['total_steps']) == ('running', 'extract', 2, 7)
    assert 'report' not in task and 'report_json' not in task and 'run_token' not in task
    with client.app.state.database.sessions() as db:
        row = db.get(IntelligenceTask, task_id)
        row.status, row.phase, row.completed_steps = 'partial', 'complete', 7
        db.commit()
    task = client.get('/api/research/status').json()['analysis_tasks'][0]
    assert task['id'] == task_id and task['status'] == 'partial'


def test_monitor_keeps_all_active_analyses_and_only_latest_recent_per_paper(client):
    client.app.state.intelligence_worker.stop()
    client.app.state.research_worker.stop()
    now = datetime.now(timezone.utc)
    with client.app.state.database.sessions() as db:
        db.add_all([Paper(id='active', title='Active paper'), Paper(id='retried', title='Retried paper'), Paper(id='history', title='History')])
        db.flush()
        db.add(IntelligenceTask(id='old-active', paper_id='active', status='queued', phase='queued', created_at=now-timedelta(days=7)))
        db.add(IntelligenceTask(id='old-failure', paper_id='retried', status='failed', phase='failed', created_at=now-timedelta(days=1)))
        db.add(IntelligenceTask(id='new-success', paper_id='retried', status='completed', phase='complete', created_at=now))
        db.add_all([IntelligenceTask(id=f'history-{i:03}', paper_id='history', status='failed', phase='failed', created_at=now+timedelta(seconds=i)) for i in range(45)])
        db.commit()
    tasks = client.get('/api/research/status').json()['analysis_tasks']
    assert {task['id'] for task in tasks} == {'old-active', 'new-success', 'history-044'}
    assert tasks[0]['id'] == 'old-active'


def test_monitor_does_not_duplicate_task_finishing_between_active_and_recent_reads(client):
    client.app.state.intelligence_worker.stop()
    client.app.state.research_worker.stop()
    with client.app.state.database.sessions() as db:
        db.add(Paper(id='finishing', title='Finishing paper'))
        db.flush()
        db.add(IntelligenceTask(id='finishing-task', paper_id='finishing', status='running', phase='synthesize'))
        db.commit()

        class FinishBetweenReads:
            reads = 0

            def execute(self, statement):
                self.reads += 1
                if self.reads == 2:
                    task = db.get(IntelligenceTask, 'finishing-task')
                    task.status, task.phase = 'completed', 'complete'
                    db.commit()
                return db.execute(statement)

        tasks = monitor_analysis_tasks(FinishBetweenReads())
        assert [task['id'] for task in tasks] == ['finishing-task']
