from manuskript.plugins import (
    EditorWorkspaceContribution,
    ExtensionDescriptor,
)

from .controller import create_workspace


PLUGIN_ID = "manuskript.variant-workspaces"


def register(registrar):
    registrar.register_editor_workspace(
        EditorWorkspaceContribution(
            descriptor=ExtensionDescriptor(
                id="manuskript.variant-workspaces.compare",
                name="Variant Workspace",
                description=(
                    "Compare, align, and synthesize translations, rewrites, "
                    "and alternate versions as independent outline text."
                ),
            ),
            workspace_factory=create_workspace,
            action_label="Open Variant Workspace…",
            shortcut="Ctrl+Alt+V",
            minimum_selection=1,
            maximum_selection=5,
        )
    )
