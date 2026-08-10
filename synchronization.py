"""How a place in one pane is found in another.

Every principle here narrows a *stretch* rather than answering outright, and
they are applied in the order the reader put them in. An alignment they
authored says which stretch of one scene answers to which stretch of the
other; counting paragraphs says which paragraph inside that stretch; a
percentage says whereabouts inside that paragraph. Each one works inside
what the one before it settled, so ordering them is a real choice rather
than a menu of alternatives, and a principle that cannot say anything here
-- no alignment reaches this far, the stretch is a single paragraph already
-- steps aside and leaves the stretch as it was.

Everywhere in this module a position is a **fractional paragraph ordinal**:
whole numbers are the tops of paragraphs and the fraction is how far the
reader has gone towards the next one. One currency throughout is what lets
the principles compose, and it is the one a reader would recognise, since
a scene is read in paragraphs rather than in pixels or in characters.
"""

from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass

from .model import SyncPrinciple


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
    #: reader is, which is what the percentage principle follows.
    block_fraction: float = 0.0
    #: The block numbers of this document's paragraphs, from prose_blocks.
    paragraph_blocks: tuple = ()

    def __post_init__(self):
        object.__setattr__(
            self, "paragraph_blocks", tuple(self.paragraph_blocks),
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


def paragraph_at_offset(state, text, offset):
    """Which paragraph a place in the text belongs to.

    An alignment remembers where it was captured as an offset into the
    prose, and everything here is counted in paragraphs, so this is where
    the one becomes the other.
    """
    return paragraph_of_block(
        state, str(text)[:max(0, int(offset))].count("\n"),
    )


def block_for_paragraph(state, ordinal):
    """The block a paragraph begins on."""
    blocks = state.paragraph_blocks
    if not blocks:
        return max(0, min(int(ordinal), state.block_count - 1))
    return blocks[max(0, min(int(ordinal), len(blocks) - 1))]


def viewport_position(state):
    """Where the top of the viewport sits, in paragraphs.

    A blank line belongs to the paragraph above it, because a reader
    looking at one has finished that paragraph -- and the height of a blank
    line says nothing about how far through a paragraph of prose the
    matching point would be.
    """
    blocks = state.paragraph_blocks
    if not blocks:
        return state.first_block + state.block_fraction
    ordinal = paragraph_of_block(state, state.first_block)
    if blocks[ordinal] != state.first_block:
        return float(ordinal + 1)
    return ordinal + state.block_fraction


def last_paragraph(state):
    return float(max(0, paragraph_count(state) - 1))


def anchor_stretch(source, target, position, anchors):
    """Narrow to the stretch between the alignments bracketing the reader.

    Alignments are ordered by where they fall in the pane being scrolled,
    and deliberately not by where they land in the other one: a passage
    moved between two versions of a scene is an alignment that runs
    backwards, and that is the whole use of authoring one. What follows a
    backwards alignment is a stretch that answers to an earlier stretch
    over there, which is exactly what the reader said it does.

    Declines where the reader has authored no alignment that reaches into
    this stretch, which is most of a scene until they have.
    """
    points = sorted(
        (float(one), float(other)) for one, other in anchors
        if source[0] <= one <= source[1]
    )
    if not points:
        return None
    # The ends of the stretch stand in only where the reader has not put an
    # alignment there themselves. An alignment on the first paragraph is
    # the usual way to say where a moved run begins, and dropping it in
    # favour of an assumed start is how it would go unheard.
    if points[0][0] > source[0]:
        points.insert(0, (source[0], target[0]))
    if points[-1][0] < source[1]:
        points.append((source[1], target[1]))
    if len(points) < 2:
        return None
    # The alignment in force is the last one at or above the reader, so a
    # reader sitting exactly on one is inside the stretch it opens rather
    # than at the tail of the stretch it closes.
    for lower, upper in reversed(list(zip(points, points[1:]))):
        if lower[0] <= position:
            return (lower[0], upper[0]), (lower[1], upper[1])
    return None


def paragraph_stretch(source, target, position, _anchors):
    """Narrow to the paragraph the reader is in, and to its counterpart.

    A paragraph is matched to a paragraph, so a reader at the top of one
    puts the other panes at the top of theirs whatever the two scenes count
    between them. Declines once the stretch is a single paragraph, which is
    all it could ever narrow it to.
    """
    low, high = int(source[0]), int(source[1])
    target_low, target_high = int(target[0]), int(target[1])
    if high - low < 1:
        return None
    # The stretch's last paragraph is one a reader can be in, so it is not
    # held back a place; what follows it is simply clamped below.
    ordinal = max(low, min(int(position), high))
    scale = float(target_high - target_low) / (high - low)
    within = sorted((target_low, target_high))

    def matching(value):
        stepped = target_low + (value - low) * scale
        return int(round(max(within[0], min(stepped, within[1]))))

    here = matching(ordinal)
    following = matching(ordinal + 1)
    if following <= here:
        # Either the end of the stretch, or an alignment that runs
        # backwards because the passage was moved. A paragraph is still
        # read forwards, so what follows it is the paragraph after it
        # rather than wherever its own counterpart went.
        following = here + 1
    return (
        (float(ordinal), float(ordinal + 1)),
        (float(here), float(following)),
    )


def percentage_stretch(source, target, position, _anchors):
    """Narrow to the one point the same share of the way through."""
    low, high = source
    share = (position - low) / (high - low) if high > low else 0.0
    share = max(0.0, min(share, 1.0))
    landed = target[0] + share * (target[1] - target[0])
    return (position, position), (landed, landed)


#: What each principle does to the stretch it is handed. A principle is
#: added by writing how it narrows and naming it here; the chain that
#: applies them does not have to know which ones exist.
PRINCIPLES = {
    SyncPrinciple.ANCHORS: anchor_stretch,
    SyncPrinciple.PARAGRAPH: paragraph_stretch,
    SyncPrinciple.PERCENTAGE: percentage_stretch,
}


def corresponding_position(stack, source, target, position, anchors=()):
    """Where a place in one pane is to be found in another, or None.

    ``position`` and the answer are fractional paragraph ordinals. An empty
    stack answers with nothing, which is how a reader says the panes are
    not to follow each other at all.
    """
    stack = tuple(SyncPrinciple(principle) for principle in stack)
    if not stack:
        return None
    source_stretch = (0.0, last_paragraph(source))
    target_stretch = (0.0, last_paragraph(target))
    for principle in stack:
        narrow = PRINCIPLES.get(principle)
        if narrow is None:
            continue
        narrowed = narrow(
            source_stretch, target_stretch, position, tuple(anchors),
        )
        if narrowed is not None:
            source_stretch, target_stretch = narrowed
    return target_stretch[0]


def following_position(stack, source, target, anchors=()):
    """Where the target belongs now that the source has been scrolled."""
    return corresponding_position(
        stack, source, target, viewport_position(source), anchors,
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
