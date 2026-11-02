import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

type MarkdownNode = {type:string;url?:string;identifier?:string;value?:string;children?:MarkdownNode[]}

/** Use the same Markdown grammar as the reader, including reference-style links. */
export function essayCitations(markdown:string):Map<string,string> {
  const tree=unified().use(remarkParse).use(remarkGfm).use(remarkMath).parse(markdown)
  const definitions=new Map<string,string>()
  const citations=new Map<string,string>()
  const walk=(node:MarkdownNode,visit:(node:MarkdownNode)=>void)=>{
    visit(node)
    for(const child of node.children??[])walk(child,visit)
  }
  walk(tree,node=>{
    if(node.type==='definition'&&node.identifier&&node.url&&!definitions.has(node.identifier))definitions.set(node.identifier,node.url)
  })
  const label=(node:MarkdownNode):string=>node.value??(node.children??[]).map(label).join('')
  walk(tree,node=>{
    const url=node.type==='link'?node.url:node.type==='linkReference'?definitions.get(node.identifier??''):undefined
    if(url?.startsWith('#source-')&&!citations.has(url.slice(8)))citations.set(url.slice(8),label(node))
  })
  return citations
}
