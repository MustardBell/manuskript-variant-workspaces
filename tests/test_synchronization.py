from variant_workspaces.model import DEFAULT_SYNC_STACK
from variant_workspaces.synchronization import (
    FeedbackGuard,
    ViewportState,
    corresponding_position,
    following_position,
    paragraph_at_offset,
    prose_blocks,
    viewport_position,
)


ANCHORS = "anchors"
PARAGRAPH = "paragraph"
PERCENTAGE = "percentage"


def spaced(paragraphs, blank_lines=1):
    """A document of so many paragraphs, spaced the way a writer chose."""
    return ("\n" * (blank_lines + 1)).join(
        "Paragraph %d." % index for index in range(paragraphs)
    )


def document(text, first_block=0, fraction=0.0):
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


def at_paragraph(text, ordinal, fraction=0.0):
    return document(text, prose_blocks(text)[ordinal], fraction)


def test_prose_blocks_names_the_lines_that_hold_paragraphs():
    assert prose_blocks("one\n\ntwo\n\n\nthree") == (0, 2, 5)
    assert prose_blocks("") == ()
    assert prose_blocks("\n \n\t\n") == ()


def test_an_empty_stack_is_how_a_reader_says_do_not_follow():
    text = spaced(10)
    assert following_position((), at_paragraph(text, 3), document(text)) is None


def test_the_same_paragraphs_align_however_they_are_spaced():
    """Blank lines are a writer's habit, not a place in the scene."""
    tight = spaced(20, blank_lines=1)
    loose = spaced(20, blank_lines=2)

    landed = following_position(
        (PARAGRAPH,), at_paragraph(tight, 7), document(loose),
    )

    assert landed == 7


def test_paragraphs_alone_land_on_a_paragraph_and_go_no_finer():
    tight = spaced(30)
    loose = spaced(27)

    landed = following_position(
        (PARAGRAPH,), at_paragraph(tight, 12, fraction=0.6), document(loose),
    )

    assert landed == int(landed)


def test_a_percentage_under_paragraphs_crosses_towards_the_next_one():
    text = spaced(20)

    landed = following_position(
        (PARAGRAPH, PERCENTAGE),
        at_paragraph(text, 5, fraction=0.5),
        document(text),
    )

    assert landed == 5.5


def test_a_percentage_on_its_own_spans_the_whole_scene():
    source = spaced(11)
    target = spaced(21)

    landed = following_position(
        (PERCENTAGE,), at_paragraph(source, 5), document(target),
    )

    assert landed == 10.0


def test_a_paragraph_top_matches_a_paragraph_top_however_many_there_are():
    """A merged variant has its own count, and boundaries must still meet."""
    source = spaced(30)
    target = spaced(27)

    landed = [
        following_position(
            DEFAULT_SYNC_STACK, at_paragraph(source, ordinal), document(target),
        )
        for ordinal in range(27)
    ]

    assert all(place == int(place) for place in landed)


def test_alignments_take_precedence_over_counting_paragraphs():
    """Twenty paragraphs against forty, with the reader's own alignment."""
    source = spaced(20)
    target = spaced(40)

    counted = following_position(
        (PARAGRAPH,), at_paragraph(source, 10), document(target),
    )
    aligned = following_position(
        (ANCHORS, PARAGRAPH),
        at_paragraph(source, 10),
        document(target),
        anchors=((10, 12),),
    )

    assert aligned == 12, "an alignment says where its own paragraph lands"
    assert counted != aligned, "counting alone would have put it elsewhere"


def test_paragraphs_are_counted_from_the_alignment_above_them():
    """Past an alignment, the shift it declares is carried straight on."""
    source = spaced(20)
    target = spaced(22)

    landed = [
        following_position(
            (ANCHORS, PARAGRAPH),
            at_paragraph(source, ordinal),
            document(target),
            anchors=((10, 12),),
        )
        for ordinal in range(10, 20)
    ]

    assert landed == [float(ordinal + 2) for ordinal in range(10, 20)]


def test_an_alignment_that_runs_backwards_repairs_a_moved_passage():
    """A passage that moved is an alignment whose target goes the other way."""
    source = spaced(30)
    target = spaced(30)
    anchors = ((10, 25), (14, 29))

    before = following_position(
        (ANCHORS, PARAGRAPH),
        at_paragraph(source, 5),
        document(target),
        anchors=anchors,
    )
    inside = following_position(
        (ANCHORS, PARAGRAPH),
        at_paragraph(source, 12),
        document(target),
        anchors=anchors,
    )

    assert before < 25, "before the move, the panes track their own order"
    assert 25 <= inside <= 29, "inside it, the reader's alignment decides"


def test_a_backwards_alignment_is_still_read_forwards_inside_itself():
    source = spaced(30)
    target = spaced(30)
    anchors = ((10, 25), (20, 4))

    stepped = following_position(
        (ANCHORS, PARAGRAPH),
        at_paragraph(source, 12),
        document(target),
        anchors=anchors,
    )
    crossing = following_position(
        (ANCHORS, PARAGRAPH, PERCENTAGE),
        at_paragraph(source, 12, fraction=0.5),
        document(target),
        anchors=anchors,
    )

    assert crossing > stepped, "a paragraph is read towards the next one"


def test_the_order_of_the_stack_is_the_whole_of_the_choice():
    source = spaced(11)
    target = spaced(21)
    reader = at_paragraph(source, 5, fraction=0.5)

    coarse = following_position((PERCENTAGE,), reader, document(target))
    refined = following_position(
        (PERCENTAGE, PARAGRAPH), reader, document(target),
    )

    assert coarse == 11.0
    assert refined == int(refined), "paragraphs after a share still land on one"


def test_a_click_is_answered_with_the_paragraph_that_matches_it():
    source = spaced(30)
    target = spaced(27, blank_lines=2)

    landed = corresponding_position(
        DEFAULT_SYNC_STACK, document(source), document(target), position=10.0,
    )

    assert landed == 9


def test_a_click_moves_nothing_when_nothing_is_stacked():
    text = spaced(10)
    assert corresponding_position(
        (), document(text), document(text), position=4.0,
    ) is None


def test_where_the_viewport_sits_is_read_in_paragraphs():
    text = spaced(10)
    blocks = prose_blocks(text)

    assert viewport_position(document(text, blocks[3])) == 3
    assert viewport_position(document(text, blocks[3], fraction=0.5)) == 3.5
    # A blank line belongs to the paragraph above it: it has been finished.
    assert viewport_position(document(text, blocks[3] + 1)) == 4


def test_an_alignment_is_placed_by_the_paragraph_it_was_captured_in():
    text = spaced(10)
    state = document(text)
    offset = text.index("Paragraph 4.") + 3

    assert paragraph_at_offset(state, text, offset) == 4
    assert paragraph_at_offset(state, text, 0) == 0


def test_a_document_of_blank_lines_still_answers():
    empty = ViewportState(0, 100, 3, 9, 8)
    target = ViewportState(0, 100, 0, 17, 16)

    assert following_position((PARAGRAPH,), empty, target) == 6


def test_feedback_guard_is_scoped_per_endpoint():
    guard = FeedbackGuard()
    with guard.programmatic("target"):
        assert guard.is_active("target")
        assert not guard.is_active("source")
    assert not guard.is_active("target")


def test_alignments_at_both_ends_of_a_moved_run_place_it_exactly():
    """The use of out-of-order alignments: a passage that changed place.

    Five paragraphs were lifted from the middle of the scene to the front
    of the other version. Alignments at both ends of the run and of what it
    displaced say so, and every paragraph then lands where it truly lives.
    """
    paragraphs = ["Paragraph %d." % index for index in range(30)]
    source = "\n\n".join(paragraphs)
    target = "\n\n".join(
        paragraphs[20:25] + paragraphs[:20] + paragraphs[25:]
    )
    truly = {
        index: target.split("\n\n").index(paragraphs[index])
        for index in range(30)
    }
    anchors = ((0, 5), (19, 24), (20, 0), (24, 4), (25, 25))

    landed = {
        index: following_position(
            (ANCHORS, PARAGRAPH),
            at_paragraph(source, index),
            document(target),
            anchors=anchors,
        )
        for index in range(30)
    }

    assert landed == {
        index: float(place) for index, place in truly.items()
    }


def test_an_alignment_on_the_first_paragraph_is_not_talked_over():
    """Where a moved run begins is exactly where a reader anchors it."""
    source = spaced(20)
    target = spaced(20)

    landed = following_position(
        (ANCHORS, PARAGRAPH),
        at_paragraph(source, 0),
        document(target),
        anchors=((0, 6),),
    )

    assert landed == 6
