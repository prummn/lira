import json

import pytest
from pydantic import ValidationError

from app.models import KnowledgeCandidate
from app.schemas import KnowledgeCandidateRead


def test_candidate_status_contract_rejects_unknown_status():
    with pytest.raises(ValidationError):
        KnowledgeCandidateRead(
            id='x', paper_id='p', entity_type='dataset', name='X', normalized_name='x',
            status='published', evidence=[{'chunk_id': 'c', 'quote': 'X'}], confidence=.5,
        )


def test_candidate_model_has_evidence_and_candidate_defaults():
    candidate = KnowledgeCandidate(
        id='kc-test', paper_id='p', entity_type='dataset', name='HotpotQA',
        normalized_name='hotpotqa', evidence_json=json.dumps([{'chunk_id': 'c', 'quote': 'HotpotQA'}]),
    )
    assert candidate.status in {None, 'candidate'}
    assert json.loads(candidate.evidence_json)[0]['chunk_id'] == 'c'
