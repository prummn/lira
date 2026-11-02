import { useEffect, useRef, useState } from 'react'
import { Check, ExternalLink, LoaderCircle, RefreshCw } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { CodexAccountStatus } from '../types'

export function CodexAccountSettings({ onChange, onReady, onModelsRefresh, disabled = false }: {
  onChange:()=>void; onReady:(ready:boolean)=>void; onModelsRefresh?:()=>void; disabled?:boolean
}) {
  const { t, language } = useUi()
  const [account, setAccount] = useState<CodexAccountStatus|null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const callbacks = useRef({onChange,onReady,onModelsRefresh})
  callbacks.current = {onChange,onReady,onModelsRefresh}
  const alive = useRef(false)
  const inFlight = useRef(false)
  const ready = useRef<boolean|null>(null)

  const update = (next:CodexAccountStatus) => {
    if (!alive.current) return
    setAccount(next)
    callbacks.current.onReady(next.authenticated)
    if(next.authenticated)callbacks.current.onModelsRefresh?.()
    if (ready.current !== null && ready.current !== next.authenticated) callbacks.current.onChange()
    ready.current = next.authenticated
  }
  const run = async (action:()=>Promise<CodexAccountStatus>) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true); setError('')
    try { update(await action()) }
    catch(e) { if(alive.current) setError(errorMessage(e)) }
    finally { inFlight.current = false; if(alive.current) setBusy(false) }
  }
  useEffect(() => {
    alive.current = true
    void run(api.codexAccount)
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    if (!account?.pending) return
    const timer = window.setInterval(() => { void run(api.codexAccount) }, 2500)
    return () => window.clearInterval(timer)
  }, [account?.pending])

  const safeLoginUrl = account?.login_url?.startsWith('https://auth.openai.com/') ? account.login_url : null
  return <div className="codex-account">
    <div className="codex-account-heading">
      <div><strong>{t('codexSubscription')}</strong><p>{t('codexSubscriptionHint')}</p></div>
      <button className="icon-btn" type="button" title={t('codexRefresh')} aria-label={t('codexRefresh')}
        disabled={busy||disabled} onClick={()=>void run(api.codexAccount)}><RefreshCw size={16} className={busy?'spin':''}/></button>
    </div>
    {(error||account?.error)&&<p className="codex-error" role="alert">{error||account?.error}</p>}
    {!account&&<p role="status"><LoaderCircle size={15} className="spin"/> {t('loading')}</p>}
    {account&&!account.available&&<p>{t('codexInstallHint')} <code>npm install -g @openai/codex</code></p>}
    {account?.authenticated ? <>
      <div className="codex-account-identity"><Check size={17}/><span>{account.email}</span>{account.plan&&<span className="codex-plan">{account.plan}</span>}
        <button className="text-btn" type="button" disabled={busy||disabled} onClick={()=>void run(api.codexLogout)}>{t('codexLogout')}</button></div>
      {account.limits.length>0?<div className="codex-limits">{account.limits.map(window=><div className="codex-limit" key={`${window.limit_id??''}-${window.name}`}>
        <div><span>{window.window_minutes ? `${window.window_minutes>=1440?window.window_minutes/1440:window.window_minutes/60} ${t(window.window_minutes>=1440?'codexDays':'codexHours')}` : t('codexQuota')}{window.limit_id&&window.limit_id!=='codex'?` · ${window.limit_id}`:''}</span><strong>{window.used_percent===null?'—':`${t('codexUsed')} ${Math.round(window.used_percent)}%`}</strong></div>
        <progress aria-label={t('codexQuota')} max={100} value={window.used_percent??undefined} aria-valuenow={window.used_percent??undefined}/>
        {window.resets_at&&<small>{t('codexResets')} {new Date(window.resets_at*1000).toLocaleString(language,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</small>}
      </div>)}</div>:<p className="codex-muted">{account.limits_error||t('codexNoLimits')}</p>}
    </> : account?.retryable ? <p>{t('codexAccountUnavailable')}</p> : account?.pending ? <div className="codex-login-pending">
      <p role="status">{t('codexAwaitingLogin')}</p>
      <div>{safeLoginUrl&&<a className="btn primary" href={safeLoginUrl} target="_blank" rel="noopener noreferrer">{t('codexOpenLogin')}<ExternalLink size={14}/></a>}
        <button className="text-btn" type="button" disabled={busy||disabled} onClick={()=>void run(api.codexCancelLogin)}>{t('codexCancelLogin')}</button></div>
    </div> : <button className="btn secondary" type="button" disabled={busy||disabled||!account?.available} onClick={()=>void run(api.codexLogin)}>{busy&&<LoaderCircle size={14} className="spin"/>}{t('codexLogin')}</button>}
    <p className="codex-muted">{t('codexAccountHint')}</p>
  </div>
}
