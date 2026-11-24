"""Pure metric and baseline tests; no network/database access required."""
import pytest
from rag.evaluation import baseline_rank, metrics_for_case


def doc(doc_id, tag, content):
    return {"document_id":doc_id,"source_path":f"runbooks/{doc_id}.md","issue_tags":[tag],"content":content}


def test_baseline_tag_filter_and_order():
    docs=[doc('a','high_latency','CPU queue'),doc('b','high_latency','CPU queue queue'),doc('c','unhealthy','CPU queue')]
    rows=baseline_rank(docs,'CPU queue',['high_latency'],3)
    assert [d['document_id'] for d in rows]==['a','b']


def test_negative_baseline():
    assert baseline_rank([doc('a','high_latency','CPU')],'CPU',[],3)==[]


def test_metrics_multiple_relevant():
    docs=[doc('a','high_latency',''),doc('b','high_latency',''),doc('c','high_latency','')]
    result=metrics_for_case(docs,['b','c'],3,['high_latency'])
    assert result['hit_at_1']==0
    assert result['recall_at_3']==1
    assert result['mrr']==0.5
    assert result['tag_leakage']==0


def test_metrics_leakage():
    rows=[doc('bad','unhealthy','')]
    result=metrics_for_case(rows,['good'],3,['high_latency'])
    assert result['tag_leakage']==1
