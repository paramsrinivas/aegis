"""Development evaluation of experimental retrieval strategies."""

import argparse
import json
import os
import statistics
from pathlib import Path

import psycopg
from google import genai

from rag.documents import load_runbooks
from rag.evaluation import DATASET, metrics_for_case
from rag.retrieve import (
    embed_query,
    semantic_search,
    lexical_search,
    reciprocal_rank_fusion,
)
from rag.optimized import (
    relaxed_lexical_search,
    weighted_rrf,
    select_with_coverage,
)


def evaluate(connection, client, dataset):
    documents = load_runbooks()
    known = {d["document_id"]: d for d in documents}
    known_tags = {
        tag for d in documents for tag in d["issue_tags"]
    }

    names = [
        "semantic",
        "original_hybrid",
        "relaxed_fts",
        "relaxed_hybrid",
        "weighted_050",
        "weighted_025",
        "weighted_coverage",
    ]

    outcomes = {name: [] for name in names}

    for case in dataset:
        query = case["query"]
        tags = case["tags"]
        relevant = case["relevant"]

        assert set(relevant) <= set(known)

        assert all(
            set(known[r]["issue_tags"]).intersection(tags)
            for r in relevant
        )

        semantic = []
        original = []
        relaxed = []

        if query.strip() and set(tags) & known_tags:
            vector = embed_query(client, query)

            semantic = semantic_search(
                connection, vector, tags, limit=10
            )

            original = lexical_search(
                connection, query, tags, limit=10
            )

            relaxed = relaxed_lexical_search(
                connection, query, tags, limit=10
            )

        weighted = weighted_rrf(
            semantic,
            relaxed,
            lexical_weight=0.25,
            limit=20,
        )

        ranked = {
            "semantic": semantic,
            "original_hybrid": reciprocal_rank_fusion(
                semantic, original, limit=3
            ),
            "relaxed_fts": relaxed,
            "relaxed_hybrid": weighted_rrf(
                semantic, relaxed,
                lexical_weight=1.0, limit=3
            ),
            "weighted_050": weighted_rrf(
                semantic, relaxed,
                lexical_weight=0.5, limit=3
            ),
            "weighted_025": weighted[:3],
            "weighted_coverage": select_with_coverage(
                weighted, tags, limit=3
            ),
        }

        for name, results in ranked.items():
            row = metrics_for_case(
                results, relevant, 3, tags
            )

            covered = {
                tag
                for document in results[:3]
                for tag in document["issue_tags"]
            }

            row.update({
                "case_id": case["id"],
                "group": case["group"],
                "query": query,
                "tags": tags,
                "relevant": relevant,
                "has_relevant": bool(relevant),
                "negative_correct": (
                    not row["ids"] if not relevant else None
                ),
                "issue_coverage": (
                    len(covered.intersection(tags))
                    / len(set(tags)) if tags else None
                ),
            })

            outcomes[name].append(row)

        print(f"Completed {case['id']}", flush=True)

    summary = {}

    for name, rows in outcomes.items():
        positive = [
            r for r in rows if r["has_relevant"]
        ]

        negative = [
            r for r in rows if not r["has_relevant"]
        ]

        multi = [
            r for r in positive if r["group"] == "multi"
        ]

        summary[name] = {
            "hit_at_1": statistics.mean(
                r["hit_at_1"] for r in positive
            ),
            "recall_at_3": statistics.mean(
                r["recall_at_3"] for r in positive
            ),
            "mrr_at_3": statistics.mean(
                r["mrr"] for r in positive
            ),
            "multi_issue_recall": statistics.mean(
                r["recall_at_3"] for r in multi
            ) if multi else None,
            "multi_issue_coverage": statistics.mean(
                r["issue_coverage"] for r in multi
            ) if multi else None,
            "negative_rejection": statistics.mean(
                r["negative_correct"] for r in negative
            ) if negative else None,
            "tag_leakage": sum(
                r["tag_leakage"] for r in rows
            ),
            "empty_positive_results": sum(
                not r["ids"] for r in positive
            ),
        }

    return {
        "metadata": {
            "cases": len(dataset),
            "documents": len(documents),
            "scope": "Synthetic development evaluation",
            "held_out": False,
            "shared_embeddings": True,
        },
        "summary": summary,
        "cases": outcomes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset", default=str(DATASET)
    )
    parser.add_argument(
        "--output",
        default="/tmp/optimization_evaluation.json",
    )
    args = parser.parse_args()

    dataset = json.loads(
        Path(args.dataset).read_text(encoding="utf-8")
    )

    with psycopg.connect(
        os.environ["AEGIS_VECTOR_DATABASE_URL"],
        autocommit=True,
    ) as connection:
        report = evaluate(
            connection,
            genai.Client(
                api_key=os.environ["GEMINI_API_KEY"]
            ),
            dataset,
        )

    print("\n=== OPTIMIZATION RESULTS ===\n")

    for name, m in report["summary"].items():
        print(
            f"{name:20} "
            f"Hit@1={m['hit_at_1']:.1%} "
            f"Recall@3={m['recall_at_3']:.1%} "
            f"MRR={m['mrr_at_3']:.3f} "
            f"MultiRecall={m['multi_issue_recall']:.1%} "
            f"Coverage={m['multi_issue_coverage']:.1%} "
            f"Leakage={m['tag_leakage']} "
            f"Empty={m['empty_positive_results']}"
        )

    Path(args.output).write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(f"\nSaved report to {args.output}")


if __name__ == "__main__":
    main()
