from variant_workspaces.synchronization import (
    FeedbackGuard,
    ViewportState,
    interpolate,
    scroll_instruction,
)


def viewport(value=50, maximum=100, first=5, blocks=11, length=1000):
    return ViewportState(value, maximum, first, blocks, length)


def test_percentage_and_paragraph_modes_return_distinct_instructions():
    target = viewport(maximum=300, blocks=21, length=2000)

    percentage = scroll_instruction("percentage", viewport(), target)
    paragraph = scroll_instruction("paragraph", viewport(), target)

    assert (percentage.kind, percentage.value) == ("scrollbar", 150)
    assert (paragraph.kind, paragraph.value) == ("block", 10)


def test_anchor_interpolation_uses_manual_segments():
    assert interpolate(50, ((0, 0), (100, 300))) == 150
    instruction = scroll_instruction(
        "anchors",
        viewport(value=50, length=100),
        viewport(maximum=500, length=400),
        source_anchor_offsets=(25, 75),
        target_anchor_offsets=(50, 350),
    )
    assert instruction.kind == "text-offset"
    assert instruction.value == 200


def test_feedback_guard_is_scoped_per_endpoint():
    guard = FeedbackGuard()
    with guard.programmatic("target"):
        assert guard.is_active("target")
        assert not guard.is_active("source")
    assert not guard.is_active("target")
