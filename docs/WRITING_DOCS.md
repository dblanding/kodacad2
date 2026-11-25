# Writing and organizing the docs

The rule that matters most: **explain each thing in exactly one place,
and link to it from everywhere else.** (Single point of truth -- "SPOT".)

## The layers, and which way links may point

```
  README.md  and  docs/INDEX.md        entry points (may link to anything)
           |
           v
     tutorials/*/README.md            learn by doing (link down to concepts
           |                           and reference; to each other freely)
           v
     docs/concepts/*.md               how one idea works (the bottom layer)
```

- **Concept pages** (`docs/concepts/`) never link *up* to a tutorial, the
  README or the INDEX. They depend on nothing above them, which is what
  keeps the link graph from becoming circular.
- A concept page may point to *another concept* only in its last section,
  **Related**. In the body it must stand alone: no "see X for the
  explanation". If you find yourself writing that, either explain it in
  one sentence or the two pages are really one.
- **Tutorials** keep a one-sentence reminder plus a link, not a second
  explanation: "Save the session (see `[how sessions work](../../docs/concepts/sessions-and-files.md)`)."
- The **README** keeps orientation and the menu-level picture; detail
  lives in the concept page.

## A concept page

One idea per page, aiming for under about 100 lines (the checker warns at
150): what it is, how it works, gotchas, then `## Related`. Name the file
for the idea (`sessions-and-files.md`), not for the dialog.

Candidates when they next come up: Undo/Redo scope, workplanes and
workplane sets, the active part, Booleans and their guard rails, Position
frames, units.

## Adding or changing a page

1. Write the page in `docs/concepts/`.
2. Add it to `docs/INDEX.md`.
3. Replace the other copies with a link.
4. Run `python3 tools/check_docs.py`.

## When a term or menu label changes

Fix the concept page, then add the old wording to `STALE` in
`tools/check_docs.py`, so a leftover copy anywhere else is reported
instead of lingering. (`docs/DEVELOPMENT_LOG.md` is exempt: it is history.)

## What the checker does

`tools/check_docs.py` (standard library only) reports broken links and
image paths, `#heading` links that match nothing, concept pages that break
the layer rules above, concept pages and tutorials missing from the INDEX,
retired phrases, and over-long concept pages. It is quick enough to run
before every commit that touches Markdown.
