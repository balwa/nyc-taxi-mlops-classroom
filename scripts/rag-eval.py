#!/usr/bin/env python3
"""Retrieval evaluation for decision 015: how often is a right wiki page among the top k chunks?

  # 1. a tunnel to the embedding server (the LLM host has no public address), in another terminal:
  aws ssm start-session --target <app instance id> --document-name AWS-StartPortForwardingSessionToRemoteHost \\
      --parameters host=<llm_private_ip>,portNumber=8081,localPortNumber=8081
  # 2. the evaluation (reads the wiki through lab/wiki, like the pipeline; needs AWS credentials):
  uv run --project pipelines python scripts/rag-eval.py [--embed-url http://127.0.0.1:8081]

For each chunk setting it chunks every page, embeds the chunks as documents and the questions as queries
(nomic-embed-text's prefixes), ranks chunks by cosine distance, and prints hit rate and mean reciprocal
rank at k = 1, 2, 3, 5. Nothing is written to the database. Settings are `max_tokens/overlap` pairs; the
defaults span the interesting range for pages of 60 to 190 tokens (the setting only matters below ~200).
"""

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipelines" / "src"))
from labpipes.chunking import chunk_markdown
from labpipes.wiki import Wiki

KS = (1, 2, 3, 5)


def embed(url: str, texts: list[str], prefix: str) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 8):
        body = json.dumps({"input": [f"{prefix}{t}" for t in texts[i : i + 8]], "model": "embed"}).encode()
        req = urllib.request.Request(f"{url}/v1/embeddings", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out += [d["embedding"] for d in sorted(json.load(r)["data"], key=lambda d: d["index"])]
    return out


def cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return 1 - dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def is_hit(question: dict, top: list[str]) -> bool:
    want = set(question["expected"])
    return want <= set(top) if question.get("all") else bool(want & set(top))


def evaluate(pages, questions, qvecs, url, max_tokens, overlap):
    chunks = [(p["id"], c) for p in pages for c in chunk_markdown(p["title"], p["body"], max_tokens, overlap)]
    vecs = embed(url, [c.text for _, c in chunks], "search_document: ")
    hits = {k: 0 for k in KS}
    rr = 0.0
    misses: list[str] = []
    for q, qv in zip(questions, qvecs, strict=True):
        ranked = [pid for _, pid in sorted(((cosine_distance(qv, v), pid) for v, (pid, _) in zip(vecs, chunks, strict=True)))]
        want = set(q["expected"])
        for k in KS:
            hits[k] += is_hit(q, ranked[:k])
        first = next((i for i, pid in enumerate(ranked, 1) if pid in want), None)
        rr += 1 / first if first else 0
        if not is_hit(q, ranked[:3]):
            misses.append(f"    miss at k=3: {q['id']} (wanted {sorted(want)}, got {list(dict.fromkeys(ranked))[:3]})")
    return len(chunks), hits, rr, misses


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed-url", default="http://127.0.0.1:8081")
    ap.add_argument("--settings", default="100/0,100/20,200/40", help="max_tokens/overlap pairs, comma separated")
    ap.add_argument("--questions", default=str(ROOT / "evals" / "wiki-questions.yaml"))
    args = ap.parse_args()

    questions = yaml.safe_load(Path(args.questions).read_text())["questions"]
    wiki = Wiki.from_secret()
    pages = [p.__dict__ for p in (wiki.page(r.id) for r in wiki.pages())]
    qvecs = embed(args.embed_url, [q["question"] for q in questions], "search_query: ")
    print(f"{len(pages)} pages, {len(questions)} questions")
    print(f"{'setting':>9} {'chunks':>6}  " + "  ".join(f"hit@{k}" for k in KS) + "    MRR")
    for s in args.settings.split(","):
        mt, ov = (int(x) for x in s.split("/"))
        n, hits, rr, misses = evaluate(pages, questions, qvecs, args.embed_url, mt, ov)
        print(f"{s:>9} {n:>6}  " + "  ".join(f"{hits[k] / len(questions):>5.0%}" for k in KS) + f"  {rr / len(questions):.3f}")
        for m in misses:
            print(m)


if __name__ == "__main__":
    main()
