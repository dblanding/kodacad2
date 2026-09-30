#!/usr/bin/env python
#
# Copyright 2026 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#
"""isolated_features.py -- automatic isolated-feature face detection.

Reimplements the topological IDEA behind Sergey Slyadnev's
("Quaoar") asiAlgo_RecognizeIsolated, from Analysis Situs
(https://analysissitus.org/features/features_isolate-features.html) --
independently, against OCP, in this codebase's own conventions, not
ported or copied from his (BSD-licensed, but not reproduced here)
C++. Confirmed against the Analysis Situs reference docs and source
tree (github.com/CadQuery/AnalysisSitus,
src/asiAlgo/features/asiAlgo_RecognizeIsolated.{h,cpp}) to describe
the algorithm; the code below is a fresh implementation of that same
idea using this project's own topology helpers. Validated end-to-end
against a live OCP install by Doug (smoke_test_auto_isolated_feature.py,
CASE 3: boss) -- every OCP call used here (TopExp.MapShapes_s,
BRepTools.OuterWire_s, TopTools_IndexedMapOfShape, and the rest,
already proven elsewhere in kodacad2) is confirmed correct on his
system.

THE IDEA: Given one or more capping/base faces -- flat (or curved)
faces that have a hole or boss footprint cut into their own boundary
as an INNER wire -- automatically find every other face belonging to
the isolated feature they cap, so "Remove Isolated Feature" no
longer needs each wall face of the feature picked by hand.

1. Build the face-adjacency graph of the whole part (two faces are
   adjacent if they share an edge).
2. Remove ALL the seed (picked) faces from that graph. What's left
   splits into separate connected "islands."
3. One island is just the rest of the part -- reachable from
   whichever faces touch a seed's OUTER boundary. Discard it (and
   any island that touches it at all).
4. Any OTHER island that touches every edge of one of the seeds'
   INNER boundaries is the feature itself -- the hole, pocket, or
   boss the seed face(s) cap.

WHY MORE THAN ONE SEED FACE CAN BE NECESSARY (found the hard way, by
a smoke-test result that didn't match expectations -- see Session
124 in DEVELOPMENT_LOG.md): a feature that's open at only ONE end
(a blind hole, a boss) is cleanly isolated by picking its single
capping face -- confirmed directly, smoke-test CASE 3. A feature
open at BOTH ends (a plain through-hole) is NOT: its cylindrical
wall is also adjacent to the SECOND opening's own face, which (if
not picked) is still in the graph and still connected to the rest of
the part through the block's side walls -- so the wall never
becomes its own separate island, and step 3 above correctly (if
unhelpfully) discards it as part of "the rest of the part." Picking
BOTH capping faces of a through-feature as seeds together removes
both connection points at once, and the wall becomes its own clean
island. This matches the Analysis Situs docs' own wording --
"selecting their capping faceS" (plural) -- and
asiAlgo_RecognizeIsolated::Perform() already takes a SET of seed
faces, not a single one, for exactly this reason.

If any seed face has more than one inner wire (e.g. one flat face
capping two separate holes), every inner wire from every seed is
grown and the results are unioned -- one Enter press removes every
feature capped by the picked face(s). Whether that's what you want
is a judgment call each time -- pick fewer/smaller capping faces if
you only want one of several features removed.
"""

from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopTools import (TopTools_IndexedMapOfShape,
                          TopTools_IndexedDataMapOfShapeListOfShape)
from OCP.BRepTools import BRepTools


def _face_edges(face):
    """Return list of every TopoDS_Edge on a face (all of its wires,
    not just the outer one)."""
    edges = []
    exp = TopExp_Explorer(face, TopAbs_EDGE)
    while exp.More():
        edges.append(TopoDS.Edge_s(exp.Current()))
        exp.Next()
    return edges


def _wire_edges(wire):
    """Return list of every TopoDS_Edge on one wire."""
    edges = []
    exp = TopExp_Explorer(wire, TopAbs_EDGE)
    while exp.More():
        edges.append(TopoDS.Edge_s(exp.Current()))
        exp.Next()
    return edges


def _edge_in_list(edge, edge_list):
    return any(edge.IsSame(e) for e in edge_list)


def build_face_adjacency(shape):
    """Return (face_map, adjacency).

    face_map: TopTools_IndexedMapOfShape of every face in shape
    (1-based index -> face, via face_map.FindKey(i); face ->
    index via face_map.FindIndex(face), 0 if absent).

    adjacency: {index: set(index, ...)} -- faces sharing at least
    one edge.
    """
    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)

    edge_face_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE,
                                   edge_face_map)

    adjacency = {i: set() for i in range(1, face_map.Extent() + 1)}
    for ei in range(1, edge_face_map.Extent() + 1):
        face_list = edge_face_map.FindFromIndex(ei)
        # TopTools_ListOfShape iterates directly in Python -- there
        # is no TopTools_ListIteratorOfListOfShape in this OCP
        # binding (confirmed: mainwindow.py, Session 91).
        indices = []
        for f_shape in face_list:
            idx = face_map.FindIndex(TopoDS.Face_s(f_shape))
            if idx:
                indices.append(idx)
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                ia, ib = indices[a], indices[b]
                if ia != ib:
                    adjacency[ia].add(ib)
                    adjacency[ib].add(ia)
    return face_map, adjacency


def connected_components(adjacency, exclude=()):
    """Return list of sets of node indices: connected components of
    `adjacency`, with every index in `exclude` removed from the graph
    entirely first (its edges don't propagate connectivity either)."""
    exclude = set(exclude)
    nodes = set(adjacency.keys()) - exclude
    seen = set()
    components = []
    for start in nodes:
        if start in seen:
            continue
        comp = set()
        stack = [start]
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            for nbr in adjacency.get(n, ()):
                if nbr not in exclude and nbr not in comp:
                    stack.append(nbr)
        seen |= comp
        components.append(comp)
    return components


def seed_inner_wires(seed_face):
    """Return list of TopoDS_Wire: every wire of seed_face EXCEPT the
    one BRepTools.OuterWire_s reports -- i.e. the boundaries of holes
    or boss footprints cut into the seed face itself."""
    outer = BRepTools.OuterWire_s(seed_face)
    inner = []
    wexp = TopExp_Explorer(seed_face, TopAbs_WIRE)
    while wexp.More():
        w = wexp.Current()
        if not w.IsSame(outer):
            inner.append(w)
        wexp.Next()
    return inner


def seed_outer_edges(seed_face):
    """Return list of TopoDS_Edge on seed_face's own outer wire."""
    outer = BRepTools.OuterWire_s(seed_face)
    return _wire_edges(outer)


def find_isolated_feature_faces(shape, seed_faces):
    """Return list of TopoDS_Face making up the isolated feature(s)
    capped by seed_faces. seed_faces is either a single TopoDS_Face
    or a list/tuple/set of them -- pass more than one for a feature
    open at BOTH ends (a through-hole needs both its capping faces;
    see this module's own docstring for why). None of the seed faces
    themselves are included in the result -- they're the surrounding
    material BRepAlgoAPI_Defeaturing heals back over, not faces to
    remove.

    Returns [] if no seed face has an inner wire (nothing to grow
    from), or if no connected component fully bounds any inner wire
    (either a genuinely non-isolated pick, or -- for a through
    feature -- only one of its two capping faces was given)."""
    if isinstance(seed_faces, (list, tuple, set)):
        seeds = list(seed_faces)
    else:
        seeds = [seed_faces]

    all_inner_wires = []
    for sf in seeds:
        all_inner_wires.extend(seed_inner_wires(sf))
    if not all_inner_wires:
        return []

    face_map, adjacency = build_face_adjacency(shape)

    seed_indices = set()
    for sf in seeds:
        idx = face_map.FindIndex(sf)
        if idx:
            seed_indices.add(idx)
    if not seed_indices:
        return []

    # Faces touching any seed's OWN OUTER boundary: the surrounding
    # part, never the feature. Any component touching one of these
    # is discarded even if it also touches an inner wire's edges --
    # shouldn't arise for a clean isolated feature (an edge has
    # exactly two incident faces, so an inner-wire edge's other face
    # is inherently feature, not surrounding material), but this is
    # the same hard exclusion the source algorithm uses rather than
    # relying on that never happening.
    neighbors_over_outer = set()
    for sf in seeds:
        sf_idx = face_map.FindIndex(sf)
        if not sf_idx:
            continue
        outer_edges = seed_outer_edges(sf)
        for nbr_idx in adjacency.get(sf_idx, ()):
            if nbr_idx in seed_indices:
                continue
            nbr_face = TopoDS.Face_s(face_map.FindKey(nbr_idx))
            if any(_edge_in_list(e, outer_edges)
                  for e in _face_edges(nbr_face)):
                neighbors_over_outer.add(nbr_idx)

    components = connected_components(adjacency, exclude=seed_indices)

    feature_indices = set()
    for comp in components:
        if comp & neighbors_over_outer:
            continue
        comp_edges = []
        for idx in comp:
            comp_edges.extend(
                _face_edges(TopoDS.Face_s(face_map.FindKey(idx))))
        for wire in all_inner_wires:
            if all(_edge_in_list(we, comp_edges)
                  for we in _wire_edges(wire)):
                feature_indices |= comp
                break

    return [TopoDS.Face_s(face_map.FindKey(idx))
            for idx in feature_indices]
