import pytest
from rag.validation import rank, retrieve

def d(i,t): return {'document_id':i,'issue_tags':[t]}
A,B,C=d('a','high_latency'),d('b','high_latency'),d('c','unhealthy')
def test_adaptive_single(): assert rank('adaptive',[A,B],[B,A],['high_latency'])==[A,B]
def test_semantic_coverage(): assert rank('semantic_coverage',[A,B,C],[],['high_latency','unhealthy'],2)==[A,C]
def test_adaptive_multi(): assert {x['document_id'] for x in rank('adaptive',[A,B,C],[C,A],['high_latency','unhealthy'],2)}=={'a','c'}
def test_tag_isolation(): assert rank('semantic',[A,C],[],['high_latency'])==[A]
def test_empty(): assert rank('adaptive',[A],[],[])==[]
def test_invalid():
    with pytest.raises(ValueError): rank('invalid',[],[],[])
def test_runtime_empty(): assert retrieve(None,None,'', ['high_latency'])==[]
