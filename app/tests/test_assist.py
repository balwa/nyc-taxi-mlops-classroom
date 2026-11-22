"""POST /assist (contracts/assistant-openapi.yaml): 503 until configured, then the contract's shape, with
the LLM host and the vector store replaced by fakes. Works before and after S6's retrieval is built."""

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import rideapp.assistant as a
from rideapp.main import app

CONTRACT = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts" / "assistant-openapi.yaml").read_text())
client = TestClient(app)


def assert_matches(name: str, body) -> None:
    defs = yaml.safe_load(yaml.safe_dump(CONTRACT["components"]["schemas"]).replace("#/components/schemas/", "#/$defs/"))
    errors = [e.message for e in Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": defs}).iter_errors(body)]
    assert not errors, errors


def test_503_until_the_llm_host_is_configured(monkeypatch):
    monkeypatch.delenv("LLM_HOST", raising=False)
    r = client.post("/assist", json={"question": "How much is the Harbor Line surcharge?"})
    assert r.status_code == 503 and "LLM_HOST" in r.json()["detail"]
    assert_matches("Error", r.json())


def test_bad_input_is_422(monkeypatch):
    monkeypatch.setenv("LLM_HOST", "10.0.0.9")
    assert client.post("/assist", json={"question": ""}).status_code == 422
    assert client.post("/assist", json={"question": "x", "top_k": 50}).status_code == 422


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setenv("LLM_HOST", "10.0.0.9")
    seen = {}

    async def embed_query(q):
        seen["question"] = q
        return [0.1] * 768

    async def retrieve(v):
        return [a.Chunk(id="c1", page_id="harbor-line", title="Harbor Line surcharge", content="Harbor Line > Pricing\n\n$4.25", score=0.84)]

    async def chat(messages, tools=None):
        seen["messages"] = messages
        return {"model": "qwen3-4b-instruct-2507", "choices": [{"message": {"content": "It's $4.25."}}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 9}}

    monkeypatch.setattr(a, "embed_query", embed_query)
    monkeypatch.setattr(a, "retrieve", retrieve)
    monkeypatch.setattr(a, "chat", chat)
    return seen


def test_answer_matches_the_contract(fake_llm):
    r = client.post("/assist", json={"question": "How much is the Harbor Line surcharge?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_matches("AssistResponse", body)
    assert body["answer"] == "It's $4.25." and body["sources"][0]["page_id"] == "harbor-line"
    assert body["model"] == {"chat": "qwen3-4b-instruct-2507", "embed": "nomic-embed-text-v1.5"} and body["trace_id"] is None
    assert set(body["timings_ms"]) == {"embed", "retrieve", "generate"} and body["tool_calls"] == []
    assert fake_llm["messages"][0]["role"] == "system" and fake_llm["messages"][-1]["role"] == "user"


def test_without_the_wiki_nothing_is_retrieved(fake_llm):
    body = client.post("/assist", json={"question": "How much is the Harbor Line surcharge?", "use_wiki": False}).json()
    assert body["sources"] == [] and "embed" not in body["timings_ms"] and "question" not in fake_llm


def test_an_unreachable_llm_host_is_503(monkeypatch):
    monkeypatch.setenv("LLM_HOST", "127.0.0.1")
    monkeypatch.setattr(a, "EMBED_PORT", 9)  # nothing listens on the discard port
    r = client.post("/assist", json={"question": "anything"})
    assert r.status_code == 503 and "LLM host" in r.json()["detail"]


def test_tracing_when_configured(fake_llm, monkeypatch, tmp_path):
    from rideapp.tracing import Tracer

    secret = tmp_path / "langfuse.json"
    secret.write_text('{"host": "https://cloud.langfuse.com", "public_key": "pk-lf-x", "secret_key": "sk-lf-x"}')
    tracer, sent = Tracer(secret), []
    monkeypatch.setattr(tracer, "send", sent.append)
    monkeypatch.setattr(a, "tracer", tracer)
    body = client.post("/assist", json={"question": "How much is the Harbor Line surcharge?"}).json()
    assert body["trace_id"] == sent[0].id
    spans = sent[0].payload()["resourceSpans"][0]["scopeSpans"][0]["spans"]
    attrs = [{a["key"]: next(iter(a["value"].values())) for a in s["attributes"]} for s in spans]
    assert [(s["name"], a["langfuse.observation.type"]) for s, a in zip(spans, attrs, strict=True)] == [
        ("retrieve", "span"), ("chat", "generation"), ("assist", "span")]
    root = spans[-1]
    assert all(s["traceId"] == body["trace_id"] for s in spans) and "parentSpanId" not in root
    assert all(s["parentSpanId"] == root["spanId"] for s in spans[:-1])
    assert attrs[1]["gen_ai.usage.input_tokens"] == "300" and attrs[1]["gen_ai.usage.output_tokens"] == "9"
    assert attrs[2]["langfuse.trace.name"] == "assist" and "Harbor Line" in attrs[2]["langfuse.observation.input"]


def chunk(i: int, title: str = "Harbor Line surcharge") -> a.Chunk:
    return a.Chunk(id=f"c{i}", page_id="harbor-line", title=title, content=f"{title} > Pricing\n\nexcerpt {i}", score=0.8)


def test_prompt_puts_the_excerpts_in_the_user_turn_and_keeps_the_system_prompt_fixed():
    one = a.build_messages("How much?", [chunk(1)])
    two = a.build_messages("Something else?", [chunk(2), chunk(3, "Quiet Hours dispatch")])
    assert one[0] == two[0] == {"role": "system", "content": a.WIKI_SYSTEM_PROMPT}  # same prefix: llama.cpp can cache it
    user = two[1]["content"]
    assert user.index("[1] (wiki page: Harbor Line surcharge)") < user.index("[2] (wiki page: Quiet Hours dispatch)") < user.index("Question: Something else?")
    assert "excerpt 2" in user and "excerpt 3" in user and "excerpt 1" not in user and "excerpt 1" in one[1]["content"]


def test_without_excerpts_the_prompt_is_the_plain_one():
    assert a.build_messages("How much?", []) == [{"role": "system", "content": a.SYSTEM_PROMPT}, {"role": "user", "content": "How much?"}]


class FakeCursor:
    def __init__(self, rows, seen):
        self.rows, self.seen = rows, seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params):
        self.seen["sql"], self.seen["params"] = sql, params

    async def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows, seen):
        self.rows, self.seen = rows, seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.rows, self.seen)


def test_retrieve_asks_for_the_top_k_nearest_by_cosine_distance(monkeypatch):
    seen = {}

    async def connect():
        return FakeConn([("c1", "harbor-line", "Harbor Line surcharge", "text", 0.83)], seen)

    monkeypatch.setattr(a, "connect", connect)
    chunks = asyncio.run(a.retrieve([0.5] * 768))
    assert chunks == [a.Chunk(id="c1", page_id="harbor-line", title="Harbor Line surcharge", content="text", score=0.83)]
    assert "<=>" in seen["sql"] and "embedding is not null" in seen["sql"] and "order by" in seen["sql"]
    assert seen["params"][0] == seen["params"][1] == a.vector_literal([0.5] * 768) and seen["params"][2] == a.TOP_K == 3
