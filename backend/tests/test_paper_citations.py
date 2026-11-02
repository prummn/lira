"""Bibliographic links are source observations, not model-inferred lineage."""
from app.models import Collection, CollectionPaper, Edge, Paper, PaperChunk


def add_paper(session, paper_id, title, chunks=(), **metadata):
    paper = Paper(id=paper_id, title=title, **metadata)
    session.add(paper)
    for index, (page, section, content) in enumerate(chunks):
        session.add(PaperChunk(id=f'{paper_id}-{index:04d}', paper=paper,
                               page=page, section=section, content=content))
    return paper


def test_graph_recovers_split_reference_and_preserves_source_evidence(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'framework', 'A reflective framework', [
            (10, 'References', '[30] Yao, S., Zhao, J. (2023). ReAct:'),
            (11, 'References', 'Synergizing reasoning and acting in language models. In ICLR.'),
            (11, 'References', '[31] A different reference.'),
        ])
        add_paper(session, 'actor', 'ReAct: Synergizing Reasoning and Acting in Language Models', year=2022)
        session.commit()
    graph = client.get('/api/graph').json()
    assert len(graph['edges']) == 1
    edge = graph['edges'][0]
    assert (edge['source'], edge['target'], edge['relation'], edge['relation_source']) == (
        'framework', 'actor', 'cites', 'explicit')
    assert edge['reference_label'] == '30'
    assert [item['page'] for item in edge['evidence']] == [10, 11]
    assert edge['evidence'][0]['quote'].startswith('[30]')
    assert 'ICLR' in edge['evidence'][1]['quote']
    assert '[31]' not in edge['description']
    assert client.get('/api/graph').json()['edges'][0]['id'] == edge['id']
    with client.app.state.database.sessions() as session:
        assert session.query(Edge).count() == 0  # GET never mutates user decisions.


def test_reverse_import_order_identifiers_and_scope(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'new', 'New method', [
            (6, 'References', '[1] Old title. arXiv:2210.03629v3.\n[2] Older. doi:10.1000/TEST.123.'),
        ])
        session.commit()
    assert client.get('/api/graph').json()['edges'] == []
    with client.app.state.database.sessions() as session:
        add_paper(session, 'old', 'Corrected metadata title', arxiv_id='2210.03629')
        add_paper(session, 'doi', 'Another corrected title', doi='10.1000/test.123')
        session.add(Collection(id='subset', name='Subset'))
        session.add_all([CollectionPaper(collection_id='subset', paper_id=p) for p in ('new', 'old')])
        session.commit()
    edges = client.get('/api/graph').json()['edges']
    assert {e['target'] for e in edges} == {'old', 'doi'}
    assert len(client.get('/api/graph?collection_id=subset').json()['edges']) == 1


def test_title_matching_is_distinctive_and_never_uses_body_mentions(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Survey of agents', [
            (1, 'Introduction', 'We discuss A distinctive paper about agents and memory.'),
            (7, 'References', '[1] A. Author. Attention.\n[2] B. Author. Another paper, not the desired title.'),
            (8, 'Appendix A', 'A distinctive paper about agents and memory.'),
        ])
        add_paper(session, 'mention', 'A distinctive paper about agents and memory')
        add_paper(session, 'short', 'Attention')
        session.commit()
    assert client.get('/api/graph').json()['edges'] == []


def test_title_matching_handles_pdf_line_breaks_and_keeps_stored_edge(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Source', [
            (7, 'Bibliography', '[1] A. Author. Learning long-term repre-\nsentations for language agents. 2023.'),
        ])
        add_paper(session, 'target', 'Learning long-term representations for language agents')
        session.commit()
    assert len(client.get('/api/graph').json()['edges']) == 1
    with client.app.state.database.sessions() as session:
        session.add(Edge(id='manual', source_paper_id='source', target_paper_id='target',
                         relation='cites', relation_source='user', description='My citation'))
        session.commit()
    edges = client.get('/api/graph').json()['edges']
    assert len(edges) == 1
    assert edges[0]['id'] == 'manual'
    assert edges[0]['description'] == 'My citation'
    assert edges[0]['evidence']


def test_reference_does_not_match_two_papers_with_the_same_title(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Source', [
            (7, 'References', '[1] Learning representations from natural language supervision.'),
        ])
        for p in ('one', 'two'):
            add_paper(session, p, 'Learning representations from natural language supervision')
        session.commit()
    assert client.get('/api/graph').json()['edges'] == []


def test_longer_title_and_identifier_take_precedence_over_embedded_titles(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Source', [
            (7, 'References', '[1] Smith. Attention Is All You Need for Building Language Agents. 2026.\n'
             '[2] Jones. A new method for reliable language agents. arXiv:2501.12345.'),
        ])
        add_paper(session, 'short', 'Attention Is All You Need')
        add_paper(session, 'long', 'Attention Is All You Need for Building Language Agents')
        add_paper(session, 'misleading-title', 'A new method for reliable language agents')
        add_paper(session, 'identifier', 'Corrected title of the cited publication', arxiv_id='2501.12345')
        session.commit()
    assert {e['target'] for e in client.get('/api/graph').json()['edges']} == {'long', 'identifier'}


def test_unnumbered_references_never_treat_years_as_labels_or_dump_the_bibliography(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Source', [
            (7, 'References', 'A. Author and B. Author.\n2023. A distinctive method for language agents.'),
            (7, 'References', 'C. Author. Another irrelevant publication, 2024.'),
            (8, 'References', 'D. Author. Evaluating retrieval augmented generation with evidence. 2024.'),
            (8, 'References', 'E. Author. Yet another irrelevant publication. 2025.'),
        ])
        add_paper(session, 'one', 'A distinctive method for language agents')
        add_paper(session, 'two', 'Evaluating retrieval augmented generation with evidence')
        session.commit()
    edges = client.get('/api/graph').json()['edges']
    assert {e['target'] for e in edges} == {'one', 'two'}
    for edge in edges:
        assert edge['reference_label'] is None
        assert len(edge['evidence']) == 1
        assert 'irrelevant' not in edge['description']


def test_embedded_title_is_not_a_match_when_the_longer_paper_is_not_imported(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Source', [
            (7, 'References', '[1] Smith. Attention Is All You Need for Building Language Agents. 2026.\n'
             '[2] Jones. Rethinking Attention Is All You Need. 2025.'),
        ])
        add_paper(session, 'short', 'Attention Is All You Need')
        session.commit()
    assert client.get('/api/graph').json()['edges'] == []


def test_bibliography_page_ranges_do_not_become_reference_numbers(client):
    with client.app.state.database.sessions() as session:
        add_paper(session, 'source', 'Source', [
            (7, 'References', 'Previous publication. Proceedings, pages 440\u2013\n466.'),
            (7, 'References', 'Smith. A distinctive method for language agents. 2023.'),
            (7, 'References', 'Unrelated reference. 2025.'),
        ])
        add_paper(session, 'target', 'A distinctive method for language agents')
        session.commit()
    edge, = client.get('/api/graph').json()['edges']
    assert edge['reference_label'] is None
    assert '466' not in edge['description']
    assert len(edge['evidence']) == 1
