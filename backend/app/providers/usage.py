"""Only numeric, documented token fields are retained from upstream usage."""
from __future__ import annotations
import math

TOKEN_FIELDS = {'input_tokens', 'output_tokens', 'total_tokens', 'prompt_tokens', 'completion_tokens', 'cached_tokens', 'reasoning_tokens', 'audio_tokens', 'accepted_prediction_tokens', 'rejected_prediction_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'}
DETAIL_FIELDS = {'input_tokens_details', 'output_tokens_details', 'prompt_tokens_details', 'completion_tokens_details'}


def sanitize_usage(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key, value in raw.items():
        if key in TOKEN_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            result[key] = value
        elif key in DETAIL_FIELDS and isinstance(value, dict):
            result[key] = sanitize_usage(value)
    return result
