import httpx

from cicero.tools.web_search import (
    GeminiGroundingAdapter,
    SearchSource,
    fetch_primary_source,
    parse_grounding_response,
)

PAYLOAD = {
    "candidates": [
        {
            "content": {"parts": [{"text": "Grounded summary text."}]},
            "groundingMetadata": {
                "webSearchQueries": ["limitation period breach of contract"],
                "groundingChunks": [
                    {
                        "web": {
                            "uri": "https://court.example.gov/judgment-1",
                            "title": "Court Judgment",
                        }
                    },
                    {"web": {"uri": "https://blog.example.com/post", "title": "Blog Post"}},
                ],
                "groundingSupports": [
                    {
                        "segment": {"text": "The limitation period is six years."},
                        "groundingChunkIndices": [0],
                    }
                ],
            },
        }
    ]
}


def test_parse_grounding_response_maps_citations() -> None:
    bundle = parse_grounding_response("limitation period", PAYLOAD)
    assert bundle.grounded_summary == "Grounded summary text."
    assert bundle.search_queries == ["limitation period breach of contract"]
    assert len(bundle.sources) == 2
    court = bundle.sources[0]
    assert court.source_type == "official"
    assert court.cited_text == "The limitation period is six years."
    assert bundle.sources[1].cited_text is None


def test_parse_grounding_response_empty() -> None:
    bundle = parse_grounding_response("q", {})
    assert bundle.sources == []
    assert bundle.grounded_summary is None


async def test_fetch_primary_source_verifies_quote() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><p>The limitation period is six years from breach.</p></body></html>",
        )

    source = SearchSource(
        source_id="SRC_1",
        title="Judgment",
        url="https://court.example.gov/judgment-1",
        cited_text="The limitation period is six years",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    fetched = await fetch_primary_source(source, transport=httpx.MockTransport(handler))
    assert fetched.verification_status == "verified"
    assert fetched.fetched_excerpt is not None


async def test_fetch_failure_stays_unverified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    source = SearchSource(
        source_id="SRC_2",
        title="Missing",
        url="https://court.example.gov/nope",
        cited_text="anything",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    fetched = await fetch_primary_source(source, transport=httpx.MockTransport(handler))
    assert fetched.verification_status == "unverified"


def test_adapter_requires_key_at_call_time() -> None:
    adapter = GeminiGroundingAdapter("key", model="gemini-2.5-flash")
    assert adapter is not None
