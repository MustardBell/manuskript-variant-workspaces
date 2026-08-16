from types import SimpleNamespace

import pytest

from PyQt5.QtCore import QEvent, QItemSelectionModel, Qt
from PyQt5.QtWidgets import QApplication, QPushButton, QTreeView, QWidget


APP = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def dispose_native_widgets_after_each_test():
    """Do not defer an entire file's native teardown to interpreter exit."""

    yield
    # Run whatever the test left queued while its widgets still exist. Doing
    # this afterwards asks a pending layout or view-state pass to re-enter a
    # destroyed QWidget, which PyQt reports as a fatal abort rather than as an
    # exception, and which macOS surfaced where Linux did not. A zero-interval
    # timer is armed by one pass and delivered by the next, so drain twice.
    APP.processEvents()
    APP.processEvents()
    for widget in tuple(APP.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    # Deferred deletion is the only thing left to deliver: it destroys the
    # native objects without running further Python callbacks.
    APP.sendPostedEvents(None, QEvent.DeferredDelete)

from manuskript.domain.plugin_data import ProjectPluginData
from manuskript.enums import Outline
from manuskript.models.outlineItem import outlineItem
from manuskript.models.outlineModel import outlineModel
from manuskript.plugins.api import EditorWorkspaceContext
from manuskript.settingsManager import SettingsManager
from manuskript.ui.editors.editor_context import EditorContext
from manuskript.ui.plugins.editor_workspaces import (
    WorkspaceEditorFactory,
    WorkspaceOutlineGateway,
)
from manuskript.ui.views.text_editor_context import TextEditorContext

from variant_workspaces.controller import create_workspace
from variant_workspaces.model import (
    DEFAULT_SYNC_STACK,
    SyncPrinciple,
    VariantRole,
)
from variant_workspaces.synchronization import viewport_position
from variant_workspaces.workspace_view import SyncStackDialog


def workspace_fixture():
    settings = SettingsManager()
    model = outlineModel(settings=settings)
    original = outlineItem(title="Original", _type="md")
    original.setData(Outline.text, "Opening line.\nShared event.\nEnding.")
    translation = outlineItem(title="Translation", _type="md")
    translation.setData(
        Outline.text,
        "Translated opening.\nShared translated event.\nTranslated ending.",
    )
    model.appendItem(original)
    model.appendItem(translation)
    tree = QTreeView()
    tree.setSelectionMode(QTreeView.ExtendedSelection)
    tree.setModel(model)
    original_index = model.indexFromItem(original)
    translation_index = model.indexFromItem(translation)
    selection = tree.selectionModel()
    selection.select(
        original_index,
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )
    selection.select(
        translation_index,
        QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )
    tree.setCurrentIndex(original_index)

    text_context = TextEditorContext(
        settings=settings,
        reload_fonts=lambda: None,
        invoke_outline_command=lambda _command: None,
    )
    editor_context = EditorContext(
        outline_model=model,
        outline_tree=tree,
        outline_views=None,
        text_editor=text_context,
    )
    owner = QWidget()
    gateway = WorkspaceOutlineGateway(model, tree, parent=owner)
    editors = WorkspaceEditorFactory(editor_context, gateway, parent=owner)
    plugin_data = ProjectPluginData()
    dirty = []
    statuses = []
    closed = []
    context = EditorWorkspaceContext(
        plugin_id="manuskript.variant-workspaces",
        project_file="/project/book.msk",
        selected_item_ids=(original.ID(), translation.ID()),
        files=plugin_data.namespace(
            "manuskript.variant-workspaces",
            on_change=lambda: dirty.append(True),
        ),
        outline=gateway,
        editors=editors,
        show_status=lambda *args: statuses.append(args),
        close_workspace=lambda: closed.append(True),
        capability=lambda _name: None,
    )
    view = create_workspace(context, owner)
    APP.processEvents()
    return SimpleNamespace(
        view=view,
        controller=view.controller,
        model=model,
        original=original,
        translation=translation,
        gateway=gateway,
        editors=editors,
        plugin_data=plugin_data,
        dirty=dirty,
        statuses=statuses,
        owner=owner,
    )


def test_real_workspace_keeps_variants_independent_and_switches_target():
    fixture = workspace_fixture()
    controller = fixture.controller
    group = controller.current_group
    assert fixture.view.splitter.count() == 2
    assert group.canonical_member.item_id == fixture.original.ID()
    assert fixture.original.compile()
    assert not fixture.translation.compile()

    source_member = next(
        member for member in group.members
        if member.item_id == fixture.translation.ID()
    )
    source = controller.endpoints[source_member.id]
    target = controller.endpoints[group.canonical_member_id]
    assert source.editing_locked
    assert not target.editing_locked

    controller.set_editable(source_member.id, True)
    source.replace_text("Independent changed translation.")
    assert fixture.translation.text() == "Independent changed translation."
    assert fixture.original.text().startswith("Opening line.")

    controller.set_canonical(source_member.id)
    assert fixture.translation.compile()
    assert not fixture.original.compile()
    assert controller.current_group.canonical_member_id == source_member.id
    fixture.view.prepare_close()
    assert fixture.plugin_data.namespace(
        "manuskript.variant-workspaces"
    ).read("variant-groups.json")


def test_pending_layout_work_dies_with_the_workspace():
    fixture = workspace_fixture()
    controller = fixture.controller
    group = controller.current_group
    source_member = next(
        member for member in group.members
        if member.id != group.canonical_member_id
    )

    controller.set_canonical(source_member.id)

    # Rebuilding the panes leaves geometry and view-state passes queued for
    # the next turn of the event loop.
    assert controller._restoreTimer.isActive()
    assert fixture.view._paneLayoutTimer.isActive()

    fixture.owner.close()
    fixture.owner.deleteLater()
    APP.sendPostedEvents(None, QEvent.DeferredDelete)
    # A reader can close a workspace in exactly this gap. The queued work must
    # be gone with the widgets it would otherwise have written into, however
    # many turns of the loop follow.
    APP.processEvents()
    APP.processEvents()

    with pytest.raises(RuntimeError):
        fixture.view.isVisible()


def test_selection_transfer_and_alignment_use_real_native_editors():
    fixture = workspace_fixture()
    controller = fixture.controller
    group = controller.current_group
    source_member = group.members[1]
    source = controller.endpoints[source_member.id]
    target = controller.endpoints[group.canonical_member_id]
    selected = "Translated opening."
    source.set_cursor_position(len(selected), anchor=0)
    target.set_cursor_position(len(target.text()))
    controller.last_active_member_id = source_member.id

    controller.transfer_selection()

    assert target.text().endswith(selected)
    assert source.text().startswith(selected)
    fixture.view.prompt_anchor_label = lambda _default: "Opening"
    controller.align_here()
    assert controller.current_group.anchors[0].label == "Opening"
    assert fixture.view.anchorList.count() == 1


def test_workspace_controls_are_text_labelled_and_accessible():
    fixture = workspace_fixture()
    view = fixture.view
    view.setParent(None)
    view.resize(1200, 700)
    view.show()
    APP.processEvents()
    APP.processEvents()

    assert view.accessibleName()
    assert view.groupList.accessibleName()
    assert view.splitter.accessibleName()
    assert view.statusLabel.accessibleName()
    assert view.transferShortcut.key().toString() == "Ctrl+Alt+Right"
    buttons = view.findChildren(QPushButton)
    assert buttons
    assert all(button.text().strip() for button in buttons)
    assert all(button.minimumHeight() >= 32 for button in buttons)
    assert not view.styleSheet()
    assert all(not button.styleSheet() for button in buttons)
    viewport_widths = {
        endpoint.viewport_width
        for endpoint in fixture.controller.endpoints.values()
    }
    assert len(viewport_widths) == 1
    view.hide()


def test_duplicate_and_delete_never_delete_or_alias_outline_prose():
    fixture = workspace_fixture()
    controller = fixture.controller
    fixture.view.prompt_new_variant = lambda _default: {
        "title": "Composite",
        "label": "Composite",
        "language": "en",
        "role": VariantRole.COMPOSITE,
    }

    controller.duplicate_target()

    group = controller.current_group
    composite = group.members[-1]
    composite_document = fixture.gateway.document(composite.item_id)
    assert composite_document.title == "Composite"
    assert composite_document.text == fixture.original.text()
    assert not composite_document.compile
    controller.endpoints[composite.id].set_editing_locked(False)
    controller.endpoints[composite.id].replace_text("Synthesized prose.")
    assert fixture.original.text().startswith("Opening line.")

    fixture.view.confirm = lambda *_args: True
    item_ids = {member.item_id for member in group.members}
    controller.delete_group()

    assert controller.state.groups == ()
    assert all(fixture.gateway.document(item_id) is not None for item_id in item_ids)
    assert all(fixture.gateway.document(item_id).compile for item_id in item_ids)


def test_pane_order_is_user_controlled_and_persisted_separately():
    fixture = workspace_fixture()
    controller = fixture.controller
    group = controller.current_group
    original_order = controller.comparison.pane_order

    controller.move_member(original_order[1], -1)

    assert controller.comparison.pane_order == tuple(reversed(original_order))
    raw = fixture.plugin_data.namespace(
        "manuskript.variant-workspaces"
    ).read("comparison-workspaces.json")
    assert original_order[1] in raw
    assert group.id in raw


def test_panes_hold_the_same_width_however_long_their_labels_are():
    """A comparison is unreadable when one column is wider than another.

    Chrome that differed between a canonical pane and its neighbours -- a
    label where they had a button -- gave each pane a different minimum
    width, and the splitter answered a request for equal shares with those
    minimums.
    """
    fixture = workspace_fixture()
    view = fixture.view
    view.setParent(None)
    view.resize(1100, 700)
    view.show()
    APP.processEvents()

    member = fixture.controller.current_group.members[1]
    view.prompt_member_settings = lambda _member: {
        "label": "A considerably longer variant label than its neighbour",
        "language": "uk",
        "role": member.role,
    }
    fixture.controller.edit_member(member.id)
    APP.processEvents()
    APP.processEvents()

    sizes = view.splitter.sizes()
    assert len(sizes) == 2
    assert max(sizes) - min(sizes) <= 1
    minimums = {
        view.splitter.widget(index).minimumSizeHint().width()
        for index in range(view.splitter.count())
    }
    assert len(minimums) == 1
    view.hide()


def test_every_pane_gets_the_same_text_column_and_none_scrolls_sideways():
    fixture = workspace_fixture()
    view = fixture.view
    view.setParent(None)
    view.resize(1100, 700)
    view.show()
    APP.processEvents()
    APP.processEvents()

    available = view.pane_content_width()
    assert available > 0
    endpoints = list(fixture.controller.endpoints.values())
    assert len({endpoint.viewport_width for endpoint in endpoints}) == 1
    for endpoint in endpoints:
        assert endpoint.widget.maximumWidth() <= available
        assert endpoint.editor.horizontalScrollBar().maximum() == 0
    view.hide()


def test_a_narrower_text_width_than_the_pane_is_what_the_reader_gets():
    fixture = workspace_fixture()
    view = fixture.view
    view.setParent(None)
    view.resize(1100, 700)
    view.show()
    APP.processEvents()

    fixture.controller.set_text_width(300)
    APP.processEvents()
    APP.processEvents()

    assert fixture.controller.comparison.text_width == 300
    for endpoint in fixture.controller.endpoints.values():
        assert endpoint.widget.maximumWidth() == 300
    view.hide()


def test_alignments_can_be_created_applied_and_removed_from_their_list():
    """Removing an anchor was the only thing the list offered."""
    fixture = workspace_fixture()
    controller = fixture.controller
    view = fixture.view
    assert not view.applyAnchorButton.isEnabled()
    assert not view.removeAnchorButton.isEnabled()

    view.prompt_anchor_label = lambda _default: "Opening"
    for endpoint in controller.endpoints.values():
        endpoint.set_cursor_position(4)
    controller.align_here()

    assert view.anchorList.count() == 1
    view.anchorList.setCurrentRow(0)
    assert view.applyAnchorButton.isEnabled()
    assert view.removeAnchorButton.isEnabled()

    applied = []
    view.anchorSelected.connect(applied.append)
    view.applyAnchorButton.click()
    assert applied == [controller.current_group.anchors[0].id]

    view.removeAnchorButton.click()
    assert controller.current_group.anchors == ()
    assert view.anchorList.count() == 0
    assert not view.applyAnchorButton.isEnabled()


def test_the_sync_stack_is_a_remembered_choice_of_the_comparison():
    fixture = workspace_fixture()
    controller = fixture.controller
    view = fixture.view
    assert controller.comparison.sync_stack == DEFAULT_SYNC_STACK

    view.syncStackChanged.emit(("paragraph",))

    assert controller.comparison.sync_stack == (SyncPrinciple.PARAGRAPH,)
    raw = fixture.plugin_data.namespace(
        "manuskript.variant-workspaces"
    ).read("comparison-workspaces.json")
    assert "sync_stack" in raw

    view.set_comparison_controls(controller.comparison)
    assert view.syncStackButton.text() == "Paragraphs"


def test_the_stack_button_says_what_order_the_principles_apply_in():
    fixture = workspace_fixture()
    view = fixture.view

    view.set_comparison_controls(fixture.controller.comparison)
    assert view.syncStackButton.text() == (
        "Alignment anchors \u2192 Paragraphs \u2192 Percentage"
    )

    view.syncStackChanged.emit(())
    view.set_comparison_controls(fixture.controller.comparison)
    assert view.syncStackButton.text() == "Off"


def test_the_stack_dialog_offers_every_principle_and_keeps_the_order():
    dialog = SyncStackDialog(("percentage", "anchors"))
    listed = [
        dialog.principleList.item(row).data(Qt.UserRole)
        for row in range(dialog.principleList.count())
    ]

    assert listed == ["percentage", "anchors", "paragraph"]
    assert dialog.values() == ("percentage", "anchors")

    dialog.principleList.setCurrentRow(1)
    dialog._move(-1)
    assert dialog.values() == ("anchors", "percentage")


def _shown_fixture(width=900, height=600):
    fixture = workspace_fixture()
    fixture.view.setParent(None)
    fixture.view.resize(width, height)
    fixture.view.show()
    APP.processEvents()
    APP.processEvents()
    return fixture


def _fill_panes(fixture):
    """Give both panes more prose than fits, in unequal amounts."""
    controller = fixture.controller
    member_ids = list(controller.endpoints)
    texts = (
        "\n\n".join("Source paragraph %d." % index for index in range(40)),
        "\n\n".join(
            "Target paragraph %d, which runs a good deal longer than the "
            "one it is set against." % index
            for index in range(40)
        ),
    )
    for member_id, text in zip(member_ids, texts):
        controller.set_editable(member_id, True)
        controller.endpoints[member_id].replace_text(text)
    APP.processEvents()
    APP.processEvents()
    return member_ids


def _followed_positions(fixture, source_id, target_id):
    controller = fixture.controller
    seen = []
    for value in range(0, 400, 20):
        controller.endpoints[source_id].set_scroll_value(value)
        controller._scrolled(source_id, value)
        APP.processEvents()
        seen.append(controller.endpoints[target_id].scroll_value)
    return seen


def test_smooth_paragraph_sync_keeps_pace_instead_of_stepping():
    """The complaint smoothing answers: panes that lurch a paragraph at a time."""
    fixture = _shown_fixture()
    controller = fixture.controller
    source_id, target_id = _fill_panes(fixture)
    controller.set_sync_stack(("paragraph",))
    stepping = _followed_positions(fixture, source_id, target_id)
    controller.set_sync_stack(("paragraph", "percentage"))
    smooth = _followed_positions(fixture, source_id, target_id)

    assert len(set(smooth)) > len(set(stepping))
    assert smooth == sorted(smooth)
    fixture.view.hide()


def test_smooth_anchor_sync_shares_out_the_span_between_alignments():
    fixture = _shown_fixture()
    controller = fixture.controller
    view = fixture.view
    source_id, target_id = _fill_panes(fixture)
    view.prompt_anchor_label = lambda _default: "Middle"
    for member_id in (source_id, target_id):
        endpoint = controller.endpoints[member_id]
        endpoint.set_cursor_position(endpoint.text().index("paragraph 20"))
    controller.align_here()
    APP.processEvents()
    controller.set_sync_stack(("anchors", "paragraph"))
    stepping = _followed_positions(fixture, source_id, target_id)
    controller.set_sync_stack(("anchors", "paragraph", "percentage"))
    smooth = _followed_positions(fixture, source_id, target_id)

    assert len(set(smooth)) > len(set(stepping))
    assert smooth == sorted(smooth)
    fixture.view.hide()


def test_paragraph_sync_matches_paragraphs_not_blank_lines():
    """The drift the reader saw: one variant spaced differently to the rest.

    Blank lines are blocks, and how many sit between two paragraphs is a
    writer's habit. Counting them made two variants of the same thirty
    paragraphs look like documents of different lengths, and the panes slid
    against each other by a fraction of a paragraph.
    """
    fixture = _shown_fixture()
    controller = fixture.controller
    member_ids = list(controller.endpoints)
    tight = "\n\n".join("Paragraph %d of this scene." % n for n in range(30))
    # A hand-merged variant, spaced the way hand merges end up: mostly the
    # same as its neighbour, with a stray blank line here and there.
    loose = "\n\n".join("Paragraph %d, merged." % n for n in range(30))
    for number in (6, 13, 21):
        loose = loose.replace(
            "Paragraph %d," % number, "\nParagraph %d," % number,
        )
    for member_id, text in zip(member_ids, (tight, loose)):
        controller.set_editable(member_id, True)
        controller.endpoints[member_id].replace_text(text)
    APP.processEvents()
    APP.processEvents()
    controller.set_sync_stack(("paragraph",))
    source_id, target_id = member_ids
    assert (
        controller.endpoints[source_id].block_count
        != controller.endpoints[target_id].block_count
    )

    def paragraph_under_the_eye(member_id):
        # Read the way the synchronizer reads it, so that a viewport
        # resting on a blank line counts as having finished the paragraph
        # above it in the measurement as well as in the answer.
        endpoint = controller.endpoints[member_id]
        return int(viewport_position(controller._viewport(endpoint)))

    drifted = []
    for value in range(0, 600, 25):
        controller.endpoints[source_id].set_scroll_value(value)
        controller._scrolled(source_id, value)
        APP.processEvents()
        seen = (
            paragraph_under_the_eye(source_id),
            paragraph_under_the_eye(target_id),
        )
        if seen[0] != seen[1]:
            drifted.append((value,) + seen)

    assert not drifted
    fixture.view.hide()


def _settle():
    """Let deferred layout finish.

    A zero-interval timer is armed by one pass of the loop and delivered by
    the next, so a single processEvents leaves pane geometry and text-width
    passes still pending.
    """

    APP.processEvents()
    APP.processEvents()


def _height_of(endpoint, needle):
    """How far below the pane's top edge a paragraph currently sits."""
    text = endpoint.text()
    block = text[:text.index(needle)].count("\n")
    return endpoint.scroll_value_for_block(block) - endpoint.scroll_value


def _two_long_panes(fixture):
    controller = fixture.controller
    member_ids = list(controller.endpoints)
    texts = (
        "\n\n".join(
            "Alpha paragraph %d, of a fairly ordinary length." % n
            for n in range(40)
        ),
        "\n\n".join(
            "Beta paragraph %d, which runs a good deal longer than the one "
            "it has been set against." % n
            for n in range(40)
        ),
    )
    for member_id, text in zip(member_ids, texts):
        controller.set_editable(member_id, True)
        controller.endpoints[member_id].replace_text(text)
    APP.processEvents()
    APP.processEvents()
    return member_ids


def test_clicking_a_paragraph_brings_its_counterpart_alongside_it():
    """Not to the top of the pane -- beside the paragraph that was clicked."""
    fixture = _shown_fixture(1100, 620)
    controller = fixture.controller
    source_id, target_id = _two_long_panes(fixture)
    controller.set_sync_stack(("paragraph", "percentage"))
    source = controller.endpoints[source_id]
    needle = "Alpha paragraph 15,"
    block = source.text()[:source.text().index(needle)].count("\n")
    # A real click can only land inside the visible viewport, and a pane
    # scrolls no further than its settled layout allows. Ask for the paragraph
    # a hundred pixels down, let the layout finish before clicking, and then
    # read where the paragraph actually ended up instead of assuming the
    # request survived: a pane whose layout was still growing clamps the
    # request, and a click delivered before it settles synchronizes the
    # counterpart against a position the source no longer holds.
    source.set_scroll_value(source.scroll_value_for_block(block) - 100)
    _settle()

    source.set_cursor_position(source.text().index(needle))
    _settle()

    height = _height_of(source, needle)
    assert height > 0, "the clicked paragraph should be below the pane's top"
    assert _height_of(
        controller.endpoints[target_id], "Beta paragraph 15,"
    ) == height
    fixture.view.hide()


def test_writing_inside_a_paragraph_leaves_the_other_panes_alone():
    fixture = _shown_fixture(1100, 620)
    controller = fixture.controller
    source_id, target_id = _two_long_panes(fixture)
    controller.set_sync_stack(("paragraph", "percentage"))
    source = controller.endpoints[source_id]
    start = source.text().index("Alpha paragraph 15,")
    source.set_cursor_position(start)
    APP.processEvents()
    settled = controller.endpoints[target_id].scroll_value

    for step in range(1, 12):
        source.set_cursor_position(start + step)
        APP.processEvents()

    assert controller.endpoints[target_id].scroll_value == settled
    fixture.view.hide()


def test_a_click_moves_nothing_when_the_reader_turned_sync_off():
    fixture = _shown_fixture(1100, 620)
    controller = fixture.controller
    source_id, target_id = _two_long_panes(fixture)
    controller.set_sync_stack(())
    source = controller.endpoints[source_id]
    settled = controller.endpoints[target_id].scroll_value

    source.set_cursor_position(source.text().index("Alpha paragraph 22,"))
    APP.processEvents()

    assert controller.endpoints[target_id].scroll_value == settled
    fixture.view.hide()


def test_following_a_caret_never_moves_another_panes_caret():
    """A pane is read to decide where the others look, never written to."""
    fixture = _shown_fixture(1100, 620)
    controller = fixture.controller
    source_id, target_id = _two_long_panes(fixture)
    controller.set_sync_stack(("paragraph", "percentage"))
    target = controller.endpoints[target_id]
    target.set_cursor_position(target.text().index("Beta paragraph 3,"))
    APP.processEvents()
    settled_caret = target.cursor_position
    settled_text = target.text()

    source = controller.endpoints[source_id]
    for paragraph in (8, 19, 27):
        source.set_cursor_position(
            source.text().index("Alpha paragraph %d," % paragraph)
        )
        APP.processEvents()

    assert target.cursor_position == settled_caret
    assert target.text() == settled_text
    fixture.view.hide()
