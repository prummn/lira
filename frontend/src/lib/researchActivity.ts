import type { ActivityDay, ActivityKind } from '../types'
import { api } from './api'

/** Color reflects research activity, not a count of repeated tool operations. */
export function researchActivityLevel(day: ActivityDay | undefined): number {
  if (!day) return 0
  const count = (kind: ActivityKind) => Math.max(0, day[kind] || 0)
  const core = 4 * Math.log2(1 + count('reading')) + 3 * Math.log2(1 + count('notes'))
  const supporting = Math.min(count('language') / 10, 1)
    + Math.min(count('search') / 4, 1) + Math.min(count('imports') / 5, 1)
  const score = core + supporting
  return score === 0 ? 0 : score < 6 ? 1 : score < 12 ? 2 : score < 20 ? 3 : 4
}

function localDay(): string {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Record explicit research actions without allowing telemetry failures to interrupt reading. */
export async function recordResearchActivity(kind: ActivityKind, paperId?: string, key?: string): Promise<void> {
  const day = localDay()
  const identity = key?.trim() || paperId || 'workspace'
  const storageKey = `riw-activity-${day}-${kind}-${identity}`
  try {
    if (localStorage.getItem(storageKey)) return
    localStorage.setItem(storageKey, '1')
  } catch {
    // Storage is optional. The activity request can still be attempted.
  }
  try {
    await api.recordActivity(kind, paperId)
  } catch {
    try { localStorage.removeItem(storageKey) } catch { /* best effort */ }
  }
}
