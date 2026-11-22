"""The wiki branch's incremental logic with fakes: a second run fetches nothing and embeds nothing."""

from dataclasses import dataclass

from labpipes.chunking import chunk_markdown
from labpipes.ragsync import embed_missing, sync_chunks, sync_pages


@dataclass
class Page:
    id: str
    title: str
    updated_at: str
    etag: str
    body: str


class FakeWiki:
    def __init__(self, pages: dict[str, Page]):
        self.pages_, self.gets = pages, []

    def pages(self):
        return list(self.pages_.values())

    def page(self, page_id, etag=None):
        self.gets.append((page_id, etag))
        p = self.pages_[page_id]
        return None if etag == p.etag else p


class FakeEmbed:
    def __init__(self):
        self.seen: list[str] = []

    def embed_documents(self, texts):
        self.seen += texts
        return [[float(len(t))] * 3 for t in texts]


class FakeStore:
    def __init__(self):
        self.p, self.c = {}, {}  # pages by id; chunks by id: dict(page_id, text, vec)

    def known_etags(self):
        return {i: p.etag for i, p in self.p.items()}

    def upsert_page(self, page):
        self.p[page.id] = page

    def delete_pages(self, ids):
        for i in ids:
            self.p.pop(i, None)
            self.c = {k: v for k, v in self.c.items() if v["page_id"] != i}

    def pages(self):
        return [(i, p.title, p.body) for i, p in sorted(self.p.items())]

    def chunk_ids(self, page_id):
        return {k for k, v in self.c.items() if v["page_id"] == page_id}

    def insert_chunk(self, chunk_id, page_id, title, chunk):
        self.c[chunk_id] = {"page_id": page_id, "text": chunk.text, "vec": None}

    def delete_chunks(self, ids):
        for i in ids:
            self.c.pop(i, None)

    def unembedded(self):
        return [(k, v["text"]) for k, v in sorted(self.c.items()) if v["vec"] is None]

    def set_embedding(self, chunk_id, vector):
        self.c[chunk_id]["vec"] = vector

    def counts(self):
        return len(self.c), sum(v["vec"] is None for v in self.c.values())


def pages(**bodies):
    return {i: Page(i, i.title(), "t", f'"{hash(b) & 0xffff}"', b) for i, b in bodies.items()}


A = "# A\n\nFirst rule about airports.\n"
B = "# B\n\n" + "Second rule about quiet hours. " * 3 + "\n"


def run(wiki, store, embed):
    return sync_pages(wiki, store), sync_chunks(store, 200, 40), embed_missing(store, embed)


def test_first_run_fetches_chunks_and_embeds_everything():
    wiki, store, embed = FakeWiki(pages(a=A, b=B)), FakeStore(), FakeEmbed()
    p, c, e = run(wiki, store, embed)
    assert p["pages_fetched"] == 2 and p["pages_unchanged"] == 0
    assert c["chunks_new"] == c["chunks_total"] >= 2
    assert e["chunks_embedded"] == c["chunks_total"] and store.counts()[1] == 0


def test_second_run_fetches_nothing_and_embeds_nothing():
    wiki, store, embed = FakeWiki(pages(a=A, b=B)), FakeStore(), FakeEmbed()
    run(wiki, store, embed)
    embedded_before = len(embed.seen)
    p, c, e = run(wiki, store, embed)
    assert p["pages_fetched"] == 0 and p["pages_unchanged"] == 2
    assert c["chunks_new"] == 0 and c["chunks_removed"] == 0
    assert e["chunks_embedded"] == 0 and len(embed.seen) == embedded_before
    assert all(etag for _, etag in wiki.gets[2:])  # the stored ETag was sent


def test_changed_page_re_embeds_only_its_new_chunks_and_drops_the_old():
    wiki, store, embed = FakeWiki(pages(a=A, b=B)), FakeStore(), FakeEmbed()
    run(wiki, store, embed)
    wiki.pages_["a"] = Page("a", "A", "t2", '"new"', "# A\n\nFirst rule about airports, now changed.\n")
    p, c, e = run(wiki, store, embed)
    assert p["pages_fetched"] == 1 and p["pages_unchanged"] == 1
    assert c["chunks_new"] == 1 and c["chunks_removed"] == 1
    assert e["chunks_embedded"] == 1
    assert store.counts()[1] == 0


def test_a_page_that_disappears_takes_its_chunks_with_it():
    wiki, store, embed = FakeWiki(pages(a=A, b=B)), FakeStore(), FakeEmbed()
    run(wiki, store, embed)
    del wiki.pages_["b"]
    p, _, _ = run(wiki, store, embed)
    assert p["pages_removed"] == 1 and {v["page_id"] for v in store.c.values()} == {"a"}


def test_chunk_hashes_match_the_given_chunker():
    wiki, store, embed = FakeWiki(pages(a=A)), FakeStore(), FakeEmbed()
    run(wiki, store, embed)
    assert set(store.c) == {c.content_hash("a") for c in chunk_markdown("A", A, 200, 40)}
