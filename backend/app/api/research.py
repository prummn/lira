from fastapi import APIRouter, Request, HTTPException
from ..research_schemas import ResearchSettings, QuotaPolicyUpdate, ScopeUpdate, ReadingPresence, FindingAction

router = APIRouter(prefix='/research', tags=['research'])


@router.get('/status')
def status(request: Request):
    return request.app.state.research_worker.status()


@router.get('/quota')
def quota(request: Request):
    return request.app.state.research_worker.refresh_quota()


@router.put('/settings')
def settings(payload: ResearchSettings, request: Request):
    profiles = request.app.state.model_profiles.public()['profiles']
    if payload.profile_id and not any(p['id'] == payload.profile_id and p.get('provider_kind') == 'codex' for p in profiles):
        raise HTTPException(422, '后台研究请选择一份官方 Codex 连接')
    if payload.enabled and not payload.profile_id:
        raise HTTPException(422, '请先选择后台使用的官方连接')
    return request.app.state.research_worker.settings(payload).model_dump()


@router.patch('/quota-policy')
def quota_policy(payload: QuotaPolicyUpdate, request: Request):
    return request.app.state.research_worker.quota_policy(payload).model_dump()


@router.post('/presence')
def presence(payload: ReadingPresence, request: Request):
    request.app.state.model_profiles.priority.presence(payload.client_id, payload.reading)
    return {'ok': True}


@router.get('/collections/{collection_id}')
def collection(collection_id: str, request: Request, revision_id: str | None = None):
    return request.app.state.research_worker.collection(collection_id, revision_id)


@router.put('/collections/{collection_id}/scope')
def scope(collection_id: str, payload: ScopeUpdate, request: Request):
    return request.app.state.research_worker.scope(collection_id, payload)


@router.post('/collections/{collection_id}/update')
def update(collection_id: str, request: Request, kind: str = 'essay'):
    return request.app.state.research_worker.enqueue(collection_id, kind=kind)


@router.get('/collections/{collection_id}/findings')
def findings(collection_id: str, request: Request):
    return request.app.state.research_worker.findings(collection_id)


@router.post('/collections/{collection_id}/agenda')
def plan_research(collection_id: str, request: Request):
    return request.app.state.research_worker.plan_research(collection_id)


@router.post('/collections/{collection_id}/reading')
def reading_questions(collection_id: str, request: Request):
    return request.app.state.research_worker.reading_questions(collection_id)


@router.patch('/findings/{finding_id}')
def finding_action(finding_id: str, payload: FindingAction, request: Request):
    return request.app.state.research_worker.finding_action(finding_id, payload.action)


@router.get('/findings/{finding_id}/history')
def finding_history(finding_id: str, request: Request):
    return request.app.state.research_worker.finding_history(finding_id)


@router.post('/tasks/{task_id}/{action}')
def task_action(task_id: str, action: str, request: Request):
    if action not in ('cancel', 'retry'):
        raise HTTPException(404, '操作不存在')
    return request.app.state.research_worker.action(task_id, action)
