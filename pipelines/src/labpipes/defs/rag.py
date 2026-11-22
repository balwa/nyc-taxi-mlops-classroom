"""S6: the wiki RAG branch, in the `rag` database on RDS (pgvector), on a daily schedule.

- wiki_pages: the published pages from the ops wiki (resource `wiki`: labpipes/wiki.py). Each page's ETag
  is stored and sent next time: an unchanged page costs a 304 and no body.
- wiki_chunks: changed text split with labpipes.chunking.chunk_markdown, stored under Chunk.content_hash,
  so unchanged text keeps its id (and its vector).
- wiki_embeddings: only chunks without a vector are embedded (resource `embed`: nomic-embed-text, 768
  dimensions) and stored as pgvector vector(768).
- every_chunk_has_a_vector: blocking check on wiki_embeddings.
- ingest_wiki: the job for the three (scripts/dagster-run.sh ingest_wiki --wait) and its daily schedule.
The logic is in labpipes/ragsync.py, so tests can run it with fakes.

Open decisions: chunk size and overlap (015) and the vector index, HNSW or IVFFlat (016). The two numbers
below are provisional until the evaluation (scripts/rag-eval.py) has been read and 015 is written.
"""

import dagster as dg

from ..ragsync import PgStore, embed_missing, sync_chunks, sync_pages
from ..resources import LlmEmbed, RagStore, WikiApi

MAX_TOKENS = 200  # provisional, decision 015
OVERLAP_TOKENS = 40  # provisional, decision 015


def _int(n: int) -> dg.MetadataValue:
    return dg.MetadataValue.int(int(n))


@dg.asset(group_name="rag", kinds={"postgres"}, description="The wiki's pages, fetched with conditional GETs.")
def wiki_pages(wiki: WikiApi, rag: RagStore) -> dg.MaterializeResult:
    conn = rag.connect()
    try:
        store = PgStore(conn)
        store.ensure_schema()
        result = sync_pages(wiki.client(), store)
    finally:
        conn.close()
    return dg.MaterializeResult(metadata={k: _int(v) for k, v in result.items()})


@dg.asset(group_name="rag", kinds={"postgres"}, deps=[wiki_pages], description="Pages split into content-hashed chunks.")
def wiki_chunks(rag: RagStore) -> dg.MaterializeResult:
    conn = rag.connect()
    try:
        result = sync_chunks(PgStore(conn), MAX_TOKENS, OVERLAP_TOKENS)
    finally:
        conn.close()
    meta = {k: _int(v) for k, v in result.items()}
    meta.update(max_tokens=_int(MAX_TOKENS), overlap_tokens=_int(OVERLAP_TOKENS))
    return dg.MaterializeResult(metadata=meta)


@dg.asset(group_name="rag", kinds={"postgres"}, deps=[wiki_chunks], description="Vectors for the chunks that have none.")
def wiki_embeddings(embed: LlmEmbed, rag: RagStore) -> dg.MaterializeResult:
    conn = rag.connect()
    try:
        result = embed_missing(PgStore(conn), embed)
    finally:
        conn.close()
    return dg.MaterializeResult(metadata={k: _int(v) for k, v in result.items()})


@dg.asset_check(asset=wiki_embeddings, blocking=True, description="There are chunks, and every one has a vector.")
def every_chunk_has_a_vector(rag: RagStore) -> dg.AssetCheckResult:
    conn = rag.connect()
    try:
        chunks, missing = PgStore(conn).counts()
    finally:
        conn.close()
    return dg.AssetCheckResult(
        passed=chunks > 0 and missing == 0,
        severity=dg.AssetCheckSeverity.ERROR,
        description=f"{chunks} chunk(s), {missing} without a vector",
        metadata={"chunks": _int(chunks), "without_vector": _int(missing)},
    )


ingest_wiki = dg.define_asset_job(
    "ingest_wiki",
    selection=dg.AssetSelection.assets(wiki_pages, wiki_chunks, wiki_embeddings),
    description="Fetch changed wiki pages, chunk them, embed the new chunks, and check every chunk has a vector.",
)

daily_wiki = dg.ScheduleDefinition(
    job=ingest_wiki,
    cron_schedule="0 6 * * *",  # 06:00 UTC, daily
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
