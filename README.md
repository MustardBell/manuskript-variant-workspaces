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

**Scroll sync** decides how the other panes follow the one you are scrolling:

| mode | the other panes |
|---|---|
| Off | stay where they are |
| Percentage | keep the same share of their own length |
| Paragraph position | show the paragraph matching yours by number |
| Manual anchors | interpolate between the alignments you authored |

**Smooth** applies to the last two. Without it the other panes step from one
paragraph — or one anchor — to the next, which reads as a jump while you
scroll continuously. With it they follow the distance between two of them as
a percentage, so the panes keep pace.

Scrolling says what belongs at the top of a pane. **Clicking says which
paragraph you are reading**, so putting the caret in one brings its
counterparts alongside it — at the same height, rather than scrolling them
to the top and making your eye chase them. Only a caret arriving in a
different paragraph moves anything, so writing inside one leaves the other
panes where they are, and Off means a click moves nothing either.

An **alignment anchor** records one moment as it occurs in every pane, and
survives editing on either side: the paragraph is found again by content, not
by counting. Put a caret in each pane and choose **New anchor from carets…**;
select one and choose **Align panes at anchor** to bring every pane back to
it.

## Data and safety

- Prose stays in ordinary Manuskript outline text files.
- `variant-groups.json` stores relationships, roles, languages, the canonical
  member, and robust alignment anchors.
- `comparison-workspaces.json` stores only UI state such as pane order, width,
  locks, synchronization mode, and whether it follows proportionally.
- Removing or disabling the plugin does not remove or rewrite prose.
- Source panes are locked by default; the canonical target remains editable.
- Synchronization only ever scrolls. A caret is read to decide where the
  other panes should look; no pane's caret is moved and no document edited.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
