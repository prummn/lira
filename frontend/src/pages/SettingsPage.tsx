import { Download } from 'lucide-react'
import { useUi } from '../lib/i18n'
import type { Workspace } from '../lib/useWorkspace'
import { exportJson } from '../components/Shared'
import { ModelProfilesSettings } from '../components/ModelProfilesSettings'

export function SettingsPage({workspace}:{workspace:Workspace}) {
  const {t,theme,setTheme,language,setLanguage}=useUi()
  return <div className="settings-page">
    <section className="page-heading"><div><div className="eyebrow">WORKSPACE SETTINGS</div><h1>{t('settings')}</h1><p>{t('settingsSubtitle')}</p></div></section>
    <section className="settings-section"><h2>{t('appearance')}</h2><p>{t('appearanceHint')}</p><div className="settings-card"><div className="setting-row"><strong>{t('theme')}</strong><div className="segmented-control">{(['light','dark','system'] as const).map(item=><button key={item} className={theme===item?'active':''} onClick={()=>setTheme(item)}>{t(item)}</button>)}</div></div><div className="setting-row"><strong>{t('language')}</strong><select aria-label={t('language')} value={language} onChange={e=>setLanguage(e.target.value as 'zh-CN'|'en-US')}><option value="zh-CN">简体中文</option><option value="en-US">English</option></select></div></div></section>
    <ModelProfilesSettings onChange={()=>void workspace.reload()}/>
    <section className="settings-section"><h2>{t('storage')}</h2><p>{t('storageHint')}</p><div className="settings-card"><div className="setting-row"><div><strong>{workspace.papers.length} {t('paperCount')}</strong><small>{t('exportHint')}</small></div><button className="btn secondary" onClick={()=>exportJson('research-library.json',{papers:workspace.papers,collections:workspace.collections})}><Download size={14}/>{t('export')}</button></div></div></section>
    <section className="settings-section"><h2>{t('shortcuts')}</h2><div className="settings-card"><div className="setting-row"><span>{t('shortcutSearch')}</span><kbd>Ctrl / Cmd + K</kbd></div><div className="setting-row"><span>{t('shortcutAsk')}</span><kbd>Ctrl / Cmd + Enter</kbd></div></div></section>
    <section className="settings-section"><h2>{t('limits')}</h2><p>{t('limitsHint')}</p></section>
    <footer className="settings-footer">LIRA · Literature Research Atlas · Local-first</footer>
  </div>
}
