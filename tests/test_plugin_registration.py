from manuskript.plugins.api import EditorWorkspaceContribution
from manuskript.plugins.registry import PluginRegistrar

from variant_workspaces.plugin import PLUGIN_ID, register


def test_plugin_registers_one_bounded_editor_workspace():
    registrar = PluginRegistrar(PLUGIN_ID)

    register(registrar)

    assert len(registrar.contributions) == 1
    contribution = registrar.contributions[0].contribution
    assert isinstance(contribution, EditorWorkspaceContribution)
    assert contribution.minimum_selection == 1
    assert contribution.maximum_selection == 5
    assert contribution.shortcut == "Ctrl+Alt+V"
