from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

from test_workflow import pdf_bytes


def public_resolver(host: str, port: int) -> list[str]:
    return ['93.184.216.34']


def test_arxiv_abs_version_normalizes_to_pdf_download() -> None:
    from app.services.downloads import download_pdf

    content = pdf_bytes('Original public PDF content')
    seen = []
    def respond(request: httpx.Request):
        seen.append(str(request.url))
        return httpx.Response(200, content=content, headers={'content-type': 'application/pdf'})
    result = download_pdf('https://arxiv.org/abs/1706.03762v7', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert seen == ['https://arxiv.org/pdf/1706.03762v7']
    assert result.source_url == 'https://arxiv.org/abs/1706.03762v7'
    assert result.arxiv_id == '1706.03762'
    assert result.data == content


@pytest.mark.parametrize('duration,allowed',[(70,True),(181,False)])
def test_slow_realistic_pdf_transfer_has_a_bounded_three_minute_deadline(monkeypatch,duration,allowed):
    from app.services.downloads import download_pdf
    content = pdf_bytes('Original PDF with a slow public transfer')
    elapsed = [0.0]
    class SlowPDF(httpx.SyncByteStream):
        def __iter__(self):
            yield content[:10]
            elapsed[0] = duration
            yield content[10:]
    monkeypatch.setattr('app.services.downloads.time.monotonic',lambda:elapsed[0])
    transport = httpx.MockTransport(lambda _:httpx.Response(200,stream=SlowPDF()))
    if allowed:
        assert download_pdf('https://papers.example/real.pdf',transport=transport,resolver=public_resolver).data == content
    else:
        with pytest.raises(HTTPException) as failure:
            download_pdf('https://papers.example/real.pdf',transport=transport,resolver=public_resolver)
        assert failure.value.status_code == 504


def test_public_redirect_pdf_is_allowed_and_each_target_is_checked() -> None:
    from app.services.downloads import download_pdf

    content = pdf_bytes('A paper acquired after a redirect')
    targets = []
    def resolve(host: str, port: int):
        targets.append(host)
        return public_resolver(host, port)
    def respond(request: httpx.Request):
        if request.url.host == 'papers.example':
            return httpx.Response(302, headers={'location': 'https://cdn.example/real.pdf'})
        return httpx.Response(200, content=content, headers={'content-type': 'application/octet-stream'})
    result = download_pdf('https://papers.example/link', transport=httpx.MockTransport(respond), resolver=resolve)
    assert result.data == content
    assert result.download_url == 'https://cdn.example/real.pdf'
    assert targets == ['papers.example', 'cdn.example']


@pytest.mark.parametrize('url', ['file:///tmp/paper.pdf', 'ftp://papers.example/paper.pdf', 'https://name:password@papers.example/paper.pdf', 'http://127.0.0.1/paper.pdf', 'http://[::1]/paper.pdf', 'http://169.254.169.254/latest/meta-data'])
def test_invalid_or_private_links_never_send_a_request(url: str) -> None:
    from app.services.downloads import download_pdf

    def forbidden(request):
        pytest.fail('Invalid URLs must not be requested')
    with pytest.raises(HTTPException) as failure:
        download_pdf(url, transport=httpx.MockTransport(forbidden), resolver=public_resolver)
    assert failure.value.status_code == 422
    assert isinstance(failure.value.detail, str)


@pytest.mark.parametrize('addresses', [['10.1.2.3'], ['93.184.216.34', '192.168.0.1'], ['::ffff:127.0.0.1']])
def test_private_dns_addresses_are_rejected(addresses: list[str]) -> None:
    from app.services.downloads import download_pdf

    with pytest.raises(HTTPException) as failure:
        download_pdf('https://private-dns.example/paper.pdf', transport=httpx.MockTransport(lambda _: pytest.fail('Private DNS target requested')), resolver=lambda *_: addresses)
    assert failure.value.status_code == 422


def test_redirect_to_private_ip_is_rejected_before_second_request() -> None:
    from app.services.downloads import download_pdf

    calls = []
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/internal.pdf'})
    with pytest.raises(HTTPException) as failure:
        download_pdf('https://public.example/paper.pdf', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert failure.value.status_code == 422
    assert len(calls) == 1


@pytest.mark.parametrize('kind,status', [('html', 415), ('large_header', 413), ('large_stream', 413), ('timeout', 504), ('not_found', 404)])
def test_download_errors_are_bounded_and_useful(kind: str, status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import downloads

    monkeypatch.setattr(downloads, 'MAX_PDF_BYTES', 100)
    def respond(request):
        if kind == 'timeout':
            raise httpx.ReadTimeout('unsafe upstream details', request=request)
        if kind == 'not_found':
            return httpx.Response(404)
        if kind == 'large_header':
            return httpx.Response(200, content=b'%PDF-', headers={'content-length': '101'})
        if kind == 'large_stream':
            return httpx.Response(200, content=b'%PDF-' + b'x' * 100)
        return httpx.Response(200, text='<html>A paper abstract page</html>', headers={'content-type': 'text/html'})
    with pytest.raises(HTTPException) as failure:
        downloads.download_pdf('https://public.example/item', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert failure.value.status_code == status
    assert 'unsafe' not in failure.value.detail


def test_default_transport_pins_validated_public_ip_and_preserves_host_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.downloads import download_pdf

    content = pdf_bytes('A pinned download')
    def respond(self, request):
        assert request.url.host == '93.184.216.34'
        assert request.headers['host'] == 'public.example'
        assert request.extensions['sni_hostname'] == 'public.example'
        return httpx.Response(200, content=content)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', respond)
    result = download_pdf('https://public.example/paper.pdf', resolver=public_resolver)
    assert result.data == content


def test_arxiv_citation_metadata_uses_original_year_and_author_order() -> None:
    from app.services.metadata import enrich_metadata

    page = '''<html><head>
    <meta name="citation_title" content="Title From Actual Citation Metadata">
    <meta name="citation_author" content="Surname, First">
    <meta name="citation_author" content="Another, Second">
    <meta name="citation_date" content="2017/06/12">
    <meta name="citation_online_date" content="2023/08/02">
    <meta name="citation_arxiv_id" content="1706.03762">
    </head></html>'''
    result = enrich_metadata(arxiv_id='1706.03762v7', transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)), resolver=public_resolver)
    assert result.fields['title'] == 'Title From Actual Citation Metadata'
    assert result.fields['authors'] == ['First Surname', 'Second Another']
    assert result.fields['year'] == 2017
    assert result.fields['arxiv_id'] == '1706.03762'
    assert result.sources['year'] == 'arxiv'
    assert result.warnings == []


def test_arxiv_metadata_fetches_requested_revision_instead_of_latest() -> None:
    from app.services.metadata import enrich_metadata
    calls = []
    def respond(request):
        calls.append(str(request.url))
        authors = ['First, Alice', 'Original, Bob'] if request.url.path.endswith('v2') else ['First, Alice']
        page = '<meta name="citation_title" content="Versioned Paper"><meta name="citation_date" content="2024/01/30"><meta name="citation_arxiv_id" content="2401.17043">'
        page += ''.join(f'<meta name="citation_author" content="{name}">' for name in authors)
        return httpx.Response(200, text=page)
    result = enrich_metadata(arxiv_id='2401.17043v2', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert calls == ['https://arxiv.org/abs/2401.17043v2']
    assert result.fields['authors'] == ['Alice First', 'Bob Original']
    assert result.fields['arxiv_id'] == '2401.17043'


def test_versioned_metadata_does_not_silently_accept_latest_atom_entry() -> None:
    from app.services.metadata import enrich_metadata
    feed = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.17043v6</id><title>Latest</title><published>2024-01-30</published><author><name>Different Author</name></author></entry></feed>'
    def respond(request):
        return httpx.Response(503) if request.url.host == 'arxiv.org' else httpx.Response(200, text=feed)
    result = enrich_metadata(arxiv_id='2401.17043v2', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields == {}
    assert result.warnings


def test_crossref_does_not_replace_unavailable_exact_revision_byline() -> None:
    from app.services.metadata import enrich_metadata
    def respond(request):
        if request.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'DOI': '10.1234/registered', 'title': ['Published version'], 'author': [{'given': 'Different', 'family': 'Author'}], 'container-title': ['Verified Journal'], 'published': {'date-parts': [[2025]]}}})
        return httpx.Response(503)
    result = enrich_metadata(arxiv_id='2401.17043v2', doi='10.1234/registered', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields == {'doi': '10.1234/registered', 'venue': 'Verified Journal'}
    assert result.warnings


@pytest.mark.parametrize('value', ['10.1145/nnnnnnn.nnnnnnn', '10.1234/XXXXXXX.XXXXXXX'])
def test_template_placeholder_dois_are_unknown(value) -> None:
    from app.services.metadata import normalize_doi
    assert normalize_doi(value) is None


def test_arxiv_atom_fallback_uses_published_not_updated() -> None:
    from app.services.metadata import enrich_metadata

    feed = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1810.04805v2</id><title>An Actual Atom Title</title><published>2018-10-11T00:00:00Z</published><updated>2019-05-24T00:00:00Z</updated><author><name>First Author</name></author><author><name>Second Author</name></author></entry></feed>'''
    def respond(request):
        if request.url.host == 'arxiv.org':
            return httpx.Response(503)
        return httpx.Response(200, text=feed)
    result = enrich_metadata(arxiv_id='1810.04805', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields['year'] == 2018
    assert result.fields['authors'] == ['First Author', 'Second Author']
    assert result.fields['title'] == 'An Actual Atom Title'


def test_authority_outage_is_a_warning_and_unknown_identifiers_do_not_fetch() -> None:
    from app.services.metadata import enrich_metadata

    calls = []
    def fail(request):
        calls.append(str(request.url))
        raise httpx.ConnectError('unsafe upstream details', request=request)
    result = enrich_metadata(arxiv_id='1706.03762', transport=httpx.MockTransport(fail), resolver=public_resolver)
    assert result.fields == {}
    assert result.warnings
    assert all('unsafe' not in warning for warning in result.warnings)
    assert len(calls) == 2
    missing = enrich_metadata(transport=httpx.MockTransport(fail), resolver=public_resolver)
    assert missing.fields == {}
    assert missing.warnings == []
    assert len(calls) == 2


def test_crossref_uses_publication_dates_and_verifies_returned_doi() -> None:
    from app.services.metadata import enrich_metadata

    response = {'message': {'DOI': '10.1234/real', 'title': ['Registered Title'], 'author': [{'given': 'Alice', 'family': 'Smith'}, {'given': 'Bob', 'family': 'Jones'}], 'container-title': ['Registered Journal'], 'published-online': {'date-parts': [[2019, 8, 1]]}, 'published-print': {'date-parts': [[2020, 1, 1]]}, 'deposited': {'date-parts': [[2025]]}}}
    result = enrich_metadata(doi='10.1234/real', transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)), resolver=public_resolver)
    assert result.fields['year'] == 2019
    assert result.fields['authors'] == ['Alice Smith', 'Bob Jones']
    assert result.fields['venue'] == 'Registered Journal'
    assert result.sources['title'] == 'crossref'
    response['message']['DOI'] = '10.9999/unrelated'
    unrelated = enrich_metadata(doi='10.1234/real', transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)), resolver=public_resolver)
    assert unrelated.fields == {}
    assert unrelated.warnings


def test_arxiv_redirect_to_unrelated_host_cannot_be_authoritative() -> None:
    from app.services.metadata import enrich_metadata

    html = '<meta name="citation_title" content="Untrusted Redirect Title"><meta name="citation_author" content="Untrusted Author"><meta name="citation_date" content="2017/01/01"><meta name="citation_arxiv_id" content="1706.03762">'
    def respond(request):
        if request.url.host == 'arxiv.org':
            return httpx.Response(302, headers={'location': 'https://unrelated.example/citations'})
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(503)
        return httpx.Response(200, text=html)
    result = enrich_metadata(arxiv_id='1706.03762', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields == {}
    assert result.sources == {}
    assert result.warnings


def test_arxiv_html_without_verified_identifier_uses_atom_fallback() -> None:
    from app.services.metadata import enrich_metadata

    html = '<meta name="citation_title" content="Unidentified Title"><meta name="citation_author" content="Someone"><meta name="citation_date" content="2017/01/01">'
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v1</id><title>Verified Atom Title</title><published>2017-06-12T00:00:00Z</published><author><name>Verified Author</name></author></entry></feed>'
    calls = []
    def respond(request):
        calls.append(request.url.host)
        return httpx.Response(200, text=html if request.url.host == 'arxiv.org' else atom)
    result = enrich_metadata(arxiv_id='1706.03762', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields['title'] == 'Verified Atom Title'
    assert result.fields['authors'] == ['Verified Author']
    assert calls == ['arxiv.org', 'export.arxiv.org']


def test_crossref_redirect_to_unrelated_host_cannot_be_authoritative() -> None:
    from app.services.metadata import enrich_metadata

    def respond(request):
        if request.url.host == 'api.crossref.org':
            return httpx.Response(302, headers={'location': 'https://unrelated.example/record'})
        return httpx.Response(200, json={'message': {'DOI': '10.1234/real', 'title': ['Untrusted redirect metadata']}})
    result = enrich_metadata(doi='10.1234/real', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields == {}
    assert result.sources == {}
    assert result.warnings


def test_slow_small_stream_checks_deadline_after_each_piece(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import downloads

    elapsed = [0.0]
    class SlowStream(httpx.SyncByteStream):
        delivered = 0
        def __iter__(self):
            for _ in range(8):
                elapsed[0] += 1.0
                self.delivered += 1
                yield b'x' * 1024
    stream = SlowStream()
    monkeypatch.setattr(downloads.time, 'monotonic', lambda: elapsed[0])
    with pytest.raises(HTTPException) as failure:
        downloads.fetch_public('https://public.example/paper.pdf', max_bytes=100000, deadline=3, transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)), resolver=public_resolver)
    assert failure.value.status_code == 504
    assert stream.delivered <= 4


def test_blank_arxiv_authors_do_not_overwrite_local_authors_or_skip_fallback() -> None:
    from app.services.metadata import enrich_metadata

    html = '<meta name="citation_arxiv_id" content="1706.03762"><meta name="citation_title" content="Valid title"><meta name="citation_author" content=" "><meta name="citation_date" content="2017/06/12">'
    calls = []
    def respond(request):
        calls.append(request.url.host)
        return httpx.Response(200, text=html) if request.url.host == 'arxiv.org' else httpx.Response(503)
    result = enrich_metadata(arxiv_id='1706.03762', transport=httpx.MockTransport(respond), resolver=public_resolver)
    assert result.fields == {}
    assert result.sources == {}
    assert result.warnings
    assert calls == ['arxiv.org', 'export.arxiv.org']
