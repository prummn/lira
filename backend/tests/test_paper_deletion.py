"""删除接口使用隔离数据库和合成文件，不访问个人论文库。"""
import logging
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import models as m


def create_paper(client, title='待删除论文'):
    response = client.post('/api/papers', json={'title': title, 'author_names': ['共享作者']})
    assert response.status_code == 201
    return response.json()['id']


def attach_pdf(client, paper_id, path=None):
    path = path or client.app.state.storage_dir / f'{paper_id}.pdf'
    path.write_bytes(b'%PDF- synthetic deletion fixture')
    with client.app.state.database.sessions() as db:
        db.get(m.Paper, paper_id).pdf_path = str(path)
        db.commit()
    return path


def test_delete_single_and_missing(client):
    paper_id = create_paper(client)
    path = attach_pdf(client, paper_id)
    response = client.delete(f'/api/papers/{paper_id}')
    assert response.status_code == 200
    assert response.json() == {'deleted_ids': [paper_id]}
    assert not path.exists()
    assert client.get(f'/api/papers/{paper_id}').status_code == 404
    assert client.delete(f'/api/papers/{paper_id}').status_code == 404


def test_batch_deduplicates_preserving_order(client):
    first, second, kept = [create_paper(client, str(i)) for i in range(3)]
    paths = [attach_pdf(client, paper_id) for paper_id in (first, second, kept)]
    response = client.post('/api/papers/batch-delete', json={'paper_ids': [second, first, second]})
    assert response.status_code == 200
    assert response.json() == {'deleted_ids': [second, first]}
    assert [path.exists() for path in paths] == [False, False, True]
    assert client.get('/api/papers').json()['total'] == 1


def test_batch_missing_validates_every_id_before_deleting(client):
    first, second = [create_paper(client, str(i)) for i in range(2)]
    paths = [attach_pdf(client, paper_id) for paper_id in (first, second)]
    response = client.post('/api/papers/batch-delete', json={'paper_ids': [first, 'missing', second]})
    assert response.status_code == 404
    assert client.get('/api/papers').json()['total'] == 2
    assert all(path.exists() for path in paths)


@pytest.mark.parametrize('payload', [
    {}, {'paper_ids': []}, {'paper_ids': ['x'] * 101}, {'paper_ids': ['']},
    {'paper_ids': [123]}, {'paper_ids': ['x' * 65]}, {'paper_ids': 'x'},
    {'paper_ids': ['x'], 'unexpected': True},
])
def test_batch_validation(client, payload):
    assert client.post('/api/papers/batch-delete', json=payload).status_code == 422


def test_batch_accepts_limit(client):
    with client.app.state.database.sessions() as db:
        ids = [f'limit-{i}' for i in range(100)]
        db.add_all([m.Paper(id=paper_id, title=paper_id) for paper_id in ids])
        db.commit()
    response = client.post('/api/papers/batch-delete', json={'paper_ids': ids})
    assert response.status_code == 200
    assert response.json() == {'deleted_ids': ids}


def test_database_cascades_and_shared_entities_survive(client):
    client.app.state.intelligence_worker.stop()
    client.app.state.research_worker.stop()
    removed, kept = [create_paper(client, str(i)) for i in range(2)]
    with client.app.state.database.sessions() as db:
        db.add_all([
            m.Collection(id='collection', name='保留集合'),
            m.KnowledgeEntity(id='entity', entity_type='method', name='共享实体', normalized_name='shared'),
            m.PaperChunk(id='chunk', paper_id=removed, content='source'),
            m.PaperChunk(id='kept-chunk', paper_id=kept, content='kept'),
            m.ChatConversation(id='chat', kind='paper', paper_id=removed, context_key='context'),
            m.TranslationJob(id='job', paper_id=removed, mode='selected', provider='test',
                             config_version='v1', prompt_version='v1', model_name='test'),
        ])
        db.flush()
        db.add_all([
            m.CollectionPaper(collection_id='collection', paper_id=removed),
            m.CollectionPaper(collection_id='collection', paper_id=kept),
            m.PaperAnalysis(paper_id=removed),
            m.Note(id='note', paper_id=removed, content='note'),
            m.Evidence(id='evidence', paper_id=removed, claim='claim', source_text='source'),
            m.IntelligenceTask(id='task', paper_id=removed, status='queued'),
            m.Edge(id='outgoing', source_paper_id=removed, target_paper_id=kept),
            m.Edge(id='incoming', source_paper_id=kept, target_paper_id=removed),
            m.KnowledgeCandidate(id='candidate', paper_id=removed, entity_id='entity',
                                 entity_type='method', name='共享实体', normalized_name='shared'),
            m.KnowledgeCandidate(id='kept-candidate', paper_id=kept, entity_id='entity',
                                 entity_type='method', name='共享实体', normalized_name='shared'),
            m.ChatTurn(id='turn', conversation_id='chat', request_id='request', question='question'),
            m.Translation(id='translation', paper_id=removed, chunk_id='chunk', source_text='source',
                          source_hash='hash', text='译文', provider='test', mode='remote',
                          config_version='v1', prompt_version='v1'),
        ])
        db.flush()
        db.add(m.KnowledgeRelation(id='relation', paper_id=removed, relation='uses',
                                  source_name='a', source_normalized_name='a', target_name='b',
                                  target_normalized_name='b', source_candidate_id='candidate'))
        db.add(m.TranslationItem(id='item', job_id='job', paragraph_id='paragraph',
                                 original_paragraph_id='paragraph', refs_json='[]',
                                 source_text='source', position=0, translation_id='translation'))
        db.commit()
    assert client.delete(f'/api/papers/{removed}').status_code == 200
    with client.app.state.database.sessions() as db:
        for model in (m.PaperAnalysis, m.Note, m.Evidence, m.IntelligenceTask, m.Edge,
                      m.KnowledgeRelation, m.ChatConversation, m.ChatTurn,
                      m.Translation, m.TranslationJob, m.TranslationItem):
            assert db.scalar(select(func.count()).select_from(model)) == 0, model.__name__
        assert db.get(m.Paper, kept) is not None
        assert db.get(m.PaperChunk, 'kept-chunk') is not None
        assert db.get(m.PaperChunk, 'chunk') is None
        assert db.get(m.KnowledgeCandidate, 'candidate') is None
        assert db.get(m.KnowledgeCandidate, 'kept-candidate') is not None
        assert db.get(m.KnowledgeEntity, 'entity') is not None
        assert db.get(m.Collection, 'collection') is not None
        assert db.scalar(select(func.count()).select_from(m.CollectionPaper)) == 1
        assert db.scalar(select(func.count()).select_from(m.Author)) == 1
        assert db.scalar(select(func.count()).select_from(m.PaperAuthor)) == 1
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []


@pytest.mark.parametrize('kind', ['external', 'traversal', 'unmanaged', 'other-paper', 'missing', 'directory'])
def test_file_path_protection(client, tmp_path, kind):
    paper_id = create_paper(client)
    storage = client.app.state.storage_dir
    if kind == 'external':
        path = tmp_path / f'{paper_id}.pdf'
    elif kind == 'traversal':
        path = storage / '..' / f'{paper_id}.pdf'
    elif kind == 'unmanaged':
        path = storage / 'personal.pdf'
    elif kind == 'other-paper':
        other = create_paper(client, '另一篇')
        path = attach_pdf(client, other)
    else:
        path = storage / f'{paper_id}.pdf'
    if kind == 'directory':
        path.mkdir()
    elif kind != 'missing':
        path.write_bytes(b'preserve')
    with client.app.state.database.sessions() as db:
        db.get(m.Paper, paper_id).pdf_path = str(path)
        db.commit()
    assert client.delete(f'/api/papers/{paper_id}').status_code == 200
    assert path.exists() == (kind != 'missing')


def test_symlink_does_not_delete_external_file(client, tmp_path):
    paper_id = create_paper(client)
    external = tmp_path / 'external.pdf'
    external.write_bytes(b'preserve')
    link = client.app.state.storage_dir / f'{paper_id}.pdf'
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip('当前系统没有创建符号链接的权限')
    with client.app.state.database.sessions() as db:
        db.get(m.Paper, paper_id).pdf_path = str(link)
        db.commit()
    assert client.delete(f'/api/papers/{paper_id}').status_code == 200
    assert external.read_bytes() == b'preserve'
    assert link.is_symlink()


def test_pdf_referenced_by_another_paper_is_preserved(client):
    first, second = [create_paper(client, str(i)) for i in range(2)]
    path = attach_pdf(client, first)
    with client.app.state.database.sessions() as db:
        db.get(m.Paper, second).pdf_path = str(path)
        db.commit()
    assert client.delete(f'/api/papers/{first}').status_code == 200
    assert path.exists()


@pytest.mark.parametrize('batch', [False, True])
def test_commit_failure_keeps_database_and_file(client, monkeypatch, batch):
    paper_id = create_paper(client)
    second = create_paper(client, '同时回滚')
    path = attach_pdf(client, paper_id)
    second_path = attach_pdf(client, second)
    def fail_commit(self):
        raise RuntimeError('模拟提交失败')
    with monkeypatch.context() as patch:
        patch.setattr(Session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='模拟提交失败'):
            if batch:
                client.post('/api/papers/batch-delete', json={'paper_ids': [paper_id, second]})
            else:
                client.delete(f'/api/papers/{paper_id}')
    assert path.exists() and second_path.exists()
    assert client.get(f'/api/papers/{paper_id}').status_code == 200
    assert client.get(f'/api/papers/{second}').status_code == 200


def test_cleanup_only_runs_after_successful_commit(client, monkeypatch):
    paper_id = create_paper(client)
    path = attach_pdf(client, paper_id)
    original_unlink = Path.unlink
    cleaned = []

    def verify_commit_then_unlink(self, **kwargs):
        if self == path:
            with client.app.state.database.sessions() as db:
                assert db.get(m.Paper, paper_id) is None
            cleaned.append(self)
        return original_unlink(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', verify_commit_then_unlink)
        response = client.delete(f'/api/papers/{paper_id}')
    assert response.status_code == 200
    assert cleaned == [path]


def test_batch_cleanup_failure_continues_with_other_files(client, monkeypatch):
    first, second = [create_paper(client, str(i)) for i in range(2)]
    first_path, second_path = [attach_pdf(client, key) for key in (first, second)]
    original_unlink = Path.unlink

    def fail_one_file(self, **kwargs):
        if self == first_path:
            raise PermissionError('模拟文件占用')
        return original_unlink(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', fail_one_file)
        response = client.post('/api/papers/batch-delete', json={'paper_ids': [first, second]})
    assert response.json() == {'deleted_ids': [first, second]}
    assert first_path.exists()
    assert not second_path.exists()
    assert client.get('/api/papers').json()['total'] == 0


def test_cleanup_failure_does_not_report_database_failure(client, monkeypatch, caplog):
    paper_id = create_paper(client)
    path = attach_pdf(client, paper_id)
    def fail_unlink(self, **kwargs):
        raise PermissionError('模拟文件占用')
    with monkeypatch.context() as patch, caplog.at_level(logging.WARNING):
        patch.setattr(Path, 'unlink', fail_unlink)
        response = client.delete(f'/api/papers/{paper_id}')
    assert response.status_code == 200
    assert path.exists()
    assert client.get(f'/api/papers/{paper_id}').status_code == 404
    assert '数据库删除已完成' in caplog.text
