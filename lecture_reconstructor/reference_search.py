from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from .models import MaterialDocument


@dataclass(slots=True)
class ReferenceHit:
    relative_path: str
    chunk_index: int
    score: float
    text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


STOPWORDS = {
    "about",
    "after",
    "also",
    "because",
    "before",
    "chapter",
    "course",
    "define",
    "example",
    "from",
    "into",
    "lecture",
    "module",
    "notes",
    "that",
    "their",
    "there",
    "these",
    "this",
    "with",
}


def search_references(
    documents: list[MaterialDocument],
    query: str,
    *,
    max_hits: int = 12,
    chunk_chars: int = 1800,
    overlap_chars: int = 250,
) -> list[ReferenceHit]:
    reference_docs = [doc for doc in documents if doc.role == "reference" and doc.text.strip()]
    if not reference_docs or not query.strip():
        return []

    query_terms = _tokens(query)
    query_phrases = _phrases(query)
    if not query_terms and not query_phrases:
        return []

    hits: list[ReferenceHit] = []
    for doc in reference_docs:
        for chunk_index, chunk in enumerate(_chunks(doc.text, chunk_chars, overlap_chars), start=1):
            score = _score_chunk(chunk, query_terms, query_phrases)
            if score > 0:
                hits.append(
                    ReferenceHit(
                        relative_path=doc.relative_path,
                        chunk_index=chunk_index,
                        score=round(score, 3),
                        text=chunk.strip(),
                    )
                )
    hits.sort(key=lambda item: (-item.score, item.relative_path, item.chunk_index))
    return _dedupe_hits(hits[: max_hits * 3])[:max_hits]


def format_reference_hits(hits: list[ReferenceHit]) -> str:
    if not hits:
        return (
        "## RETRIEVED REFERENCE EXCERPTS\n"
        "No reference excerpts matched the current primary-material query. "
        "Generate from primary materials only; do not invent textbook support. "
        "Reference materials are searchable backup only; 不要纳入逐页覆盖."
        )
    blocks = [
        "## RETRIEVED REFERENCE EXCERPTS",
        "These excerpts were retrieved locally from reference materials after the outline pass. "
        "Use them only to deepen concepts that appear in the primary materials. "
        "Do not treat reference files as page-by-page coverage targets; 不要纳入逐页覆盖.",
    ]
    for index, hit in enumerate(hits, start=1):
        blocks.append(
            f"### Reference Hit {index}: {hit.relative_path} [chunk {hit.chunk_index}, score {hit.score}]\n"
            f"{hit.text}"
        )
    return "\n\n".join(blocks)


def reference_index(documents: list[MaterialDocument]) -> str:
    refs = [doc for doc in documents if doc.role == "reference"]
    if not refs:
        return ""
    lines = [
        "## REFERENCE INDEX",
        "The following files are reference-only. They are searchable backup materials, "
        "not required coverage targets. Their full text is not included in this prompt unless retrieved.",
    ]
    for index, doc in enumerate(refs, start=1):
        warnings = f" Warnings: {'; '.join(doc.warnings)}" if doc.warnings else ""
        text_len = len(doc.text or "")
        lines.append(
            f"{index}. {doc.relative_path} | type={doc.material_type} | status={doc.status} | chars={text_len}.{warnings}"
        )
    return "\n".join(lines)


def _score_chunk(chunk: str, query_terms: set[str], query_phrases: list[str]) -> float:
    lowered = chunk.casefold()
    chunk_terms = _tokens(lowered)
    overlap = query_terms & chunk_terms
    if not overlap:
        phrase_score = sum(8.0 for phrase in query_phrases if phrase in lowered)
        return phrase_score

    rare_bonus = sum(1.0 / math.sqrt(max(1, lowered.count(term))) for term in overlap)
    phrase_score = sum(8.0 for phrase in query_phrases if phrase in lowered)
    density = len(overlap) / max(1, len(chunk_terms))
    return len(overlap) + rare_bonus + phrase_score + density


def _tokens(text: str) -> set[str]:
    lowered = text.casefold()
    words = {
        token
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", lowered)
        if token not in STOPWORDS and not token.isdigit()
    }
    cjk = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    for segment in cjk:
        if len(segment) <= 6:
            words.add(segment)
        else:
            words.update(segment[index : index + 2] for index in range(len(segment) - 1))
            words.update(segment[index : index + 3] for index in range(len(segment) - 2))
    return words


def _phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for match in re.finditer(r"\b[a-z][a-z0-9-]+(?:\s+[a-z][a-z0-9-]+){1,4}\b", text.casefold()):
        phrase = re.sub(r"\s+", " ", match.group(0)).strip()
        words = phrase.split()
        if any(word in STOPWORDS for word in words):
            continue
        if len("".join(words)) < 8:
            continue
        phrases.append(phrase)
    return list(dict.fromkeys(phrases))[:80]


def _chunks(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_chars)
        if end < len(normalized):
            paragraph_end = normalized.rfind("\n\n", start, end)
            if paragraph_end > start + chunk_chars // 2:
                end = paragraph_end
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
    return [chunk for chunk in chunks if chunk]


def _dedupe_hits(hits: list[ReferenceHit]) -> list[ReferenceHit]:
    deduped: list[ReferenceHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        signature = (hit.relative_path, re.sub(r"\s+", " ", hit.text[:220]).casefold())
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(hit)
    return deduped
