from variant_workspaces.synchronization import (
    AnchorPairs,
    FeedbackGuard,
    ViewportState,
    interpolate,
    prose_blocks,
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


def spaced(paragraphs, blank_lines):
    """A document of so many paragraphs, spaced the way a writer chose."""
    return ("\n" * (blank_lines + 1)).join(
        "Paragraph %d." % index for index in range(paragraphs)
    )


def document_viewport(text, first_block, fraction=0.0):
    lines = text.split("\n")
    return ViewportState(
        value=0,
        maximum=1000,
        first_block=first_block,
        block_count=len(lines),
        text_length=len(text),
        block_fraction=fraction,
        paragraph_blocks=prose_blocks(text),
    )


def test_prose_blocks_names_the_lines_that_hold_paragraphs():
    assert prose_blocks("one\n\ntwo\n\n\nthree") == (0, 2, 5)
    assert prose_blocks("") == ()
    assert prose_blocks("\n \n\t\n") == ()


def test_the_same_paragraphs_align_however_they_are_spaced():
    """Blank lines are a writer's habit, not a place in the scene."""
    tight = spaced(20, blank_lines=1)
    loose = spaced(20, blank_lines=2)
    source = document_viewport(tight, first_block=prose_blocks(tight)[7])
    target = document_viewport(loose, first_block=0)

    instruction = scroll_instruction("paragraph", source, target)

    assert instruction.value == prose_blocks(loose)[7]


def test_smoothing_keeps_the_paragraph_it_would_otherwise_land_on():
    tight = spaced(20, blank_lines=1)
    loose = spaced(20, blank_lines=2)
    source = document_viewport(
        tight, first_block=prose_blocks(tight)[7], fraction=0.5,
    )
    target = document_viewport(loose, first_block=0)

    instruction = scroll_instruction(
        "paragraph", source, target, proportional=True,
    )

    assert instruction.value == prose_blocks(loose)[7]
    assert instruction.fraction == 0.5


def test_a_reader_on_a_blank_line_has_finished_the_paragraph_above_it():
    text = spaced(20, blank_lines=1)
    blank = prose_blocks(text)[7] + 1
    source = document_viewport(text, first_block=blank, fraction=0.4)
    target = document_viewport(text, first_block=0)

    instruction = scroll_instruction(
        "paragraph", source, target, proportional=True,
    )

    assert instruction.value == prose_blocks(text)[8]
    assert instruction.fraction == 0


def test_paragraph_sync_still_answers_for_a_document_of_blank_lines():
    empty = ViewportState(0, 100, 3, 9, 8)
    target = ViewportState(0, 100, 0, 17, 16)

    instruction = scroll_instruction("paragraph", empty, target)

    assert instruction.kind == "block"
    assert instruction.value == 6


def test_a_paragraph_top_matches_a_paragraph_top_however_many_there_are():
    """A merged variant has its own count, and boundaries must still meet.

    Scaling a mid-paragraph position put the other panes part way down a
    paragraph while the pane being scrolled sat squarely at the head of
    one, which is the slight, intermittent slippage a reader notices.
    """
    source_text = spaced(30, blank_lines=1)
    target_text = spaced(27, blank_lines=1)
    target_paragraphs = prose_blocks(target_text)
    landed = []
    for ordinal in range(27):
        instruction = scroll_instruction(
            "paragraph",
            document_viewport(source_text, prose_blocks(source_text)[ordinal]),
            document_viewport(target_text, 0),
            proportional=True,
        )
        landed.append((instruction.value, instruction.fraction))

    assert all(fraction == 0 for _block, fraction in landed)
    assert all(block in target_paragraphs for block, _fraction in landed)


def test_smoothing_moves_the_other_panes_the_whole_way_down():
    """Smooth means many positions across the scene, not one per paragraph.

    Where two of the scrolled pane's paragraphs answer to one of another's
    -- which is what a merge does -- that pane necessarily rests while the
    second is read: it cannot be at the head of that paragraph for both and
    move continuously in between. It never goes backwards, and over the
    scene it lands far more places than it has paragraphs.
    """
    source_text = spaced(30, blank_lines=1)
    target_text = spaced(27, blank_lines=1)
    places = []
    for ordinal in range(30):
        for step in range(10):
            instruction = scroll_instruction(
                "paragraph",
                document_viewport(
                    source_text,
                    prose_blocks(source_text)[ordinal],
                    fraction=step / 10.0,
                ),
                document_viewport(target_text, 0),
                proportional=True,
            )
            places.append(instruction.value + instruction.fraction)

    assert places == sorted(places)
    assert len(set(places)) > 2 * len(prose_blocks(target_text))
