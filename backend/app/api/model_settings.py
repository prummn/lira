"""Named model connections. Credentials never appear in public responses."""
from fastapi import APIRouter, HTTPException, Request
from ..schemas import ModelProfileUpdate, ModelRoutingUpdate

router = APIRouter(prefix='/settings')


@router.get('/codex')
def codex_status(request: Request):
    return request.app.state.model_profiles.codex.status(refresh=True)


@router.get('/codex/models')
def codex_models(request: Request, refresh: bool = False):
    return request.app.state.model_profiles.codex.models(refresh=refresh)


@router.post('/codex/login')
def codex_login(request: Request):
    return request.app.state.model_profiles.codex.login()


@router.delete('/codex/login')
def codex_cancel_login(request: Request):
    return request.app.state.model_profiles.codex.cancel_login()


@router.post('/codex/logout')
def codex_logout(request: Request):
    return request.app.state.model_profiles.codex.logout()


def change(action):
    try:
        return action()
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except OSError:
        raise HTTPException(500, '本机模型配置文件无法保存；当前配置未改变') from None


@router.get('/profiles')
def profiles(request: Request):
    return change(request.app.state.model_profiles.public)


@router.post('/profiles', status_code=201)
def add_profile(payload: ModelProfileUpdate, request: Request):
    return change(lambda: request.app.state.model_profiles.save(payload))


@router.put('/profiles/{profile_id}')
def update_profile(profile_id: str, payload: ModelProfileUpdate, request: Request):
    return change(lambda: request.app.state.model_profiles.save(payload, profile_id))


@router.delete('/profiles/{profile_id}')
def delete_profile(profile_id: str, request: Request):
    return change(lambda: request.app.state.model_profiles.delete(profile_id))


@router.put('/routing')
def routing(payload: ModelRoutingUpdate, request: Request):
    return change(lambda: request.app.state.model_profiles.route(payload))
