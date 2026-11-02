import type { ResearchBudget as Budget } from '../types'

export function ResearchBudget({budget}:{budget?:Budget|null}) {
  if(!budget||budget.allowance===undefined)return null
  return <section className="research-budget" aria-label="今日后台预算">
    <div><strong>{budget.allowed?'按周额度，留出每日研究空间':'今日已留足，稍后继续'}</strong><span>还可约 {budget.remaining??0} 个百分点</span></div>
    <meter aria-label="今日预算剩余" min={0} max={Math.max(.01,budget.allowance)} value={budget.remaining??0}/>
    <p>今日安排约 {budget.allowance} 个百分点，账号用量已增加 {budget.observed_use??0} 个百分点。{!budget.allowed&&budget.resumes_at?`预计 ${new Date(budget.resumes_at*1000).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'})} 重新安排。`:''}</p>
    <small>按周剩余量与重置时间分配。阅读及其他客户端的用量也计入观察，前台阅读不受这项预算限制。</small>
  </section>
}
