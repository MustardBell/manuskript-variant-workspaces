# Variant Workspaces — open questions

Decisions that have been deliberately left open, with enough context to take
them later without re-deriving the argument.

## Legacy pixel scroll positions

Reading positions used to be persisted as scroll offsets in pixels, under
`scroll_positions` in `variant-comparisons.json`. They are now persisted as
fractional paragraphs under `scroll_paragraphs`, because a pixel only means
something inside the layout that produced it.

A project written before that change is currently read with its old key
ignored: the pane opens at the top once and remembers prose from then on. The
alternative is a one-time best-effort restore — apply the stored pixel offset
on first render, then immediately record where it landed in paragraphs and
never read the old key again.

Arguments for leaving it as it is: a pixel offset cannot be converted without
the layout that produced it, and the layout at the moment of restore is not
that layout, so a best-effort restore silently puts the reader somewhere
plausible but wrong. Opening at the top is at least honestly wrong.

Arguments for the one-time restore: for a reader who left a pane deep inside a
long scene and reopens the project at the same window size and font, the old
number is very nearly right, and losing the place is the more visible harm.

No maintained project is known to depend on either behaviour, and the plugin's
data format is still pre-release, which is why this was not treated as a
migration obligation.
