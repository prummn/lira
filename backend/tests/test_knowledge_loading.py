"""Field views fetch stored summaries, never reader-sized source payloads."""
from sqlalchemy import event
from app.models import Collection, CollectionPaper, Paper, PaperChunk


def test_knowledge_papers_is_scoped_and_never_loads_reader_tables(client):
    with client.app.state.database.sessions() as db:
        db.add_all([Collection(id='topic', name='Agents'), Paper(id='p',title='ReAct'), Paper(id='other',title='Other')])
        db.flush()
        db.add(CollectionPaper(collection_id='topic',paper_id='p'))
        db.add(PaperChunk(id='chunk',paper_id='p',page=1,content='PRIVATE FULL TEXT'*1000))
        db.commit()
    queries=[]
    def record(conn,cursor,statement,parameters,context,executemany):
        queries.append(statement.lower())
    engine=client.app.state.database.engine
    event.listen(engine,'before_cursor_execute',record)
    try:
        response=client.get('/api/knowledge/papers?collection_id=topic')
    finally:
        event.remove(engine,'before_cursor_execute',record)
    assert response.status_code == 200, response.text
    assert [p['id'] for p in response.json()['items']] == ['p']
    paper=response.json()['items'][0]
    assert paper['analysis'] is None
    assert not {'chunks','notes','translations','intelligence_report','intelligence_task'} & paper.keys()
    assert not any('paper_chunks' in q or 'translations' in q or 'intelligence_tasks' in q for q in queries)
    assert len(client.get('/api/knowledge/papers').json()['items']) == 2
    assert client.get('/api/knowledge/papers?collection_id=missing').status_code == 404
