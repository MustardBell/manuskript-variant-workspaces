from types import SimpleNamespace

from PyQt5.QtCore import QItemSelectionModel
from PyQt5.QtWidgets import QApplication, QPushButton, QTreeView, QWidget


APP = QApplication.instance() or QApplication([])

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
from variant_workspaces.model import VariantRole


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
        create_character=lambda _name: None,
        create_plot=lambda _name: None,
        create_world_item=lambda _name: None,
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
