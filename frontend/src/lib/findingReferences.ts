type Node = {type:string;value?:string;url?:string;children?:Node[]}

/** Resolve provider source IDs in prose while leaving links, code and math intact. */
export function findingReferences(labels:Record<string,string>) {
  return () => (tree:Node) => {
    const walk=(parent:Node)=>{
      if(!parent.children||['link','linkReference','code','inlineCode','math','inlineMath'].includes(parent.type))return
      parent.children=parent.children.flatMap(child=>{
        if(child.type!=='text'||!child.value){walk(child);return [child]}
        const parts:Node[]=[];let start=0
        for(const match of child.value.matchAll(/\bS\d+\b/g)){
          if(!labels[match[0]])continue
          const index=match.index!
          if(index>start)parts.push({type:'text',value:child.value.slice(start,index)})
          parts.push({type:'link',url:`#source-${match[0]}`,children:[{type:'text',value:labels[match[0]]}]})
          start=index+match[0].length
        }
        if(!parts.length)return [child]
        if(start<child.value.length)parts.push({type:'text',value:child.value.slice(start)})
        return parts
      })
    }
    walk(tree)
  }
}
