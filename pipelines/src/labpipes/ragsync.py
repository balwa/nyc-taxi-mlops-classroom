"""The wiki RAG branch's logic (S6), apart from Dagster: what to fetch, what to chunk, what to embed.

The assets in defs/rag.py call these with the real wiki, the real embedding server and Postgres (PgStore);
the tests call them with fakes. Everything is incremental: a page that hasn't changed costs a 304, a
chunk whose text hasn't changed keeps its hash and its vector, and only chunks with no vector are embedded.
"""

from __future__ import annotations

from typing import Protocol

from .chunking import chunk_markdown

SCHEMA = [
    "create extension if not exists vector",
    "create schema if not exists rag",
    # One row per wiki page, with the ETag we last saw and the body, so chunking never needs the wiki again.
    """create table if not exists rag.pages (
        id text primary key, title text not null, updated_at text not null, etag text not null,
        body text not null, fetched_at timestamptz not null default now())""",
    # One row per chunk. id is Chunk.content_hash, so the same text keeps its id; embedding is null until embedded.
    # No vector index yet: which kind (HNSW or IVFFlat) is decision 016.
    """create table if not exists rag.chunks (
        id text primary key, page_id text not null references rag.pages(id) on delete cascade,
        chunk_index int not null, heading text not null, title text not null, content text not null,
        tokens int not null, embedding vector(768))""",
]


class Store(Protocol):
    def known_etags(self) -> dict[str, str]: ...
    def upsert_page(self, page) -> None: ...
    def delete_pages(self, ids: list[str]) -> None: ...
    def pages(self) -> list[tuple[str, str, str]]: ...  # (id, title, body)
    def chunk_ids(self, page_id: str) -> set[str]: ...
    def insert_chunk(self, chunk_id: str, page_id: str, title: str, chunk) -> None: ...
    def delete_chunks(self, ids: list[str]) -> None: ...
    def unembedded(self) -> list[tuple[str, str]]: ...  # (id, text)
    def set_embedding(self, chunk_id: str, vector: list[float]) -> None: ...
    def counts(self) -> tuple[int, int]: ...  # (chunks, chunks without a vector)


def sync_pages(wiki, store: Store) -> dict[str, int]:
    """Conditional GET for every listed page with the ETag we stored; keep what changed, drop what's gone."""
    refs = wiki.pages()
    known = store.known_etags()
    fetched = unchanged = 0
    for ref in refs:
        page = wiki.page(ref.id, known.get(ref.id))
        if page is None:  # 304: no body sent
            unchanged += 1
            continue
        store.upsert_page(page)
        fetched += 1
    gone = sorted(set(known) - {r.id for r in refs})
    if gone:
        store.delete_pages(gone)
    return {"pages_listed": len(refs), "pages_fetched": fetched, "pages_unchanged": unchanged, "pages_removed": len(gone)}


def sync_chunks(store: Store, max_tokens: int, overlap_tokens: int) -> dict[str, int]:
    """Chunk every stored page and reconcile with the table by content hash: new text is inserted, text
    that's no longer on its page is deleted, and the rest is left alone (keeping its vector)."""
    new = removed = total = 0
    for page_id, title, body in store.pages():
        wanted = {c.content_hash(page_id): c for c in chunk_markdown(title, body, max_tokens, overlap_tokens)}
        have = store.chunk_ids(page_id)
        for chunk_id, chunk in wanted.items():
            if chunk_id not in have:
                store.insert_chunk(chunk_id, page_id, title, chunk)
                new += 1
        stale = sorted(have - set(wanted))
        if stale:
            store.delete_chunks(stale)
            removed += len(stale)
        total += len(wanted)
    return {"chunks_total": total, "chunks_new": new, "chunks_removed": removed}


def embed_missing(store: Store, embed) -> dict[str, int]:
    """Embed only the chunks that have no vector yet (documents get the search_document: prefix inside `embed`)."""
    todo = store.unembedded()
    if todo:
        for (chunk_id, _), vector in zip(todo, embed.embed_documents([text for _, text in todo]), strict=True):
            store.set_embedding(chunk_id, vector)
    return {"chunks_embedded": len(todo)}


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


class PgStore:
    """Store on the `rag` database (resource RagStore.connect: psycopg2, autocommit off, one commit per call)."""

    def __init__(self, conn):
        self.conn = conn

    def _run(self, sql: str, params: tuple = (), fetch: bool = False):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if fetch else None
        self.conn.commit()
        return rows

    def ensure_schema(self) -> None:
        for statement in SCHEMA:
            self._run(statement)

    def known_etags(self) -> dict[str, str]:
        return dict(self._run("select id, etag from rag.pages", fetch=True))

    def upsert_page(self, page) -> None:
        self._run(
            """insert into rag.pages (id, title, updated_at, etag, body) values (%s, %s, %s, %s, %s)
               on conflict (id) do update set title = excluded.title, updated_at = excluded.updated_at,
               etag = excluded.etag, body = excluded.body, fetched_at = now()""",
            (page.id, page.title, page.updated_at, page.etag, page.body),
        )

    def delete_pages(self, ids: list[str]) -> None:
        self._run("delete from rag.pages where id = any(%s)", (ids,))

    def pages(self) -> list[tuple[str, str, str]]:
        return self._run("select id, title, body from rag.pages order by id", fetch=True)

    def chunk_ids(self, page_id: str) -> set[str]:
        return {r[0] for r in self._run("select id from rag.chunks where page_id = %s", (page_id,), fetch=True)}

    def insert_chunk(self, chunk_id: str, page_id: str, title: str, chunk) -> None:
        self._run(
            """insert into rag.chunks (id, page_id, chunk_index, heading, title, content, tokens)
               values (%s, %s, %s, %s, %s, %s, %s) on conflict (id) do nothing""",
            (chunk_id, page_id, chunk.index, chunk.heading, title, chunk.text, chunk.tokens),
        )

    def delete_chunks(self, ids: list[str]) -> None:
        self._run("delete from rag.chunks where id = any(%s)", (ids,))

    def unembedded(self) -> list[tuple[str, str]]:
        return self._run("select id, content from rag.chunks where embedding is null order by id", fetch=True)

    def set_embedding(self, chunk_id: str, vector: list[float]) -> None:
        self._run("update rag.chunks set embedding = %s::vector where id = %s", (vector_literal(vector), chunk_id))

    def counts(self) -> tuple[int, int]:
        return self._run("select count(*), count(*) filter (where embedding is null) from rag.chunks", fetch=True)[0]
