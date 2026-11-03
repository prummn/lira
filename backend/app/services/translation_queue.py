"""Durable paragraph tasks executed by the existing research worker.

Transactions end before provider calls. Source refs and frozen provider identity
are revalidated on both sides of every generating call.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import re
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from ..models import IntelligenceTask, Paper, PaperChunk, Translation, TranslationItem, TranslationJob
from ..providers.base import ProviderError
from ..providers.priority import scheduled_work, check_background
from .reading_paragraphs import ordered_source_chunks, paragraphs_for
from .serialization import find_paper
from .translations import find_cached, identity, save_translation, source_lock, translation_error

ACTIVE = ('queued', 'running', 'paused')

_SECTION_PREFIX = re.compile(r'^(?:(?:[A-Za-z]|\d+(?:\.\d+)*)(?:[.)。：:\-])?\s+)+')
_ENGLISH_CUTOFF = re.compile(
    r'^(?:appendix|appendices|supplementary(?:\s+(?:material|materials|information))?|references|bibliography)(?:\b|\s|[:：.])',
    re.I,
)


def _cutoff_section(section):
    """Return whether a derived section label starts the skipped tail."""
    label = re.sub(r'\s+', ' ', str(section or '')).strip().strip('.:：')
    if not label:
        return False
    label = _SECTION_PREFIX.sub('', label).strip()
    if label.startswith(('附录', '参考文献', '参考资料', '参考书目')):
        return True
    return bool(_ENGLISH_CUTOFF.match(label))


def full_translation_scope(paragraphs, source_chunks=()):
    """Split full pretranslation at the first appendix/reference section.

    The parser supplies the section label as derived metadata. We only use
    that label here, never a phrase found inside paragraph content, so a
    sentence mentioning references cannot truncate the paper accidentally.
    Ordered source chunks retain headings that the reading view filters out.
    """
    cutoff = next((index for index, paragraph in enumerate(paragraphs)
                   if _cutoff_section(paragraph.get('section'))), len(paragraphs))
    chunks = list(source_chunks)
    source_cutoff = next((index for index, chunk in enumerate(chunks)
                          if _cutoff_section(chunk.section)), None)
    if source_cutoff is not None:
        positions = {chunk.id: index for index, chunk in enumerate(chunks)}
        cutoff = min(cutoff, next((index for index, paragraph in enumerate(paragraphs)
            if paragraph.get('refs') and min(positions.get(ref['chunk_id'], -1)
                for ref in paragraph['refs']) >= source_cutoff), len(paragraphs)))
    eligible = list(paragraphs[:cutoff])
    skipped = list(paragraphs[cutoff:])
    return eligible, skipped, 'appendix_or_references' if skipped else None


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _clear_cooldown(job):
    usage = json.loads(job.usage_json or '{}')
    usage.pop('next_retry_at',None)
    usage.pop('defer_count',None)
    job.usage_json = dumps(usage)


def _backoff(job,error):
    usage = json.loads(job.usage_json or '{}')
    failures = min(8,usage.get('defer_count',0)+1)
    minimum = 60 if error.code == 'rate_limit' else 5
    supplied = error.retry_after if isinstance(error.retry_after,(int,float)) else 0
    delay = max(supplied,min(300,minimum*2**(failures-1)))
    usage.update(next_retry_at=time.time()+delay,defer_count=failures)
    job.usage_json = dumps(usage)


def serialize(db, job, translations=None):
    if translations is None:
        ids = [i.translation_id for i in job.items if i.translation_id]
        translations = {t.id:t for t in db.scalars(select(Translation).where(Translation.id.in_(ids)))} if ids else {}
    items = []
    for item in job.items:
        row = translations.get(item.translation_id)
        result = {k:getattr(item,k) for k in ('id','paragraph_id','original_paragraph_id','status','phase','error','page')}
        result['aliases'] = json.loads(item.aliases_json)
        invalid = translation_error(row.source_text, row.text) if row is not None else None
        if invalid and item.status == 'completed':
            result.update(status='failed', phase=None, error=invalid)
        elif row is not None and not invalid:
            result['translation'] = {'text':row.text, 'model':row.model_version}
        items.append(result)
    status = job.status
    if status == 'completed' and any(item['status'] == 'failed' for item in items):
        status = 'failed'
    return {**{k:getattr(job,k) for k in ('id','paper_id','mode','status','reason','error','model_name',
        'scope_total','scope_skipped','scope_reason')},
        'status':status, 'items':items, 'completed':sum(i['status'] == 'completed' for i in items), 'total':len(items),
        'failed':sum(i['status'] == 'failed' for i in items),
        'created_at':job.created_at.replace(tzinfo=timezone.utc).isoformat(),
        'updated_at':job.updated_at.replace(tzinfo=timezone.utc).isoformat()}


def list_jobs(db, paper_id):
    if find_paper(db, paper_id) is None:
        raise HTTPException(404, '未找到这篇论文')
    active = list(db.scalars(select(TranslationJob).where(TranslationJob.paper_id == paper_id,
        TranslationJob.status.in_(ACTIVE)).options(selectinload(TranslationJob.items)).order_by(TranslationJob.created_at.desc())))
    recent = list(db.scalars(select(TranslationJob).where(TranslationJob.paper_id == paper_id,
        ~TranslationJob.status.in_(ACTIVE)).options(selectinload(TranslationJob.items))
        .order_by(TranslationJob.created_at.desc()).limit(10)))
    jobs = sorted([*active,*recent], key=lambda j:j.created_at, reverse=True)
    ids = [i.translation_id for j in jobs for i in j.items if i.translation_id]
    translations = {t.id:t for t in db.scalars(select(Translation).where(Translation.id.in_(ids)))} if ids else {}
    return {'jobs':[serialize(db,j,translations) for j in jobs]}


def monitor_jobs(db):
    """Global progress summaries; polling never loads source text or translations."""
    counts = select(TranslationItem.job_id.label('job_id'),
        func.count().label('total'),
        func.sum(case((TranslationItem.status == 'completed', 1), else_=0)).label('completed'),
        func.sum(case((TranslationItem.status == 'failed', 1), else_=0)).label('failed'),
        func.sum(case((TranslationItem.status == 'running', 1), else_=0)).label('running')
        ).group_by(TranslationItem.job_id).subquery()
    query = select(TranslationJob, Paper.title, counts.c.total, counts.c.completed, counts.c.failed,
        counts.c.running).join(Paper, Paper.id == TranslationJob.paper_id).outerjoin(counts, counts.c.job_id == TranslationJob.id)
    active = db.execute(query.where(TranslationJob.status.in_(ACTIVE)).order_by(TranslationJob.created_at.desc())).all()
    recent = db.execute(query.where(~TranslationJob.status.in_(ACTIVE))
        .order_by(TranslationJob.updated_at.desc()).limit(10)).all()
    return [{**{key:getattr(job,key) for key in
        ('id','paper_id','mode','status','reason','error','model_name','scope_total','scope_skipped','scope_reason')},
        'paper_title':title, 'total':total or 0, 'completed':completed or 0, 'failed':failed or 0,
        'in_flight':bool(running),
        'created_at':job.created_at.replace(tzinfo=timezone.utc).isoformat(),
        'updated_at':job.updated_at.replace(tzinfo=timezone.utc).isoformat()}
        for job,title,total,completed,failed,running in [*active,*recent]]


def _chunk(paper_id, paragraph):
    return PaperChunk(id=paragraph['refs'][0]['chunk_id'], paper_id=paper_id,
        content=paragraph['source_text'], section=paragraph.get('section'))


def _finish(job):
    job.updated_at = datetime.now(timezone.utc)
    if job.status in ('paused','cancelled'):
        return
    if any(i.status in ('queued','running') for i in job.items):
        job.status = 'queued'
    elif any(i.status == 'failed' for i in job.items):
        job.status = 'failed'
        job.error = '部分段落翻译失败，可重试失败项；已完成译文已保留'
    else:
        job.status = 'completed'
        job.error = None
    if job.status in ('completed','failed'):
        job.reason = None


def enqueue(worker, db, paper_id, mode, paragraph_ids, provider=None):
    with worker._mutation:
        paper = find_paper(db, paper_id)
        if paper is None:
            raise HTTPException(404, '未找到这篇论文')
        settings = worker.settings()
        scope_total = scope_skipped = 0
        scope_reason = None
        requested = mode == 'full' and provider is not None
        if mode == 'full' and not requested:
            profiles = worker.profiles.public()['profiles']
            if not any(p['id'] == settings.profile_id and p.get('provider_kind') == 'codex' for p in profiles):
                raise HTTPException(409, '请先在后台设置中选择官方 Codex 连接，再使用后台预译全文')
            provider = worker.profiles.subscription_provider(settings.profile_id)
            profile_id = settings.profile_id
        else:
            profile_id = getattr(provider, 'profile_id', None)
        if provider is None or not provider.translation_available:
            raise HTTPException(503, '翻译需要配置模型，原文和已有译文已保留')
        expected = identity(provider)
        paragraphs = paragraphs_for(paper)
        if mode == 'full':
            paragraphs, skipped, scope_reason = full_translation_scope(paragraphs,
                ordered_source_chunks(paper.chunks, paper.pdf_path))
            paragraphs = [p for p in paragraphs if p['kind'] in ('prose','caption')]
            scope_total = len(paragraphs)
            scope_skipped = sum(p.get('kind') in ('prose', 'caption') for p in skipped)
        else:
            if not paragraph_ids:
                raise HTTPException(422, '请先选择要翻译的段落')
            selected = set(paragraph_ids)
            paragraphs = [p for p in paragraphs if p['id'] in selected]
            if selected != {p['id'] for p in paragraphs}:
                raise HTTPException(409, '段落已更新，请重新选择原文')
        if not paragraphs:
            raise HTTPException(409, '没有可翻译的正文段落')
        wanted = {p['id'] for p in paragraphs}
        jobs = db.scalars(select(TranslationJob).where(TranslationJob.paper_id == paper_id,
            TranslationJob.status.in_(ACTIVE)).options(selectinload(TranslationJob.items))).all()
        # Reuse a covering active task; a selected click on a full task becomes
        # explicit priority without authorizing the rest of the paper as manual.
        extend = None
        for existing in jobs:
            if (existing.provider,existing.config_version,existing.prompt_version) != expected:
                continue
            # A reusable result/work identity does not replace authorization:
            # the job must retain the chosen connection and a new explicit
            # selection must not inherit another authorization's pause.
            if existing.profile_id != profile_id or mode == 'selected' and existing.status == 'paused':
                continue
            covered = {alias for i in existing.items for alias in [i.paragraph_id,*json.loads(i.aliases_json)]}
            if wanted <= covered and (mode == 'selected' or existing.mode == 'full'):
                if requested:
                    usage = json.loads(existing.usage_json or '{}')
                    usage['requested'] = True
                    existing.usage_json = dumps(usage)
                    if existing.reason in ('disabled', 'hourly_budget', 'daily_budget', 'profile_changed'):
                        existing.reason = None
                    db.commit()
                if mode == 'selected':
                    _clear_cooldown(existing)
                    for i in existing.items:
                        if wanted.intersection([i.paragraph_id,*json.loads(i.aliases_json)]):
                            i.priority = max(i.priority, 1)
                    db.commit()
                return serialize(db, existing)
            if mode == existing.mode == 'selected' and wanted.intersection(covered):
                extend = existing
        if extend:
            job = extend
            covered = {alias for i in job.items for alias in [i.paragraph_id,*json.loads(i.aliases_json)]}
            paragraphs = [p for p in paragraphs if p['id'] not in covered]
        else:
            job = TranslationJob(id='translation-job-'+uuid.uuid4().hex, paper_id=paper_id, mode=mode,
                profile_id=profile_id, provider=expected[0], config_version=expected[1], prompt_version=expected[2],
                model_name=provider.model, status='queued', reason='disabled' if mode == 'full' and not requested and not settings.enabled else None,
                usage_json=dumps({'requested': True}) if requested else '{}',
                scope_total=scope_total, scope_skipped=scope_skipped, scope_reason=scope_reason)
            db.add(job)
        start = len(job.items)
        for position,p in enumerate(paragraphs,start=start):
            cached = find_cached(db,paper_id,_chunk(paper_id,p),expected=expected)
            shared = next((i for other in jobs
                if (other.provider,other.config_version,other.prompt_version) == expected
                for i in other.items if i.status in ('queued','running') and
                i.source_text == p['source_text'] and _refs({'refs':json.loads(i.refs_json)}) == _refs(p)),None)
            job.items.append(TranslationItem(id='translation-item-'+uuid.uuid4().hex,
                paragraph_id=p['id'], original_paragraph_id=p['id'], aliases_json=dumps([p['id']]),
                work_item_id=(shared.work_item_id or shared.id) if shared else None,
                refs_json=dumps(p['refs']), source_text=p['source_text'], position=position,
                priority=1 if mode == 'selected' else 0, page=p.get('page') or (p['anchors'][0]['page'] if p['anchors'] else None),
                status='completed' if cached else 'queued', translation_id=cached.id if cached else None))
        _finish(job)
        db.commit()
        worker.wake()
        return serialize(db, job)


def action(worker, db, job_id, action):
    with worker._mutation:
        job = db.get(TranslationJob,job_id)
        if job is None:
            raise HTTPException(404, '翻译任务不存在')
        if action == 'retry':
            for item in job.items:
                row = db.get(Translation, item.translation_id) if item.translation_id else None
                if item.status == 'completed' and row is not None and translation_error(row.source_text, row.text):
                    item.status, item.error, item.translation_id = 'failed', translation_error(row.source_text, row.text), None
        if action == 'pause' and job.status in ('queued','running'):
            job.status,job.reason = 'paused','user_paused'
        elif action == 'resume' and job.status == 'paused':
            job.status,job.reason = 'queued',None
            _clear_cooldown(job)
            _finish(job)
        elif action == 'cancel':
            job.status,job.reason = 'cancelled',None
            for item in job.items:
                if item.status in ('queued','running'):
                    item.status,item.phase = 'cancelled',None
        elif action == 'retry' and any(i.status == 'failed' for i in job.items):
            job.status,job.reason,job.error = 'queued',None,None
            _clear_cooldown(job)
            for item in job.items:
                if item.status == 'failed':
                    item.status,item.phase,item.error,item.attempts = 'queued',None,None,0
        else:
            raise HTTPException(409, '当前任务状态不支持这项操作')
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        worker.wake()
        return serialize(db,job)


def prioritize(worker, db, paper_id, paragraph_id):
    with worker._mutation:
        jobs = db.scalars(select(TranslationJob).where(TranslationJob.paper_id == paper_id,
            TranslationJob.status.in_(ACTIVE)).order_by(TranslationJob.created_at.desc())).all()
        for job in sorted(jobs,key=lambda j:j.status == 'paused'):
            for item in job.items:
                if paragraph_id in [item.paragraph_id,*json.loads(item.aliases_json)]:
                    if item.status not in ('queued','running') or job.status == 'paused':
                        return serialize(db,job)
                    priority = int(time.time()*1000)
                    for related in _related(db,item):
                        related_job = db.get(TranslationJob,related.job_id)
                        if related_job.status in ('queued','running'):
                            related.priority = priority
                            _clear_cooldown(related_job)
                    db.commit()
                    worker._translation_urgent.add(item.work_item_id or item.id)
                    worker.profiles.priority.prefer(item.work_item_id or item.id)
                    worker.wake()
                    return serialize(db,job)
        raise HTTPException(404, '该段落没有正在排队的翻译任务')


def recover(db):
    # Repair legacy false successes once at startup, so the lightweight global
    # monitor can continue counting persisted states without loading text.
    affected = set()
    rows = db.execute(select(TranslationItem, Translation).join(Translation,
        TranslationItem.translation_id == Translation.id).where(TranslationItem.status == 'completed'))
    for item, row in rows:
        error = translation_error(row.source_text, row.text)
        if error:
            item.status, item.phase, item.error, item.translation_id = 'failed', None, error, None
            affected.add(item.job_id)
    for job_id in affected:
        _finish(db.get(TranslationJob, job_id))
    for job in db.scalars(select(TranslationJob).where(TranslationJob.status.in_(('queued','running','paused')))):
        if job.status == 'running':
            job.status,job.reason = 'queued','service_restarted'
        for item in job.items:
            if item.status == 'running':
                item.status,item.phase = 'queued',None
    db.commit()


def _refs(paragraph):
    return {(r['chunk_id'],r['start'],r['end']) for r in paragraph['refs']}


def _resolve(db, job, item):
    paper = find_paper(db,job.paper_id)
    if paper is None:
        raise ProviderError('论文已移除',409,code='source_changed')
    chunks = {c.id:c for c in paper.chunks}
    refs = json.loads(item.refs_json)
    try:
        source = '\n'.join(chunks[r['chunk_id']].content[r['start']:r['end']] for r in refs)
    except (KeyError,TypeError):
        raise ProviderError('论文原文已更新，请重新选择段落',409,code='source_changed') from None
    if source != item.source_text:
        raise ProviderError('论文原文已更新，请重新选择段落',409,code='source_changed')
    wanted = {(r['chunk_id'],r['start'],r['end']) for r in refs}
    paragraph = next((p for p in paragraphs_for(paper) if wanted <= _refs(p)),None)
    if paragraph is None:
        raise ProviderError('论文分段已更新，请重新选择段落',409,code='source_changed')
    return paragraph


def _map(db,job,paragraph,anchor):
    # A merge may join work owned by separate selected/full jobs. All pending
    # authorizations keep their own item while referring to one durable work ID.
    merged = _refs(paragraph)
    root_id = anchor.work_item_id or anchor.id
    jobs = db.scalars(select(TranslationJob).where(TranslationJob.paper_id == job.paper_id,
        TranslationJob.provider == job.provider,TranslationJob.config_version == job.config_version,
        TranslationJob.prompt_version == job.prompt_version,TranslationJob.status.in_(ACTIVE))).all()
    paper = find_paper(db,job.paper_id)
    chunks = {c.id:c for c in paper.chunks}
    for other in jobs:
      for item in other.items:
        refs = {(r['chunk_id'],r['start'],r['end']) for r in json.loads(item.refs_json)}
        snapshot = '\n'.join(chunks[r['chunk_id']].content[r['start']:r['end']] for r in json.loads(item.refs_json)
            if r['chunk_id'] in chunks)
        if refs <= merged and item.status in ('queued','running') and snapshot == item.source_text:
            aliases = set(json.loads(item.aliases_json)) | {item.paragraph_id,item.original_paragraph_id,paragraph['id']}
            item.aliases_json = dumps(sorted(aliases))
            item.paragraph_id,item.refs_json,item.source_text = paragraph['id'],dumps(paragraph['refs']),paragraph['source_text']
            item.work_item_id = root_id if item.id != root_id else None


def _related(db,item):
    root_id = item.work_item_id or item.id
    return db.scalars(select(TranslationItem).where(
        (TranslationItem.id == root_id) | (TranslationItem.work_item_id == root_id))).all()


def _complete(db,item,translation_id):
    for sibling in _related(db,item):
        related_job = db.get(TranslationJob,sibling.job_id)
        if related_job.status != 'cancelled' and sibling.status in ('queued','running'):
            sibling.translation_id,sibling.status,sibling.phase,sibling.error = translation_id,'completed',None,None
            _clear_cooldown(related_job)
            _finish(related_job)


class Deferred(Exception):
    def __init__(self,reason):
        self.reason=reason


def _provider(worker,job):
    if job.mode == 'full' and not json.loads(job.usage_json or '{}').get('requested'):
        provider = worker.profiles.subscription_provider(job.profile_id)
    else:
        provider = worker.profiles.provider(job.profile_id) if job.profile_id else worker.profiles.selected()
    if provider is None or not provider.translation_available:
        raise Deferred('profile_required')
    if identity(provider) != (job.provider,job.config_version,job.prompt_version):
        raise ProviderError('模型或翻译提示词已更新，请重新提交这些段落',409,code='configuration_changed')
    return provider


def _gate(worker,job_id,item_id,manual, *, reserved=False):
    check_background()
    with worker.database.sessions() as db:
        job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
        if job is None or item is None or job.status in ('paused','cancelled'):
            raise Deferred('user_paused' if job and job.status == 'paused' else 'cancelled')
        manual = manual or job.mode == 'selected' or item.priority > 0
        requested = bool(json.loads(job.usage_json or '{}').get('requested'))
        # A foreground request has priority at shared provider admission. It
        # does not block pretranslation from using the other account positions.
        # A selection can arrive while a quota/account RPC is preparing this
        # call, before its cancellation context exists. Recheck durable order.
        ahead = db.execute(select(TranslationJob.usage_json, TranslationItem.id, TranslationItem.work_item_id)
            .join(TranslationItem,TranslationJob.id == TranslationItem.job_id)
            .where(TranslationJob.status.in_(('queued','running')),
                TranslationJob.profile_id == job.profile_id,
                TranslationItem.status == 'queued',TranslationItem.priority > item.priority)).all()
        if any((root or key) not in worker._translation_claims and
               json.loads(usage).get('next_retry_at',0) <= time.time() for usage,key,root in ahead):
            raise Deferred('foreground')
        _resolve(db,job,item)
    if not manual and not requested:
        settings = worker.settings()
        if not settings.enabled:
            raise Deferred('disabled')
        if settings.profile_id != job.profile_id:
            raise Deferred('profile_changed')
    if not manual and (requested or reserved):
        provider = _provider(worker, job)
        if provider.name == 'CodexSubscriptionProvider':
            from .research_policy import quota_decision
            state = worker.profiles.codex.status()
            worker._capture_quota(state)
            if not state.get('authenticated') or state.get('error_code'):
                raise Deferred('account_unavailable')
            if worker._quota_error_code and not worker._quota_using_recent:
                raise Deferred('quota_unavailable')
            settings = worker.settings()
            decision = quota_decision(worker._quota, age=max(0,time.time()-worker._quota_at),
                running=True, stop_remaining=settings.stop_remaining, long_reserve=settings.long_reserve)
            if not decision['allowed']:
                raise Deferred(decision['reason'])
    elif not manual:
        settings = worker.settings()
        if settings.profile_id != job.profile_id:
            raise Deferred('profile_changed')
        if not worker._eligible(settings,running=job.calls > 0,allow_reading=True):
            raise Deferred(worker._reason)
    check_background()


def _record(worker,job_id,item_id,phase):
    with worker._mutation,worker.database.sessions() as db:
        job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
        if job.status not in ('queued','running') or item.status not in ('queued','running'):
            raise Deferred('user_paused' if job.status == 'paused' else 'cancelled')
        manual = job.mode == 'selected' or item.priority > 0
        if not manual and not json.loads(job.usage_json or '{}').get('requested'):
            # Claiming and quota RPCs can overlap. Reserve the hourly call
            # budget atomically just before recording an optional call.
            if not worker._remaining_calls(worker.settings()):
                raise Deferred('hourly_budget')
        usage = json.loads(job.usage_json)
        usage.setdefault('call_times',[]).append(time.time())
        usage.setdefault('events',[]).append({'phase':phase,'at':time.time()})
        job.usage_json,job.calls = dumps(usage),job.calls+1
        for sibling in _related(db,item):
            related_job = db.get(TranslationJob,sibling.job_id)
            if related_job.status in ('queued','running') and sibling.status in ('queued','running'):
                related_job.status,related_job.reason = 'running',None
                sibling.status,sibling.phase,sibling.error = 'running',phase,None
        db.commit()
        worker._reason = 'translation_working'


def _choose_next(worker, *, allow_idle=True, blocked_jobs=()):
    """Select metadata cheaply; resolve only candidates that can claim a slot."""
    with worker.database.sessions() as db:
        candidates = db.execute(select(TranslationJob.id, TranslationItem.id,
            TranslationItem.priority, TranslationJob.mode, TranslationItem.work_item_id)
            .join(TranslationItem, TranslationItem.job_id == TranslationJob.id)
            .where(TranslationJob.status.in_(('queued', 'running')), TranslationItem.status == 'queued')
            .order_by(TranslationItem.priority.desc(), case((TranslationJob.mode == 'selected', 0), else_=1),
                TranslationJob.created_at, TranslationItem.position)).all()
        if not candidates:
            return None
        jobs = {job.id: job for job in db.scalars(select(TranslationJob).where(
            TranslationJob.id.in_({candidate[0] for candidate in candidates})))}
        settings, eligible, counts, reviewing_papers = worker.settings(), [], {}, set()
        for paper_id, reviewing in worker._translation_claims.values():
            counts[paper_id] = counts.get(paper_id, 0) + 1
            if reviewing:
                reviewing_papers.add(paper_id)
        for candidate in candidates:
            job = jobs[candidate[0]]
            if candidate[0] in blocked_jobs or (candidate[4] or candidate[1]) in worker._translation_claims:
                continue
            if job.paper_id in reviewing_papers:
                continue
            usage = json.loads(job.usage_json or '{}')
            if usage.get('next_retry_at', 0) > time.time():
                continue
            if candidate[3] == 'full' and candidate[2] <= 0 and not usage.get('requested'):
                if job.profile_id != settings.profile_id:
                    job.reason = 'profile_changed'
                    continue
                if not allow_idle:
                    continue
            eligible.append(candidate)
        db.commit()
        # Equal-priority papers share capacity; urgent selections keep precedence.
        eligible.sort(key=lambda candidate: (-candidate[2], candidate[3] != 'selected',
            counts.get(jobs[candidate[0]].paper_id, 0)))
        for candidate in eligible:
            job = jobs[candidate[0]]
            if counts.get(job.paper_id):
                try:
                    item = db.get(TranslationItem, candidate[1])
                    if _resolve(db, job, item).get('review_needed'):
                        continue
                except (ProviderError, HTTPException):
                    pass  # The execution path records permanent source errors.
            return tuple(candidate[:4])
    return None


@contextmanager
def claim_next(worker, *, allow_idle=True):
    blocked_jobs, root, chosen = set(), None, None
    try:
        while True:
            with worker._mutation:
                # A failed final commit must not strand an item until restart.
                # Only roots absent from the live claim map can be recovered.
                with worker.database.sessions() as db:
                    abandoned = db.scalars(select(TranslationItem).where(TranslationItem.status == 'running')).all()
                    affected = set()
                    for item in abandoned:
                        if (item.work_item_id or item.id) not in worker._translation_claims:
                            item.status, item.phase = 'queued', None
                            affected.add(item.job_id)
                    for job_id in affected:
                        _finish(db.get(TranslationJob, job_id))
                    if affected:
                        db.commit()
                chosen = _choose_next(worker, allow_idle=allow_idle, blocked_jobs=blocked_jobs)
                if chosen is None:
                    break
                with worker.database.sessions() as db:
                    job, item = db.get(TranslationJob, chosen[0]), db.get(TranslationItem, chosen[1])
                    root = item.work_item_id or item.id
                    try:
                        reviewing = bool(_resolve(db, job, item).get('review_needed'))
                    except (ProviderError, HTTPException):
                        reviewing = False
                    worker._translation_claims[root] = (job.paper_id, reviewing)
            # Admission may perform account RPCs. Never hold the mutation lock
            # here: the reader must be able to prioritize, pause or cancel.
            try:
                _gate(worker, chosen[0], chosen[1], chosen[3] == 'selected' or chosen[2] > 0)
                break
            except Deferred as error:
                with worker._mutation, worker.database.sessions() as db:
                    worker._translation_claims.pop(root, None)
                    root = None
                    blocked_jobs.add(chosen[0])
                    job = db.get(TranslationJob, chosen[0])
                    if job and job.status in ('queued', 'running'):
                        job.reason = error.reason
                        db.commit()
                    worker._reason = error.reason
            except (ProviderError, HTTPException):
                break  # Permanent errors are recorded by the normal execution path.
        yield chosen
    finally:
        if root is not None:
            with worker._mutation:
                worker._translation_claims.pop(root, None)
                worker._translation_urgent.discard(root)


def process_next(worker, *, allow_idle=True):
    with claim_next(worker, allow_idle=allow_idle) as chosen:
        if chosen is None:
            return False, False
        try:
            return _process_claimed(worker, chosen)
        except Exception:
            # Do not expose arbitrary exception text (it may contain prompts or
            # credentials). Bound unexpected retries; retain completed siblings.
            with worker._mutation, worker.database.sessions() as db:
                item = db.get(TranslationItem, chosen[1])
                if item is not None:
                    affected = set()
                    for sibling in _related(db, item):
                        if sibling.status not in ('queued', 'running'):
                            continue
                        sibling.attempts += 1
                        sibling.status = 'failed' if sibling.attempts >= 2 else 'queued'
                        sibling.phase, sibling.error = None, '翻译步骤中断，完成的译文已保留，可重试'
                        affected.add(sibling.job_id)
                    for job_id in affected:
                        job = db.get(TranslationJob, job_id)
                        _backoff(job, ProviderError('temporary service error', code='internal_retry'))
                        _finish(job)
                    db.commit()
            worker._reason = 'service_error'
            return True, False


def _process_claimed(worker, chosen):
    job_id,item_id,priority,mode = chosen
    manual = mode == 'selected' or priority > 0
    worker._translation_manual = manual
    did_work=False
    try:
        _gate(worker,job_id,item_id,manual)
        with worker.database.sessions() as db:
            job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
            provider = _provider(worker,job)
            paragraph = _resolve(db,job,item)
            source = paragraph['source_text']
            work_id = item.work_item_id or item.id
        lock = source_lock(worker.database.url,job.paper_id,source)
        access = lock if paragraph.get('review_needed') else lock.translation(source)
        with access,scheduled_work(lambda: 1 if manual or work_id in worker._translation_urgent else 2,
                admission=lambda: _gate(worker, job_id, item_id, manual, reserved=True)):
            _gate(worker,job_id,item_id,manual)
            with worker.database.sessions() as db:
                current = _resolve(db, db.get(TranslationJob, job_id), db.get(TranslationItem, item_id))
                if current['source_text'] != source:
                    raise Deferred('structure_updated')
            if paragraph.get('review_needed'):
                from .reading_boundaries import review
                def before_call():
                    _gate(worker,job_id,item_id,manual)
                    with worker.database.sessions() as db:
                        _provider(worker,db.get(TranslationJob,job_id))
                    _record(worker,job_id,item_id,'checking')
                reviewed = review(worker.database,job.paper_id,paragraph['id'],provider,before_call=before_call,max_calls=1)
                did_work = True
                with worker._mutation,worker.database.sessions() as db:
                    job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
                    paragraph = _resolve(db,job,item)
                    _map(db,job,paragraph,item)
                    if job.status in ('paused','cancelled'):
                        db.commit()
                        return True,True
                    if reviewed['review']['incomplete']:
                        item.status,item.phase = 'queued','checking'
                        _finish(job)
                        db.commit()
                        return True,True
                    db.commit()
            with worker._mutation,worker.database.sessions() as db:
                job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
                paragraph = _resolve(db,job,item)
                _map(db,job,paragraph,item)
                chunk = _chunk(job.paper_id,paragraph)
                expected = (job.provider,job.config_version,job.prompt_version)
                cached = find_cached(db,job.paper_id,chunk,expected=expected)
                cached_id = cached.id if cached else None
                db.commit()
            if cached_id is None:
                _gate(worker,job_id,item_id,manual)
                with worker.database.sessions() as db:
                    _provider(worker,db.get(TranslationJob,job_id))
                _record(worker,job_id,item_id,'translating')
                worker._reason = 'translation_working'
                text = provider.translate(chunk)
                did_work=True
            with worker._mutation,worker.database.sessions() as db:
                job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
                _provider(worker,job)
                current = _resolve(db,job,item)
                if current['source_text'] != chunk.content:
                    raise ProviderError('翻译期间段落已更新，请重试',409,code='source_changed')
                if cached_id is None:
                    cached_id = save_translation(db,job.paper_id,chunk,provider,text,expected=expected).id
                _complete(db,item,cached_id)
                _finish(job)
                db.commit()
                return True,True
    except (Deferred,ProviderError,HTTPException) as error:
        code = error.reason if isinstance(error,Deferred) else getattr(error,'code',None)
        transient = isinstance(error,Deferred) or code in ('background_preempted','local_capacity','rate_limit','subscription_required') or isinstance(error,ProviderError) and error.retryable
        with worker._mutation,worker.database.sessions() as db:
            job,item = db.get(TranslationJob,job_id),db.get(TranslationItem,item_id)
            if job and item:
                if transient:
                    deferred_jobs = set()
                    for sibling in _related(db,item):
                        related_job = db.get(TranslationJob,sibling.job_id)
                        if sibling.status == 'running':
                            sibling.status,sibling.phase = 'queued',None
                        if related_job.status not in ('paused','cancelled'):
                            related_job.status,related_job.reason = 'queued',('foreground' if code == 'background_preempted' else
                                'profile_required' if code == 'subscription_required' else code)
                            if related_job.id not in deferred_jobs and isinstance(error,ProviderError) and (error.retryable or code in ('rate_limit','local_capacity')):
                                _backoff(related_job,error)
                                deferred_jobs.add(related_job.id)
                    worker._reason = job.reason or code
                elif item.status not in ('cancelled','completed'):
                    permanent = code in ('source_changed','configuration_changed') or isinstance(error,HTTPException) and error.status_code == 409
                    related = _related(db,item)
                    attempts = max(i.attempts for i in related)+1
                    for sibling in related:
                        related_job = db.get(TranslationJob,sibling.job_id)
                        if sibling.status in ('cancelled','completed'):
                            continue
                        sibling.attempts = attempts
                        sibling.status = 'failed' if permanent or attempts >= 2 else 'queued'
                        sibling.error = str(error.detail) if isinstance(error,HTTPException) else str(error)
                        sibling.phase = None
                        related_job.reason = None
                        _finish(related_job)
                db.commit()
        return True,did_work or not transient
