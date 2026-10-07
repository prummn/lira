import { FileText, Upload } from 'lucide-react'
import { useUi } from '../lib/i18n'
import { remoteAvailable, useAnalysisPreference } from '../lib/intelligence'
import type { ModelSettings } from '../types'
import { Modal } from './Shared'

export function AnalysisImportChoice({settings,value,change}:{settings:ModelSettings|null;value:boolean;change:(value:boolean)=>void}) {
  const {t}=useUi();const enabled=remoteAvailable(settings)
  return <div className="analysis-import-choice"><label><input type="checkbox" checked={enabled&&value} disabled={!enabled} onChange={e=>change(e.target.checked)}/><strong>{t('analysisAfterImport')}</strong></label>
    <p>{t(enabled?'analysisImportHint':'analysisUnavailable')}</p><small>{t('analysisRemembered')}</small></div>
}
export function ImportFilesDialog({files,settings,close,confirm}:{files:File[];settings:ModelSettings|null;close:()=>void;confirm:(analyze:boolean)=>void}) {
  const {t}=useUi();const [analyze,setAnalyze]=useAnalysisPreference()
  return <Modal title={t('importPreflight')} close={close}><p className="dialog-description">{t('importBatchHint')}</p>
    <div className="import-file-list">{files.map((file,index)=><div key={index}><FileText size={16}/><span>{file.name}</span><small>{(file.size/1024/1024).toFixed(1)} MB</small></div>)}</div>
    <AnalysisImportChoice settings={settings} value={analyze} change={setAnalyze}/>
    <div className="modal-actions"><span className="muted">{files.length} {t('importFileCount')}</span><button className="btn secondary" onClick={close}>{t('cancel')}</button><button className="btn primary" onClick={()=>confirm(remoteAvailable(settings)&&analyze)}><Upload size={15}/>{t('importStart')}</button></div>
  </Modal>
}
