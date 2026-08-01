from variant_workspaces.alignment import (
    capture_anchor,
    capture_point,
    repair_anchor,
    resolve_point,
)


def test_anchor_repairs_after_paragraphs_are_inserted():
    original = "Heading\nFirst paragraph.\nImportant landing point.\nEnd."
    point = capture_point(original, original.index("landing"))
    edited = "New preface.\n" + original

    resolved = resolve_point(edited, point)

    assert resolved.resolved
    assert resolved.repaired
    assert edited[resolved.start:].startswith("landing")
    assert resolved.paragraph_index == point.paragraph_index + 1


def test_unresolved_anchor_remains_visible_at_safe_approximation():
    point = capture_point("Recognizable source", 4)

    resolved = resolve_point("Completely unrelated replacement", point)

    assert not resolved.resolved
    assert resolved.confidence == 0.0
    assert 0 <= resolved.start <= len("Completely unrelated replacement")


def test_capture_and_repair_multi_pane_anchor():
    sources = {
        "original": "A\nShared event\nC",
        "translation": "X\nTranslated event\nZ",
    }
    anchor = capture_anchor(
        "Event",
        sources,
        {
            "original": (2, 8),
            "translation": (2, 12),
        },
    )
    changed = dict(sources)
    changed["translation"] = "Preface\n" + changed["translation"]

    repaired, resolved, unresolved = repair_anchor(anchor, changed)

    assert not unresolved
    assert resolved["translation"].repaired
    assert repaired.points["translation"].paragraph_index == 2
