"""Reproducible retrieval evaluation on the isolated Aegis v2 runbook corpus.

Corpus-label cases below are synthetic diagnostic queries, not production incidents.
The same query embedding and database connection are reused across methods.
"""
import argparse
import json
import math
import os
import re
import statistics
import time
from pathlib import Path

import psycopg
from google import genai
from psycopg.rows import dict_row

from rag.documents import load_runbooks
from rag.retrieve import (
    EMBEDDING_MODEL, CANDIDATE_LIMIT, embed_query,
    lexical_search, reciprocal_rank_fusion, semantic_search,
)

HERE = Path(__file__).resolve().parent
DATASET = HERE / "evaluation_cases.json"


def baseline_rank(documents, query, issue_tags, limit):
    """Apply the v1 overlap formula to the full 12-document corpus.

    This does not modify or call the production v1 retriever.
    """
    if not query.strip() or not issue_tags:
        return []
    terms = set(re.findall(r"[a-z]{4,}", query.lower()))
    issues = set(issue_tags)
    ranked = []
    for document in documents:
        matched_issues = len(issues.intersection(document["issue_tags"]))
        if not matched_issues:
            continue
        tokens = set(re.findall(r"[a-z]{4,}", document["content"].lower()))
        score = 10 * matched_issues + len(tokens.intersection(terms))
        ranked.append((-score, document["source_path"], document))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in ranked[:limit]]


def metrics_for_case(results, relevant, limit, allowed_tags):
    ids = [r["document_id"] for r in results[:limit]]
    positive = set(relevant)
    first = next((rank for rank, doc_id in enumerate(ids, 1) if doc_id in positive), None)
    leakage = sum(not set(row["issue_tags"]).intersection(allowed_tags) for row in results[:limit])
    return {
        "hit_at_1": float(bool(ids) and ids[0] in positive),
        "recall_at_3": len(positive.intersection(ids[:3])) / len(positive) if positive else None,
        "mrr": 1.0 / first if first else 0.0,
        "tag_leakage": leakage,
        "returned": len(ids),
        "ids": ids,
    }


def evaluate(connection, client, dataset, limit=3, print_cases=False):
    if limit < 3:
        raise ValueError("Evaluation requires limit >= 3 for Recall@3")
    documents = load_runbooks()
    known = {d["document_id"]: d for d in documents}
    if len(known) != 12:
        raise ValueError(f"Expected 12 local runbooks, found {len(known)}")
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT document_id, source_path, content_sha256, issue_tags, embedding_model, vector_dims(embedding) AS dims FROM rag_documents")
        stored = {r["document_id"]: r for r in cursor.fetchall()}
    if set(known) != set(stored):
        raise ValueError("Local runbooks and stored database document IDs differ")
    for doc_id, doc in known.items():
        row = stored[doc_id]
        if (row["source_path"] != doc["source_path"] or row["content_sha256"] != doc["content_sha256"] or
            set(row["issue_tags"]) != set(doc["issue_tags"]) or row["embedding_model"] != EMBEDDING_MODEL or row["dims"] != 768):
            raise ValueError(f"Database content/provenance/model mismatch for {doc_id}")

    names = ("overlap", "fts", "semantic", "hybrid")
    outcomes = {name: [] for name in names}
    embedding_times = []
    active_embed_count = 0
    for case in dataset:
        query, tags, relevant = case["query"], case["tags"], case["relevant"]
        if not isinstance(query, str) or not isinstance(tags, list) or not isinstance(relevant, list):
            raise ValueError(f"Malformed evaluation case: {case!r}")
        if not set(relevant) <= set(known):
            raise ValueError(f"Unknown relevant document in {case['id']}")
        if any(not set(known[r]["issue_tags"]).intersection(tags) for r in relevant):
            raise ValueError(f"Ineligible relevance label in {case['id']}")
        expected_none = not tags or not set(tags).intersection({t for d in documents for t in d['issue_tags']})
        if expected_none and relevant:
            raise ValueError(f"Negative case has relevant docs: {case['id']}")

        start = time.perf_counter()
        overlap = baseline_rank(documents, query, tags, limit)
        overlap_ms = (time.perf_counter()-start)*1000

        start = time.perf_counter()
        fts = lexical_search(connection, query, tags, limit=max(CANDIDATE_LIMIT, limit))
        fts_ms = (time.perf_counter()-start)*1000

        semantic, semantic_ms, embed_ms = [], 0.0, 0.0
        if query.strip() and tags and any(set(d["issue_tags"]) & set(tags) for d in documents):
            active_embed_count += 1
            start = time.perf_counter()
            vector = embed_query(client, query)
            embed_ms = (time.perf_counter()-start)*1000
            start = time.perf_counter()
            semantic = semantic_search(connection, vector, tags, limit=max(CANDIDATE_LIMIT, limit))
            semantic_ms = (time.perf_counter()-start)*1000
        embedding_times.append(embed_ms)
        start = time.perf_counter()
        hybrid = reciprocal_rank_fusion(semantic, fts, limit=limit)
        fusion_ms = (time.perf_counter()-start)*1000
        ranked = {"overlap": overlap, "fts": fts, "semantic": semantic, "hybrid": hybrid}
        durations = {"overlap": overlap_ms, "fts": fts_ms, "semantic": semantic_ms+embed_ms,
                     "hybrid": fts_ms+semantic_ms+embed_ms+fusion_ms}
        for method in names:
            result = metrics_for_case(ranked[method], relevant, limit, tags)
            result["latency_ms"] = durations[method]
            result["case_id"] = case["id"]
            result["group"] = case["group"]
            result["has_relevant"] = bool(relevant)
            # Expected empty output is a pass on negative cases, not a ranking hit.
            result["negative_correct"] = not result["ids"] if not relevant else None
            outcomes[method].append(result)
        if print_cases:
            print(f"{case['id']}: " + " | ".join(f"{name}={outcomes[name][-1]['ids']}" for name in names))
    summary = {}
    for method, rows in outcomes.items():
        positive = [r for r in rows if r["has_relevant"]]
        negatives = [r for r in rows if not r["has_relevant"]]
        times = [r["latency_ms"] for r in rows]
        summary[method] = {
            "positive_cases": len(positive),
            "negative_cases": len(negatives),
            "hit_at_1": statistics.mean(r["hit_at_1"] for r in positive) if positive else None,
            "recall_at_3": statistics.mean(r["recall_at_3"] for r in positive) if positive else None,
            "mrr": statistics.mean(r["mrr"] for r in positive) if positive else None,
            "negative_rejection_rate": statistics.mean(r["negative_correct"] for r in negatives) if negatives else None,
            "tag_leakage_count": sum(r["tag_leakage"] for r in rows),
            "mean_latency_ms": statistics.mean(times),
            "median_latency_ms": statistics.median(times),
            "p95_latency_ms": sorted(times)[math.ceil(.95*len(times))-1],
        }
    return {
        "metadata": {
            "cases": len(dataset), "documents": len(known), "model": EMBEDDING_MODEL,
            "scope": "synthetic curated runbook retrieval; not production incident accuracy",
            "shared_embedding_mean_ms": statistics.mean([x for x in embedding_times if x > 0]) if active_embed_count else None,
            "active_embedding_requests": active_embed_count,
            "latencies": "Sequential timings; hybrid sums the component stages; not concurrent end-to-end timing",
        }, "summary": summary, "cases": outcomes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("AEGIS_VECTOR_DATABASE_URL"))
    parser.add_argument("--output", default="/tmp/aegis-retrieval-evaluation.json")
    parser.add_argument("--print-cases", action="store_true")
    args = parser.parse_args()
    if not args.database_url or not os.getenv("GEMINI_API_KEY"):
        parser.error("AEGIS_VECTOR_DATABASE_URL and GEMINI_API_KEY are required")
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    ids = [case["id"] for case in dataset]
    if len(ids) != len(set(ids)):
        parser.error("Duplicate evaluation case IDs")
    with psycopg.connect(args.database_url, autocommit=True) as connection:
        report = evaluate(connection, genai.Client(api_key=os.environ["GEMINI_API_KEY"]), dataset, print_cases=args.print_cases)
    for name, metrics in report["summary"].items():
        def pct(value): return f"{100*value:.1f}%" if value is not None else "n/a"
        print(f"{name:8} Hit@1={pct(metrics['hit_at_1'])} Recall@3={pct(metrics['recall_at_3'])} MRR={metrics['mrr']:.3f} "
              f"Negative={pct(metrics['negative_rejection_rate'])} TagLeakage={metrics['tag_leakage_count']} "
              f"Mean={metrics['mean_latency_ms']:.1f}ms P95={metrics['p95_latency_ms']:.1f}ms")
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved evaluation report to {args.output}")

if __name__ == "__main__":
    main()
