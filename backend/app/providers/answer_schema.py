"""The answer itself is structured; it is never JSON encoded inside a string."""
ANSWER_SCHEMA = {
    'type': 'object',
    'properties': {
        'answer': {'type': 'string'},
        'facts': {'type': 'array', 'items': {'type': 'string'}},
        'inferences': {'type': 'array', 'items': {'type': 'string'}},
        'unknowns': {'type': 'array', 'items': {'type': 'string'}},
        'needs_more_context': {'type': 'boolean'},
        'citations': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'chunk_id': {'type': 'string'}, 'source_text': {'type': 'string'}},
            'required': ['chunk_id', 'source_text'], 'additionalProperties': False,
        }},
        'insufficient_evidence': {'type': 'boolean'},
    },
    'required': ['answer', 'facts', 'inferences', 'unknowns', 'needs_more_context',
                 'citations', 'insufficient_evidence'],
    'additionalProperties': False,
}
