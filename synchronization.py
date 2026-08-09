from contextlib import contextmanager
from dataclasses import dataclass

from .model import SyncMode


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


@dataclass(frozen=True)
class ScrollInstruction:
    kind: str
    value: int
    fraction: float = 0.0


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


def paragraph_instruction(source, target, _anchors, proportional):
    """Put the same paragraph of the target under the reader's eye.

    Landing on a paragraph boundary is the honest answer while the reader is
    on one. Between two of them, a whole-paragraph answer makes the other
    panes jump a paragraph at a time behind a smoothly scrolling one, so
    proportional synchronization carries the distance across as well.
    """
    position = source.first_block + (
        source.block_fraction if proportional else 0.0
    )
    last_target_block = max(0, target.block_count - 1)
    scaled = min(
        position / max(1, source.block_count - 1) * last_target_block,
        float(last_target_block),
    )
    if not proportional:
        return ScrollInstruction("block", round(scaled))
    block = int(scaled)
    return ScrollInstruction("block", block, scaled - block)


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
