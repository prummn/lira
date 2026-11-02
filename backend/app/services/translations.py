"""Shared exact-source, exact-configuration translation cache."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import re
import threading
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from ..models import Translation
from ..providers.base import ProviderError


INVALID_TRANSLATION = '模型未返回有效译文，请重新翻译。原文已保留。'
_MISSING_SOURCE = re.compile(
    r'(?:(?:抱歉|对不起)[，,：:\s]*)?(?:'
    r'(?:未提供|没有提供|尚未提供|未收到|没有收到|缺少)(?:待翻译的?|需要翻译的?|要翻译的?)?(?:原文|文本|内容)'
    r'|(?:请提供|请先提供|请发送)(?:待翻译的?|需要翻译的?|要翻译的?)?(?:原文|文本|内容)'
    r'|no (?:source |input )?(?:text|content|paragraph)(?: (?:was |has been )?provided)?'
    r'|please provide (?:the )?(?:source |input )?(?:text|content|paragraph)(?: to translate)?'
    r')[。.!！\s]*', re.I)


def translation_error(source, text):
    """Reject empty or standalone missing-input replies, not prose mentioning them."""
    if not isinstance(text, str) or not text.strip():
        return INVALID_TRANSLATION
    # A source can itself discuss missing input. Avoid rejecting its literal
    # translation; this is a narrow failure check, not a semantic quality score.
    source_discusses_missing_input = bool(re.search(
        r'(?:no|missing|not provided|not received|absent|please provide).{0,35}(?:text|content|source|input)'
        r'|(?:text|content|source|input).{0,35}(?:not provided|not received|missing|absent)'
        r'|(?:未提供|未收到|缺少).{0,12}(?:原文|文本|内容)', source, re.I))
    if _MISSING_SOURCE.fullmatch(text.strip()) and not source_discusses_missing_input:
        return INVALID_TRANSLATION
    return None

class PaperTranslationLock:
    """Shared stable reads; exclusive boundary changes; exact-source deduplication."""
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.readers, self.writer, self.depth, self.writers_waiting = 0, None, 0, 0
        self.sources = {}

    def __enter__(self):
        from ..providers.priority import check_background
        owner = threading.get_ident()
        with self.condition:
            self.writers_waiting += 1
            try:
                while self.writer not in (None, owner) or self.readers:
                    check_background()
                    self.condition.wait(.2)
                self.writer, self.depth = owner, self.depth + 1
            finally:
                self.writers_waiting -= 1
        return self

    def __exit__(self, *args):
        with self.condition:
            self.depth -= 1
            if not self.depth:
                self.writer = None
            self.condition.notify_all()

    @contextmanager
    def translation(self, source):
        from ..providers.priority import check_background
        key = hashlib.sha256(source.encode()).hexdigest()
        with self.condition:
            while self.writer is not None or self.writers_waiting:
                check_background()
                self.condition.wait(.2)
            self.readers += 1
            entry = self.sources.setdefault(key, [threading.RLock(), 0])
            entry[1] += 1
        acquired = False
        try:
            while not acquired:
                check_background()
                acquired = entry[0].acquire(timeout=.2)
            yield
        finally:
            if acquired:
                entry[0].release()
            with self.condition:
                self.readers -= 1
                entry[1] -= 1
                if not entry[1]:
                    self.sources.pop(key, None)
                self.condition.notify_all()


LOCKS = tuple(PaperTranslationLock() for _ in range(64))


def source_lock(database_url, paper_id, source):
    # A boundary review takes exclusive access. Stable source requests use
    # .translation(source), sharing paper access and deduplicating exact sources.
    # Database URLs can be percent encoded differently between request and
    # worker sessions; the process owns one worker per app, so paper identity
    # alone is the canonical lock key and cannot diverge across those forms.
    return LOCKS[hash(paper_id) % len(LOCKS)]


def identity(provider):
    return provider.name, provider.translation_configuration_version, provider.translation_prompt_version


def find_cached(session, paper_id, chunk, provider=None, *, expected=None):
    statement = select(Translation).where(Translation.paper_id == paper_id, Translation.chunk_id == chunk.id,
        Translation.source_hash == hashlib.sha256(chunk.content.encode()).hexdigest(), Translation.source_text == chunk.content)
    if expected is None and provider is not None and provider.translation_available:
        expected = identity(provider)
    if expected is not None:
        statement = statement.where(Translation.provider == expected[0], Translation.config_version == expected[1],
                                    Translation.prompt_version == expected[2])
    rows = session.scalars(statement.order_by(Translation.created_at.desc(), Translation.id)
        .execution_options(populate_existing=True))
    return next((row for row in rows if not translation_error(row.source_text, row.text)), None)


def save_translation(session, paper_id, chunk, provider, text, *, expected=None):
    error = translation_error(chunk.content, text)
    if error:
        raise ProviderError(error, code='invalid_translation')
    name, config, prompt = expected or identity(provider)
    values = dict(id='translation-'+uuid.uuid4().hex[:20], paper_id=paper_id, chunk_id=chunk.id,
        source_text=chunk.content, source_hash=hashlib.sha256(chunk.content.encode()).hexdigest(), text=text,
        provider=name, mode=provider.mode, config_version=config, prompt_version=prompt,
        model_version=provider.response_model or provider.model, created_at=datetime.now(timezone.utc))
    session.execute(insert(Translation).values(**values).on_conflict_do_update(
        index_elements=['chunk_id','source_hash','provider','config_version','prompt_version'],
        set_={k:v for k,v in values.items() if k != 'id'}))
    session.flush()
    return find_cached(session, paper_id, chunk, expected=(name, config, prompt))
