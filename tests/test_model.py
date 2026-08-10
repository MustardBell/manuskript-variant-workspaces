import pytest

from variant_workspaces.model import (
    DEFAULT_SYNC_STACK,
    AlignmentAnchor,
    AnchorPoint,
    ComparisonState,
    SyncPrinciple,
    VariantDataError,
    VariantGroup,
    VariantMember,
    VariantRole,
    VariantState,
    comparison_from_dict,
    comparison_to_dict,
    state_from_dict,
    state_to_dict,
)


def members():
    return (
        VariantMember.create("scene-1", "Original", "en", VariantRole.ORIGINAL),
        VariantMember.create(
            "scene-2", "Translation", "uk", VariantRole.TRANSLATION
        ),
    )


def test_state_round_trip_preserves_roles_and_anchor_ranges():
    first, second = members()
    point = AnchorPoint(1, 2, 3, 4, 20, "fingerprint", "snippet")
    group = VariantGroup.create("Opening", (first, second))
    group = group.with_anchor(AlignmentAnchor.create(
        "Arrival",
        {first.id: point, second.id: point},
    ))
    state = VariantState((group,), active_group_id=group.id)

    restored = state_from_dict(state_to_dict(state))

    assert restored == state
    assert restored.groups[0].members[1].role is VariantRole.TRANSLATION


def test_group_enforces_unique_documents_and_five_pane_limit():
    first, _second = members()
    duplicate = VariantMember.create("scene-1", "Same document")
    with pytest.raises(VariantDataError, match="only once"):
        VariantGroup.create("Invalid", (first, duplicate))

    too_many = tuple(
        VariantMember.create(str(index), "Pane {}".format(index))
        for index in range(6)
    )
    with pytest.raises(VariantDataError, match="one and five"):
        VariantGroup.create("Invalid", too_many)


def test_removing_canonical_selects_a_new_target_and_drops_bad_anchors():
    first, second = members()
    point = AnchorPoint(0, 0, 0, 0, 0, "x", "x")
    group = VariantGroup.create("Opening", (first, second))
    group = group.with_anchor(AlignmentAnchor.create(
        "Start", {first.id: point, second.id: point}
    ))

    updated = group.without_member(first.id)

    assert updated.canonical_member_id == second.id
    assert updated.anchors == ()


def test_document_cannot_belong_to_two_scene_families():
    member = VariantMember.create("scene-1", "Original")
    first = VariantGroup.create("First", (member,))
    duplicate = VariantMember.create("scene-1", "Same document")
    second = VariantGroup.create("Second", (duplicate,))

    with pytest.raises(VariantDataError, match="multiple"):
        VariantState((first, second))


def test_a_project_written_before_the_stack_is_read_as_what_it_meant():
    """A reader's comparison must go on behaving the way they left it."""
    assert comparison_from_dict({
        "group_id": "g", "sync_mode": "paragraph", "proportional_sync": True,
    }).sync_stack == (SyncPrinciple.PARAGRAPH, SyncPrinciple.PERCENTAGE)
    assert comparison_from_dict({
        "group_id": "g", "sync_mode": "anchors", "proportional_sync": False,
    }).sync_stack == (SyncPrinciple.ANCHORS,)
    assert comparison_from_dict({
        "group_id": "g", "sync_mode": "off",
    }).sync_stack == ()
    # Nothing recorded either way: the default stands.
    assert comparison_from_dict(
        {"group_id": "g"}
    ).sync_stack == DEFAULT_SYNC_STACK


def test_the_stack_survives_a_round_trip_and_never_repeats_a_principle():
    state = ComparisonState(
        group_id="g",
        sync_stack=("percentage", "anchors", "percentage"),
    )

    assert state.sync_stack == (
        SyncPrinciple.PERCENTAGE, SyncPrinciple.ANCHORS,
    )
    assert comparison_from_dict(
        comparison_to_dict(state)
    ).sync_stack == state.sync_stack
