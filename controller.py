from dataclasses import replace
from functools import partial

from PyQt5.QtCore import QObject, QTimer

from .alignment import capture_anchor, repair_anchor, resolve_point
from .model import (
    ComparisonState,
    SyncPrinciple,
    VariantDataError,
    VariantGroup,
    VariantMember,
    VariantRole,
)
from .repository import VariantRepository
from .synchronization import (
    FeedbackGuard,
    ViewportState,
    block_for_paragraph,
    corresponding_position,
    following_position,
    paragraph_at_offset,
    paragraph_of_block,
    prose_blocks,
)
from .workspace_view import PaneBinding, VariantWorkspaceView


class VariantWorkspaceController(QObject):
    """Coordinate domain state, host capabilities, and the Qt view."""

    def __init__(self, context, view):
        super().__init__(view)
        self.context = context
        self.view = view
        self.repository = VariantRepository(context.files)
        self.state = None
        self.comparisons = {}
        self.current_group_id = None
        self.endpoints = {}
        self.resolved_anchors = {}
        #: The paragraph each pane's caret was last in, so that writing
        #: inside one does not keep nudging the other panes.
        self.caret_paragraphs = {}
        self.last_active_member_id = None
        self.guard = FeedbackGuard()
        self._loading = False
        self._applying_compile = False
        self._persistence_disabled = False
        self.saveTimer = QTimer(self)
        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(350)
        self.saveTimer.timeout.connect(self._flush_view_state)
        # Work that has to wait for the panes to exist re-enters those panes
        # when it runs. Own the timers so that closing the workspace cancels
        # them, and keep what they need as data rather than in a closure that
        # Qt has no way to disconnect.
        self._pending_view_state = None
        self._restoreTimer = QTimer(self)
        self._restoreTimer.setSingleShot(True)
        self._restoreTimer.setInterval(0)
        self._restoreTimer.timeout.connect(self._restore_pending_view_state)
        self._widthTimer = QTimer(self)
        self._widthTimer.setSingleShot(True)
        self._widthTimer.setInterval(0)
        self._widthTimer.timeout.connect(self._normalize_text_width)
        self._connect_view()
        context.outline.documentChanged.connect(self._document_changed)
        context.outline.structureChanged.connect(self._structure_changed)
        self._load()

    @property
    def current_group(self):
        return (
            self.state.group(self.current_group_id)
            if self.state is not None and self.current_group_id is not None
            else None
        )

    @property
    def comparison(self):
        group = self.current_group
        if group is None:
            return None
        return self.comparisons.get(
            group.id,
            ComparisonState(
                group_id=group.id,
                pane_order=tuple(member.id for member in group.members),
            ),
        )

    def _connect_view(self):
        self.view.groupSelected.connect(self.select_group)
        self.view.newGroupRequested.connect(self.new_group_from_selection)
        self.view.deleteGroupRequested.connect(self.delete_group)
        self.view.renameGroupRequested.connect(self.rename_group)
        self.view.addSelectedRequested.connect(self.add_selected)
        self.view.duplicateRequested.connect(self.duplicate_target)
        self.view.targetRequested.connect(self.set_canonical)
        self.view.memberSettingsRequested.connect(self.edit_member)
        self.view.removeMemberRequested.connect(self.remove_member)
        self.view.editingChanged.connect(self.set_editable)
        self.view.memberMoved.connect(self.move_member)
        self.view.equalizeRequested.connect(self.view.equalize_panes)
        self.view.textWidthChanged.connect(self.set_text_width)
        self.view.syncStackChanged.connect(self.set_sync_stack)
        self.view.alignRequested.connect(self.align_here)
        self.view.anchorSelected.connect(self.jump_to_anchor)
        self.view.removeAnchorRequested.connect(self.remove_anchor)
        self.view.transferRequested.connect(self.transfer_selection)
        self.view.paneGeometryChanged.connect(self._schedule_width_normalization)

    def _load(self):
        try:
            self.state = self.repository.load_state()
            self.comparisons = self.repository.load_comparisons()
        except VariantDataError as error:
            self._persistence_disabled = True
            from .model import VariantState
            self.state = VariantState()
            self.comparisons = {}
            self.view.show_error(
                self.view.tr("Variant data needs repair"),
                self.view.tr(
                    "The plugin did not overwrite its invalid project data. "
                    "Use Tools → Plugins → Raw Plugin Data to repair it.\n\n{}"
                ).format(error),
            )
        selected = self.context.selected_item_ids
        matching = next((
            group
            for group in self.state.groups
            if any(member.item_id in selected for member in group.members)
        ), None)
        if matching is not None:
            self.current_group_id = matching.id
        elif self.state.active_group_id is not None:
            self.current_group_id = self.state.active_group_id
        elif selected and not self._persistence_disabled:
            self._create_group(selected, prompt=False)
        self._render()

    def select_group(self, group_id):
        if self.state.group(group_id) is None:
            return
        self._save_current_view_state()
        self.current_group_id = group_id
        self.state = replace(self.state, active_group_id=group_id)
        self._save_state()
        self._render()

    def new_group_from_selection(self):
        if self._persistence_disabled:
            return
        self._create_group(self.context.outline.selected_item_ids(), prompt=True)

    def _create_group(self, item_ids, prompt):
        assigned = {
            member.item_id
            for group in self.state.groups
            for member in group.members
        }
        candidate_ids = [
            item_id
            for item_id in dict.fromkeys(item_ids)
            if item_id not in assigned
        ][:5]
        documents = [
            self.context.outline.document(item_id)
            for item_id in candidate_ids
        ]
        documents = [
            document
            for document in documents
            if document is not None and document.kind == "md"
        ]
        if not documents:
            self._status("Select one to five text items in the outline first.")
            return
        default_title = "{} variants".format(documents[0].title)
        title = (
            self.view.prompt_group_title(default_title)
            if prompt
            else default_title
        )
        if not title:
            return
        members = tuple(
            VariantMember.create(
                document.id,
                document.title,
                role=(
                    VariantRole.ORIGINAL
                    if index == 0
                    else VariantRole.ALTERNATE
                ),
                parent_item_id=document.parent_id,
                read_only=True,
            )
            for index, document in enumerate(documents)
        )
        group = VariantGroup.create(title, members)
        self.state = self.state.upsert(group)
        self.current_group_id = group.id
        self.comparisons[group.id] = ComparisonState(
            group_id=group.id,
            pane_order=tuple(member.id for member in members),
        )
        self._apply_compile_target(group)
        self._save_all()
        self._render()
        self._status("Created scene family “{}”.".format(title))

    def delete_group(self):
        group = self.current_group
        if group is None or not self.view.confirm(
            self.view.tr("Delete scene family"),
            self.view.tr(
                "Delete the relationship “{}”? The outline documents and "
                "their prose will not be deleted."
            ).format(group.title),
        ):
            return
        self.context.outline.set_compile_many({
            member.item_id: True
            for member in group.members
            if self.context.outline.document(member.item_id) is not None
        })
        self.state = self.state.remove(group.id)
        self.comparisons.pop(group.id, None)
        self.current_group_id = self.state.active_group_id
        self._save_all()
        self._render()

    def rename_group(self):
        group = self.current_group
        if group is None:
            return
        title = self.view.prompt_group_title(group.title)
        if title:
            self._store_group(replace(group, title=title))

    def add_selected(self):
        group = self.current_group
        if group is None:
            self.new_group_from_selection()
            return
        known = {member.item_id for member in group.members}
        assigned_elsewhere = {
            member.item_id
            for other in self.state.groups
            if other.id != group.id
            for member in other.members
        }
        candidates = [
            self.context.outline.document(item_id)
            for item_id in self.context.outline.selected_item_ids()
            if item_id not in known and item_id not in assigned_elsewhere
        ]
        candidates = [
            document for document in candidates
            if document is not None and document.kind == "md"
        ]
        if not candidates:
            self._status("No new selected text items can be added.")
            return
        capacity = 5 - len(group.members)
        candidates = candidates[:capacity]
        try:
            for document in candidates:
                group = group.with_member(VariantMember.create(
                    document.id,
                    document.title,
                    parent_item_id=document.parent_id,
                ))
        except VariantDataError as error:
            self._status(str(error))
            return
        self._store_group(group)

    def duplicate_target(self):
        group = self.current_group
        if group is None:
            return
        if len(group.members) >= 5:
            self._status("A scene family cannot contain more than five panes.")
            return
        target = group.canonical_member
        document = self.context.outline.document(target.item_id)
        if document is None:
            self._status("The canonical target document is missing.")
            return
        values = self.view.prompt_new_variant(
            "{} variant".format(document.title)
        )
        if values is None:
            return
        duplicate = self.context.outline.duplicate_text_document(
            target.item_id,
            title=values["title"],
            compile_document=False,
        )
        member = VariantMember.create(
            duplicate.id,
            values["label"],
            language=values["language"],
            role=values["role"],
            parent_item_id=duplicate.parent_id,
        )
        self._store_group(group.with_member(member))
        self._status("Created independent outline variant “{}”.".format(
            duplicate.title
        ))

    def set_canonical(self, member_id):
        group = self.current_group
        if group is None:
            return
        group = group.with_canonical(member_id)
        self._apply_compile_target(group)
        self._store_group(group)
        self._status("Canonical compile target changed to “{}”.".format(
            group.canonical_member.label
        ))

    def edit_member(self, member_id):
        group = self.current_group
        member = group.member(member_id) if group is not None else None
        if member is None:
            return
        values = self.view.prompt_member_settings(member)
        if values is None:
            return
        if not values["label"]:
            self._status("Pane labels cannot be empty.")
            return
        self._store_group(group.update_member(replace(member, **values)))

    def remove_member(self, member_id):
        group = self.current_group
        member = group.member(member_id) if group is not None else None
        if member is None:
            return
        if not self.view.confirm(
            self.view.tr("Remove family member"),
            self.view.tr(
                "Remove “{}” from this family? Its outline document and "
                "prose will remain unchanged."
            ).format(member.label),
        ):
            return
        try:
            updated = group.without_member(member_id)
        except VariantDataError as error:
            self._status(str(error))
            return
        comparison = self.comparison
        if self.context.outline.document(member.item_id) is not None:
            self.context.outline.set_compile(member.item_id, True)
        self.comparisons[group.id] = replace(
            comparison,
            pane_order=tuple(
                value for value in comparison.pane_order if value != member_id
            ),
            unlocked_member_ids=tuple(
                value
                for value in comparison.unlocked_member_ids
                if value != member_id
            ),
        )
        self._apply_compile_target(updated)
        self._store_group(updated)

    def move_member(self, member_id, direction):
        group = self.current_group
        comparison = self.comparison
        if group is None or comparison is None:
            return
        order = list(comparison.pane_order)
        if member_id not in order:
            return
        old_index = order.index(member_id)
        new_index = max(0, min(old_index + int(direction), len(order) - 1))
        if new_index == old_index:
            return
        order.pop(old_index)
        order.insert(new_index, member_id)
        self.comparisons[group.id] = replace(
            comparison,
            pane_order=tuple(order),
        )
        self._save_comparisons()
        self._render()

    def set_editable(self, member_id, editable):
        group = self.current_group
        comparison = self.comparison
        if group is None or comparison is None:
            return
        values = set(comparison.unlocked_member_ids)
        if editable:
            values.add(member_id)
        else:
            values.discard(member_id)
        self.comparisons[group.id] = replace(
            comparison,
            unlocked_member_ids=tuple(sorted(values)),
        )
        endpoint = self.endpoints.get(member_id)
        if endpoint is not None:
            endpoint.set_editing_locked(not editable)
        self._save_comparisons()

    def set_text_width(self, width):
        group = self.current_group
        comparison = self.comparison
        if self._loading or group is None or comparison is None:
            return
        self.comparisons[group.id] = replace(comparison, text_width=width)
        self._schedule_width_normalization()
        self._save_comparisons()

    def set_sync_stack(self, stack):
        group = self.current_group
        comparison = self.comparison
        if self._loading or group is None or comparison is None:
            return
        self.comparisons[group.id] = replace(
            comparison,
            sync_stack=tuple(SyncPrinciple(value) for value in stack),
        )
        self._save_comparisons()
        self.view.set_comparison_controls(self.comparison)

    def align_here(self):
        group = self.current_group
        if group is None or len(self.endpoints) < 2:
            self._status("At least two available panes are required to align.")
            return
        label = self.view.prompt_anchor_label(
            "Alignment {}".format(len(group.anchors) + 1)
        )
        if not label:
            return
        sources = {
            member_id: endpoint.text()
            for member_id, endpoint in self.endpoints.items()
        }
        selections = {
            member_id: endpoint.selection_range()
            for member_id, endpoint in self.endpoints.items()
        }
        anchor = capture_anchor(label, sources, selections)
        self._store_group(group.with_anchor(anchor))
        self._status("Created authoritative alignment “{}”.".format(label))

    def jump_to_anchor(self, anchor_id):
        group = self.current_group
        anchor = next((
            value for value in group.anchors if value.id == anchor_id
        ), None) if group is not None else None
        if anchor is None:
            return
        unresolved = []
        for member_id, point in anchor.points.items():
            endpoint = self.endpoints.get(member_id)
            if endpoint is None:
                unresolved.append(member_id)
                continue
            resolved = resolve_point(endpoint.text(), point)
            endpoint.scroll_to_text_offset(resolved.start)
            if not resolved.resolved:
                unresolved.append(member_id)
        self._status(
            "Anchor contains unresolved panes."
            if unresolved
            else "Aligned panes at “{}”.".format(anchor.label)
        )

    def remove_anchor(self, anchor_id):
        group = self.current_group
        if group is not None:
            self._store_group(group.without_anchor(anchor_id))

    def transfer_selection(self):
        group = self.current_group
        if group is None:
            return
        target_id = group.canonical_member_id
        source_id = self.last_active_member_id
        source = self.endpoints.get(source_id)
        if source is None or source_id == target_id or not source.selected_text():
            source = next((
                endpoint
                for member_id, endpoint in self.endpoints.items()
                if member_id != target_id and endpoint.selected_text()
            ), None)
        target = self.endpoints.get(target_id)
        if source is None or target is None:
            self._status("Select text in a source pane first.")
            return
        text = source.selected_text()
        target.set_editing_locked(False)
        target.insert_at_cursor(text)
        self._status("Sent {} characters to the canonical target.".format(
            len(text)
        ))

    def _render(self):
        self._loading = True
        try:
            self.view.set_groups(self.state.groups, self.current_group_id)
            group = self.current_group
            if group is None:
                self.endpoints = {}
                self.view.set_panes(())
                self.view.set_anchors(())
                self.view.show_status(
                    "Select outline text and create a scene family."
                )
                return
            comparison = self.comparison
            member_by_id = {member.id: member for member in group.members}
            order = [
                value
                for value in comparison.pane_order
                if value in member_by_id
            ]
            order.extend(
                member.id
                for member in group.members
                if member.id not in order
            )
            if tuple(order) != comparison.pane_order:
                comparison = replace(comparison, pane_order=tuple(order))
                self.comparisons[group.id] = comparison
                self._save_comparisons()

            for endpoint in self.endpoints.values():
                endpoint.submit()
            self.endpoints = {}
            self.caret_paragraphs = {}
            bindings = []
            for member_id in order:
                member = member_by_id[member_id]
                document = self.context.outline.document(member.item_id)
                missing = document is None or document.kind != "md"
                canonical = member.id == group.canonical_member_id
                unlocked = (
                    canonical
                    or member.id in comparison.unlocked_member_ids
                    or not member.read_only
                )
                endpoint = None
                if not missing:
                    endpoint = self.context.editors.create(
                        member.item_id,
                        parent=None,
                        editing_locked=not unlocked,
                    )
                    endpoint.set_presentation_mode("formatted-source")
                    endpoint.set_maximum_text_width(comparison.text_width)
                    endpoint.scrolled.connect(
                        partial(self._scrolled, member.id)
                    )
                    endpoint.cursorChanged.connect(
                        partial(self._cursor_changed, member.id)
                    )
                    endpoint.selectionChanged.connect(
                        partial(self._selection_changed, member.id)
                    )
                    self.endpoints[member.id] = endpoint
                bindings.append(PaneBinding(
                    member=member,
                    endpoint=endpoint,
                    canonical=canonical,
                    editing_locked=not unlocked,
                    missing=missing,
                ))
            self.view.set_panes(bindings)
            self.view.set_comparison_controls(comparison)
            self._schedule_width_normalization()
            self._repair_and_render_anchors(group)
            self._restore_view_state(comparison)
            missing_count = sum(binding.missing for binding in bindings)
            self.view.show_status(
                "{} panes; canonical target: {}.{}".format(
                    len(bindings),
                    group.canonical_member.label,
                    (
                        " {} referenced documents are missing.".format(
                            missing_count
                        )
                        if missing_count
                        else ""
                    ),
                )
            )
        finally:
            self._loading = False

    def _repair_and_render_anchors(self, group):
        sources = {
            member_id: endpoint.text()
            for member_id, endpoint in self.endpoints.items()
        }
        repaired_values = []
        rows = []
        changed = False
        self.resolved_anchors = {}
        for anchor in group.anchors:
            repaired, resolved, unresolved = repair_anchor(anchor, sources)
            repaired_values.append(repaired)
            self.resolved_anchors[anchor.id] = resolved
            changed = changed or repaired != anchor
            status = (
                "unresolved in {} pane{}".format(
                    len(unresolved),
                    "" if len(unresolved) == 1 else "s",
                )
                if unresolved
                else "resolved"
            )
            rows.append((anchor.id, anchor.label, status))
        self.view.set_anchors(rows)
        if changed:
            updated = replace(group, anchors=tuple(repaired_values))
            self.state = self.state.upsert(updated)
            self._save_state()

    def _restore_view_state(self, comparison):
        self._pending_view_state = comparison
        self._restoreTimer.start()

    def _restore_pending_view_state(self):
        comparison = self._pending_view_state
        self._pending_view_state = None
        if comparison is None:
            return
        for member_id, endpoint in self.endpoints.items():
            # Putting the panes back where they were left is not the
            # reader pointing at anything, so it must not drag the
            # other panes to wherever this one's caret happens to sit.
            with self.guard.programmatic(member_id):
                if member_id in comparison.cursor_positions:
                    endpoint.set_cursor_position(
                        comparison.cursor_positions[member_id]
                    )
                if member_id in comparison.scroll_positions:
                    endpoint.set_scroll_value(
                        comparison.scroll_positions[member_id]
                    )
            self.caret_paragraphs[member_id] = paragraph_of_block(
                self._viewport(endpoint), endpoint.cursor_block,
            )

    def _schedule_width_normalization(self):
        if self.endpoints:
            self._widthTimer.start()

    def _normalize_text_width(self):
        """Give every pane the same text column, as wide as the reader asked.

        The width comes from the panes rather than from the editors: capping
        an editor narrows the very viewport that would be measured next, and
        the column would ratchet itself shut a pass at a time.
        """
        comparison = self.comparison
        if comparison is None or not self.endpoints:
            return
        available = self.view.pane_content_width()
        effective = comparison.text_width
        if available > 0:
            effective = min(effective, available)
        for endpoint in self.endpoints.values():
            endpoint.set_maximum_text_width(effective)

    def _scrolled(self, member_id, _value):
        if self._loading or self.guard.is_active(member_id):
            return
        self._remember_current_view_state()
        self.saveTimer.start()
        group = self.current_group
        comparison = self.comparison
        source = self.endpoints.get(member_id)
        if group is None or comparison is None or source is None:
            return
        source_state = self._viewport(source)
        for target_id, target, target_state in self._other_panes(member_id):
            landed = following_position(
                comparison.sync_stack,
                source_state,
                target_state,
                self._shared_anchors(
                    group, member_id, source, target_id, target,
                    source_state, target_state,
                ),
            )
            if landed is None:
                continue
            with self.guard.programmatic(target_id):
                target.set_scroll_value(
                    self._scroll_value_at(target, target_state, landed)
                )

    def _other_panes(self, member_id):
        """Every pane but the one the reader is working in."""
        return [
            (target_id, target, self._viewport(target))
            for target_id, target in self.endpoints.items()
            if target_id != member_id
        ]

    def _shared_anchors(self, group, source_id, source, target_id, target,
                        source_state, target_state):
        """The alignments two panes share, as pairs of paragraphs.

        Deliberately not sorted by where they land in the other pane: an
        alignment that runs backwards is how a reader says a passage was
        moved, and putting the pairs in order over there would throw that
        away.
        """
        pairs = []
        for anchor in group.anchors:
            source_point = anchor.points.get(source_id)
            target_point = anchor.points.get(target_id)
            if source_point is None or target_point is None:
                continue
            source_resolved = resolve_point(source.text(), source_point)
            target_resolved = resolve_point(target.text(), target_point)
            if not (source_resolved.resolved and target_resolved.resolved):
                continue
            pairs.append((
                paragraph_at_offset(source_state, source.text(),
                                    source_resolved.start),
                paragraph_at_offset(target_state, target.text(),
                                    target_resolved.start),
            ))
        return tuple(pairs)

    @staticmethod
    def _scroll_value_at(endpoint, state, ordinal):
        """The scroll value that puts a fractional paragraph at the top."""
        landed = int(ordinal)
        fraction = ordinal - landed
        top = endpoint.scroll_value_for_block(
            block_for_paragraph(state, landed)
        )
        if fraction <= 0:
            return top
        following = endpoint.scroll_value_for_block(
            block_for_paragraph(state, landed + 1)
        )
        return int(round(top + fraction * (following - top)))

    def _cursor_changed(self, member_id, position, block):
        self.last_active_member_id = member_id
        if self._loading:
            return
        self._remember_current_view_state()
        self.saveTimer.start()
        self._follow_caret(member_id, position, block)

    def _follow_caret(self, member_id, position, block):
        """Show the paragraph the reader just pointed at in every other pane.

        Scrolling asks what belongs at the top of a pane, and that is the
        wrong answer for a click: the reader is looking at a paragraph part
        way down and wants its counterparts beside it, not the panes jumping
        so that it sits at the top. So the matching paragraph is put at the
        same height the clicked one is at, and the eye does not have to move.

        Only a caret arriving in a different paragraph moves anything, so
        writing inside one leaves the other panes alone.
        """
        group = self.current_group
        comparison = self.comparison
        source = self.endpoints.get(member_id)
        if group is None or comparison is None or source is None:
            return
        if self.guard.is_active(member_id):
            return
        source_state = self._viewport(source)
        paragraph = paragraph_of_block(source_state, block)
        if self.caret_paragraphs.get(member_id) == paragraph:
            return
        self.caret_paragraphs[member_id] = paragraph
        height = source.scroll_value_for_block(block) - source.scroll_value
        for target_id, target, target_state in self._other_panes(member_id):
            landed = corresponding_position(
                comparison.sync_stack,
                source_state,
                target_state,
                float(paragraph),
                self._shared_anchors(
                    group, member_id, source, target_id, target,
                    source_state, target_state,
                ),
            )
            if landed is None:
                continue
            with self.guard.programmatic(target_id):
                target.set_scroll_value(
                    self._scroll_value_at(target, target_state, landed)
                    - height
                )

    def _selection_changed(self, member_id, *_args):
        self.last_active_member_id = member_id

    @staticmethod
    def _viewport(endpoint):
        text = endpoint.text()
        return ViewportState(
            value=endpoint.scroll_value,
            maximum=endpoint.scroll_maximum,
            first_block=endpoint.first_visible_block,
            block_count=endpoint.block_count,
            text_length=len(text),
            block_fraction=endpoint.first_visible_block_fraction,
            paragraph_blocks=prose_blocks(text),
        )

    def _document_changed(self, item_id):
        if self._applying_compile:
            return
        group = self.current_group
        if group is None:
            return
        member = next((
            value for value in group.members if value.item_id == item_id
        ), None)
        if member is not None and member.id not in self.endpoints:
            self._render()

    def _structure_changed(self):
        self._render()

    def _apply_compile_target(self, group):
        values = {
            member.item_id: member.id == group.canonical_member_id
            for member in group.members
            if self.context.outline.document(member.item_id) is not None
        }
        self._applying_compile = True
        try:
            self.context.outline.set_compile_many(values)
        finally:
            self._applying_compile = False

    def _store_group(self, group):
        updated_state = self.state.upsert(group)
        self._apply_compile_target(group)
        self.state = updated_state
        self.current_group_id = group.id
        self._save_all()
        self._render()

    def _save_current_view_state(self):
        self._remember_current_view_state()
        self._save_comparisons()

    def _remember_current_view_state(self):
        group = self.current_group
        comparison = self.comparison
        if group is None or comparison is None:
            return
        self.comparisons[group.id] = replace(
            comparison,
            scroll_positions={
                member_id: endpoint.scroll_value
                for member_id, endpoint in self.endpoints.items()
            },
            cursor_positions={
                member_id: endpoint.cursor_position
                for member_id, endpoint in self.endpoints.items()
            },
        )

    def _flush_view_state(self):
        self._remember_current_view_state()
        self._save_comparisons()

    def prepare_close(self):
        self.saveTimer.stop()
        self._restoreTimer.stop()
        self._widthTimer.stop()
        self._pending_view_state = None
        for endpoint in self.endpoints.values():
            endpoint.submit()
        self._save_current_view_state()

    def _save_state(self):
        if not self._persistence_disabled:
            self.repository.save_state(self.state)

    def _save_comparisons(self):
        if not self._persistence_disabled:
            self.repository.save_comparisons(self.comparisons)

    def _save_all(self):
        self._save_state()
        self._save_comparisons()

    def _status(self, message):
        self.view.show_status(message)
        self.context.show_status(str(message), 5000, 1)


def create_workspace(context, parent):
    view = VariantWorkspaceView(parent)
    controller = VariantWorkspaceController(context, view)
    view.controller = controller
    return view
