"""Frozen retrieval strategies and shared-embedding validation."""
import json, os, statistics, time, hashlib
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from google import genai
from rag.documents import load_runbooks
from rag.retrieve import embed_query, semantic_search, EMBEDDING_MODEL
from rag.optimized import relaxed_lexical_search, weighted_rrf, select_with_coverage
from rag.evaluation import metrics_for_case

STRATEGIES = ('semantic', 'semantic_coverage', 'weighted_coverage', 'adaptive')

def rank(strategy, semantic, lexical, tags, limit=3):
    if strategy not in STRATEGIES or limit <= 0:
        raise ValueError('Invalid strategy or limit')
    tags = set(tags)
    semantic = [d for d in semantic if tags.intersection(d['issue_tags'])]
    lexical = [d for d in lexical if tags.intersection(d['issue_tags'])]
    if strategy == 'semantic' or (strategy == 'adaptive' and len(tags) <= 1):
        return semantic[:limit]
    if strategy == 'semantic_coverage':
        return select_with_coverage(semantic, tags, limit)
    fused = weighted_rrf(semantic, lexical, lexical_weight=.25, k=60, limit=max(20, limit*2))
    return select_with_coverage(fused, tags, limit)

def retrieve(connection, client, query, tags, strategy='adaptive', limit=3):
    if strategy not in STRATEGIES or limit <= 0:
        raise ValueError('Invalid strategy or limit')
    tags = sorted(set(tags) & {t for d in load_runbooks() for t in d['issue_tags']})
    if not tags or not query.strip():
        return []
    semantic = semantic_search(connection, embed_query(client, query), tags, limit=max(10,limit))
    lexical = relaxed_lexical_search(connection, query, tags, limit=max(10,limit)) if strategy == 'weighted_coverage' or (strategy == 'adaptive' and len(tags)>1) else []
    return rank(strategy, semantic, lexical, tags, limit)

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--dataset', default=str(Path(__file__).with_name('validation_cases.json')))
    args = p.parse_args()
    raw = Path(args.dataset).read_bytes()
    cases = json.loads(raw)
    docs = {d['document_id']:d for d in load_runbooks()}
    tags_known = {t for d in docs.values() for t in d['issue_tags']}
    if len({c['id'] for c in cases}) != len(cases): raise ValueError('Duplicate case IDs')
    outcomes = {s:[] for s in STRATEGIES}
    with psycopg.connect(os.environ['AEGIS_VECTOR_DATABASE_URL'], autocommit=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT document_id, content, content_sha256, source_path, issue_tags, embedding_model, vector_dims(embedding) AS dims FROM rag_documents')
            stored = {d['document_id']:d for d in cur.fetchall()}
        if set(stored)!=set(docs): raise ValueError('Corpus IDs mismatch')
        for key,d in docs.items():
            r=stored[key]
            if hashlib.sha256(r['content'].encode()).hexdigest()!=d['content_sha256'] or r['content_sha256']!=d['content_sha256'] or r['source_path']!=d['source_path'] or set(r['issue_tags'])!=set(d['issue_tags']) or r['embedding_model']!=EMBEDDING_MODEL or r['dims']!=768: raise ValueError('Corpus mismatch: '+key)
        client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        for c in cases:
            tags=sorted(set(c['tags']) & tags_known)
            if any(r not in docs or not set(docs[r]['issue_tags']) & set(tags) for r in c['relevant']): raise ValueError('Invalid labels: '+c['id'])
            sem,lex=[],[]
            sem_ms=lex_ms=0
            if tags and c['query'].strip():
                start=time.perf_counter(); sem=semantic_search(conn,embed_query(client,c['query']),tags,limit=10); sem_ms=(time.perf_counter()-start)*1000
                start=time.perf_counter(); lex=relaxed_lexical_search(conn,c['query'],tags,limit=10); lex_ms=(time.perf_counter()-start)*1000
            for s in STRATEGIES:
                start=time.perf_counter(); result=rank(s,sem,lex,tags); rank_ms=(time.perf_counter()-start)*1000
                row=metrics_for_case(result,c['relevant'],3,c['tags'])
                covered={t for d in result for t in d['issue_tags']}
                row.update(case=c, coverage=len(covered & set(tags))/len(tags) if tags else None, latency_ms=sem_ms+rank_ms+(lex_ms if s=='weighted_coverage' or (s=='adaptive' and len(tags)>1) else 0))
                outcomes[s].append(row)
            print('Completed',c['id'],flush=True)
    summary={}
    for s,rows in outcomes.items():
        pos=[r for r in rows if r['case']['relevant']]; neg=[r for r in rows if not r['case']['relevant']]; multi=[r for r in pos if len(set(r['case']['tags']))>1]
        m=dict(hit_at_1=statistics.mean(r['hit_at_1'] for r in pos),recall_at_3=statistics.mean(r['recall_at_3'] for r in pos),mrr_at_3=statistics.mean(r['mrr'] for r in pos),multi_recall=statistics.mean(r['recall_at_3'] for r in multi),multi_coverage=statistics.mean(r['coverage'] for r in multi),negative_rejection=statistics.mean(not r['ids'] for r in neg),tag_leakage=sum(r['tag_leakage'] for r in rows),positive_mean_component_ms=statistics.mean(r['latency_ms'] for r in pos))
        summary[s]=m
        print(s,json.dumps(m))
    Path(args.output).write_text(json.dumps(dict(metadata=dict(dataset_sha256=hashlib.sha256(raw).hexdigest(),cases=len(cases),documents=len(docs),model=EMBEDDING_MODEL,scope='fresh synthetic queries; shared component timings, not runtime latency'),summary=summary,cases=outcomes),indent=2))
if __name__=='__main__': main()
