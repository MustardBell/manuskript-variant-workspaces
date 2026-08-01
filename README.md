# Manuskript Variant Workspaces

An installable Manuskript plugin for treating translations, rewrites,
alternates, and synthesis drafts as a **scene family** of independent outline
documents.

The plugin provides a dedicated, flat comparison workspace with two to five
native Manuskript editors. One family member is the canonical compile target;
the others remain ordinary editable `.md` outline documents but are excluded
from compilation. Variant relationships and manual alignment anchors are
portable project data owned by the plugin, never hidden inside the prose.

## Compatibility

This plugin requires a Manuskript build whose Plugin API 1 includes editor
workspace contributions. That capability is developed in
[`MustardBell/manuskript`](https://github.com/MustardBell/manuskript) on the
`feature-manuskript/variant-workspaces` branch. Compatibility is based on the
advertised plugin capability, not on whether Manuskript is an original project
or a fork.

## Install

Clone the repository as one direct child of Manuskript's plugin directory:

```console
cd /path/to/manuskript/manuskript/plugins
git clone https://github.com/MustardBell/manuskript-variant-workspaces.git variant_workspaces
```

Start Manuskript, open **Tools → Plugins → Manage Plugins**, enable **Variant
Workspaces**, and restart if the manager requests it. Select one to five text
items in the outline and choose **Tools → Plugins → Open Variant Workspace**.

When this repository is shipped as a submodule by a compatible Manuskript
checkout, initialize it with:

```console
git submodule update --init --recursive
```

## Data and safety

- Prose stays in ordinary Manuskript outline text files.
- `variant-groups.json` stores relationships, roles, languages, the canonical
  member, and robust alignment anchors.
- `comparison-workspaces.json` stores only UI state such as pane order, width,
  locks, and synchronization mode.
- Removing or disabling the plugin does not remove or rewrite prose.
- Source panes are locked by default; the canonical target remains editable.
- Synchronized scrolling never moves the caret or edits a document.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
