"""Provider selection: no key means deterministic local extraction and no network."""
from __future__ import annotations
import os
from .base import ModelProvider, MetadataProvider, EmbeddingProvider
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider

__all__ = ['ModelProvider','MetadataProvider','EmbeddingProvider','MockProvider','OpenAICompatibleProvider','get_model_provider']

def get_model_provider() -> ModelProvider:
    key = (os.getenv('PAPER_READER_MODEL_API_KEY') or os.getenv('OPENAI_API_KEY') or '').strip()
    if not key:
        return MockProvider()
    base_url = os.getenv('PAPER_READER_MODEL_BASE_URL','https://api.openai.com/v1').strip()
    model = os.getenv('PAPER_READER_MODEL_NAME','gpt-4.1-mini').strip()
    try:
        return OpenAICompatibleProvider(api_key=key,base_url=base_url,model=model)
    except (ValueError,TypeError):
        local = MockProvider()
        local.configuration_error = '模型配置无效，请检查 base URL 与 model name'
        return local
