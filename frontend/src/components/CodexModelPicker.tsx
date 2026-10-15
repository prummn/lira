import { useEffect, useId, useRef, useState } from 'react'
import { LoaderCircle, RefreshCw } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { CodexModels, ModelProfile } from '../types'
import './codex-model-picker.css'

type Effort=ModelProfile['reasoning_effort']
export function CodexModelPicker({ready,refreshRevision,model,effort,disabled,onChange,onValidityChange}:{
  ready:boolean;refreshRevision:number;model:string;effort:Effort;disabled:boolean
  onChange:(model:string,effort:Effort)=>void;onValidityChange:(valid:boolean)=>void
}) {
  const {t}=useUi()
  const modelId=useId()
  const [catalog,setCatalog]=useState<CodexModels|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const generation=useRef(0)
  const latest=useRef({model,effort,onChange,onValidityChange})
  latest.current={model,effort,onChange,onValidityChange}
  const chosen=catalog?.models.find(item=>item.model===model)
  const valid=ready&&!loading&&!error&&!!chosen&&(effort==='disabled'||!!chosen.supported_reasoning_efforts.some(option=>option.effort===effort))

  const load=async(refresh=false)=>{
    const token=++generation.current
    setLoading(true);setError('')
    try {
      const next=await api.codexModels(refresh)
      if(token!==generation.current)return
      setCatalog(next)
      if(!latest.current.model){
        const initial=next.models.find(item=>item.model===next.default_model)??next.models[0]
        if(initial)latest.current.onChange(initial.model,'disabled')
      }
    }catch(e){if(token===generation.current)setError(errorMessage(e))}
    finally{if(token===generation.current)setLoading(false)}
  }
  useEffect(()=>{
    if(ready)void load(refreshRevision>0)
    else{generation.current++;setCatalog(null);setLoading(false);setError('')}
    return()=>{generation.current++}
  },[ready,refreshRevision])
  useEffect(()=>{latest.current.onValidityChange(valid)},[valid])
  const missing=!!catalog&&!chosen&&!!model
  const badEffort=!!chosen&&effort!=='disabled'&&!chosen.supported_reasoning_efforts.some(option=>option.effort===effort)
  return <div className="codex-model-picker" aria-busy={loading}>
    <div className="codex-model-field"><div className="codex-model-label"><label htmlFor={modelId}>{t('modelName')}</label><button className="text-btn" type="button" disabled={!ready||disabled||loading} onClick={()=>void load(true)}>{loading?<LoaderCircle size={13} className="spin"/>:<RefreshCw size={13}/>} {t('codexRefreshModels')}</button></div>
      <select id={modelId} aria-label={t('modelName')} value={model} disabled={!ready||disabled||loading||!catalog?.models.length} onChange={event=>onChange(event.target.value,'disabled')} required>
        {!chosen&&<option value={model} disabled>{model||t(!ready?'codexModelsAfterLogin':loading?'loading':'codexChooseModel')}</option>}
        {catalog?.models.map(item=><option value={item.model} key={item.model}>{item.display_name}{item.is_default?` · ${t('codexOfficialDefault')}`:''}</option>)}
      </select>
    </div>
    <label><span>{t('reasoningEffort')}</span><select aria-label={t('reasoningEffort')} value={effort} disabled={!chosen||disabled||loading||!ready} onChange={event=>onChange(model,event.target.value as Effort)}>
      <option value="disabled">{t('codexFollowDefault')}{chosen?.default_reasoning_effort?` · ${chosen.default_reasoning_effort}`:''}</option>
      {badEffort&&<option value={effort} disabled>{effort} · {t('codexEffortUnavailable')}</option>}
      {chosen?.supported_reasoning_efforts.map(option=><option key={option.effort} value={option.effort} title={option.description}>{option.effort}</option>)}
    </select></label>
    <div className="codex-model-detail">
      {error?<p role="alert" className="codex-model-warning">{error}</p>:!ready?<p>{t('codexModelsAfterLogin')}</p>:loading?<p role="status">{t('codexModelsLoading')}</p>:catalog?.models.length===0?<p role="alert">{t('codexModelsEmpty')}</p>:<>
        {missing&&<p role="alert" className="codex-model-warning"><code>{model}</code> {t('codexModelUnavailable')}</p>}
        {badEffort&&<p role="alert" className="codex-model-warning">{t('codexEffortUnavailableHint')}</p>}
        {chosen&&<><p><code>{chosen.model}</code>{chosen.description&&<span>{chosen.description}</span>}</p><p className="codex-model-source">{t('codexModelSource')}</p></>}
      </>}
    </div>
  </div>
}
