import type { LocaleKey } from './i18n'
import type { KnowledgeEntityType } from '../types'

export const entityTypes: KnowledgeEntityType[] = ['method','dataset','benchmark','task','metric','concept','paper','venue']
export const relationTypes = ['builds_on','extends','inspired_by','replaces','compares_with','contrasts_with','requires_concept','uses_dataset','evaluated_on'] as const
export const relationLabel = (kind:string) => `kr_${kind}` as LocaleKey
export const statusLabel = (status:string) => `ks_${status}` as LocaleKey
export const roleLabel = (role:string) => `krole_${role}` as LocaleKey
export const typeLabel = (kind:string) => `knowledgeGroup_${kind}` as LocaleKey
