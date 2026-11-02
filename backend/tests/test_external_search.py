import httpx

from app.services.external_search import search_external, transient_chunks


def test_external_search_reconstructs_openalex_abstract_and_keeps_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params['search'] == 'HotpotQA exact match'
        return httpx.Response(200, json={'results': [{
            'id': 'https://openalex.org/W1',
            'title': 'HotpotQA: A Dataset',
            'publication_year': 2018,
            'primary_location': {'landing_page_url': 'https://doi.org/10.18653/v1/d18-1259', 'source': {'display_name': 'EMNLP'}},
            'abstract_inverted_index': {'HotpotQA': [1], 'is': [0], 'a': [2], 'dataset': [3]},
        }]})

    items = search_external('HotpotQA exact match', transport=httpx.MockTransport(handler))
    assert len(items) == 1
    assert items[0].text.endswith('is HotpotQA a dataset')
    chunks = transient_chunks('paper-1', items)
    assert chunks[0].source_type == 'external'
    assert chunks[0].source_url == 'https://doi.org/10.18653/v1/d18-1259'
