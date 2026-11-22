# 016: HNSW or IVFFlat

Stage: S6 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

No vector index now: `rag.chunks` is scanned exactly. At about a million chunks, an HNSW index with `vector_cosine_ops` (the operator `retrieve` orders by, `<=>`). The trigger to add it is retrieval time rather than a chunk count: when `retrieve` in the Langfuse traces is no longer a small fraction of an answer's time, or the chunk count nears 100,000, whichever comes first, and the instance has memory for it.

## Rejected alternative

IVFFlat. It builds faster and takes less memory, but it needs rows to exist before it is built (its bucket centres come from the data), and as the wiki's content changes the buckets go stale and recall drops until the index is rebuilt, which would be a recurring job for a wiki that is refreshed daily. HNSW takes new rows as they come and needs no rebuild.

## Why

<!-- Student: rewrite in your own words. -->
Today there are 22 chunks. An exact scan takes tens of milliseconds (27 to 45 ms for `retrieve` in the three traces of 2026-11-22, connection included) against 25 to 35 s for the LLM to generate, so an index would add nothing a rider can feel, and an approximate index could only lower recall from the exact 100%. IVFFlat with this few rows would have `lists = 1`, which is no index at all.

At a million chunks the picture changes: 768 dimensions at 4 bytes is about 3 KB a vector, so about 3 GB of vectors before any index, and the RDS instance this lab runs (micro or small, 1 to 2 GB of memory) could not hold an index in memory. HNSW gives the best recall and speed and copes with daily small changes, but it uses the most memory and has the longest first build. At that size the answer is probably a bigger instance, and `halfvec` or quantization to shrink the vectors, as well as the index.

## What would show this was wrong

- `retrieve` getting slow as the wiki grows (visible in the trace as the `retrieve` span), or chunk counts growing faster than expected, which would bring the trigger forward.
- After adding HNSW: answers missing a page that an exact scan finds (recall too low: raise `ef_search`), or queries returning fewer than the top 3 chunks because the `embedding is not null` filter removes candidates (pgvector 0.8's iterative scans).
- The index not fitting in the instance's memory, which would show as slow queries after the build.
