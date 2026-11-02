from __future__ import annotations

import json

import httpx
import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Paper

TITLE = 'ReAct: Synergizing Reasoning and Acting in Language Models'


@pytest.fixture
def session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def paper(session, **values):
    item = Paper(id='paper-source', title=TITLE, arxiv_id='2210.03629', year=2022, **values)
    session.add(item)
    session.flush()
    return item


def pdf_header(path):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((60, 50), 'Published as a conference paper at ICLR 2023', fontsize=10)
        page.insert_text((60, 95), TITLE, fontsize=16)
        page.insert_text((60, 140), 'arXiv:2210.03629v3', fontsize=10)
        page.insert_text((60, 190), 'Abstract', fontsize=12)
        page.insert_text((60, 215), 'We study reasoning and acting.', fontsize=10)
        document.save(path)


def work(*, title=TITLE, doi='10.1234/react', arxiv='2210.03629', repository=False):
    return {
        'id': 'https://openalex.org/W123', 'title': title,
        'doi': 'https://doi.org/' + doi if doi else None, 'publication_year': 2023,
        'primary_location': {'landing_page_url': 'https://publisher.example/paper',
                             'source': {'display_name': 'arXiv' if repository else 'ICLR 2023',
                                        'type': 'repository' if repository else 'conference'}},
        'locations': [{'landing_page_url': 'https://arxiv.org/abs/' + arxiv}] if arxiv else [],
    }


def remote_client(respond):
    return httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)


def test_exact_publication_header_is_not_filtered_as_license(tmp_path):
    from app.services.pdf import parse_pdf
    path = tmp_path / 'source.pdf'
    pdf_header(path)
    parsed = parse_pdf(path.read_bytes())
    assert parsed.venue == 'ICLR 2023'
    assert parsed.year == 2022
    assert parsed.metadata_sources['venue'] == 'pdf_front_matter'


def test_local_header_enriches_without_external_requests_and_keeps_first_year(session, tmp_path):
    from app.services.publication_metadata import enrich_publication
    path = tmp_path / 'source.pdf'
    pdf_header(path)
    item = paper(session, pdf_path=str(path))
    report = enrich_publication(session, item, allow_external=False)
    assert report['changed'] == {'venue': 'ICLR 2023'}
    assert item.year == 2022
    assert report['provenance'][0]['publication_year'] == 2023
    assert report['provenance'][0]['source'] == 'pdf_front_matter'
    assert report['fingerprint']
    assert session.in_transaction()


def test_exact_arxiv_link_can_add_publication_without_rewriting_revision_metadata(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    with remote_client(lambda _: httpx.Response(200, json={'results': [work(title='Revised publication title')]})) as client:
        report = enrich_publication(session, item, client=client)
    assert item.venue == 'ICLR 2023'
    assert item.doi == '10.1234/react'
    assert item.title == TITLE
    assert item.year == 2022
    assert report['provenance'][0]['publication_year'] == 2023
    assert report['provenance'][0]['url'].startswith('https://api.openalex.org/')
    assert report['provenance'][0]['fingerprint']


def test_official_conference_name_has_readable_label_and_publication_year(session):
    from app.services.publication_metadata import enrich_publication
    item=paper(session)
    payload=work()
    payload['primary_location']['source']['display_name']='neural information processing systems'
    with remote_client(lambda _:httpx.Response(200,json={'results':[payload]})) as client:
        enrich_publication(session,item,client=client)
    assert item.venue=='NeurIPS 2023'
    assert item.year==2022


def test_repository_is_not_treated_as_a_conference_or_formal_doi(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    def respond(request):
        if request.url.host == 'api.openalex.org':
            return httpx.Response(200, json={'results': [work(doi='10.48550/arXiv.2210.03629', repository=True)]})
        return httpx.Response(200, json={'message': {'items': []}})
    with remote_client(respond) as client:
        report = enrich_publication(session, item, client=client)
    assert item.venue is None
    assert item.doi is None
    assert report['changed'] == {}


def test_exact_doi_response_is_verified_and_conflicting_identifier_is_rejected(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session, doi='10.1234/registered')
    def respond(request):
        if request.url.host == 'api.crossref.org' and 'query.title' not in request.url.params:
            return httpx.Response(200, json={'message': {'DOI': '10.1234/wrong', 'container-title': ['Wrong Venue']}})
        return httpx.Response(200, json={'results': [], 'message': {'items': []}})
    with remote_client(respond) as client:
        report = enrich_publication(session, item, client=client)
    assert item.doi == '10.1234/registered'
    assert item.venue is None
    assert report['changed'] == {}


def test_exact_doi_enriches_from_crossref(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session, doi='10.1234/registered')
    payload = {'message': {'DOI': '10.1234/registered', 'title': ['Different revision title'],
                           'container-title': ['Verified Conference'], 'published': {'date-parts': [[2023, 5, 2]]}}}
    with remote_client(lambda _: httpx.Response(200, json=payload)) as client:
        report = enrich_publication(session, item, client=client)
    assert item.venue == 'Verified Conference'
    assert item.year == 2022
    assert report['changed'] == {'venue': 'Verified Conference'}


@pytest.mark.parametrize('results', [
    [work(title=TITLE + ' A Survey', arxiv=None)],
    [work(arxiv='2301.99999')],
    [work(arxiv=None), {**work(doi='10.1234/other', arxiv=None), 'id': 'https://openalex.org/W999'}],
])
def test_title_fallback_rejects_partial_conflicting_or_ambiguous_matches(session, results):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    def respond(request):
        return httpx.Response(200, json={'results': results} if request.url.host == 'api.openalex.org' else {'message': {'items': []}})
    with remote_client(respond) as client:
        report = enrich_publication(session, item, client=client)
    assert report['changed'] == {}
    assert item.venue is None


def test_strict_full_title_fallback_is_accepted(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    with remote_client(lambda _: httpx.Response(200, json={'results': [work(arxiv=None)]})) as client:
        report = enrich_publication(session, item, client=client)
    assert item.venue == 'ICLR 2023'
    assert report['provenance'][0]['match'] == 'title'


def test_manual_values_including_intentional_empty_fields_survive(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session, venue='Personal Venue', metadata_sources_json=json.dumps({'venue': 'manual', 'doi': 'manual'}))
    with remote_client(lambda _: httpx.Response(200, json={'results': [work()]})) as client:
        report = enrich_publication(session, item, client=client)
    assert item.venue == 'Personal Venue'
    assert item.doi is None
    assert report['changed'] == {}
    assert json.loads(item.metadata_sources_json)['doi'] == 'manual'


def test_fingerprint_cache_avoids_calls_and_is_invalidated_by_manual_edit(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={'results': [work()]} if request.url.host == 'api.openalex.org' else {'message': {'items': []}})
    with remote_client(respond) as client:
        first = enrich_publication(session, item, client=client)
        count = len(requests)
        second = enrich_publication(session, item, client=client)
        assert second['cached'] is True
        assert second['changed'] == {}
        assert len(requests) == count
        item.title = TITLE + ' revised'
        third = enrich_publication(session, item, client=client)
    assert third['cached'] is False
    assert third['fingerprint'] != first['fingerprint']
    assert len(requests) > count


def test_outages_are_bounded_preserve_originals_and_return_evidence_warning(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session, doi='10.1234/known')
    requests = []
    def respond(request):
        requests.append(request)
        raise httpx.ReadTimeout('offline', request=request)
    with remote_client(respond) as client:
        report = enrich_publication(session, item, client=client)
    assert len(requests) <= 3
    assert report['warnings']
    assert report['changed'] == {}
    assert item.doi == '10.1234/known'
    assert item.year == 2022


def test_doi_duplicate_is_skipped_without_losing_other_verified_metadata(session):
    from app.services.publication_metadata import enrich_publication
    session.add(Paper(id='paper-existing', title='Registered publication', doi='10.1234/react'))
    session.flush()
    item = paper(session)
    with remote_client(lambda _: httpx.Response(200, json={'results': [work()]})) as client:
        report = enrich_publication(session, item, client=client)
    assert item.venue == 'ICLR 2023'
    assert item.doi is None
    assert report['warnings']
    session.flush()


def test_malformed_public_metadata_cannot_abort_librarian_or_merge_unknown_identities(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    entries = [work(), work(doi='10.1234/other')]
    for entry in entries:
        entry['id'] = {'invalid': 'identifier'}
        entry['doi'] = None
        entry['locations'] = [{'landing_page_url': 1234}]
    with remote_client(lambda _: httpx.Response(200, json={'results': entries, 'message': {'items': []}})) as client:
        report = enrich_publication(session, item, client=client)
    assert report['changed'] == {}


def test_identifier_must_not_hide_conflicting_arxiv_locations(session):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    entry = work()
    entry['locations'].append({'landing_page_url': 'https://arxiv.org/abs/2301.99999'})
    with remote_client(lambda _: httpx.Response(200, json={'results': [entry], 'message': {'items': []}})) as client:
        report = enrich_publication(session, item, client=client)
    assert report['changed'] == {}


def test_unpublished_header_body_quote_cannot_be_used_as_front_matter(session, tmp_path):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    path = tmp_path / 'body.pdf'
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((60, 60), TITLE, fontsize=16)
        page.insert_text((60, 110), 'Abstract', fontsize=12)
        page.insert_text((60, 140), 'Published as a conference paper at ICLR 2023', fontsize=10)
        document.save(path)
    item.pdf_path = str(path)
    report = enrich_publication(session, item, allow_external=False)
    assert report['changed'] == {}


def test_template_publication_declaration_is_not_trusted(session, tmp_path):
    from app.services.publication_metadata import enrich_publication
    item = paper(session)
    path = tmp_path / 'template.pdf'
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((60, 40), 'Published as a conference paper at Conference Acronym 2023', fontsize=10)
        page.insert_text((60, 80), TITLE, fontsize=16)
        page.insert_text((60, 120), 'Abstract', fontsize=12)
        document.save(path)
    item.pdf_path = str(path)
    report = enrich_publication(session, item, allow_external=False)
    assert report['changed'] == {}


def test_cache_expiry_and_force_recheck_public_source(session, monkeypatch):
    from app.services import publication_metadata
    item = paper(session)
    now = [2000000000.0]
    monkeypatch.setattr(publication_metadata.time, 'time', lambda: now[0])
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'results': [], 'message': {'items': []}})
    with remote_client(respond) as client:
        publication_metadata.enrich_publication(session, item, client=client)
        count = len(requests)
        assert publication_metadata.enrich_publication(session, item, client=client)['cached'] is True
        now[0] += 7 * 3600
        assert publication_metadata.enrich_publication(session, item, client=client)['cached'] is False
        assert len(requests) > count
        count = len(requests)
        assert publication_metadata.enrich_publication(session, item, client=client, force=True)['cached'] is False
        assert len(requests) > count
