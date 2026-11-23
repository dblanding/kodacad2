# extract-roots: splitting as1-oc-214 into a kit of parts

This folder holds the script that produced the starting material for the
[build-as1-oc-214](../build-as1-oc-214/README.md) tutorial. You do **not**
need to run it to follow that tutorial; the output is already here. It is
kept in case the kit ever needs to be regenerated.

## Files

| File | What it is |
|---|---|
| `as1-oc-214.stp` | The finished assembly (the Open CASCADE as1 sample), the script's input. |
| `extract_prototypes.py` | The script. |
| `as1-oc-214-kit-of-parts.stp` | The script's output: the five leaf prototypes, un-positioned, at the origin. |
| `colors.png` | Reference image of the part colors. |

## What the script does

It loads `as1-oc-214.stp`, finds every *prototype* that is a plain solid
(not a reference to another shape, and not an assembly of components),
and saves them in a fresh document, each at its own native origin and
with its color carried over. For as1-oc-214 that is exactly five parts:
rod, nut, bolt, l-bracket and plate. The build-as1-oc-214 tutorial then
puts them back together using the Position tools.

The test is structural (reference / assembly flags in the STEP's XCAF
structure), not based on part names.

## Running it

From this folder, in the kodacad2 environment (it needs OCP and imports
`docmodel.py` from the repository root):

    cd tutorials/extract-roots
    uv run python extract_prototypes.py

Optionally give the input and output file names:

    uv run python extract_prototypes.py my-assembly.stp my-kit.stp

It prints what it finds and writes the output file next to the script.
Another assembly can be used in place of as1-oc-214, but the colors and
the "five parts" expectation are specific to this one.
