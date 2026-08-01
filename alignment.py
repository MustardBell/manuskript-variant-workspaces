import difflib
import hashlib
import re
from dataclasses import dataclass

from .model import AlignmentAnchor, AnchorPoint


SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Paragraph:
    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ResolvedPoint:
    start: int
    end: int
    paragraph_index: int
    repaired: bool
    confidence: float
    resolved: bool = True


def normalize(text):
    return SPACE.sub(" ", str(text)).strip().casefold()


def fingerprint(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:20]


def paragraphs(source):
    source = str(source)
    lines = source.splitlines(True)
    if not lines:
        return (Paragraph(0, 0, 0, ""),)
    result = []
    position = 0
    for index, line in enumerate(lines):
        end = position + len(line)
        result.append(Paragraph(index, position, end, line.rstrip("\r\n")))
        position = end
    if position < len(source) or source.endswith(("\n", "\r")):
        result.append(Paragraph(len(result), position, len(source), source[position:]))
    return tuple(result)


def paragraph_at(source, offset):
    values = paragraphs(source)
    offset = max(0, min(int(offset), len(source)))
    for paragraph in values:
        if paragraph.start <= offset < paragraph.end:
            return paragraph
    return values[-1]


def capture_point(source, start, end=None):
    source = str(source)
    start = max(0, min(int(start), len(source)))
    end = start if end is None else max(start, min(int(end), len(source)))
    first = paragraph_at(source, start)
    last = paragraph_at(source, end)
    snippet_start = max(first.start, start - 36)
    snippet_end = min(last.end, max(end, start) + 44)
    return AnchorPoint(
        paragraph_index=first.index,
        paragraph_end_index=last.index,
        offset_in_paragraph=start - first.start,
        end_offset_in_paragraph=end - last.start,
        approximate_offset=start,
        fingerprint=fingerprint(first.text),
        snippet=source[snippet_start:snippet_end].strip()[:80],
    )


def capture_anchor(label, sources, selections):
    points = {}
    for member_id, source in sources.items():
        start, end = selections[member_id]
        points[member_id] = capture_point(source, start, end)
    return AlignmentAnchor.create(label, points)


def resolve_point(source, point):
    source = str(source)
    values = paragraphs(source)
    candidates = [
        paragraph
        for paragraph in values
        if fingerprint(paragraph.text) == point.fingerprint
    ]
    if candidates:
        candidate = min(
            candidates,
            key=lambda value: abs(value.index - point.paragraph_index),
        )
        end_index = max(candidate.index, min(
            candidate.index
            + point.paragraph_end_index
            - point.paragraph_index,
            len(values) - 1,
        ))
        end_paragraph = values[end_index]
        return ResolvedPoint(
            start=min(
                candidate.start + point.offset_in_paragraph,
                candidate.end,
            ),
            end=min(
                end_paragraph.start + point.end_offset_in_paragraph,
                end_paragraph.end,
            ),
            paragraph_index=candidate.index,
            repaired=candidate.index != point.paragraph_index,
            confidence=1.0,
        )

    normalized_snippet = normalize(point.snippet)
    if normalized_snippet:
        best = None
        for paragraph in values:
            score = difflib.SequenceMatcher(
                None,
                normalized_snippet,
                normalize(paragraph.text),
            ).ratio()
            distance_penalty = min(
                abs(paragraph.index - point.paragraph_index) * 0.01,
                0.2,
            )
            candidate = (score - distance_penalty, paragraph)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is not None and best[0] >= 0.55:
            paragraph = best[1]
            return ResolvedPoint(
                start=min(
                    paragraph.start + point.offset_in_paragraph,
                    paragraph.end,
                ),
                end=min(
                    paragraph.start + point.end_offset_in_paragraph,
                    paragraph.end,
                ),
                paragraph_index=paragraph.index,
                repaired=True,
                confidence=max(0.0, min(best[0], 0.99)),
            )

    approximate = max(0, min(point.approximate_offset, len(source)))
    paragraph = paragraph_at(source, approximate)
    return ResolvedPoint(
        start=approximate,
        end=approximate,
        paragraph_index=paragraph.index,
        repaired=True,
        confidence=0.0,
        resolved=False,
    )


def repair_anchor(anchor, sources):
    resolved = {}
    repaired_points = {}
    unresolved = []
    for member_id, point in anchor.points.items():
        source = sources.get(member_id)
        if source is None:
            unresolved.append(member_id)
            continue
        result = resolve_point(source, point)
        resolved[member_id] = result
        if result.resolved:
            repaired_points[member_id] = capture_point(
                source,
                result.start,
                result.end,
            )
        else:
            repaired_points[member_id] = point
            unresolved.append(member_id)
    repaired = AlignmentAnchor(
        id=anchor.id,
        label=anchor.label,
        points=repaired_points,
    )
    return repaired, resolved, tuple(unresolved)
