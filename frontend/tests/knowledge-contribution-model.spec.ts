import { expect, test } from '@playwright/test'
import { isCoreContribution, methodNetwork } from '../src/lib/knowledgeMap'
import type { KnowledgeCandidate } from '../src/types'

const candidate=(id:string,type:KnowledgeCandidate['entity_type'],role:string,paper_id:string):KnowledgeCandidate=>({
  id,paper_id,entity_id:id,entity_type:type,name:id,normalized_name:id.toLowerCase(),aliases:[],description:null,role,confidence:.95,status:'confirmed',evidence:[],conflict:{},run_id:null,model_version:null,prompt_version:null,layer:type==='method'?'primary':'evaluation',importance:'core',
})

test('core contributions include proposed datasets and legacy own-paper benchmarks without promoting external evaluations',()=>{
  const papers=[{id:'own',title:'SWE-bench: Can language models resolve real-world GitHub issues?'},{id:'other',title:'ReAct: Synergizing reasoning and acting'}]
  const own=candidate('SWE-bench','benchmark','used','own')
  const external={...own,id:'external',paper_id:'other'}
  const dataset=candidate('NL2Repo','dataset','proposed','dataset-paper')
  const method=candidate('ReAct','method','proposed','other')
  expect(isCoreContribution(own,papers)).toBe(true)
  expect(isCoreContribution(external,papers)).toBe(false)
  expect(isCoreContribution(dataset,papers)).toBe(true)
  expect(isCoreContribution({...dataset,status:'rejected'},papers)).toBe(false)
  expect(methodNetwork([own,external,dataset,method],[],papers).core.map(node=>node.name).sort()).toEqual(['NL2Repo','ReAct','SWE-bench'])
})

test('a benchmark mention in a paper title does not establish ownership',()=>{
  const benchmark=candidate('HumanEval','benchmark','used','comparison')
  const papers=[{id:'comparison',title:'Improving agents on HumanEval and SWE-bench'}]
  expect(isCoreContribution(benchmark,papers)).toBe(false)
})

test('a retained contextual example stays out of the method graph while its identity is preserved',()=>{
  const context={...candidate('BookWorm','method','proposed','p'),layer:'comparison' as const,importance:'context' as const,conflict:{_steward_context:{verdict:'incidental',reason:'Reproduced example'}}}
  expect(isCoreContribution(context)).toBe(false)
  expect(methodNetwork([context],[]).nodes).toHaveLength(0)
  const real={...candidate('BookWorm','method','proposed','own'),entity_id:context.entity_id}
  expect(methodNetwork([context,real],[]).core[0].candidates.map(c=>c.paper_id)).toEqual(['own'])
})
