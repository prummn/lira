import type {MaintenanceTaskSummary} from '../types'
import type {LocaleKey} from './i18n'

export const activeMaintenance=(task:MaintenanceTaskSummary)=>task.status==='queued'||task.status==='running'||task.status==='partial'&&task.pending>0
const states:Record<MaintenanceTaskSummary['status'],LocaleKey>={queued:'maintenanceQueued',running:'maintenanceRunning',partial:'maintenancePartial',complete:'maintenanceComplete',failed:'maintenanceFailed',cancelled:'maintenanceCancelled'}
const reasons:Record<string,LocaleKey>={reading:'curationWaitingReading',maintenance_reading:'curationWaitingReading',
  foreground_queue:'curationWaitingForeground',disabled:'curationDisabled',maintenance_disabled:'curationDisabled',
  profile_required:'curationProfileRequired',account_unavailable:'curationAccountUnavailable',
  hourly_budget:'curationHourlyBudget',quota_reserve:'curationQuotaReserve',daily_budget:'curationQuotaReserve',
  quota_unknown:'quotaQueryHint',quota_timeout:'quotaQueryTimeout',quota_unavailable:'quotaQueryFailed',quota_stale:'quotaQueryHint',
  retry_wait:'curationRetryWait',cooldown:'curationRetryWait',maintenance_error:'curationRetryWait'}
export function maintenanceStatus(task:MaintenanceTaskSummary,t:(key:LocaleKey)=>string){
  if(task.status==='running'&&task.active_paper_title)return `${t('maintenanceRunning')} · ${task.active_paper_title}`
  const state=t(task.status==='partial'&&task.pending>0?'maintenanceQueued':states[task.status])
  const reason=activeMaintenance(task)&&task.reason?reasons[task.reason]:undefined
  return reason?`${state} · ${t(reason)}`:state
}
