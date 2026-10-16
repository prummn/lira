"""Credential-free dictionary lookup used by the reader's word quick-translate."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas import QuickDefinitionRead, QuickTranslationRequest, QuickTranslationResponse
from ..services.dictionary import DictionaryUnavailable, lookup

router = APIRouter()


@router.post('/dictionary/lookup', response_model=QuickTranslationResponse)
def dictionary_lookup(payload: QuickTranslationRequest) -> QuickTranslationResponse:
    try:
        result = lookup(payload.text)
    except DictionaryUnavailable:
        raise HTTPException(503, '词典服务暂不可用，请稍后重试或展开段落翻译') from None
    return QuickTranslationResponse(
        query=result.query,
        normalized_query=result.normalized_query,
        translation=result.translation,
        phonetic=result.phonetic,
        definitions=[QuickDefinitionRead(part_of_speech=item.part_of_speech, text=item.text, example=item.example) for item in result.definitions],
        source=result.source,
        cached=result.cached,
    )
