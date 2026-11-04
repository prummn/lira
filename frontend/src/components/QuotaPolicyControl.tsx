import { useEffect, useState } from 'react'
import { LoaderCircle, RefreshCw, SlidersHorizontal } from 'lucide-react'
import type { ResearchSettings, ResearchStatus } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { applyQuotaPreset, quotaPresetId, quotaPresets } from '../lib/researchPolicy'
import { ErrorBanner, Modal } from './Shared'
import './quota-policy.css'

type Policy=Pick<ResearchSettings,'start_remaining'|'stop_remaining'|'long_reserve'>
const policy=(settings:ResearchSettings):Policy=>({start_remaining:settings.start_remaining,stop_remaining:settings.stop_remaining,long_reserve:settings.long_reserve})

export function QuotaPolicyControl({status,onSaved}:{status?:ResearchStatus;onSaved?:()=>Promise<void>}) {
 const {t}=useUi()
 const [open,setOpen]=useState(false)
 return <><button type="button" className="quota-policy-trigger" onClick={()=>setOpen(true)}><SlidersHorizontal size={13}/>{t('quotaEdit')}</button>{open&&<QuotaPolicyDialog status={status} onSaved={onSaved} close={()=>setOpen(false)}/>}</>
}

function QuotaPolicyDialog({status,onSaved,close}:{status?:ResearchStatus;onSaved?:()=>Promise<void>;close:()=>void}) {
 const {t}=useUi()
 const [snapshot,setSnapshot]=useState(status)
 const [draft,setDraft]=useState<Policy|undefined>(status?policy(status.settings):undefined)
 const [error,setError]=useState(''),[notice,setNotice]=useState('')
 const [busy,setBusy]=useState(false),[refreshing,setRefreshing]=useState(false)
 const [customOpen,setCustomOpen]=useState(status?quotaPresetId(status.settings)==='custom':false)
 useEffect(()=>{
  let alive=true
  if(!status)void api.researchStatus().then(next=>{if(alive){setSnapshot(next);setDraft(policy(next.settings))}}).catch(e=>{if(alive)setError(errorMessage(e))})
  return()=>{alive=false}
 },[])
 const refresh=async()=>{
  if(refreshing||busy)return
  setRefreshing(true);setError('')
  try{await api.researchQuota();const next=await api.researchStatus();setSnapshot(next);if(!draft)setDraft(policy(next.settings))}catch(e){setError(errorMessage(e))}finally{setRefreshing(false)}
 }
 const save=async()=>{
  if(!draft||busy)return
  setBusy(true);setError('');setNotice('')
  try{
   const saved=await api.quotaPolicy(draft)
   setDraft(policy(saved));setSnapshot(old=>old?{...old,settings:saved}:old);setNotice(t('quotaSaved'))
   // Saving has finished; a slow monitor refresh must not lock the dialog.
   if(onSaved)void onSaved().catch(e=>setError(errorMessage(e)))
  }catch(e){setError(errorMessage(e))}finally{setBusy(false)}
 }
 const valid=!!draft&&Object.values(draft).every(Number.isInteger)&&draft.start_remaining>draft.stop_remaining&&draft.start_remaining>=1&&draft.start_remaining<=100&&draft.stop_remaining>=0&&draft.stop_remaining<=99&&draft.long_reserve>=0&&draft.long_reserve<=100
 const selected= draft ? quotaPresetId(draft) : 'custom'
 return <Modal title={t('quotaPolicyTitle')} className="quota-policy-dialog" close={()=>{if(!busy)close()}}>
  <p className="quota-policy-intro">后台研究只在额度宽裕时开始。你选择的是“留多少给自己阅读”，不是每篇文章的消费上限。</p>
  <div className="quota-policy-windows">{snapshot?.quota.filter(q=>q.used_percent!==null).map((q,i)=>{
   const long=(q.window_minutes??0)>=1440,remaining=Math.max(0,100-q.used_percent!),reserve=draft?(long?draft.long_reserve:draft.stop_remaining):0
   return <div key={i}><span>{long?'较长周期额度':'短周期额度'}</span><strong>{remaining}% <small>剩余</small></strong><p>{remaining<=reserve?`已到后台暂停线（${reserve}%）`:`高于后台暂停线（${reserve}%）`}</p></div>
  })}{!snapshot?.quota.some(q=>q.used_percent!==null)&&<p>{t('queueUnknownQuota')}</p>}</div>
  {draft?<form onSubmit={e=>{e.preventDefault();void save()}}>
   <div className="quota-policy-presets" role="group" aria-label="后台额度策略">{quotaPresets.map(preset=><button type="button" key={preset.id} aria-pressed={selected===preset.id} disabled={busy} onClick={()=>{setDraft(applyQuotaPreset(draft,preset.id));setCustomOpen(false);setNotice('')}}><strong>{preset.label}</strong><small>{preset.hint}</small></button>)}</div>
   <details className="quota-policy-advanced" open={customOpen} onToggle={event=>setCustomOpen(event.currentTarget.open)}>
    <summary>{selected==='custom'?'自定义阈值':'自定义阈值（高级）'}</summary>
    <fieldset disabled={busy} className="quota-policy-fields">{([
    ['long_reserve','quotaLongReserve','quotaLongHint'],['stop_remaining','quotaShortReserve','quotaShortHint'],['start_remaining','quotaStartReserve','quotaStartHint'],
   ] as const).map(([key,label,hint])=><label key={key}><span>{t(label)}<small>{t(hint)}</small></span><input type="number" aria-label={t(label)} min={key==='start_remaining'?1:0} max={key==='stop_remaining'?99:100} step={1} required value={Number.isNaN(draft[key])?'':draft[key]} onChange={e=>{setDraft({...draft,[key]:e.target.value===''?NaN:Number(e.target.value)});setNotice('')}}/></label>)}</fieldset>
   </details>
   {!valid&&<p className="quota-policy-error">{t('quotaInvalid')}</p>}
   <p className="quota-policy-footnote">适用于所有官方连接的后台任务。前台提问和手动翻译仍优先；官方服务本身的额度限制照常生效。</p>
   {error&&<ErrorBanner error={error}/>}
   <div className="quota-policy-actions"><button type="button" className="text-btn" disabled={refreshing||busy} onClick={()=>void refresh()}><RefreshCw size={13} className={refreshing?'spin':''}/>{t('quotaRefresh')}</button><span role="status">{notice}</span><button className="btn primary" type="submit" disabled={!valid||busy}>{busy&&<LoaderCircle size={14} className="spin"/>}{t('quotaSave')}</button></div>
  </form>:error?<ErrorBanner error={error} retry={()=>void refresh()}/>:<p><LoaderCircle size={14} className="spin"/> {t('loading')}</p>}
 </Modal>
}
