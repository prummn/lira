import json

import pytest
from sqlalchemy import select
from app.models import KnowledgeCandidate, KnowledgeEntity, KnowledgeRelation, Paper, PaperChunk
from app.providers.base import ProviderError
from test_knowledge_service import make_db


def setup_paper(db):
    paper = Paper(id='p', title='TraceBench: Evaluating agents', intelligence_status='failed')
    paper.chunks = [PaperChunk(id='c', page=1, section='Introduction', content=
        'We introduce TraceBench, a benchmark for agents. TraceBench evaluates ReAct on HotpotQA. '
        'ReAct means Reasoning and Acting. We compare it with Reflexion.')]
    db.add(paper); db.flush()
    return paper


def candidate(name, kind='method', role='used', confidence=.98, **extra):
    return dict(name=name, entity_type=kind, role=role, description='A verified research object',
                aliases=[], confidence=confidence, citations=[{'chunk_id':'c','quote':name}], **extra)


def batch():
    return {'summary':'补全基准、方法与评测对象并连接来源。','candidates':[candidate('TraceBench','benchmark','proposed'),
            candidate('ReAct'),candidate('HotpotQA','dataset')],
            'relations':[dict(source_name='TraceBench',target_name='ReAct',relation='compares_with',
                description='The benchmark evaluates ReAct.',confidence=.98,
                citations=[{'chunk_id':'c','quote':'TraceBench evaluates ReAct on HotpotQA.'}])]}


def test_failed_analysis_can_be_curated_with_canonical_objects_and_relations(tmp_path):
    from app.services.knowledge_steward import build_bundle, apply_batch
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        bundle=build_bundle(db,paper)
        assert bundle['chunks'][0]['content']==paper.chunks[0].content
        result=apply_batch(db,paper,batch(),bundle)
        db.flush()
        assert result['objects_added']==3
        assert result['relations_confirmed']==1
        assert db.scalar(select(KnowledgeCandidate).where(KnowledgeCandidate.name=='TraceBench')).entity_type=='benchmark'
        assert db.scalar(select(KnowledgeRelation)).status=='confirmed'
        assert len(list(db.scalars(select(KnowledgeEntity))))==3
        again=apply_batch(db,paper,batch(),build_bundle(db,paper))
        assert again['objects_added']==0
        assert len(list(db.scalars(select(KnowledgeRelation))))==1


def test_invalid_quote_rejects_the_whole_batch_before_mutation(tmp_path):
    from app.services.knowledge_steward import build_bundle, apply_batch
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db);data=batch()
        data['candidates'][-1]['citations'][0]['quote']='Invented benchmark claim'
        with pytest.raises(ProviderError): apply_batch(db,paper,data,build_bundle(db,paper))
        assert list(db.scalars(select(KnowledgeCandidate)))==[]


def test_low_confidence_and_human_rejection_are_not_auto_confirmed(tmp_path):
    from app.services.knowledge_steward import build_bundle, apply_batch
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        rejected=KnowledgeCandidate(id='rejected',paper_id='p',entity_type='method',name='ReAct',
            normalized_name='react',role='used',status='rejected',evidence_json='[]')
        db.add(rejected);db.flush()
        data=batch();data['candidates'][-1]['confidence']=.7
        result=apply_batch(db,paper,data,build_bundle(db,paper))
        assert rejected.status=='rejected'
        assert result['protected']>=1 and result['deferred']>=1
        assert db.scalar(select(KnowledgeCandidate).where(KnowledgeCandidate.name=='HotpotQA')) is None
        assert list(db.scalars(select(KnowledgeRelation)))==[]


def test_alias_requires_declared_identity_not_model_confidence(tmp_path):
    from app.services.knowledge_steward import build_bundle, apply_batch
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        db.add(KnowledgeEntity(id='existing',entity_type='method',name='Reasoning and Acting',normalized_name='reasoning and acting',aliases_json='[]'))
        db.flush()
        data={'candidates':[candidate('ReAct',entity_id='existing')],'relations':[]}
        result=apply_batch(db,paper,data,build_bundle(db,paper))
        assert result['deferred']==1
        data['candidates'][0]['citations']=[{'chunk_id':'c','quote':'ReAct means Reasoning and Acting.'}]
        result=apply_batch(db,paper,data,build_bundle(db,paper))
        assert result['aliases_linked']==1
        assert db.scalar(select(KnowledgeCandidate)).entity_id=='existing'


def test_clean_paper_gets_one_semantic_checkpoint_without_repeating(tmp_path):
    from app.services.knowledge_maintenance import prepare_run,execute_run
    database=make_db(tmp_path)
    class Curator:
        mode='remote';configured=True;last_usage={};calls=0
        def audit_knowledge_bundle(self,bundle):
            self.calls+=1
            assert bundle['mode']=='paper_curation'
            return batch()
    provider=Curator()
    with database.sessions() as db:
        paper=setup_paper(db);db.commit()
        run=prepare_run(db,scope_type='papers',paper_ids=['p'])
        execute_run(db,run,provider,max_calls=1);db.commit()
        assert provider.calls==1
        assert run.status=='complete'
        assert json.loads(run.usage_json)['paper_audits'][0]['objects_added']==3
        next_run=prepare_run(db,scope_type='papers',paper_ids=['p'])
        execute_run(db,next_run,provider,max_calls=1)
        assert provider.calls==1


def test_curation_undo_preserves_subsequent_human_changes(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch,undo_changes
    from app.services.knowledge_curation import record,snapshot
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db);result=apply_batch(db,paper,batch(),build_bundle(db,paper));db.flush()
        row=db.scalar(select(KnowledgeCandidate).where(KnowledgeCandidate.name=='ReAct'))
        before=snapshot(row);row.description='My own research judgement';record(db,row,'confirm_candidate',before);db.flush()
        with pytest.raises(ProviderError):undo_changes(db,result['change_ids'])
        assert row.description=='My own research judgement'


def test_curation_can_be_undone_without_orphan_objects(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch,undo_changes
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db);result=apply_batch(db,paper,batch(),build_bundle(db,paper));db.flush()
        undo_changes(db,result['change_ids']);db.flush()
        assert list(db.scalars(select(KnowledgeCandidate)))==[]
        assert list(db.scalars(select(KnowledgeRelation)))==[]
        assert list(db.scalars(select(KnowledgeEntity)))==[]


def test_body_stops_at_references_but_pending_appendix_evidence_is_reviewable(tmp_path):
    from app.services.knowledge_steward import build_bundle
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        paper.chunks.extend([PaperChunk(id='ref',page=2,section='References',content='A reference'),
            PaperChunk(id='app',page=3,section='A Task Examples',content='TraceBench uses BookWorm only as a reproduced external example.')])
        db.add(KnowledgeRelation(id='r',paper_id='p',source_name='TraceBench',source_normalized_name='tracebench',
            target_name='BookWorm',target_normalized_name='bookworm',relation='builds_on',status='unresolved',
            evidence_json=json.dumps([{'chunk_id':'app','quote':'TraceBench uses BookWorm only as a reproduced external example.'}])))
        db.flush();bundle=build_bundle(db,paper)
        assert [c['chunk_id'] for c in bundle['chunks']]==['c']
        assert 'app' in {c['chunk_id'] for c in bundle['review_chunks']}
        assert bundle['coverage']=='main_text'


def test_semantically_wrong_edge_can_be_rejected_but_human_decision_is_preserved(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch,undo_changes
    from app.services.knowledge_curation import record,snapshot
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        edge=KnowledgeRelation(id='r',paper_id='p',source_name='TraceBench',source_normalized_name='tracebench',
            target_name='ReAct',target_normalized_name='react',relation='builds_on',status='unresolved',evidence_json='[]')
        db.add(edge);db.flush()
        data={'reviews':[{'relation_id':'r','verdict':'unsupported','confidence':.99,
            'reason':'Evaluation does not establish inheritance.',
            'citations':[{'chunk_id':'c','quote':'TraceBench evaluates ReAct on HotpotQA.'}]}]}
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        assert edge.status=='rejected' and report['relations_rejected']==1
        undo_changes(db,report['change_ids']);db.flush()
        assert edge.status=='unresolved'
        before=snapshot(edge);edge.status='confirmed';record(db,edge,'confirm_relation',before);db.flush()
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        assert edge.status=='confirmed' and report['protected']==1


def test_provider_call_releases_database_lock_and_rejects_stale_result(tmp_path):
    from app.services.knowledge_maintenance import prepare_run,execute_run
    database=make_db(tmp_path)
    class ConcurrentCurator:
        mode='remote';configured=True;last_usage={}
        def audit_knowledge_bundle(self,bundle):
            with database.sessions() as other:
                row=KnowledgeCandidate(id='manual',paper_id='p',name='ReAct',normalized_name='react',entity_type='method',
                    status='rejected',role='used',evidence_json='[]')
                other.add(row);other.commit()
            return batch()
    with database.sessions() as db:
        setup_paper(db);db.commit();run=prepare_run(db,scope_type='papers',paper_ids=['p'])
        execute_run(db,run,ConcurrentCurator(),max_calls=1);db.commit()
        assert run.status=='partial' and '更新' in run.error_message
        assert list(db.scalars(select(KnowledgeCandidate.name)))==['ReAct']
        assert db.get(KnowledgeCandidate,'manual').status=='rejected'


def test_incidental_example_is_removed_with_its_edges_and_can_be_undone(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch,undo_changes
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        paper.chunks[0].content += ' BookWorm is a reproduced example from a prior benchmark, not a TraceBench task.'
        obj=KnowledgeCandidate(id='example',paper_id='p',name='BookWorm',normalized_name='bookworm',
            entity_type='concept',role='used',status='confirmed',evidence_json='[]')
        edge=KnowledgeRelation(id='example-edge',paper_id='p',source_name='TraceBench',source_normalized_name='tracebench',
            target_name='BookWorm',target_normalized_name='bookworm',target_candidate_id='example',relation='requires_concept',status='candidate',evidence_json='[]')
        db.add(obj);db.flush();db.add(edge);db.flush()
        data={'object_reviews':[{'candidate_id':'example','verdict':'incidental','confidence':.99,'reason':'Wrong task owner',
            'citations':[{'chunk_id':'c','quote':'BookWorm is a reproduced example from a prior benchmark, not a TraceBench task.'}]}]}
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        assert obj.status==edge.status=='rejected'
        assert report['objects_rejected']==1 and report['relations_rejected']==1
        undo_changes(db,report['change_ids']);db.flush()
        assert obj.status=='confirmed' and edge.status=='candidate'


def test_quote_formatting_restores_complete_original_without_changing_claims(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        paper.chunks[0].content='TraceBench uses ReAct, and retains every original result. ReAct performs reasoning and acting.'
        data={'candidates':[candidate('ReAct')]}
        data['candidates'][0]['citations']=[{'chunk_id':'c','quote':'TraceBench uses ReAct ... ReAct performs reasoning and acting.'}]
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        row=db.scalar(select(KnowledgeCandidate))
        assert report['objects_confirmed']==1
        assert json.loads(row.evidence_json)[0]['quote']==paper.chunks[0].content


def test_human_confirmed_example_gets_reversible_context_without_losing_identity(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch,undo_changes
    from app.services.knowledge_curation import record,snapshot
    from app.services.serialization import knowledge_candidate_read
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        paper.chunks[0].content += ' BookWorm is a reproduced example from a prior benchmark.'
        obj=KnowledgeCandidate(id='example',paper_id='p',name='BookWorm',normalized_name='bookworm',
            entity_type='method',role='proposed',status='new',evidence_json=json.dumps([{'chunk_id':'c','quote':'BookWorm is a reproduced example from a prior benchmark.'}]))
        db.add(obj);db.flush()
        before=snapshot(obj);obj.status='confirmed';record(db,obj,'confirm_candidate',before);db.flush()
        edge=KnowledgeRelation(id='context-edge',paper_id='p',source_name='TraceBench',source_normalized_name='tracebench',
            target_name='BookWorm',target_normalized_name='bookworm',relation='builds_on',status='unresolved',evidence_json='[]')
        db.add(edge);db.flush()
        data={'object_reviews':[{'candidate_id':'example','verdict':'incidental','confidence':.99,'reason':'Reproduced example',
            'citations':[{'chunk_id':'c','quote':'BookWorm is a reproduced example from a prior benchmark.'}]}]}
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        assert obj.status=='confirmed' and obj.role=='proposed'
        context=json.loads(obj.conflict_json)['_steward_context']
        assert context['verdict']=='incidental' and context['evidence'][0]['quote'] in paper.chunks[0].content
        assert knowledge_candidate_read(obj).importance=='context'
        assert report['objects_contextualized']==1 and report['objects_rejected']==0
        assert edge.status=='rejected' and report['relations_rejected']==1
        undo_changes(db,report['change_ids']);db.flush()
        assert '_steward_context' not in json.loads(obj.conflict_json)
        assert edge.status=='unresolved'
        assert obj.status=='confirmed' and knowledge_candidate_read(obj).importance=='core'
        apply_batch(db,paper,data,build_bundle(db,paper))
        from app.services.knowledge import confirm_candidate
        confirm_candidate(db,obj,description='My corrected interpretation')
        assert '_steward_context' not in json.loads(obj.conflict_json)
        apply_batch(db,paper,data,build_bundle(db,paper))
        assert '_steward_context' not in json.loads(obj.conflict_json)


def test_example_owner_heading_can_contextualize_the_following_named_passage(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch
    from app.services.knowledge_curation import record,snapshot
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        paper.chunks.extend([PaperChunk(id='d',page=2,section='A Examples',content='The following example is reproduced from a prior benchmark.'),
            PaperChunk(id='e',page=2,section='A Examples',content='BookWorm retrieves metadata through Google Books.')])
        obj=KnowledgeCandidate(id='example',paper_id='p',name='BookWorm metadata retrieval',normalized_name='bookworm metadata retrieval',
            entity_type='task',role='used',status='new',evidence_json=json.dumps([{'chunk_id':'e','quote':'BookWorm retrieves metadata through Google Books.'}]))
        db.add(obj);db.flush();before=snapshot(obj);obj.status='confirmed';record(db,obj,'confirm_candidate',before);db.flush()
        data={'object_reviews':[{'candidate_id':'example','verdict':'incidental','confidence':.99,'reason':'Prior benchmark example',
            'citations':[{'chunk_id':'d','quote':'The following example is reproduced from a prior benchmark.'}]}]}
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        assert report['objects_contextualized']==1
        assert {e['chunk_id'] for e in json.loads(obj.conflict_json)['_steward_context']['evidence']}=={'d','e'}


def test_review_resolves_source_pronouns_without_demanding_both_labels_in_one_quote(tmp_path):
    from app.services.knowledge_steward import build_bundle,apply_batch
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db);apply_batch(db,paper,batch(),build_bundle(db,paper))
        paper.chunks.append(PaperChunk(id='d',page=2,section='Method',content='We use this agent as our fixed evaluation scaffold.'))
        objects={r.name:r for r in paper.knowledge_candidates}
        edge=KnowledgeRelation(id='review-pronoun',paper_id='p',source_name='TraceBench',source_normalized_name='tracebench',
            target_name='ReAct',target_normalized_name='react',source_candidate_id=objects['TraceBench'].id,target_candidate_id=objects['ReAct'].id,
            relation='requires_concept',status='unresolved',evidence_json=json.dumps([{'chunk_id':'d','quote':'We use this agent as our fixed evaluation scaffold.'}]))
        db.add(edge);db.flush()
        data={'reviews':[{'relation_id':edge.id,'verdict':'supported','confidence':.99,'reason':'The full source identifies the scaffold.',
            'citations':[{'chunk_id':'d','quote':'We use this agent as our fixed evaluation scaffold.'}]}]}
        report=apply_batch(db,paper,data,build_bundle(db,paper))
        assert edge.status=='confirmed' and report['relations_confirmed']==1


def test_analysis_completion_enqueues_curation_from_persisted_research_settings(tmp_path):
    from app.models import ResearchControl,KnowledgeMaintenanceRun
    from app.research_schemas import ResearchSettings
    from app.services.knowledge_maintenance import enqueue_after_analysis
    database=make_db(tmp_path)
    with database.sessions() as db:
        paper=setup_paper(db)
        db.add(ResearchControl(id=1,settings_json=ResearchSettings(enabled=True,maintenance_enabled=True).model_dump_json()))
        db.flush()
        enqueue_after_analysis(db,paper)
        run=db.scalar(select(KnowledgeMaintenanceRun))
        assert run.status=='queued' and len(run.issues)==1
        assert json.loads(run.issues[0].proposed_action_json)['paper_id']==paper.id
