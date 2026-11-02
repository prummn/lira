from app.services.knowledge_view import classify_candidate, classify_relation


def test_candidate_presentation_separates_core_method_from_ablation_and_component():
    assert classify_candidate('method', 'ReAct', 'proposed', '') == ('primary', 'core')
    assert classify_candidate('method', 'Chain-of-thought', 'baseline', '') == ('baseline', 'supporting')
    assert classify_candidate('method', 'ReAct-IM', 'compared', '') == ('ablation', 'context')
    assert classify_candidate('concept', 'thought', 'proposed', '') == ('component', 'supporting')
    assert classify_candidate('method', 'ReAct reasoning module', 'component', '') == ('component', 'supporting')
    assert classify_candidate('benchmark', 'HotPotQA', 'used', '') == ('evaluation', 'core')


def test_relation_presentation_keeps_lineage_above_evaluation_and_ablation_comparisons():
    assert classify_relation('extends', 'ReAct') == ('lineage', 'core')
    assert classify_relation('evaluated_on', 'HotPotQA') == ('evaluation', 'supporting')
    assert classify_relation('compares_with', 'ReAct-IM') == ('ablation', 'context')
    assert classify_relation('compares_with', 'Chain-of-thought') == ('comparison', 'supporting')
    assert classify_relation('requires_concept', 'thought') == ('dependency', 'supporting')
