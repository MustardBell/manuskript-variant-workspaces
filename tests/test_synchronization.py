from variant_workspaces.synchronization import (
    AnchorPairs,
    FeedbackGuard,
    ViewportState,
    interpolate,
    scroll_instruction,
)


def viewport(value=50, maximum=100, first=5, blocks=11, length=1000,
             fraction=0.0):
    return ViewportState(value, maximum, first, blocks, length, fraction)


def test_percentage_and_paragraph_modes_return_distinct_instructions():
    target = viewport(maximum=300, blocks=21, length=2000)

    percentage = scroll_instruction("percentage", viewport(), target)
    paragraph = scroll_instruction("paragraph", viewport(), target)

    assert (percentage.kind, percentage.value) == ("scrollbar", 150)
    assert (paragraph.kind, paragraph.value) == ("block", 10)
    assert paragraph.fraction == 0


def test_anchor_interpolation_uses_manual_segments():
    assert interpolate(50, ((0, 0), (100, 300))) == 150
    instruction = scroll_instruction(
        "anchors",
        viewport(value=50, length=100),
        viewport(maximum=500, length=400),
        anchors=AnchorPairs(text_offsets=((25, 50), (75, 350))),
    )
    assert instruction.kind == "text-offset"
    assert instruction.value == 200


def test_proportional_paragraph_sync_carries_the_distance_between_them():
    """Half way through the source paragraph is half way through its twin."""
    source = viewport(first=5, blocks=11, fraction=0.5)
    target = viewport(blocks=21)

    stepping = scroll_instruction("paragraph", source, target)
    smooth = scroll_instruction("paragraph", source, target, proportional=True)

    assert (stepping.value, stepping.fraction) == (10, 0)
    assert (smooth.value, smooth.fraction) == (11, 0)


def test_proportional_paragraph_sync_lands_between_two_paragraphs():
    source = viewport(first=1, blocks=11, fraction=0.5)
    target = viewport(blocks=11)

    smooth = scroll_instruction("paragraph", source, target, proportional=True)

    assert smooth.kind == "block"
    assert smooth.value == 1
    assert smooth.fraction == 0.5


def test_proportional_paragraph_sync_never_overruns_the_last_paragraph():
    source = viewport(value=100, first=10, blocks=11, fraction=1.0)
    target = viewport(blocks=6)

    smooth = scroll_instruction("paragraph", source, target, proportional=True)

    assert smooth.value == 5
    assert smooth.fraction == 0


def test_proportional_anchor_sync_interpolates_between_alignments():
    """Between two alignments the reader keeps their share of the span."""
    source = viewport(value=150, maximum=400)
    target = viewport(value=0, maximum=800)

    smooth = scroll_instruction(
        "anchors",
        source,
        target,
        anchors=AnchorPairs(scroll_values=((100, 200), (300, 600))),
        proportional=True,
    )

    assert smooth.kind == "scrollbar"
    assert smooth.value == 300


def test_proportional_anchor_sync_falls_back_to_the_whole_document():
    source = viewport(value=200, maximum=400)
    target = viewport(value=0, maximum=800)

    smooth = scroll_instruction(
        "anchors", source, target, proportional=True,
    )

    assert (smooth.kind, smooth.value) == ("scrollbar", 400)


def test_off_mode_answers_with_no_instruction_however_it_is_read():
    assert scroll_instruction("off", viewport(), viewport()) is None
    assert scroll_instruction(
        "off", viewport(), viewport(), proportional=True,
    ) is None


def test_feedback_guard_is_scoped_per_endpoint():
    guard = FeedbackGuard()
    with guard.programmatic("target"):
        assert guard.is_active("target")
        assert not guard.is_active("source")
    assert not guard.is_active("target")
