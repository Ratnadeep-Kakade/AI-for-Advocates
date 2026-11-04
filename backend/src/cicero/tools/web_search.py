"""Google Grounding via Gemini: search-and-source discovery for the Researcher.

Gemini is an intermediary only. This adapter runs a grounded Gemini request,
extracts the search queries, citation metadata (URLs + cited text spans) and
grounded summary from ``groundingMetadata``, then fetches the primary source
at each URL. A citation is marked ``verified`` only when the cited text was
found in the fetched primary source; otherwise it stays ``unverified`` —
Discovery is never treated as legal evidence acquisition.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, Field

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Domains treated as primary legal sources (statute/judgment publishers).
_OFFICIAL_HOST_MARKERS = (
    ".gov",
    "gov.",
    "judiciary",
    "court",
    "legislation",
    "indiankanoon",
    "bailii",
    "canlii",
    "austlii",
)

_MAX_SOURCE_CHARS = 12000


class SearchSource(BaseModel):
    source_id: str
    title: str
    url: str
    cited_text: str | None = None
    publisher: str | None = None
    publication_date: str | None = None
    retrieved_at: str
    source_type: str = "web"
    verification_status: str = "unverified"
    fetched_excerpt: str | None = None


class SearchBundle(BaseModel):
    query: str
    sources: list[SearchSource] = Field(default_factory=list)
    grounded_summary: str | None = None
    search_queries: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source_type_for(url: str) -> str:
    lowered = url.lower()
    if any(marker in lowered for marker in _OFFICIAL_HOST_MARKERS):
        return "official"
    return "web"


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_grounding_response(query: str, payload: dict) -> SearchBundle:
    """Extract queries, sources and cited spans from a Gemini response."""
    candidates = payload.get("candidates") or []
    if not candidates:
        return SearchBundle(query=query)
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    summary = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    metadata = candidate.get("groundingMetadata") or {}
    chunks = metadata.get("groundingChunks") or []
    supports = metadata.get("groundingSupports") or []

    # Map each grounding chunk (source) to the cited text spans that cite it.
    cited_by_index: dict[int, list[str]] = {}
    for support in supports:
        segment = support.get("segment") or {}
        cited_text = segment.get("text")
        if not cited_text:
            continue
        for index in support.get("groundingChunkIndices") or []:
            cited_by_index.setdefault(int(index), []).append(cited_text)

    sources: list[SearchSource] = []
    for index, chunk in enumerate(chunks):
        web = chunk.get("web") or {}
        url = web.get("uri")
        if not url:
            continue
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        cited = cited_by_index.get(index) or []
        sources.append(
            SearchSource(
                source_id=f"SRC_{digest}",
                title=web.get("title") or url,
                url=url,
                cited_text="\n".join(cited) if cited else None,
                retrieved_at=_now(),
                source_type=_source_type_for(url),
            )
        )
    return SearchBundle(
        query=query,
        sources=sources,
        grounded_summary=summary.strip() or None,
        search_queries=list(metadata.get("webSearchQueries") or []),
    )


async def fetch_primary_source(
    source: SearchSource,
    *,
    timeout: float = 20.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SearchSource:
    """Fetch the source URL; verify the cited text appears in the original."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, transport=transport
        ) as client:
            response = await client.get(
                source.url, headers={"User-Agent": "CiceroResearch/1.0"}
            )
            response.raise_for_status()
            body = response.text
    except httpx.HTTPError:
        source.verification_status = "unverified"
        source.fetched_excerpt = None
        return source
    text = _strip_html(body) if "<" in body[:200] else body
    source.fetched_excerpt = text[:_MAX_SOURCE_CHARS]
    if source.cited_text and source.cited_text.strip()[:80] in text:
        source.verification_status = "verified"
    else:
        source.verification_status = "fetched_unverified_quote"
    return source


class GeminiGroundingAdapter:
    """Search adapter exposing Gemini Grounding with Google Search."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-2.5-flash",
        transport: httpx.AsyncBaseTransport | None = None,
        fetch_sources: bool = True,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport
        self._fetch_sources = fetch_sources

    async def search(self, query: str) -> SearchBundle:
        payload = {
            "contents": [{"parts": [{"text": query}]}],
            "tools": [{"google_search": {}}],
        }
        async with httpx.AsyncClient(
            timeout=60.0, transport=self._transport
        ) as client:
            response = await client.post(
                GEMINI_API_URL.format(model=self._model),
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            bundle = parse_grounding_response(query, response.json())
        if self._fetch_sources:
            for source in bundle.sources:
                await fetch_primary_source(source, transport=self._transport)
        return bundle
