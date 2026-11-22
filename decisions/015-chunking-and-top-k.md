# 015: Chunk size, overlap and top-k

Stage: S6 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Chunks of at most 100 tokens with 20 tokens of overlap (`MAX_TOKENS` and `OVERLAP_TOKENS` in `pipelines/src/labpipes/defs/rag.py`), and the top 3 chunks by cosine distance for every question (`TOP_K` in `app/src/rideapp/assistant.py`).

## Rejected alternative

Whole pages as chunks (200 tokens or more, 16 chunks: no page is longer than 188 tokens, so overlap does nothing), and top-k of 5. Pages as chunks scored lower on the first hits (69% at k=1 against 75%). Top-5 reaches 94% instead of 88%, but each extra chunk costs about 11 s of prompt processing on the CPU LLM host, which with generation puts an answer close to the 120 s clients are told to wait.

## Why

<!-- Student: rewrite in your own words. -->
Evidence: `scripts/rag-eval.py` with 16 questions written from the wiki (`evals/wiki-questions.yaml`), on 2026-11-22, with the real embedding model:

| max tokens / overlap | chunks | hit@1 | hit@2 | hit@3 | hit@5 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| 100 / 0 | 22 | 75% | 81% | 88% | 94% | 0.855 |
| 100 / 20 | 22 | 75% | 75% | 88% | 94% | 0.851 |
| 200 / 40 | 16 | 69% | 69% | 88% | 94% | 0.818 |

The wiki's pages are 62 to 188 tokens, so chunk size changes little: 100 tokens splits the longer pages and is slightly better at the top ranks. Overlap did not help on this wiki (100/0 and 100/20 are within a question of each other), and was kept at 20 because a page that grows will be split and a rule can then straddle two chunks. Top-3 is where most of the gain is: from k=1 to k=3 the hit rate rises by 13 points, and k=5 adds only 6 more for about 22 s more prompt time.

Two questions missed at k=3 in every setting: "Why does my quoted ETA from JFK include 7 extra minutes?" (`airport-buffer` lost to `eta-quoting`, `eta-complaints` and `rider-faq`) and "Why is my ETA 12 percent higher near Times Square on weekday evenings?" (`blue-corridor`). Both are generic "why is my ETA..." questions that match the ETA pages better than the policy behind them, which chunk size can't fix. 16 questions is a small sample: one question is 6 points.

## What would show this was wrong

- Answers that cite the wrong page, or "I don't know" for something the wiki does say. Traces in Langfuse show which chunks came back.
- The wiki growing to pages of thousands of tokens, or to hundreds of pages: re-run the evaluation with new questions; top-3 may no longer hold the right chunk.
- Latency: an answer over the 120 s clients wait, or users complaining it is slow, would argue for k=2 even at the cost of recall.
