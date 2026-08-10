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

## Comparing

Every pane is the same width as every other one, and **Text width** narrows
the column each of them gets. **Equalize panes** puts the splitter back after
you have dragged it.

**Scroll sync** is a stack rather than a choice of one. Each principle
applies inside what the one above it settled, so the order is the whole of
the decision, and unchecking one leaves it out:

| principle | what it settles |
|---|---|
| Alignment anchors | which stretch of this scene answers to which stretch of that one |
| Paragraphs | which paragraph inside that stretch, so their tops meet |
| Percentage | whereabouts inside that paragraph, so the panes keep pace |

The default is all three in that order. Drop **Percentage** and the panes
step from paragraph to paragraph instead of gliding. Drop **Paragraphs**
and they slide proportionally between your alignments. Uncheck everything
and they stop following each other.

A principle that cannot say anything where you are steps aside — before you
have authored any alignment, **Alignment anchors** does nothing at all, and
the stack behaves as though it were not there.

An **alignment anchor** records one moment as it occurs in every pane, and
survives editing on either side: the paragraph is found again by content, not
by counting. Put a caret in each pane and choose **New anchor from carets…**;
select one and choose **Align panes at anchor** to bring every pane back to
it.

Anchors are ordered by where they fall in the pane you are scrolling and
deliberately not by where they land in the others, so **an anchor may run
backwards** — which is how you tell the workspace that a passage changed
place between two versions. Anchor both ends of a run that moved, and both
ends of whatever it displaced, and every paragraph then lands where it
really is rather than where counting would have put it.

## Data and safety

- Prose stays in ordinary Manuskript outline text files.
- `variant-groups.json` stores relationships, roles, languages, the canonical
  member, and robust alignment anchors.
- `comparison-workspaces.json` stores only UI state such as pane order, width,
  locks, and the synchronization stack. A project written before the stack
  existed is read as the stack its old mode amounts to.
- Removing or disabling the plugin does not remove or rewrite prose.
- Source panes are locked by default; the canonical target remains editable.
- Synchronization only ever scrolls. A caret is read to decide where the
  other panes should look; no pane's caret is moved and no document edited.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
