import type { Answer, Collection, ExplainStyle, Graph, ModelSettings, Note, NoteKind, Paper, PaperDetail, ReadingStatus, SearchHit } from '../types'

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError' }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(`/api${path}`, init) }
  catch { throw new ApiError('无法连接本地服务，请运行启动脚本后重试。', 0) }
  const text = await response.text()
  let payload: unknown
  try { payload = text ? JSON.parse(text) : null }
  catch { throw new ApiError('本地服务返回了无法读取的响应。请检查服务是否启动。', response.status) }
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? (payload as { detail: unknown }).detail : null
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg ?? '').join('；') : `请求失败 (${response.status})`
    throw new ApiError(message, response.status)
  }
  return payload as T
}
const json = (body: unknown): RequestInit => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
async function loadPapers() {
  const first=await request<{items:Paper[];total:number}>('/papers?limit=200&offset=0')
  const items=[...first.items]
  for(let offset=items.length;offset<first.total;) {
    const next=await request<{items:Paper[];total:number}>(`/papers?limit=200&offset=${offset}`)
    if(!next.items.length)break
    items.push(...next.items);offset+=next.items.length
  }
  return {items:[...new Map(items.map(p=>[p.id,p])).values()],total:first.total}
}
export const api = {
  papers: loadPapers,
  collections: () => request<{ items: Collection[] }>('/collections'),
  paper: (id: string) => request<PaperDetail>(`/papers/${encodeURIComponent(id)}`),
  update: (id: string, body: { is_favorite?: boolean; reading_status?: ReadingStatus; tags?: string[] }) => request<Paper>(`/papers/${encodeURIComponent(id)}`, { method: 'PATCH', ...json(body) }),
  import: (file: File) => { const body = new FormData(); body.append('file', file); return request<PaperDetail>('/papers/import', { method: 'POST', body }) },
  createCollection: (name: string, description: string) => request<Collection>('/collections', { method: 'POST', ...json({ name, description, color: '#536f89' }) }),
  membership: (collectionId: string, paperId: string, add: boolean) => request<unknown>(`/collections/${encodeURIComponent(collectionId)}/papers/${encodeURIComponent(paperId)}`, { method: add ? 'PUT' : 'DELETE' }),
  analyze: (id: string) => request<PaperDetail>(`/papers/${encodeURIComponent(id)}/analyze`, { method: 'POST' }),
  ask: (id: string, question: string) => request<Answer>(`/papers/${encodeURIComponent(id)}/ask`, { method: 'POST', ...json({ question }) }),
  explain: (id:string, body:{chunk_id:string;selected_text:string;style:ExplainStyle}) => request<Answer>(`/papers/${encodeURIComponent(id)}/explain`, {method:'POST',...json(body)}),
  note: (id: string, body: {content: string; kind: NoteKind; page?: number | null; source_text?: string | null; bbox?: number[] | null}) => request<Note>(`/papers/${encodeURIComponent(id)}/notes`, { method: 'POST', ...json(body) }),
  deleteNote: (id: string, noteId: string) => request<unknown>(`/papers/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`, { method: 'DELETE' }),
  graph: (collectionId: string) => request<Graph>(`/graph${collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : ''}`),
  search: (query: string, collectionId='') => request<{items: SearchHit[]}>(`/search?query=${encodeURIComponent(query)}${collectionId?'&collection_id='+encodeURIComponent(collectionId):''}`),
  settings: () => request<ModelSettings>('/settings'),
  translate: (id: string, chunkId: string) => request<{text: string; provider: string}>(`/papers/${encodeURIComponent(id)}/translate`, {method: 'POST', ...json({chunk_id: chunkId})}),
}
export const errorMessage = (error: unknown): string => error instanceof Error ? error.message : String(error)
