#!/usr/bin/env python3
"""check_docs.py -- keep KodaCAD's Markdown documentation tidy.

Run from the repository root:   python3 tools/check_docs.py
Needs only the standard library (no OCP, no Qt).  Exit status 1 if any
ERROR is found; WARNINGs do not fail the run.  The rules are explained
in docs/WRITING_DOCS.md.

Checks
  ERROR  a relative link or image whose target file does not exist
  ERROR  a link to '#heading' (same file or another) that matches no heading
  ERROR  a concept page (docs/concepts/) linking UP to a tutorial, the
         README or the INDEX (concepts never depend on the layers above)
  ERROR  a concept page linking to another concept page outside its final
         "Related" section (no "see X for the explanation" chains)
  ERROR  a concept page or tutorial README that INDEX.md does not list
  ERROR  a retired phrase (STALE below) still present in a document
         (found even when the text wraps across lines; it cannot catch a
         new sentence that is simply wrong -- that takes a human read)
  WARN   a concept page longer than MAX_CONCEPT_LINES (split it)
"""
import os
import re
import sys
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_CONCEPT_LINES = 150
SKIP_DIRS = {".git", ".venv", "node_modules", "OCCUtils", "src", "__pycache__"}
# History is allowed to mention anything.
STALE_EXEMPT = {os.path.join("docs", "DEVELOPMENT_LOG.md")}

# Phrases that were true once and are not any more.  When you retire a
# term or menu label, add it here so a stray copy cannot survive.
STALE = [
    "native save format of its own",
    "doesn't have its own native save format",
    "Position Selected",
    "Align Gizmo",
    "Clear Selection",
    "Modify Active Part",
    "Merge seam faces",
    "Total Distance",
    "save the session as a STEP file",
    "saving and loading a session as a STEP file",
    "does not store workplanes",
    "Both copies share",
]

LINK = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def md_files():
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md"):
                yield os.path.relpath(os.path.join(d, f), ROOT)


def lines_of(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read().splitlines()


def slug(text, seen):
    """GitHub-style heading anchor."""
    t = re.sub(r"[`*_]", "", text)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = t.strip().lower()
    t = re.sub(r"[^\w\- ]", "", t)
    t = t.replace(" ", "-")
    n = seen.get(t, 0)
    seen[t] = n + 1
    return t if n == 0 else f"{t}-{n}"


def scan(rel):
    """([(lineno, target, section)], {anchors}) with code fences skipped.
    `section` is the text of the most recent heading."""
    links, anchors, seen = [], set(), {}
    fence, section = False, ""
    for n, line in enumerate(lines_of(rel), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = HEAD.match(line)
        if m:
            section = m.group(2)
            anchors.add(slug(section, seen))
        for lm in LINK.finditer(re.sub(r"`[^`]*`", "", line)):
            links.append((n, lm.group(1), section))
    return links, anchors


def kind(rel):
    rel = rel.replace(os.sep, "/")
    if rel.startswith("docs/concepts/"):
        return "concept"
    if rel.startswith("tutorials/"):
        return "tutorial"
    return "other"


def main():
    files = sorted(md_files())
    info = {f: scan(f) for f in files}
    errors, warns = [], []

    for f in files:
        links, _ = info[f]
        for n, target, section in links:
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):      # http:, mailto:
                continue
            path, _, frag = target.partition("#")
            path = unquote(path)
            if path:
                full = os.path.normpath(os.path.join(ROOT, os.path.dirname(f), path))
                dest = os.path.relpath(full, ROOT)
                if not os.path.exists(full):
                    errors.append(f"{f}:{n}: broken link -> {target}")
                    continue
            else:
                dest = f
            if frag and dest.endswith(".md") and dest in info:
                if unquote(frag).lower() not in info[dest][1]:
                    errors.append(f"{f}:{n}: no such heading -> {target}")
            if kind(f) == "concept" and dest.endswith(".md"):
                dk = kind(dest)
                if dk == "tutorial" or dest in ("README.md", "docs/INDEX.md"):
                    errors.append(f"{f}:{n}: concept page links up to {dest}")
                if (dk == "concept" and dest != f
                        and section.strip().lower() != "related"):
                    errors.append(
                        f"{f}:{n}: link to another concept outside the "
                        f"'Related' section -> {target}")

    # INDEX must list every concept page and every tutorial README.
    idx = os.path.join("docs", "INDEX.md")
    if idx in info:
        listed = set()
        for _, target, _ in info[idx][0]:
            path = unquote(target.partition("#")[0])
            if path:
                listed.add(os.path.normpath(os.path.join("docs", path)))
        for f in files:
            if kind(f) in ("concept", "tutorial") and (
                    kind(f) == "concept" or f.endswith("README.md")):
                if os.path.normpath(f) not in listed:
                    errors.append(f"{idx}: does not list {f}")
    else:
        warns.append("docs/INDEX.md not found")

    for f in files:
        if f in STALE_EXEMPT:
            continue
        ls = [" ".join(x.split()) for x in lines_of(f)]
        for n, line in enumerate(ls, 1):
            # Look through a 3-line window so a phrase wrapped across
            # lines is still found; report it where it starts.
            window = " ".join(ls[n - 1:n + 2])
            for ph in STALE:
                at = window.lower().find(" ".join(ph.split()).lower())
                if 0 <= at < len(line) or (at == 0 and not line):
                    errors.append(f"{f}:{n}: retired phrase '{ph}'")
        if kind(f) == "concept" and len(lines_of(f)) > MAX_CONCEPT_LINES:
            warns.append(f"{f}: {len(lines_of(f))} lines (> {MAX_CONCEPT_LINES});"
                         " consider splitting it")

    for w in warns:
        print("WARNING", w)
    for e in errors:
        print("ERROR  ", e)
    print(f"{len(files)} Markdown files checked: "
          f"{len(errors)} error(s), {len(warns)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
