import { expect, test } from '@playwright/test'
import { maintenanceStatus } from '../src/lib/maintenanceStatus'

const task = (reason: string) => ({
  id: 'curation-status', scope_type: 'library', scope_id: null, scope_title: null,
  status: 'queued', paper_count: 1, total: 1, completed: 0, pending: 1,
  failed: 0, reason, active_paper_id: null, active_paper_title: null, error: null,
  model_name: null,
}) as Parameters<typeof maintenanceStatus>[0]

const translate = ((key: string) => ({
  maintenanceQueued: '排队中',
  curationQuotaRecheck: '正在按官方额度重新安排',
  curationQuotaReserve: '官方剩余额度低于保留线',
}[key] ?? key)) as Parameters<typeof maintenanceStatus>[1]

test('legacy local budget reasons are rechecked without claiming the quota reserve was reached', () => {
  expect(maintenanceStatus(task('daily_budget'), translate)).toContain('重新安排')
  expect(maintenanceStatus(task('hourly_budget'), translate)).toContain('重新安排')
  expect(maintenanceStatus(task('quota_reserve'), translate)).toContain('官方剩余额度低于保留线')
})
