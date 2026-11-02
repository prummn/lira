"""Validate saved real-model replies, with backup and reversible run records."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy import select
from app.db import Database
from app.models import Paper, KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun
from app.services.knowledge_maintenance import prepare_run, _refresh_run_counts
from app.services.knowledge_steward import VERSION, apply_batch, fingerprint
from app.services.publication_metadata import enrich_publication


def backup(source, target):
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as origin:
        with sqlite3.connect(target) as destination: origin.backup(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',nargs='+',type=Path,required=True)
    parser.add_argument('--collection',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Write validated decisions to the live library, after backup')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    target=output/'before.db'
    if target.exists(): raise SystemExit('Use a fresh output directory; previous evidence is preserved')
    production=ROOT/'backend/paper_reader.db'
    backup(production,target)
    database_path=production if args.apply else output/'replay.db'
    if not args.apply: backup(target,database_path)
    database=Database('sqlite:///'+database_path.as_posix())
    pairs={}
    for source in args.sources:
        for response in source.glob('paper-*-response.json'):
            identifier=response.name.removesuffix('-response.json')
            original=source/(identifier+'-input.json')
            if original.exists(): pairs[identifier]=(original,response,source)
    reports=[]
    # Check every original snapshot before creating a production run. A later
    # edit must never leave a partially replayed, stale batch in the library.
    with database.sessions() as db:
        for identifier,(original,_,source) in pairs.items():
            paper=db.get(Paper,identifier)
            bundle=json.loads(original.read_text(encoding='utf-8'))
            if paper is None or fingerprint(paper)!=bundle['fingerprint']:
                raise SystemExit('Source changed since model evaluation: '+identifier)
    with database.sessions() as db:
        run=prepare_run(db,scope_type='collection',scope_id=args.collection,allow_external=True,force=True)
        run_id=run.id;run.status='running';db.commit()
    for identifier,(original,response,source) in pairs.items():
        bundle=json.loads(original.read_text(encoding='utf-8'))
        data=json.loads(response.read_text(encoding='utf-8'))
        with database.sessions() as db:
            paper=db.get(Paper,identifier)
            run=db.get(KnowledgeMaintenanceRun,run_id)
            issue=next((i for i in run.issues if json.loads(i.proposed_action_json).get('paper_id')==identifier),None)
            if paper is None or issue is None: continue
            before={'objects':len(paper.knowledge_candidates),'relations':len(paper.knowledge_relations),
                'pending_relations':sum(r.status in {'candidate','unresolved','conflict'} for r in paper.knowledge_relations)}
            publication=enrich_publication(db,paper,allow_external=True)
            db.commit()
            report=apply_batch(db,paper,data,bundle)
            metrics=json.loads((source/'results.json').read_text(encoding='utf-8'))
            measured=next((item for item in metrics if item.get('paper_id')==identifier),{})
            report['evaluation_usage']=measured.get('usage',{})
            report['evaluation_seconds']=measured.get('seconds')
            report['publication']=publication;report['before']=before
            report['after']={'objects':len(paper.knowledge_candidates),'relations':len(paper.knowledge_relations),
                'pending_relations':sum(r.status in {'candidate','unresolved','conflict'} for r in paper.knowledge_relations)}
            issue.proposed_action_json=json.dumps({'type':'curate_paper','paper_id':identifier,'version':VERSION,
                'result_fingerprint':report['result_fingerprint']},ensure_ascii=False)
            issue.applied_change_ids_json=json.dumps(report['change_ids'])
            issue.summary=report['summary'] or paper.title
            issue.reasoning='真实模型检查；已重新核验原文、身份、人工决定及当前快照，所有修改保留撤销记录'
            issue.auto_eligible=True;issue.status='auto_applied' if report['change_ids'] else 'accepted'
            # Journal exact persisted source, never formatting-abbreviated model quotes.
            evidence=[]
            for row in [*paper.knowledge_candidates,*paper.knowledge_relations]:
                for item in json.loads(row.evidence_json or '[]'):
                    if item.get('quote') and item not in evidence: evidence.append(item)
                if len(evidence)>=3: break
            issue.evidence_json=json.dumps([dict(e,paper_id=identifier,paper_title=paper.title) for e in evidence[:3]],ensure_ascii=False)
            reports.append(report)
            usage_totals={key:sum(r.get('evaluation_usage',{}).get(key) or 0 for r in reports) for key in ('input_tokens','output_tokens')}
            run.prompt_version=VERSION
            run.usage_json=json.dumps({'curation_version':VERSION,'paper_count':len(pairs),'paper_audits':reports,
                **usage_totals,'total_tokens':sum(usage_totals.values()),'replay_model_calls':0,
                'replayed_model_results':True,'auto_actions':sum(sum(r.get(k,0) for k in ('objects_confirmed','objects_rejected','objects_contextualized','relations_confirmed','relations_rejected','aliases_linked')) for r in reports),
                'processed_issue_ids':[i.id for i in run.issues if i.status in {'auto_applied','accepted'}]},ensure_ascii=False)
            _refresh_run_counts(db,run);db.commit()
            (output/'results.json').write_text(json.dumps({'run_id':run_id,'production':args.apply,'papers':reports},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in report.items() if k not in {'change_ids','summary','publication'}},ensure_ascii=True),flush=True)
    with database.sessions() as db:
        run=db.get(KnowledgeMaintenanceRun,run_id)
        run.status='complete' if all(i.status in {'auto_applied','accepted'} for i in run.issues) else 'partial'
        run.finished_at=datetime.now(timezone.utc);db.commit()
    database.engine.dispose()


if __name__=='__main__':main()
