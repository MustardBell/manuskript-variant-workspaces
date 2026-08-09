from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass

from .model import SyncMode


def prose_blocks(text):
    """Which of a document's lines carry prose.

    An editor counts blocks, and a block is a line, so the blank lines
    between paragraphs are blocks as well -- and how many there are is a
    writer's habit rather than a property of the scene. Two variants with
    exactly the same twenty paragraphs can therefore be 39 blocks and 58,
    and synchronizing by block number slides one pane against the other
    for no reason a reader would recognise.
    """
    return tuple(
        number
        for number, line in enumerate(str(text).split("\n"))
        if line.strip()
    )


@dataclass(frozen=True)
class ViewportState:
    value: int
    maximum: int
    first_block: int
    block_count: int
    text_length: int
    #: How far the viewport top sits through its first visible block. A
    #: paragraph number alone cannot say where between two paragraphs a
    #: reader is, which is what proportional synchronization follows.
    block_fraction: float = 0.0
    #: The block numbers of this document's paragraphs, from prose_blocks.
    paragraph_blocks: tuple = ()

    def __post_init__(self):
        object.__setattr__(
            self, "paragraph_blocks", tuple(self.paragraph_blocks),
        )


@dataclass(frozen=True)
class ScrollInstruction:
    kind: str
    value: int
    fraction: float = 0.0


@dataclass(frozen=True)
class Correspondence:
    """Where a place in one pane is to be found in another.

    ``kind`` says which currency ``value`` is counted in -- a paragraph's
    block, or an offset into the text -- because the modes do not all
    answer in the same one, and a pane cannot be scrolled to a number
    whose units it has to guess.
    """

    kind: str
    value: int


@dataclass(frozen=True)
class AnchorPairs:
    """The authored alignments, in whichever currency a reading works in.

    Text offsets land a pane on the paragraph an alignment names; scroll
    values are the only currency that can express a position between two of
    them. A reading is given both and takes the one it needs, so a reading
    added later can want a currency the others never asked for.
    """

    text_offsets: tuple = ()
    scroll_values: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "text_offsets", tuple(self.text_offsets))
        object.__setattr__(self, "scroll_values", tuple(self.scroll_values))


def interpolate(value, points):
    points = sorted((int(x), int(y)) for x, y in points)
    if not points:
        return 0
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if left_x <= value <= right_x:
            width = max(1, right_x - left_x)
            ratio = float(value - left_x) / width
            return round(left_y + ratio * (right_y - left_y))
    return points[-1][1]


def scrolled_ratio(state):
    return float(state.value) / state.maximum if state.maximum > 0 else 0.0


def stopped_instruction(_source, _target, _anchors, _proportional):
    """The panes the reader is not scrolling are left alone."""
    return None


def percentage_instruction(source, target, _anchors, _proportional):
    """Keep every pane the same share of the way through its own length."""
    return ScrollInstruction(
        "scrollbar",
        round(scrolled_ratio(source) * target.maximum),
    )


def paragraph_count(state):
    """How many paragraphs the document is, counting lines if it has none."""
    return len(state.paragraph_blocks) or state.block_count


def paragraph_of_block(state, block):
    """Which paragraph a block belongs to, blank lines counting backwards."""
    blocks = state.paragraph_blocks
    if not blocks:
        return max(0, min(int(block), state.block_count - 1))
    return max(0, bisect_right(blocks, int(block)) - 1)


def paragraph_position(state):
    """Which paragraph the viewport sits in, and how far through it.

    A blank line belongs to the paragraph above it, because a reader
    looking at one has finished that paragraph -- and the height of a blank
    line says nothing about how far through a paragraph of prose the
    matching point would be.
    """
    blocks = state.paragraph_blocks
    if not blocks:
        return state.first_block, state.block_fraction
    ordinal = paragraph_of_block(state, state.first_block)
    if blocks[ordinal] != state.first_block:
        return ordinal, 1.0
    return ordinal, state.block_fraction


def block_for_paragraph(state, ordinal):
    """The block a paragraph begins on."""
    blocks = state.paragraph_blocks
    if not blocks:
        return max(0, min(int(ordinal), state.block_count - 1))
    return blocks[max(0, min(int(ordinal), len(blocks) - 1))]


def paragraph_scale(source, target):
    """How many of the target's paragraphs answer to one of the source's."""
    last_target = max(0, paragraph_count(target) - 1)
    return (
        float(last_target) / max(1, paragraph_count(source) - 1),
        last_target,
    )


def matching_paragraph_block(source, target, block):
    """The block of the target paragraph that answers to one of the source's."""
    scale, last_target = paragraph_scale(source, target)
    ordinal = paragraph_of_block(source, block)
    return block_for_paragraph(target, min(round(ordinal * scale), last_target))


def matching_place(mode, source, target, block, offset, anchors=None):
    """Where in the target the reader has just put their finger, or None.

    Scrolling asks what belongs at the top of a pane. A click asks
    something narrower and easier: this paragraph, whereabouts is it over
    there. The panes correspond the way the chosen mode says they do --
    through the reader's own alignments where there are some -- and Off
    means the panes are not to be moved, by a click no less than a scroll.
    """
    mode = SyncMode(mode)
    if mode is SyncMode.OFF:
        return None
    anchors = anchors if anchors is not None else AnchorPairs()
    if mode is SyncMode.ANCHORS and anchors.text_offsets:
        pairs = list(anchors.text_offsets)
        pairs.extend(((0, 0), (source.text_length, target.text_length)))
        return Correspondence("text-offset", interpolate(int(offset), pairs))
    return Correspondence(
        "block", matching_paragraph_block(source, target, block),
    )


def paragraph_instruction(source, target, _anchors, proportional):
    """Put the same paragraph of the target under the reader's eye.

    A paragraph is matched to a paragraph, so a reader sitting at the top
    of one sees the others sitting at the top of theirs -- whatever the two
    scenes count between them. Scaling a mid-paragraph position instead
    landed the other panes part way down a paragraph while the pane being
    scrolled was squarely at the head of one, which reads as the panes
    having quietly slipped.

    Smoothing changes what happens between two paragraphs, not at them:
    rather than waiting and jumping when the next one arrives, the other
    panes cross the same share of the distance to their own next paragraph.
    """
    ordinal, progress = paragraph_position(source)
    last_target = max(0, paragraph_count(target) - 1)
    scale = float(last_target) / max(1, paragraph_count(source) - 1)

    def matching(value):
        return min(round(value * scale), last_target)

    here = matching(ordinal)
    if not proportional:
        return ScrollInstruction("block", block_for_paragraph(target, here))
    span = matching(ordinal + 1) - here
    position = here + progress * span
    landed = int(position)
    return ScrollInstruction(
        "block",
        block_for_paragraph(target, landed),
        position - landed,
    )


def anchor_instruction(source, target, anchors, proportional):
    """Follow the reader through the span between two authored alignments.

    Both readings interpolate between the same alignments; they differ in
    what they interpolate. Paragraph coordinates land the target on the
    paragraph an alignment names. Scroll coordinates keep the reader the
    same fraction of the way between two alignments as they are in the pane
    they are scrolling.
    """
    if proportional:
        pairs = list(anchors.scroll_values)
        pairs.extend(((0, 0), (source.maximum, target.maximum)))
        return ScrollInstruction(
            "scrollbar",
            interpolate(source.value, pairs),
        )
    pairs = list(anchors.text_offsets)
    pairs.extend(((0, 0), (source.text_length, target.text_length)))
    return ScrollInstruction(
        "text-offset",
        interpolate(
            round(scrolled_ratio(source) * source.text_length),
            pairs,
        ),
    )


#: How each offered mode reads a scroll. A mode is added by writing its
#: reading and naming it here; nothing that already dispatches has to change.
READINGS = {
    SyncMode.OFF: stopped_instruction,
    SyncMode.PERCENTAGE: percentage_instruction,
    SyncMode.PARAGRAPH: paragraph_instruction,
    SyncMode.ANCHORS: anchor_instruction,
}


def scroll_instruction(mode, source, target, anchors=None,
                       proportional=False):
    """What to do to ``target`` now that ``source`` has been scrolled."""
    mode = SyncMode(mode)
    reading = READINGS.get(mode)
    if reading is None:
        raise ValueError("Unsupported synchronization mode {}.".format(mode))
    return reading(
        source,
        target,
        anchors if anchors is not None else AnchorPairs(),
        proportional,
    )


class FeedbackGuard:
    """Prevent programmatic synchronized scrolls from feeding back."""

    def __init__(self):
        self._active = set()

    def is_active(self, endpoint_id):
        return str(endpoint_id) in self._active

    @contextmanager
    def programmatic(self, endpoint_id):
        endpoint_id = str(endpoint_id)
        self._active.add(endpoint_id)
        try:
            yield
        finally:
            self._active.discard(endpoint_id)
