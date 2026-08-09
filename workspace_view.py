from dataclasses import dataclass

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFontMetrics, QKeySequence
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .model import SyncMode, VariantRole


@dataclass(frozen=True)
class PaneBinding:
    member: object
    endpoint: object
    canonical: bool
    editing_locked: bool
    missing: bool = False


class MemberSettingsDialog(QDialog):
    def __init__(self, member, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Variant member settings"))
        self.setModal(True)
        layout = QFormLayout(self)
        self.labelEdit = QLineEdit(member.label, self)
        self.labelEdit.setAccessibleName(self.tr("Pane label"))
        layout.addRow(self.tr("&Pane label:"), self.labelEdit)
        self.languageEdit = QLineEdit(member.language, self)
        self.languageEdit.setPlaceholderText(self.tr("for example: en, uk"))
        self.languageEdit.setAccessibleName(self.tr("Language"))
        layout.addRow(self.tr("&Language:"), self.languageEdit)
        self.roleCombo = QComboBox(self)
        self.roleCombo.setAccessibleName(self.tr("Variant role"))
        for role, label in (
            (VariantRole.ORIGINAL, self.tr("Original")),
            (VariantRole.TRANSLATION, self.tr("Translation")),
            (VariantRole.REWRITE, self.tr("Rewrite")),
            (VariantRole.COMPOSITE, self.tr("Composite")),
            (VariantRole.ALTERNATE, self.tr("Alternate")),
        ):
            self.roleCombo.addItem(label, role.value)
        role_index = self.roleCombo.findData(member.role.value)
        self.roleCombo.setCurrentIndex(max(0, role_index))
        layout.addRow(self.tr("&Role:"), self.roleCombo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self):
        return {
            "label": self.labelEdit.text().strip(),
            "language": self.languageEdit.text().strip(),
            "role": VariantRole(self.roleCombo.currentData()),
        }


class NewVariantDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Create independent variant"))
        layout = QFormLayout(self)
        explanation = QLabel(
            self.tr(
                "This creates a new ordinary outline text next to the "
                "canonical target and copies its current prose."
            ),
            self,
        )
        explanation.setWordWrap(True)
        layout.addRow(explanation)
        self.titleEdit = QLineEdit(title, self)
        layout.addRow(self.tr("&Outline title:"), self.titleEdit)
        self.labelEdit = QLineEdit(title, self)
        layout.addRow(self.tr("&Pane label:"), self.labelEdit)
        self.languageEdit = QLineEdit(self)
        layout.addRow(self.tr("&Language:"), self.languageEdit)
        self.roleCombo = QComboBox(self)
        for role, label in (
            (VariantRole.TRANSLATION, self.tr("Translation")),
            (VariantRole.REWRITE, self.tr("Rewrite")),
            (VariantRole.COMPOSITE, self.tr("Composite")),
            (VariantRole.ALTERNATE, self.tr("Alternate")),
            (VariantRole.ORIGINAL, self.tr("Original")),
        ):
            self.roleCombo.addItem(label, role.value)
        layout.addRow(self.tr("&Role:"), self.roleCombo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _accept_if_valid(self):
        if not self.titleEdit.text().strip() or not self.labelEdit.text().strip():
            QMessageBox.warning(
                self,
                self.tr("Missing title"),
                self.tr("Outline title and pane label are required."),
            )
            return
        self.accept()

    def values(self):
        return {
            "title": self.titleEdit.text().strip(),
            "label": self.labelEdit.text().strip(),
            "language": self.languageEdit.text().strip(),
            "role": VariantRole(self.roleCombo.currentData()),
        }


class ElidingLabel(QLabel):
    """A label that gives way instead of holding a pane open.

    A plain QLabel asks for the width of its whole text and never accepts
    less, so the pane holding the longest variant title claimed more of the
    splitter than its neighbours and the columns came out uneven. This one
    keeps the full text for assistive technology and for its tooltip, and
    paints as much of it as the pane can currently spare.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self.setAccessibleName(self._full_text)
        self.updateGeometry()
        self._paint_elided()

    def text(self):
        return self._full_text

    def sizeHint(self):
        # Measured from the whole text, never from what is currently on
        # screen: a hint that shrank with the ellipsis would make the label
        # ask for less room each time it was given less, and it would never
        # grow back when the pane widened again.
        hint = super().sizeHint()
        hint.setWidth(
            QFontMetrics(self.font()).horizontalAdvance(self._full_text)
        )
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._paint_elided()

    def _paint_elided(self):
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(
            self._full_text,
            Qt.ElideRight,
            max(0, self.width()),
        ))


class VariantPane(QFrame):
    targetRequested = pyqtSignal(str)
    settingsRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)
    editingChanged = pyqtSignal(str, bool)
    moveRequested = pyqtSignal(str, int)

    #: Panes are read side by side, so every pane must be able to shrink to
    #: the same width as every other one. Two rows of buttons are the floor.
    MINIMUM_WIDTH = 180

    def __init__(self, binding, parent=None):
        super().__init__(parent)
        self.binding = binding
        member = binding.member
        self.setObjectName("variantPane")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(self.MINIMUM_WIDTH)
        self.setAccessibleName(member.label)
        self.setAccessibleDescription(
            self.tr("Independent scene variant editor pane")
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        identity_header = QHBoxLayout()
        title = ElidingLabel(member.label, self)
        title.setObjectName("variantPaneTitle")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        identity_header.addWidget(title, 1)
        details = " · ".join(filter(None, (
            member.role.value.replace("-", " ").title(),
            member.language,
        )))
        detail_label = ElidingLabel(details, self)
        detail_label.setAccessibleDescription(self.tr("Role and language"))
        identity_header.addWidget(detail_label)

        # Every pane offers the same control in the same place. Announcing
        # the canonical pane with a label instead of a button made its
        # geometry differ from its neighbours', which is precisely what a
        # comparison workspace must not do.
        self.targetButton = QPushButton(self)
        self.targetButton.setMinimumHeight(32)
        if binding.canonical:
            self.targetButton.setObjectName("canonicalTargetButton")
            self.targetButton.setText(self.tr("Target"))
            self.targetButton.setCheckable(True)
            self.targetButton.setChecked(True)
            self.targetButton.setEnabled(False)
            self.targetButton.setAccessibleName(
                self.tr("Canonical compile target")
            )
            self.targetButton.setToolTip(
                self.tr("This variant is the one that compiles")
            )
        else:
            self.targetButton.setText(self.tr("Set as target"))
            self.targetButton.setToolTip(
                self.tr("Compile this member and exclude the other variants")
            )
            self.targetButton.clicked.connect(
                lambda: self.targetRequested.emit(member.id)
            )
        identity_header.addWidget(self.targetButton)
        layout.addLayout(identity_header)

        actions_header = QGridLayout()

        self.editingCheck = QCheckBox(self.tr("Allow editing"), self)
        self.editingCheck.setChecked(binding.canonical or not binding.editing_locked)
        if binding.canonical:
            self.editingCheck.setEnabled(False)
            self.editingCheck.setToolTip(
                self.tr("The compile target is always editable")
            )
            self.editingCheck.setAccessibleDescription(
                self.tr("Canonical target editing is enabled")
            )
        else:
            self.editingCheck.setEnabled(not binding.missing)
            self.editingCheck.setToolTip(
                self.tr("Source variants are protected from accidental edits")
            )
            self.editingCheck.toggled.connect(
                lambda checked: self.editingChanged.emit(member.id, checked)
            )
        actions_header.addWidget(self.editingCheck, 0, 0, 1, 2)
        move_left = QPushButton(self.tr("Move left"), self)
        move_left.setMinimumHeight(32)
        move_left.clicked.connect(
            lambda: self.moveRequested.emit(member.id, -1)
        )
        actions_header.addWidget(move_left, 1, 0)
        move_right = QPushButton(self.tr("Move right"), self)
        move_right.setMinimumHeight(32)
        move_right.clicked.connect(
            lambda: self.moveRequested.emit(member.id, 1)
        )
        actions_header.addWidget(move_right, 1, 1)
        settings = QPushButton(self.tr("Settings…"), self)
        settings.setMinimumHeight(32)
        settings.clicked.connect(
            lambda: self.settingsRequested.emit(member.id)
        )
        actions_header.addWidget(settings, 2, 0)
        remove = QPushButton(self.tr("Remove"), self)
        remove.setMinimumHeight(32)
        remove.setAccessibleName(self.tr("Remove from scene family"))
        remove.setToolTip(
            self.tr("Remove this relationship without deleting its prose")
        )
        remove.clicked.connect(
            lambda: self.removeRequested.emit(member.id)
        )
        actions_header.addWidget(remove, 2, 1)
        layout.addLayout(actions_header)

        if binding.missing:
            missing = QLabel(
                self.tr(
                    "Missing document — the relationship is preserved until "
                    "you remove this member from the family."
                ),
                self,
            )
            missing.setWordWrap(True)
            missing.setAlignment(Qt.AlignCenter)
            missing.setAccessibleName(self.tr("Missing variant document"))
            layout.addWidget(missing, 1)
        else:
            layout.addWidget(binding.endpoint.widget, 1)

    def content_width(self):
        """How much width this pane can currently give a text column.

        Measured from the pane's own geometry rather than from its layout,
        which reports a stale rectangle until the first layout pass has run.
        """
        margins = self.layout().contentsMargins()
        return max(0, (
            self.contentsRect().width()
            - margins.left()
            - margins.right()
        ))


class VariantWorkspaceView(QWidget):
    groupSelected = pyqtSignal(str)
    newGroupRequested = pyqtSignal()
    deleteGroupRequested = pyqtSignal()
    renameGroupRequested = pyqtSignal()
    addSelectedRequested = pyqtSignal()
    duplicateRequested = pyqtSignal()
    targetRequested = pyqtSignal(str)
    memberSettingsRequested = pyqtSignal(str)
    removeMemberRequested = pyqtSignal(str)
    editingChanged = pyqtSignal(str, bool)
    memberMoved = pyqtSignal(str, int)
    equalizeRequested = pyqtSignal()
    textWidthChanged = pyqtSignal(int)
    syncModeChanged = pyqtSignal(str)
    proportionalSyncChanged = pyqtSignal(bool)
    alignRequested = pyqtSignal()
    anchorSelected = pyqtSignal(str)
    removeAnchorRequested = pyqtSignal(str)
    transferRequested = pyqtSignal()
    paneGeometryChanged = pyqtSignal()

    #: Sync modes that step from one landmark to the next, and so have a
    #: proportional reading of the distance between two of them.
    PROPORTIONAL_MODES = (SyncMode.PARAGRAPH, SyncMode.ANCHORS)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("variantWorkspace")
        self.setAccessibleName(self.tr("Variant comparison workspace"))
        self.setAccessibleDescription(
            self.tr(
                "Compare and edit independent variants with one canonical "
                "compile target."
            )
        )
        self._pane_widgets = []
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        sidebar = QWidget(self)
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(340)
        side_layout = QVBoxLayout(sidebar)
        groups_label = QLabel(self.tr("Scene families"), sidebar)
        groups_label.setBuddy(None)
        groups_font = groups_label.font()
        groups_font.setBold(True)
        groups_label.setFont(groups_font)
        side_layout.addWidget(groups_label)
        self.groupList = QListWidget(sidebar)
        self.groupList.setAccessibleName(self.tr("Scene families"))
        groups_label.setBuddy(self.groupList)
        self.groupList.currentItemChanged.connect(self._group_changed)
        side_layout.addWidget(self.groupList, 1)
        new_group = QPushButton(self.tr("New from outline selection"), sidebar)
        new_group.setMinimumHeight(32)
        new_group.clicked.connect(self.newGroupRequested)
        side_layout.addWidget(new_group)
        rename_group = QPushButton(self.tr("Rename scene family…"), sidebar)
        rename_group.setMinimumHeight(32)
        rename_group.clicked.connect(self.renameGroupRequested)
        side_layout.addWidget(rename_group)
        delete_group = QPushButton(self.tr("Delete family relationship"), sidebar)
        delete_group.setMinimumHeight(32)
        delete_group.clicked.connect(self.deleteGroupRequested)
        side_layout.addWidget(delete_group)

        anchors_label = QLabel(self.tr("Alignment anchors"), sidebar)
        anchors_label.setBuddy(None)
        anchors_font = anchors_label.font()
        anchors_font.setBold(True)
        anchors_label.setFont(anchors_font)
        side_layout.addWidget(anchors_label)
        self.anchorList = QListWidget(sidebar)
        self.anchorList.setAccessibleName(self.tr("Alignment anchors"))
        anchors_label.setBuddy(self.anchorList)
        self.anchorList.itemActivated.connect(self._anchor_activated)
        self.anchorList.currentItemChanged.connect(
            self._update_anchor_buttons
        )
        side_layout.addWidget(self.anchorList, 1)
        # Removing an anchor was the only thing this list could do. Creating
        # one lived in the pane toolbar and applying one was a double-click,
        # so an anchor deleted by mistake had no visible way back.
        new_anchor = QPushButton(self.tr("New anchor from carets…"), sidebar)
        new_anchor.setMinimumHeight(32)
        new_anchor.setToolTip(
            self.tr("Create an authoritative alignment at each pane's caret")
        )
        new_anchor.clicked.connect(self.alignRequested)
        side_layout.addWidget(new_anchor)
        self.applyAnchorButton = QPushButton(
            self.tr("Align panes at anchor"),
            sidebar,
        )
        self.applyAnchorButton.setMinimumHeight(32)
        self.applyAnchorButton.setToolTip(
            self.tr("Scroll every pane to the selected alignment")
        )
        self.applyAnchorButton.clicked.connect(self._apply_anchor)
        side_layout.addWidget(self.applyAnchorButton)
        self.removeAnchorButton = QPushButton(
            self.tr("Remove selected anchor"),
            sidebar,
        )
        self.removeAnchorButton.setMinimumHeight(32)
        self.removeAnchorButton.clicked.connect(self._remove_anchor)
        side_layout.addWidget(self.removeAnchorButton)
        self._update_anchor_buttons()
        root.addWidget(sidebar)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        add_selected = QPushButton(self.tr("Add selected items"), content)
        add_selected.setMinimumHeight(32)
        add_selected.clicked.connect(self.addSelectedRequested)
        toolbar.addWidget(add_selected)
        duplicate = QPushButton(self.tr("Duplicate target…"), content)
        duplicate.setMinimumHeight(32)
        duplicate.clicked.connect(self.duplicateRequested)
        toolbar.addWidget(duplicate)
        equalize = QPushButton(self.tr("Equalize panes"), content)
        equalize.setMinimumHeight(32)
        equalize.clicked.connect(self.equalizeRequested)
        toolbar.addWidget(equalize)

        width_label = QLabel(self.tr("Text &width:"), content)
        self.widthSpin = QSpinBox(content)
        self.widthSpin.setRange(280, 1600)
        self.widthSpin.setSingleStep(20)
        self.widthSpin.setSuffix(self.tr(" px"))
        self.widthSpin.setAccessibleName(self.tr("Shared text width"))
        width_label.setBuddy(self.widthSpin)
        self.widthSpin.valueChanged.connect(self.textWidthChanged)
        toolbar.addWidget(width_label)
        toolbar.addWidget(self.widthSpin)

        sync_label = QLabel(self.tr("&Scroll sync:"), content)
        self.syncCombo = QComboBox(content)
        self.syncCombo.setAccessibleName(self.tr("Scroll synchronization"))
        for mode, label in (
            (SyncMode.OFF, self.tr("Off")),
            (SyncMode.PERCENTAGE, self.tr("Percentage")),
            (SyncMode.PARAGRAPH, self.tr("Paragraph position")),
            (SyncMode.ANCHORS, self.tr("Manual anchors")),
        ):
            self.syncCombo.addItem(label, mode.value)
        sync_label.setBuddy(self.syncCombo)
        self.syncCombo.currentIndexChanged.connect(self._sync_mode_chosen)
        toolbar.addWidget(sync_label)
        toolbar.addWidget(self.syncCombo)

        self.proportionalCheck = QCheckBox(self.tr("S&mooth"), content)
        self.proportionalCheck.setAccessibleName(
            self.tr("Proportional scroll synchronization")
        )
        self.proportionalCheck.setToolTip(self.tr(
            "Follow the distance between two paragraphs or anchors as a "
            "percentage instead of jumping from one to the next"
        ))
        self.proportionalCheck.toggled.connect(self.proportionalSyncChanged)
        toolbar.addWidget(self.proportionalCheck)
        toolbar.addStretch(1)
        content_layout.addLayout(toolbar)

        action_toolbar = QHBoxLayout()
        action_toolbar.addStretch(1)
        align = QPushButton(self.tr("Align panes here…"), content)
        align.setMinimumHeight(32)
        align.setToolTip(
            self.tr("Create an authoritative alignment at each pane's caret")
        )
        align.clicked.connect(self.alignRequested)
        action_toolbar.addWidget(align)
        transfer = QPushButton(self.tr("Send selection to target"), content)
        transfer.setMinimumHeight(32)
        transfer.setToolTip(self.tr("Shortcut: Ctrl+Alt+Right"))
        transfer.clicked.connect(self.transferRequested)
        action_toolbar.addWidget(transfer)
        content_layout.addLayout(action_toolbar)

        self.splitter = QSplitter(Qt.Horizontal, content)
        self.splitter.setObjectName("variantPaneSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.setAccessibleName(self.tr("Variant editor panes"))
        self.splitter.splitterMoved.connect(
            lambda *_args: self.paneGeometryChanged.emit()
        )
        content_layout.addWidget(self.splitter, 1)
        self.statusLabel = QLabel(content)
        self.statusLabel.setWordWrap(True)
        self.statusLabel.setAccessibleName(self.tr("Workspace status"))
        self.statusLabel.setTextInteractionFlags(Qt.TextSelectableByKeyboard)
        content_layout.addWidget(self.statusLabel)
        root.addWidget(content, 1)

        self.transferShortcut = QShortcut(
            QKeySequence("Ctrl+Alt+Right"),
            self,
        )
        self.transferShortcut.activated.connect(self.transferRequested)
        self._update_proportional_control()

    def set_groups(self, groups, active_id):
        previous = self.groupList.blockSignals(True)
        self.groupList.clear()
        selected_row = -1
        for row, group in enumerate(groups):
            item = QListWidgetItem(group.title)
            item.setData(Qt.UserRole, group.id)
            item.setToolTip(
                self.tr("{} members; canonical target: {}").format(
                    len(group.members),
                    group.canonical_member.label,
                )
            )
            self.groupList.addItem(item)
            if group.id == active_id:
                selected_row = row
        self.groupList.setCurrentRow(selected_row)
        self.groupList.blockSignals(previous)

    def set_panes(self, bindings):
        while self.splitter.count():
            widget = self.splitter.widget(0)
            widget.setParent(None)
            widget.deleteLater()
        self._pane_widgets = []
        for index, binding in enumerate(bindings):
            pane = VariantPane(binding, self.splitter)
            pane.targetRequested.connect(self.targetRequested)
            pane.settingsRequested.connect(self.memberSettingsRequested)
            pane.removeRequested.connect(self.removeMemberRequested)
            pane.editingChanged.connect(self.editingChanged)
            pane.moveRequested.connect(self.memberMoved)
            self.splitter.addWidget(pane)
            # Equal shares of any width the workspace is later given.
            self.splitter.setStretchFactor(index, 1)
            self._pane_widgets.append(pane)
        self.equalize_panes()
        QTimer.singleShot(0, self._finish_initial_pane_layout)

    def _finish_initial_pane_layout(self):
        self.equalize_panes()
        self.paneGeometryChanged.emit()

    def set_anchors(self, anchors):
        selected = self.selected_anchor_id()
        previous = self.anchorList.blockSignals(True)
        self.anchorList.clear()
        for anchor_id, label, status in anchors:
            item = QListWidgetItem("{} — {}".format(label, status))
            item.setData(Qt.UserRole, anchor_id)
            item.setData(
                Qt.AccessibleTextRole,
                "{}; {}".format(label, status),
            )
            self.anchorList.addItem(item)
            if anchor_id == selected:
                self.anchorList.setCurrentItem(item)
        self.anchorList.blockSignals(previous)
        self._update_anchor_buttons()

    def selected_anchor_id(self):
        item = self.anchorList.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else ""

    def set_comparison_controls(self, state):
        previous = self.widthSpin.blockSignals(True)
        self.widthSpin.setValue(state.text_width)
        self.widthSpin.blockSignals(previous)
        previous = self.syncCombo.blockSignals(True)
        index = self.syncCombo.findData(state.sync_mode.value)
        self.syncCombo.setCurrentIndex(max(0, index))
        self.syncCombo.blockSignals(previous)
        previous = self.proportionalCheck.blockSignals(True)
        self.proportionalCheck.setChecked(state.proportional_sync)
        self.proportionalCheck.blockSignals(previous)
        self._update_proportional_control()

    def equalize_panes(self):
        """Give every pane the same width, to the pixel.

        Asking the splitter for equal shares is not enough on its own: it
        answers with each pane's minimum width when the shares are smaller
        than that, and a pane whose title or role happened to be longer used
        to claim a larger minimum than its neighbours.
        """
        count = self.splitter.count()
        if not count:
            return
        available = (
            self.splitter.width()
            - self.splitter.handleWidth() * (count - 1)
        )
        if available <= 0:
            return
        share = available // count
        sizes = [share] * count
        sizes[-1] = available - share * (count - 1)
        self.splitter.setSizes(sizes)

    def pane_content_width(self):
        """The narrowest width any pane can give a text column."""
        widths = [
            pane.content_width()
            for pane in self._pane_widgets
            if pane.content_width() > 0
        ]
        return min(widths) if widths else 0

    def show_status(self, message):
        self.statusLabel.setText(str(message))
        self.statusLabel.setAccessibleDescription(str(message))

    def prompt_group_title(self, default_title):
        title, accepted = QInputDialog.getText(
            self,
            self.tr("New scene family"),
            self.tr("Family &name:"),
            text=default_title,
        )
        return title.strip() if accepted else ""

    def prompt_anchor_label(self, default_label):
        label, accepted = QInputDialog.getText(
            self,
            self.tr("Alignment anchor"),
            self.tr("Anchor &label:"),
            text=default_label,
        )
        return label.strip() if accepted else ""

    def prompt_member_settings(self, member):
        dialog = MemberSettingsDialog(member, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def prompt_new_variant(self, default_title):
        dialog = NewVariantDialog(default_title, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def confirm(self, title, message):
        return QMessageBox.question(
            self,
            str(title),
            str(message),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def show_error(self, title, message):
        QMessageBox.critical(self, str(title), str(message))

    def prepare_close(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.prepare_close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.paneGeometryChanged.emit)

    def _group_changed(self, current, _previous):
        if current is not None:
            self.groupSelected.emit(str(current.data(Qt.UserRole)))

    def _sync_mode_chosen(self, _index):
        self._update_proportional_control()
        self.syncModeChanged.emit(self.syncCombo.currentData())

    def _update_proportional_control(self):
        mode = SyncMode(self.syncCombo.currentData())
        self.proportionalCheck.setEnabled(mode in self.PROPORTIONAL_MODES)

    def _anchor_activated(self, item):
        self.anchorSelected.emit(str(item.data(Qt.UserRole)))

    def _apply_anchor(self):
        anchor_id = self.selected_anchor_id()
        if anchor_id:
            self.anchorSelected.emit(anchor_id)

    def _remove_anchor(self):
        anchor_id = self.selected_anchor_id()
        if anchor_id:
            self.removeAnchorRequested.emit(anchor_id)

    def _update_anchor_buttons(self, *_args):
        selected = bool(self.selected_anchor_id())
        self.applyAnchorButton.setEnabled(selected)
        self.removeAnchorButton.setEnabled(selected)
