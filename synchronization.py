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


@dataclass(frozen=True)
class ScrollInstruction:
    kind: str
    value: int


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


def scroll_instruction(
        mode, source, target, source_anchor_offsets=(),
        target_anchor_offsets=()):
    mode = SyncMode(mode)
    if mode is SyncMode.OFF:
        return None
    if mode is SyncMode.PERCENTAGE:
        ratio = (
            float(source.value) / source.maximum
            if source.maximum > 0
            else 0.0
        )
        return ScrollInstruction("scrollbar", round(ratio * target.maximum))
    if mode is SyncMode.PARAGRAPH:
        ratio = (
            float(source.first_block) / max(1, source.block_count - 1)
        )
        return ScrollInstruction(
            "block",
            round(ratio * max(0, target.block_count - 1)),
        )
    if mode is SyncMode.ANCHORS:
        pairs = list(zip(source_anchor_offsets, target_anchor_offsets))
        pairs.extend(((0, 0), (source.text_length, target.text_length)))
        return ScrollInstruction(
            "text-offset",
            interpolate(
                round(
                    float(source.value) / max(1, source.maximum)
                    * source.text_length
                ),
                pairs,
            ),
        )
    raise ValueError("Unsupported synchronization mode {}.".format(mode))


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
