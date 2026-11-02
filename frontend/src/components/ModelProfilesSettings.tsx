import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Check, LoaderCircle, Plus, Trash2, X } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { ModelProfile, ModelProfileInput, ModelProfiles, ModelRouting } from '../types'
import { ErrorBanner } from './Shared'
import { CodexAccountSettings } from './CodexAccountSettings'
import { CodexModelPicker } from './CodexModelPicker'

const empty = ():ModelProfileInput => ({provider_kind:'api',name:'',base_url:'https://spacetimeai.cc/v1',model:'gpt-6.1-sol',
  api_key:null,wire_api:'responses',reasoning_effort:'xhigh',timeout:600,max_concurrency:1,
  completion_parameter:'max_completion_tokens',json_mode:'json_object',test_connection:true})

export function ModelProfilesSettings({onChange}:{onChange:()=>void}) {
  const {t}=useUi()
  const [state,setState]=useState<ModelProfiles|null>(null)
  const [selected,setSelected]=useState<string|null>(null)
  const [draft,setDraft]=useState(empty)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState('')
  const [routing,setRouting]=useState(false)
  const routingRevision=useRef(0)
  const [notice,setNotice]=useState('')
  const [deleting,setDeleting]=useState<string|null>(null)
  const [codexReady,setCodexReady]=useState(false)
  const [codexModelReady,setCodexModelReady]=useState(false)
  const [codexCatalogRevision,setCodexCatalogRevision]=useState(0)
  const isCodex=draft.provider_kind==='codex'
  const editing=state?.profiles.find(p=>p.id===selected)
  const edit=(profile?:ModelProfile)=>{
    setSelected(profile?.id??null);setDraft(profile?{...profile,api_key:null,test_connection:true}:empty())
    setNotice('');setError('');setDeleting(null)
  }
  useEffect(()=>{
    let alive=true
    api.modelProfiles().then(next=>{
      if(!alive)return
      setState(next)
      const profile=next.profiles.find(p=>p.id===next.active_id)??next.profiles[0]
      if(profile){setSelected(profile.id);setDraft({...profile,api_key:null,test_connection:true})}
    }).catch(e=>{if(alive)setError(errorMessage(e))})
    return()=>{alive=false}
  },[])
  const field=<K extends keyof ModelProfileInput>(key:K,value:ModelProfileInput[K])=>setDraft(d=>({...d,[key]:value}))
  const act=async(kind:string,work:()=>Promise<void>)=>{
    if(busy)return
    setBusy(kind);setError('');setNotice('')
    try{await work();onChange()}catch(e){setError(errorMessage(e))}finally{setBusy('')}
  }
  const route=(patch:Partial<ModelRouting>)=>{
    if(!state||routing)return
    const next={active_id:state.active_id,fallback_ids:state.fallback_ids,auto_fallback:state.auto_fallback,...patch}
    const previous={active_id:state.active_id,fallback_ids:state.fallback_ids,auto_fallback:state.auto_fallback}
    routingRevision.current++
    if(!next.fallback_ids.length)next.auto_fallback=false
    setState({...state,...next})
    setRouting(true);setError('')
    void api.modelRouting(next).then(saved=>{routingRevision.current++;setState(current=>current?{...current,active_id:saved.active_id,fallback_ids:saved.fallback_ids,auto_fallback:saved.auto_fallback}:saved);setNotice(t('modelRouteSaved'));onChange()})
      .catch(error=>{routingRevision.current++;setState(current=>current?{...current,...previous}:state);setError(errorMessage(error))}).finally(()=>setRouting(false))
  }
  const save=(testConnection:boolean)=>void act('save',async()=>{
    const revision=routingRevision.current
    const saved=await api.saveModelProfile(selected,{...draft,api_key:draft.api_key?.trim()||null,test_connection:testConnection})
    const next=await api.modelProfiles()
    setState(current=>current&&revision!==routingRevision.current?{...next,active_id:current.active_id,fallback_ids:current.fallback_ids,auto_fallback:current.auto_fallback}:next)
    setSelected(saved.id);setDraft({...saved,api_key:null,test_connection:true})
    setNotice(t(testConnection?'modelTestSaved':'modelSaveSuccess'))
  })
  return <section className="settings-section model-profiles-section" aria-busy={!!busy||routing}>
    <div className="model-section-heading"><div><h2>{t('modelConnections')}</h2><p>{t('modelConnectionsHint')}</p></div><button className="btn secondary" disabled={!!busy||!state} onClick={()=>edit()}><Plus size={14}/>{t('modelAddConnection')}</button></div>
    {(error||state?.configuration_error)&&<ErrorBanner error={error||state?.configuration_error||''}/>}
    {!state&&!error&&<p role="status"><LoaderCircle size={14} className="spin"/> {t('loading')}</p>}
    {state&&<>
      <div className="settings-card model-profile-list">
        {state.profiles.length===0?<p className="model-empty">{t('modelNoConnections')}</p>:state.profiles.map(profile=>{
          const active=profile.id===state.active_id, backup=state.fallback_ids.indexOf(profile.id)
          return <div className={`model-profile-row ${active?'is-active':''} ${profile.id===selected?'is-editing':''}`} key={profile.id}>
            <div className="model-profile-info"><div><strong>{profile.name}</strong>{active&&<span className="model-profile-badge"><span className="model-status-dot"/>{t('modelInUse')}</span>}{backup>=0&&<span className="model-profile-backup">{t('modelBackup')} {backup+1}</span>}</div><span>{profile.model} <span aria-hidden="true">·</span> {profile.provider_kind==='codex'?t('codexSubscription'):new URL(profile.base_url).host}</span></div>
            <div className="model-profile-actions">
              {!active&&<button className="btn secondary" disabled={routing||busy==='delete'} onClick={()=>route({active_id:profile.id,fallback_ids:state.fallback_ids.filter(id=>id!==profile.id)})}>{t('modelActivate')}</button>}
              <button className="text-btn" disabled={!!busy} onClick={()=>edit(profile)}>{t('edit')}</button>
              {!active&&<button className="text-btn" disabled={routing||busy==='delete'} onClick={()=>route({fallback_ids:backup<0?[...state.fallback_ids,profile.id]:state.fallback_ids.filter(id=>id!==profile.id)})}>{t(backup<0?'modelAddBackup':'modelRemoveBackup')}</button>}
              {backup>0&&<button className="icon-btn" title={t('modelMoveBackup')} aria-label={t('modelMoveBackup')} disabled={routing||busy==='delete'} onClick={()=>{const ids=[...state.fallback_ids];[ids[backup-1],ids[backup]]=[ids[backup],ids[backup-1]];route({fallback_ids:ids})}}><ArrowUp size={14}/></button>}
              <button className="icon-btn" title={`${t('delete')} ${profile.name}`} aria-label={`${t('delete')} ${profile.name}`} disabled={!!busy||routing} onClick={()=>setDeleting(profile.id)}><Trash2 size={14}/></button>
            </div>
            {deleting===profile.id&&<div className="model-delete-confirm"><span>{t('modelDeleteConfirm')}</span><button className="btn secondary" disabled={!!busy||routing} onClick={()=>void act('delete',async()=>{const next=await api.deleteModelProfile(profile.id);setState(next);if(selected===profile.id)edit();setDeleting(null);setNotice(t('modelDeleted'))})}>{t('modelConfirmDelete')}</button><button className="text-btn" onClick={()=>setDeleting(null)}>{t('cancel')}</button></div>}
          </div>
        })}
        <div className="model-routing-options"><label><input type="checkbox" checked={state.auto_fallback} disabled={routing||busy==='delete'||!state.active_id||!state.fallback_ids.length} onChange={e=>route({auto_fallback:e.target.checked})}/><span>{t('modelAutoFallback')}</span></label><p>{t('modelFallbackHint')}</p>{!state.active_id&&state.profiles.length>0&&<p>{t('modelChooseActive')}</p>}</div>
      </div>
      <form className="settings-card model-profile-editor" onSubmit={e=>{e.preventDefault();save(true)}}>
        <div className="model-config-head"><div><strong>{editing?`${t('modelEditConnection')} · ${editing.name}`:t('modelNewConnection')}</strong><small>{t(isCodex?'codexConfigHint':'modelConfigHint')}</small></div>{!isCodex&&<div className="model-presets"><button className="text-btn" type="button" disabled={!!busy} onClick={()=>setDraft(d=>({...d,base_url:'https://api.openai.com/v1',model:'',wire_api:'responses',reasoning_effort:'disabled'}))}>OpenAI API</button><button className="text-btn" type="button" disabled={!!busy} onClick={()=>setDraft(d=>({...d,base_url:'https://spacetimeai.cc/v1',model:'gpt-6.1-sol',wire_api:'responses',reasoning_effort:'xhigh'}))}>SpacetimeAI</button></div>}</div>
        <fieldset disabled={!!busy} className="model-config-form">
          <label><span>{t('modelConnectionKind')}</span><select aria-label={t('modelConnectionKind')} value={draft.provider_kind??'api'} onChange={e=>{const codex=e.target.value==='codex';setCodexModelReady(false);setDraft(d=>({...d,provider_kind:codex?'codex':'api',api_key:null,base_url:codex?'https://chatgpt.com':empty().base_url,model:codex?'':'gpt-6.1-sol',reasoning_effort:codex?'disabled':'xhigh',max_concurrency:1}));setError('');setNotice('')}}><option value="api">{t('modelApiConnection')}</option><option value="codex">{t('codexSubscription')}</option></select></label>
          <label><span>{t('modelConnectionName')}</span><input aria-label={t('modelConnectionName')} value={draft.name} onChange={e=>field('name',e.target.value)} placeholder={t('modelConnectionNameHint')} required maxLength={80}/></label>
          {!isCodex&&<label><span>{t('modelBaseUrl')}</span><input aria-label={t('modelBaseUrl')} value={draft.base_url} onChange={e=>field('base_url',e.target.value)} placeholder="https://api.example.com/v1" required/></label>}
          {isCodex?<CodexModelPicker key={selected??'new'} ready={codexReady} refreshRevision={codexCatalogRevision} model={draft.model} effort={draft.reasoning_effort} disabled={!!busy} onChange={(model,reasoning_effort)=>setDraft(d=>({...d,model,reasoning_effort}))} onValidityChange={setCodexModelReady}/>:<label><span>{t('modelName')}</span><input aria-label={t('modelName')} value={draft.model} onChange={e=>field('model',e.target.value)} placeholder={t('modelNamePlaceholder')} required/></label>}
          {!isCodex&&<><label><span>{t('apiKey')} {editing?.api_key_configured&&<small>· {t('modelKeyStored')}</small>}</span><input aria-label={t('apiKey')} type="password" value={draft.api_key??''} onChange={e=>field('api_key',e.target.value)} placeholder={editing?.api_key_configured?t('apiKeyKeepHint'):t('apiKeyPlaceholder')} autoComplete="new-password"/></label>
          <label><span>{t('wireApi')}</span><select aria-label={t('wireApi')} value={draft.wire_api} onChange={e=>field('wire_api',e.target.value as ModelProfileInput['wire_api'])}><option value="responses">Responses</option><option value="chat_completions">Chat Completions</option></select></label></>}
          {!isCodex&&<label><span>{t('reasoningEffort')}</span><select aria-label={t('reasoningEffort')} value={draft.reasoning_effort} onChange={e=>field('reasoning_effort',e.target.value as ModelProfileInput['reasoning_effort'])}>{(['disabled','none','minimal','low','medium','high','xhigh'] as const).map(v=><option key={v} value={v}>{v==='disabled'?t('modelReasoningOmitted'):v}</option>)}</select></label>}
          <label><span>{t('modelTimeout')}</span><input aria-label={t('modelTimeout')} type="number" min={1} max={1800} value={draft.timeout} onChange={e=>field('timeout',Number(e.target.value))} required/></label>
          {!isCodex&&<><label><span>{t('modelConcurrency')}</span><input aria-label={t('modelConcurrency')} type="number" min={1} max={16} value={draft.max_concurrency} onChange={e=>field('max_concurrency',Number(e.target.value))} required/></label>
          <label><span>{t('modelJsonMode')}</span><select aria-label={t('modelJsonMode')} value={draft.json_mode} onChange={e=>field('json_mode',e.target.value as ModelProfileInput['json_mode'])}><option value="json_object">JSON mode</option><option value="none">{t('modelJsonOmitted')}</option></select></label>
          {draft.wire_api==='chat_completions'&&<label><span>{t('modelOutputParameter')}</span><select aria-label={t('modelOutputParameter')} value={draft.completion_parameter} onChange={e=>field('completion_parameter',e.target.value as ModelProfileInput['completion_parameter'])}><option>max_completion_tokens</option><option>max_tokens</option></select></label>}</>}
        </fieldset>
        {isCodex&&<><CodexAccountSettings onChange={onChange} onReady={setCodexReady} onModelsRefresh={()=>setCodexCatalogRevision(value=>value+1)} disabled={!!busy}/>
          <div className="codex-concurrency"><label><span>{t('codexConcurrencyLabel')}</span><select aria-label={t('codexConcurrencyLabel')} value={state.codex_max_concurrency??4} disabled={!!busy} onChange={event=>{const limit=Number(event.target.value);void act('concurrency',async()=>{const next=await api.codexConcurrency(limit);setState(next);setNotice(t('codexConcurrencySaved'))})}}>{Array.from({length:8},(_,index)=>index+1).map(limit=><option value={limit} key={limit}>{limit===1?t('codexConcurrencySerial'):limit===4?`4 · ${t('codexConcurrencyDefault')}`:String(limit)}</option>)}</select></label><p>{t('codexConcurrencyHint')}</p></div>
        </>}
        <div className="model-config-actions"><button className="btn primary" type="submit" disabled={!!busy||!draft.name.trim()||!draft.model.trim()||!draft.base_url.trim()||(isCodex&&(!codexReady||!codexModelReady))}>{busy==='save'?<LoaderCircle className="spin" size={14}/>:<Check size={14}/>} {t('testAndSave')}</button><button className="btn secondary" type="button" disabled={!!busy||!draft.name.trim()||!draft.model.trim()||!draft.base_url.trim()||(isCodex&&(!codexReady||!codexModelReady))} onClick={()=>save(false)}>{t('modelSaveOnly')}</button>{editing&&<button className="text-btn" type="button" disabled={!!busy} onClick={()=>edit()}><X size={13}/>{t('modelCloseEditor')}</button>}<span className="model-save-success" role="status">{notice}</span></div>
      </form>
      <p className="capability-notice">{t('modelSecurityHint')}</p>
    </>}
  </section>
}
