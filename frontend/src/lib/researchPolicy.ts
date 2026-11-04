import type { ResearchSettings } from '../types'

export const quotaPresets = [
  { id: 'reading', label: '优先留给阅读', hint: '后台更克制，给近期阅读和提问留出更多余量。', start_remaining: 70, stop_remaining: 55, long_reserve: 45 },
  { id: 'balanced', label: '均衡', hint: '在日常阅读与后台整理之间平衡安排。', start_remaining: 50, stop_remaining: 35, long_reserve: 30 },
  { id: 'research', label: '后台多做一些', hint: '额度宽裕时更积极地推进专题研究。', start_remaining: 35, stop_remaining: 20, long_reserve: 15 },
] as const

export type QuotaPresetId = typeof quotaPresets[number]['id'] | 'custom'
export type QuotaValues = Pick<ResearchSettings, 'start_remaining' | 'stop_remaining' | 'long_reserve'>

export function quotaPresetId(values: QuotaValues): QuotaPresetId {
  return quotaPresets.find(preset => preset.start_remaining === values.start_remaining
    && preset.stop_remaining === values.stop_remaining && preset.long_reserve === values.long_reserve)?.id ?? 'custom'
}

export function applyQuotaPreset<T extends QuotaValues>(values: T, id: Exclude<QuotaPresetId, 'custom'>): T {
  const preset = quotaPresets.find(item => item.id === id)!
  return { ...values, start_remaining: preset.start_remaining, stop_remaining: preset.stop_remaining, long_reserve: preset.long_reserve }
}

export const researchLenses = [
  {
    id: 'integrated', label: '跨论文融会贯通', hint: '按自然脉络连接，不强凑成一条主线。',
    instruction: '请以本专题全部论文为材料，帮助读者融会贯通：解释各工作的研究问题、方法机制与真实联系，区分核心贡献、后续扩展、基线与消融，串联数据集和 benchmark、关键结果及证据边界。按研究脉络组织，不按论文逐篇罗列。不要预设所有论文构成单一主线；若材料自然分成几条脉络，分别讲清它们的联系与差异，也指出暂时孤立的工作，不为统一而硬凑。用原文证据支持判断，对材料不足或关系不确定处明确说明。',
  },
  {
    id: 'methods', label: '看清方法如何演进', hint: '沿设计动机与机制变化追踪研究脉络。',
    instruction: '请以本专题全部论文为材料，融会贯通地解释方法演进：说明各自的设计动机、核心机制及有证据支持的影响关系，区分核心贡献、后续扩展、基线与消融，并联系关键数据、结果和证据边界。按自然形成的研究脉络组织；不预设所有论文属于同一条演进线，也不为统一而硬凑。以原文证据支持关系判断。',
  },
  {
    id: 'evidence', label: '看数据与证据地图', hint: '贯通数据集、benchmark、指标、结果和结论边界。',
    instruction: '请以本专题全部论文为材料，融会贯通地整理数据与证据：解释常用数据集、benchmark、指标及其适用问题，比较关键结果和实验设计，说明这些证据支持什么、仍不能说明什么，并将结果连回方法机制。按自然形成的研究脉络组织，不假定论文都在同一条主线上；以原文证据支持判断。',
  },
] as const

export type ResearchLensId = typeof researchLenses[number]['id']

export function readResearchFocus(saved: string): { lens: ResearchLensId; supplement: string } {
  const preset = researchLenses.find(item => saved === item.instruction || saved.startsWith(`${item.instruction}\n\n补充关注：`))
  if (!preset) return { lens: 'integrated', supplement: saved }
  return { lens: preset.id, supplement: saved === preset.instruction ? '' : saved.slice(`${preset.instruction}\n\n补充关注：`.length) }
}

export function buildResearchFocus(lens: ResearchLensId, supplement: string): string {
  const instruction = researchLenses.find(item => item.id === lens)!.instruction
  return supplement.trim() ? `${instruction}\n\n补充关注：${supplement.trim()}` : instruction
}

export function researchFocusLabel(saved: string): string {
  const { lens } = readResearchFocus(saved)
  return researchLenses.find(item => item.id === lens)!.label
}
