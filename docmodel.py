#!/usr/bin/env python
#
# Copyright 2022 Doug Blanding (dblanding@gmail.com)
# Ported to OCP/PySide6 2026
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
# OCP port: OCC.Core.X -> OCP.X, PyQt5 -> PySide6
# API changes:
#   binxcafdrivers_DefineFormat(app) -> BinXCAFDrivers.DefineFormat_s(app)
#   XCAFApp_Application_GetApplication() -> XCAFApp_Application.GetApplication_s()
#   brepgprop_SurfaceProperties -> BRepGProp.SurfaceProperties_s
#   topods_Edge/Face/Vertex -> TopoDS.Edge_s/Face_s/Vertex_s

from dataclasses import dataclass
import logging
import os
import os.path

from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRep import BRep_Builder
from OCP.IFSelect import IFSelect_RetDone
from OCP.PCDM import PCDM_SS_OK, PCDM_RS_OK
from OCP.Quantity import Quantity_Color
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TCollection import TCollection_ExtendedString as TColEStr
from OCP.TDF import TDF_CopyLabel, TDF_Label, TDF_LabelSequence, TDF_ChildIterator
from OCP.TDocStd import TDocStd_Document, TDocStd_XLinkTool
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import (
    XCAFDoc_Location,
    XCAFDoc_ColorGen,
    XCAFDoc_ColorSurf,
    XCAFDoc_DocumentTool,
)
from OCP.XSControl import XSControl_WorkSession
from PySide6.QtWidgets import QFileDialog

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # set to DEBUG | INFO | ERROR


@dataclass
class Prototype:
    """A prototype shape and its associated label"""
    shape: TopoDS_Shape
    label: TDF_Label


def get_label_name(label):
    """Get the name of a TDF_Label (replaces PythonOCC's GetLabelName())."""
    try:
        # In OCP, use the static Get_s method which returns the name string
        from OCP.TDataStd import TDataStd_Name
        name = TDataStd_Name.Get_s(label)
        if name is not None:
            return str(name.ToExtString())
    except Exception:
        pass
    # Fallback: try FindAttribute pattern
    try:
        name_attr = TDataStd_Name()
        found = label.FindAttribute(TDataStd_Name.GetID_s(), name_attr)
        if found:
            return str(name_attr.Get().ToExtString())
    except Exception as e:
        pass
    return ""


def get_label_location(label):
    """Get the TopLoc_Location of a label (replaces shape_tool.GetLocation()).

    Uses shape.Location() which is safe on all label types.
    FindAttribute segfaults on root labels that have no location attribute.
    """
    from OCP.TopLoc import TopLoc_Location
    try:
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        # We need a shape_tool to get the shape -- but we don't have one here.
        # Instead use XCAFDoc_Location with IsAttribute check first.
        from OCP.XCAFDoc import XCAFDoc_Location
        if label.IsAttribute(XCAFDoc_Location.GetID_s()):
            loc_attr = XCAFDoc_Location()
            if label.FindAttribute(XCAFDoc_Location.GetID_s(), loc_attr):
                return loc_attr.Get()
    except Exception:
        pass
    return TopLoc_Location()


def get_label_entry(label):
    """Get the entry string of a TDF_Label (replaces PythonOCC's EntryDumpToString())."""
    from OCP.TDF import TDF_Tool
    from OCP.TCollection import TCollection_AsciiString
    entry = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry)
    return entry.ToCString()


def get_last_component(shape_tool, assembly_label):
    """Return the most-recently-added component label of assembly_label.

    XCAFDoc_Editor.Extract_s() (unlike shape_tool.AddComponent()) only
    returns True/False for success -- it doesn't hand back the label it
    just created. OCAF assigns child tags in increasing order and
    GetComponents_s returns them in that order, so the newest component
    is reliably the last one in the sequence.
    """
    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(assembly_label, comps, False)
    return comps.Value(comps.Length())


def rebuild_imported_structure(src_label, shape_tool, color_tool, memo):
    """Recursively read src_label's structure (from ANOTHER document)
    as plain data and rebuild it NATIVELY in this document via
    AddShape/AddComponent -- the validated replacement for
    XCAFDoc_Editor.Extract_s in add_component_from_label (Session 52,
    smoke_test_production_fix.py: name, location, AND sharing all
    confirmed surviving a reposition + STEP round trip).

    Why this works where Extract_s didn't: the Session 51 test chain
    established that the STEP writer handles label-based natively-
    built structures correctly (including through RemoveComponent+
    AddComponent reposition cycles), while Extract_s-imported
    structures are ones it cannot generate a proper NAUO for. This is
    also how FreeCAD's ExportOCAF works -- it never label-copies
    across documents; every shape it writes is natively created in
    the document being written.

    memo: dict mapping source entry string -> destination label. A
    source shape referenced by MULTIPLE components (a genuinely
    shared part within the imported file) is rebuilt ONCE and
    referenced multiple times -- preserving sharing, the specific
    thing Session 29's earlier rebuild attempt got wrong (that
    attempt's actual flaw; its apparent export failure was later
    shown to be confounded by a mixed-geometry-root test structure,
    see Session 51).

    Reads via the static (_s) accessors, which work on labels from
    any document; writes via the instance methods of THIS document's
    shape_tool. Colors are carried over best-effort (source document's
    own color tool resolved via XCAFDoc_DocumentTool.ColorTool_s on
    the source label itself; shape-keyed GetColor matching
    parse_doc's proven read pattern, Surf first then Gen) -- a color
    hiccup prints a warning but never breaks the structural rebuild.

    Returns the destination label for src_label's underlying shape --
    the caller adds it as a component wherever it belongs.
    """
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder

    entry = get_label_entry(src_label)
    if entry in memo:
        return memo[entry]

    if shape_tool.IsAssembly_s(src_label):
        empty = TopoDS_Compound()
        BRep_Builder().MakeCompound(empty)
        dst_label = shape_tool.AddShape(empty, True)
        set_label_name(dst_label, get_label_name(src_label))
        memo[entry] = dst_label

        children = TDF_LabelSequence()
        shape_tool.GetComponents_s(src_label, children, False)
        for i in range(1, children.Length() + 1):
            child_comp = children.Value(i)
            child_ref = TDF_Label()
            if not shape_tool.GetReferredShape_s(child_comp, child_ref):
                continue
            child_dst_label = rebuild_imported_structure(
                child_ref, shape_tool, color_tool, memo)
            child_loc = shape_tool.GetShape_s(child_comp).Location()
            new_comp = shape_tool.AddComponent(dst_label, child_dst_label,
                                               child_loc)
            # Component names in source STEP files can be generic NAUO
            # identifiers ("NAUO1", "NAUO2", ...) assigned by the STEP
            # reader when the NAUO entity's descriptive-name field is
            # empty. These are meaningless -- the real part name lives
            # on the REFERRED shape. Fall back to that with a suffix
            # (matching the _1 convention used throughout this app).
            comp_name = get_label_name(child_comp)
            if not comp_name or comp_name.startswith("NAUO"):
                ref_name = get_label_name(child_ref)
                comp_name = f"{ref_name}_1" if ref_name else comp_name
            set_label_name(new_comp, comp_name)
    else:
        shape = shape_tool.GetShape_s(src_label)
        dst_label = shape_tool.AddShape(shape, False)
        set_label_name(dst_label, get_label_name(src_label))
        memo[entry] = dst_label
        _transfer_color(src_label, dst_label, shape_tool, color_tool)

    return dst_label


def _transfer_color(src_label, dst_label, shape_tool, color_tool):
    """Best-effort color carry-over from a source-document label to
    its rebuilt destination label.

    Three real-world storage patterns handled (Sessions 52-53):

    1. parse_doc reads colors via GetColor(ref_SHAPE, Surf, ...) --
       shape-keyed. Writes here use the shape-keyed SetColor to match.
    2. Some files store the color on the part LABEL instead -- the
       source read falls back to label-keyed lookups.
    3. Vendor part files very often color the SUB-SHAPES (the solid
       or faces INSIDE the product) and put nothing on the part label
       at all -- "still yellow even after save/reload" is the tell,
       since it means the top-level source read found nothing to
       transfer, so nothing ever reached the exported file. Sub-shape
       labels are enumerated (GetSubShapes_s), their colors read, and
       matching sub-shape labels created on the destination
       (FindSubShape/AddSubShape) with the colors applied.

    Prints a one-line [color] diagnostic per part so a terminal run
    shows exactly what was found where. Never raises -- a failure
    here should cost a color, not the import."""
    top_found = False
    n_sub = 0
    from OCP.XCAFDoc import XCAFDoc_ShapeTool, XCAFDoc_ColorTool
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    try:
        src_color_tool = XCAFDoc_DocumentTool.ColorTool_s(src_label)
        src_shape = XCAFDoc_ShapeTool.GetShape_s(src_label)
        dst_shape = XCAFDoc_ShapeTool.GetShape_s(dst_label)
        color = Quantity_Color()
        # Shape-keyed reads are INSTANCE methods; label-keyed reads
        # are STATIC in this binding (GetColor_s) -- confirmed
        # directly from the binding's own error message listing the
        # instance overloads (all three shape-keyed only). Same _s
        # convention as GetShape_s/IsAssembly_s throughout.
        if (src_color_tool.GetColor(src_shape, XCAFDoc_ColorSurf, color)
                or src_color_tool.GetColor(src_shape, XCAFDoc_ColorGen, color)
                or XCAFDoc_ColorTool.GetColor_s(src_label,
                                                XCAFDoc_ColorSurf, color)
                or XCAFDoc_ColorTool.GetColor_s(src_label,
                                                XCAFDoc_ColorGen, color)):
            top_found = True
            color_tool.SetColor(dst_shape, color, XCAFDoc_ColorSurf)
            color_tool.SetColor(dst_shape, color, XCAFDoc_ColorGen)
    except Exception as e:
        print(f"[color] top-level transfer failed for "
              f"{get_label_name(src_label)!r}: {e}")

    # Sub-shape colors (pattern 3) -- own try block, so a top-level
    # failure can't abort this scan (that's exactly what hid the
    # sub-shape data on the first instrumented run).
    try:
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(src_label, subs)
        for i in range(1, subs.Length() + 1):
            sub_label = subs.Value(i)
            sub_color = Quantity_Color()
            if not (XCAFDoc_ColorTool.GetColor_s(sub_label,
                                                 XCAFDoc_ColorSurf, sub_color)
                    or XCAFDoc_ColorTool.GetColor_s(sub_label,
                                                    XCAFDoc_ColorGen,
                                                    sub_color)):
                continue
            try:
                sub_shape = XCAFDoc_ShapeTool.GetShape_s(sub_label)
                dst_sub = TDF_Label()
                if not shape_tool.FindSubShape(dst_label, sub_shape, dst_sub):
                    dst_sub = shape_tool.AddSubShape(dst_label, sub_shape)
                if not dst_sub.IsNull():
                    color_tool.SetColor(dst_sub, sub_color, XCAFDoc_ColorSurf)
                    color_tool.SetColor(dst_sub, sub_color, XCAFDoc_ColorGen)
                    n_sub += 1
            except Exception as sub_e:
                print(f"[color] sub-shape transfer failed for one "
                      f"sub-shape of {get_label_name(src_label)!r}: {sub_e}")
    except Exception as e:
        print(f"[color] sub-shape scan failed for "
              f"{get_label_name(src_label)!r}: {e}")
    print(f"[color] {get_label_name(src_label)!r}: top-level "
          f"{'FOUND' if top_found else 'none'}, sub-shape colors "
          f"transferred: {n_sub}")


def get_part_display_color(color_tool, shape_tool, ref_label, ref_shape):
    """Single display color for a part, with the full fallback chain:
    top-level Surf (parse_doc's original read), then top-level Gen,
    then the FIRST COLORED SUB-SHAPE -- vendor part files very often
    color only the solid/faces inside the product, leaving nothing on
    the part label itself (Session 53). Returns OCCT's default
    (yellow) only when nothing is found anywhere; a part displaying
    pure yellow genuinely has no color information at any level.

    Note: Kodacad displays one color per part (part_dict stores a
    single color), so a genuinely multi-colored part shows its first
    sub-shape color -- a display simplification, not a data loss; the
    document itself keeps all sub-shape colors and exports them."""
    color = Quantity_Color()
    if color_tool.GetColor(ref_shape, XCAFDoc_ColorSurf, color):
        return color
    if color_tool.GetColor(ref_shape, XCAFDoc_ColorGen, color):
        return color
    try:
        from OCP.XCAFDoc import XCAFDoc_ShapeTool, XCAFDoc_ColorTool
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(ref_label, subs)
        for i in range(1, subs.Length() + 1):
            sub_label = subs.Value(i)
            # Label-keyed GetColor is STATIC in this binding
            # (GetColor_s) -- the instance method only accepts
            # shape-keyed calls (confirmed from the binding's own
            # error output, Session 53).
            if (XCAFDoc_ColorTool.GetColor_s(sub_label,
                                             XCAFDoc_ColorSurf, color)
                    or XCAFDoc_ColorTool.GetColor_s(sub_label,
                                                    XCAFDoc_ColorGen,
                                                    color)):
                return color
    except Exception:
        pass
    # Nothing found anywhere -- confirmed possible with real vendor
    # files (Session 53: raw-text scan showed ZERO color entities;
    # Onshape/Creo displayed them colored only via their own app-side
    # default schemes). Return a neutral gray instead of OCCT's
    # default-constructor yellow. DISPLAY-ONLY -- deliberately not
    # SetColor'd into the document, so exported files stay honestly
    # colorless as authored rather than gaining fake color data.
    from OCP.Quantity import Quantity_TypeOfColor
    return Quantity_Color(0.72, 0.72, 0.72,
                          Quantity_TypeOfColor.Quantity_TOC_RGB)


def remove_shape_and_orphaned_descendants(shape_tool, label):
    """Remove `label` completely, AND recursively clean up any of its
    own children that become newly orphaned as a result.

    RemoveShape(label, True) alone does not correctly cascade orphan-
    detection through nested levels -- confirmed directly (Session 47
    cont'd): cleanup_orphans.py's first pass removed a top-level
    orphaned assembly (e.g. l-bracket-assembly) but left ITS OWN
    children (e.g. nut-bolt-assembly, l-bracket) behind as NEW orphans,
    requiring repeated passes to fully clean up. This is the same
    class of issue delete_component() already handles for a single
    level -- here it's handled recursively, so a multi-level nested
    assembly is fully cleaned up in one call rather than needing the
    caller to loop.

    Captures each child's referred label BEFORE removing `label`
    itself (since removing label destroys the component references
    that point at them), then checks each captured child for orphan
    status (GetUsers_s == 0) and recurses into it if so.
    """
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    child_refs = []
    if shape_tool.IsAssembly_s(label):
        children = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, children, False)
        for i in range(1, children.Length() + 1):
            child_comp = children.Value(i)
            child_ref = TDF_Label()
            if (shape_tool.GetReferredShape_s(child_comp, child_ref)
                    and not child_ref.IsNull()):
                child_refs.append(child_ref)

    shape_tool.RemoveShape(label, True)

    for child_ref in child_refs:
        users = TDF_LabelSequence()
        n_users = shape_tool.GetUsers_s(child_ref, users, False)
        if n_users == 0:
            remove_shape_and_orphaned_descendants(shape_tool, child_ref)


UNDO_LIMIT = 50  # OCAF undo history depth (Session 61)


from contextlib import contextmanager


@contextmanager
def undo_transaction(dm):
    """One undoable OCAF transaction around a user gesture (Session
    61, gauge-certified 7/7). JOINS an already-open command instead
    of nesting -- so the Position dialog (option (b): whole session =
    ONE transaction committed at Done) can hold a command open while
    its internal moves call through here safely. Aborts on exception,
    commits otherwise; committing an empty command records nothing.
    """
    if dm.doc.HasOpenCommand():
        yield  # join the outer transaction (e.g. Position dialog)
        return
    dm.doc.NewCommand()
    try:
        yield
    except Exception:
        dm.doc.AbortCommand()
        raise
    dm.doc.CommitCommand()


def create_doc():
    """Create (and return) XCAF doc and app

    entry       label <class 'OCP.TDF.TDF_Label'>
    0:1         doc.Main()                          (Depth = 1)
    0:1:1       shape_tool is at this label entry   (Depth = 2)
    0:1:2       color_tool at this entry            (Depth = 2)
    0:1:1:1     root_label and all referred shapes  (Depth = 3)
    0:1:1:x:x   component labels (references)       (Depth = 4)
    """
    doc_format = "BinXCAF"
    doc = TDocStd_Document(TCollection_ExtendedString(doc_format))
    app = XCAFApp_Application.GetApplication_s()
    app.NewDocument(TCollection_ExtendedString(doc_format), doc)
    BinXCAFDrivers.DefineFormat_s(app)
    return doc, app


class DocModel:
    """Maintain the 3D CAD model in OCAF XDE format.

    Maintains self.part_dict and self.label_dict by parsing self.doc.
    These 2 dicts provide mainwindow with convenient access to CAD data.
    With the exception of the Top assembly, each item in the tree view
    represents a component label in the OCAF document and has a uid
    comprising the label entry with an appended '.' followed by an integer.
    The integer makes each instance unique (allowing to distinguish between
    different instances of shared data)."""

    def __init__(self):
        self.doc, self.app = create_doc()
        # Session 89's attempt to pre-create the root '/' here (before
        # SetUndoLimit, so its creation would never be part of the
        # undo history at all) was reverted per Doug's own test: it
        # correctly eliminated the root-creation transaction, but
        # exposed that the underlying redo issue is deeper than root-
        # creation alone -- rebuild_imported_structure (used by Import
        # STEP) has the identical create-then-wire pattern recurring
        # at EVERY level of nested assembly structure in an imported
        # file, not just the top. Doug's own call: accept the known,
        # minor limitation from Session 86/88's fix (undoing all the
        # way back on a first-ever import or part, past the root's own
        # creation, then redoing, fails -- but undoing ONE step and
        # redoing works correctly, which is the common case) rather
        # than chase the recursive case further or make Import STEP
        # non-undoable outright. He specifically wants imports to stay
        # undoable, including a SEQUENCE of several imports.
        self.doc.SetUndoLimit(UNDO_LIMIT)  # Session 61
        self.part_dict = {}   # {uid: {keys: 'shape', 'name', 'color', 'loc'}}
        self.label_dict = {}  # {uid: {keys: 'entry', 'name', 'parent_uid', ...}}
        self._share_dict = {}
        self.parent_uid_stack = []
        self.assy_entry_stack = []
        self.assy_loc_stack = []

    def get_uid_from_entry(self, entry):
        """Generate uid from label entry. format: 'entry.serial_number'"""
        if entry in self._share_dict:
            value = self._share_dict[entry]
        else:
            value = -1
        value += 1
        self._share_dict[entry] = value
        return entry + '.' + str(value)

    def parse_doc(self):
        """Generate new part_dict & label_dict from self.doc"""
        self._share_dict = {'0:1:1': 0}
        self.part_dict = {}
        self.label_dict = {}
        self.parent_uid_stack = []
        self.assy_entry_stack = ['0:1:1']
        self.assy_loc_stack = []

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())
        labels = TDF_LabelSequence()
        shape_tool.GetShapes(labels)
        if labels.Length() == 0:
            # EMPTY document -- legitimate state (a brand-new session,
            # or an Undo of the transaction that created the first
            # content). Found by the Session 61 undo/redo gauge:
            # parse_doc crashed on Value(1) here. Empty dicts ARE the
            # correct parse of an empty document.
            return
        root_label = labels.Value(1)
        root_name = get_label_name(root_label)
        root_entry = get_label_entry(root_label)
        root_uid = self.get_uid_from_entry(root_entry)
        loc = get_label_location(root_label)

        root_name = get_label_name(root_label)
        root_entry = get_label_entry(root_label)
        root_uid = self.get_uid_from_entry(root_entry)
        loc = get_label_location(root_label)
        self.assy_loc_stack.append(loc)
        self.assy_entry_stack.append(root_entry)
        self.label_dict = {root_uid: {'entry': root_entry, 'name': root_name,
                                      'parent_uid': None, 'ref_entry': None,
                                      'is_assy': True, 'inv_loc': loc.Inverted()}}
        self.parent_uid_stack.append(root_uid)
        top_comps = TDF_LabelSequence()
        subchilds = False
        shape_tool.GetComponents_s(root_label, top_comps, subchilds)
        if top_comps.Length():
            self.parse_components(top_comps, shape_tool, color_tool)
        # Pop the root-level push for symmetry with the fix above
        # (not load-bearing -- these stacks reset at the top of
        # every parse_doc() call regardless -- but kept paired for
        # the same reason: a push without its own pop is exactly
        # the bug pattern just fixed).
        self.assy_entry_stack.pop()
        self.assy_loc_stack.pop()
        self.parent_uid_stack.pop()
        # If no components found, free shapes at root will be picked up below

        # Free shapes at root are now all assemblies (/, as1, etc.)
        # New parts are added as components, so parse_components handles them.

    def parse_components(self, comps, shape_tool, color_tool):
        """Parse components from comps (LabelSequence)."""
        for j in range(comps.Length()):
            c_label = comps.Value(j+1)
            c_name = get_label_name(c_label)
            c_entry = get_label_entry(c_label)
            c_uid = self.get_uid_from_entry(c_entry)
            c_shape = shape_tool.GetShape_s(c_label)
            ref_label = TDF_Label()
            is_ref = shape_tool.GetReferredShape_s(c_label, ref_label)
            if is_ref:
                ref_name = get_label_name(ref_label)
                ref_shape = shape_tool.GetShape_s(ref_label)
                ref_entry = get_label_entry(ref_label)
                self.label_dict[c_uid] = {'entry': c_entry,
                                          'name': c_name,
                                          'parent_uid': self.parent_uid_stack[-1],
                                          'ref_entry': ref_entry}
                if shape_tool.IsSimpleShape_s(ref_label):
                    self.label_dict[c_uid].update({'is_assy': False})
                    temp_assy_loc_stack = list(self.assy_loc_stack)
                    if len(temp_assy_loc_stack) > 1:
                        res_loc = temp_assy_loc_stack.pop(0)
                        for loc in temp_assy_loc_stack:
                            res_loc = res_loc.Multiplied(loc)
                        display_shape = BRepBuilderAPI_Transform(
                            c_shape, res_loc.Transformation()).Shape()
                    elif len(temp_assy_loc_stack) == 1:
                        res_loc = temp_assy_loc_stack.pop()
                        display_shape = BRepBuilderAPI_Transform(
                            c_shape, res_loc.Transformation()).Shape()
                    else:
                        res_loc = None
                        display_shape = c_shape
                    c_loc = get_label_location(c_label)
                    if c_loc and res_loc:
                        loc = res_loc.Multiplied(c_loc)
                    else:
                        loc = c_loc
                    color = get_part_display_color(
                        color_tool, shape_tool, ref_label, ref_shape)
                    self.part_dict[c_uid] = {'shape': display_shape,
                                             'color': color,
                                             'name': c_name,
                                             'loc': loc}
                elif shape_tool.IsAssembly_s(ref_label):
                    self.label_dict[c_uid].update({'is_assy': True})
                    a_loc = get_label_location(c_label)
                    inv_loc = a_loc.Inverted()
                    # Compute world location of this assembly by composing
                    # the current stack with this assembly's local loc
                    temp_stack = list(self.assy_loc_stack)
                    if temp_stack:
                        world_loc = temp_stack[0]
                        for l in temp_stack[1:]:
                            world_loc = world_loc.Multiplied(l)
                        world_loc = world_loc.Multiplied(a_loc)
                    else:
                        world_loc = a_loc
                    self.label_dict[c_uid].update({
                        'inv_loc': inv_loc,
                        'world_loc': world_loc})
                    self.assy_loc_stack.append(a_loc)
                    self.assy_entry_stack.append(ref_entry)
                    self.parent_uid_stack.append(c_uid)
                    r_comps = TDF_LabelSequence()
                    subchilds = False
                    shape_tool.GetComponents_s(ref_label, r_comps, subchilds)
                    if r_comps.Length():
                        self.parse_components(r_comps, shape_tool, color_tool)
                    # STACK IMBALANCE FIX (Session 72, Doug's cross-
                    # session insight connecting the create-new-
                    # assembly nesting bug and the reparent-onto-
                    # empty-as1 bug -- same root cause). The push
                    # above was UNCONDITIONAL; the matching pop used
                    # to live only inside the recursive call above,
                    # which only ran if r_comps.Length() was nonzero.
                    # An EMPTY assembly pushed with no recursive call
                    # to ever pop it -- parent_uid_stack (and the loc/
                    # entry stacks) stayed one level too deep for the
                    # REST of the walk, mis-parenting every sibling
                    # processed afterward as a child of the empty
                    # assembly instead of ITS OWN parent. Popping here,
                    # paired directly with the push, guarantees every
                    # push has exactly one pop regardless of whether
                    # the assembly had children to recurse into.
                    self.assy_entry_stack.pop()
                    self.assy_loc_stack.pop()
                    self.parent_uid_stack.pop()
            else:
                print(f"Oops! Component is not a reference: {c_uid}")


    def reparent_component(self, uid, new_parent_uid):
        """Move a component to a new parent assembly in the XDE document.

        Preserves world position by applying the inverse of the new parent's
        world transform: new_local = parent_world.Inverted() x part_world

        Adds the part to the TARGET assembly's root (referred) label so that
        ALL shared instances of that assembly receive the new component.
        """
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TopLoc import TopLoc_Location

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())

        # Get the dragged item's world location and color. part_dict
        # is ONLY populated for simple parts (parse_components's own
        # branching -- assemblies never get a part_dict entry, only
        # label_dict[uid]['world_loc']). Reading uid's world location
        # exclusively via part_dict silently defaulted to a FRESH
        # IDENTITY transform for every assembly-type drag -- Doug's
        # own readback diagnostic exposed this precisely: 3 of 4
        # drags (all assemblies) showed identity going INTO
        # AddComponent, while the one simple part (plate) showed its
        # genuine value. AddComponent itself was never at fault.
        if self.label_dict.get(uid, {}).get('is_assy'):
            part_world_loc = self.label_dict.get(
                uid, {}).get('world_loc', TopLoc_Location())
        else:
            part_world_loc = self.part_dict.get(
                uid, {}).get('loc', TopLoc_Location())
        part_color = self.part_dict.get(uid, {}).get('color')

        # Get world location of target assembly from label_dict
        parent_world_loc = self.label_dict.get(
            new_parent_uid, {}).get('world_loc', TopLoc_Location())

        # Compute new local transform: parent_world.Inverted() x part_world
        if not parent_world_loc.IsIdentity():
            new_local = parent_world_loc.Inverted().Multiplied(part_world_loc)
        else:
            new_local = part_world_loc

        # Find the referred LABEL (root geometry) for the part being moved.
        # Deliberately reference the label itself, not shape_tool.
        # GetShape_s(ref_label) -- see set_component_location() for why
        # (that same GetShape_s + AddComponent(...,True) pattern was
        # confirmed, Session 16, to lose names/substructure on
        # compounds/assemblies since raw geometry carries none of that
        # XCAF metadata).
        comp_label = self._find_label_by_entry(self.label_dict[uid]['entry'])
        if comp_label is None:
            print(f"[reparent] Could not find component label for {uid}")
            return

        ref_label_entry = self.label_dict[uid].get('ref_entry')
        if ref_label_entry:
            ref_label = self._find_label_by_entry(ref_label_entry)
        else:
            # Free root shape: the component label IS the shape label
            ref_label = comp_label
        if ref_label is None:
            print(f"[reparent] Could not find ref label for {uid}")
            return

        # Find target assembly's ROOT label (ref_entry) so both shared
        # instances of the target assembly receive the new component
        new_parent_info = self.label_dict[new_parent_uid]
        target_entry = new_parent_info.get('ref_entry') or new_parent_info['entry']
        target_label = self._find_label_by_entry(target_entry)
        if target_label is None:
            print(f"[reparent] Could not find target label")
            return

        # Add component to target with correct local transform, by
        # LABEL (preserves ref_label's full existing name/substructure)
        new_comp = shape_tool.AddComponent(target_label, ref_label, new_local)
        part_name = self.label_dict[uid]['name']
        set_label_name(new_comp, part_name)
        # Also name the referred shape so it shows correctly in all viewers
        new_ref = TDF_Label()
        if shape_tool.GetReferredShape_s(new_comp, new_ref):
            set_label_name(new_ref, part_name)

        # Set color on the new component's referred label (label-based
        # SetColor overload -- ref_shape is no longer fetched here)
        if part_color:
            from OCP.XCAFDoc import XCAFDoc_ColorGen
            color_tool.SetColor(ref_label, part_color, XCAFDoc_ColorGen)
            if not new_ref.IsNull():
                color_tool.SetColor(new_ref, part_color, XCAFDoc_ColorGen)

        # Remove from old location
        current_parent_uid = self.label_dict[uid].get('parent_uid')
        if current_parent_uid:
            # It's a component under an assembly -- use RemoveComponent
            shape_tool.RemoveComponent(comp_label)
        else:
            # It's a free root shape -- use RemoveShape
            shape_tool.RemoveShape(comp_label, True)

        shape_tool.UpdateAssemblies()
        self.parse_doc()


    def delete_component(self, uid):
        """Delete a part or assembly component from the XDE document.

        A component under an assembly is removed with RemoveComponent
        (drops that one reference -- other shared instances of the
        same part/assembly elsewhere in the tree are unaffected). If
        that was the LAST reference to its underlying shape (checked
        via GetUsers_s, the same method already used for shared-
        instance detection since Session 22), the now-orphaned
        referred shape is removed too -- RECURSIVELY, via
        remove_shape_and_orphaned_descendants(), since a multi-level
        nested assembly (e.g. l-bracket-assembly, which itself
        contains nut-bolt-assembly) can have its OWN children become
        newly orphaned one level deeper -- a single RemoveShape() call
        does not cascade orphan-detection through nested levels on its
        own (confirmed directly via cleanup_orphans.py hitting the
        identical issue). Otherwise an orphan lingers in the document
        as an unreferenced free shape, which XCAF still writes out to
        STEP regardless of nothing pointing at it. Confirmed directly:
        Doug deleted several original components from as1 and saved,
        and CAD Assistant showed them still present as free shapes
        alongside as1 in the file, even though Kodacad's own tree
        correctly showed them gone.

        A free root shape (no parent) is removed the same recursive
        way. Mirrors the removal step already used in
        reparent_component().
        """
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TDF import TDF_Label, TDF_LabelSequence
        if uid not in self.label_dict:
            print(f"[delete] Unknown uid {uid}")
            return False
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        comp_label = self._find_label_by_entry(self.label_dict[uid]['entry'])
        if comp_label is None:
            print(f"[delete] Could not find label for {uid}")
            return False
        current_parent_uid = self.label_dict[uid].get('parent_uid')
        if current_parent_uid:
            ref_label = TDF_Label()
            has_ref = shape_tool.GetReferredShape_s(comp_label, ref_label)
            shape_tool.RemoveComponent(comp_label)
            # Refresh XCAF's own bookkeeping BEFORE checking orphan
            # status -- hypothesis being tested (Doug's report: deleting
            # BOTH shared instances of l-bracket-assembly still left it
            # behind as an orphan): GetUsers_s/RemoveShape may be
            # working off a stale view of what's free immediately after
            # RemoveComponent, without an explicit refresh here.
            shape_tool.UpdateAssemblies()
            if has_ref and not ref_label.IsNull():
                users = TDF_LabelSequence()
                n_users = shape_tool.GetUsers_s(ref_label, users, False)
                print(f"[delete] orphan check: ref_label users={n_users} "
                     f"(0 means the underlying shape should now be removed too)")
                if n_users == 0:
                    remove_shape_and_orphaned_descendants(shape_tool, ref_label)
        else:
            remove_shape_and_orphaned_descendants(shape_tool, comp_label)
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        return True

    def set_component_location(self, uid, new_local_loc):
        """Reposition a component IN PLACE (same parent) by removing it
        and re-adding it at the new location.

        Originally used XCAFDoc_ShapeTool::SetLocation directly (the
        docs describe it as the purpose-built primitive: "if label is
        reference, changes location attribute"). That worked correctly
        in-memory -- confirmed via readback immediately after the call
        -- but a real-world test caught it NOT surviving STEP export:
        moving 'manual-lathe' (a component added via XCAFDoc_Editor.
        Extract_s, see add_component_from_label) and saving showed the
        new location correctly in the live document right up to
        Write(), but the saved STEP file had that one component's
        placement written as identity while four other, unrelated
        components (added the normal way, via the STEP reader's own
        AddComponent calls) all round-tripped correctly with their
        (non-identity) locations intact. See docs/DEVELOPMENT_LOG.md,
        Session 14, for the full diagnostic trail.

        Rather than chase why SetLocation's result doesn't survive
        export, this uses RemoveComponent + AddComponent(location) --
        the exact pattern reparent_component() already uses
        successfully, and the same mechanism the STEP reader itself
        used to build the four components that round-tripped
        correctly.

        Only the ONE component instance at `uid` is moved -- if the
        same part is shared/dragged into multiple places in the tree,
        the other instances are untouched (contrast with
        reparent_component(), which deliberately targets the referred/
        root label so ALL shared instances move together).

        new_local_loc: TopLoc_Location expressed relative to the
        component's current parent (same convention as
        reparent_component's new_local).

        Returns the component's NEW uid on success, or None on
        failure. IMPORTANT: because AddComponent creates a new label
        rather than mutating the old one, `uid` changes on every call
        -- callers that apply several moves in sequence to the same
        item (e.g. PositionDialog's Step 1 / Back / Reverse) MUST use
        the returned uid for the next call, not the original one.
        """
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        if uid not in self.label_dict:
            print(f"[set_component_location] Unknown uid {uid}")
            return None
        info = self.label_dict[uid]
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())

        comp_label = self._find_label_by_entry(info['entry'])
        if comp_label is None:
            print(f"[set_component_location] Could not find label for {uid}")
            return None

        # Referred (root) shape's LABEL -- deliberately reference the
        # label itself, not shape_tool.GetShape_s(ref_label). That
        # call returns bare geometry with no XCAF name/structure
        # attached (the exact trap Session 9 already fixed once, for
        # STEP imports -- reintroduced here in Session 14 while fixing
        # a different problem). Passing raw geometry through
        # AddComponent(..., expand=True) for a compound/assembly tells
        # OCCT to decompose it into a FRESH assembly structure with no
        # name information to work from, so it falls back to
        # auto-numbering (confirmed: 'manual-lathe' and the hub
        # assembly came back named '22' and '25' after a Position
        # move + save/reload -- see Session 16). Referencing ref_label
        # directly via the label-based AddComponent overload avoids
        # ever converting to raw geometry, so the existing names and
        # substructure are untouched.
        ref_entry = info.get('ref_entry')
        ref_label = self._find_label_by_entry(ref_entry) if ref_entry else comp_label
        if ref_label is None:
            print(f"[set_component_location] Could not find referred label for {uid}")
            return None

        # UNSHARE-ON-REPOSITION: RETIRED (Session 54). The Session 22
        # defensive step -- cloning a multi-user shape's geometry
        # before repositioning one of its instances -- is no longer
        # performed. History: back then, direct STEP inspection showed
        # repositioning one of N shared instances corrupting on export
        # (blank name, identity location), so the moved instance was
        # given an independent clone first ("make unique"). But that
        # evidence predates every structural discovery of Session 51,
        # and was very likely confounded by that era's Extract_s-
        # tainted document structures -- the same confound that
        # invalidated smoke_test_freecad_strategy's first result.
        # smoke_test_shared_reposition.py (Session 54) settled it:
        # repositioning one of two shared instances, with NO unshare,
        # round-trips cleanly -- names, locations, and SHARING all
        # preserved -- for both a shared leaf part and a shared
        # assembly-with-children. Removing the unshare makes
        # Create Shared Instance -> Position yield genuine persistent
        # sharing end to end, the whole point of a shared instance.
        from OCP.TDF import TDF_Label, TDF_LabelSequence

        # Parent assembly label (component's CURRENT parent -- we are
        # repositioning in place, not reparenting).
        #
        # Resolves through the parent's REFERRED (shared) label when
        # the parent is itself a shared instance (e.g. l-bracket-
        # assembly_1/_2 both referencing one product) -- this is
        # deliberate, not a bug: it means repositioning a child within
        # a shared parent propagates to every instance of that parent,
        # the same way editing the child's own shape already
        # propagates. Confirmed with Doug (Session 31) as the actually
        # desired behavior, matching Session 19-era behavior he
        # specifically wants back: move the shared L-bracket once, see
        # it correctly in both assemblies, survives save/reload.
        #
        # Session 24 read a component's parent_uid appearing to change
        # between calls as corruption and "fixed" it by resolving
        # through the parent's own instance entry instead -- which
        # crashed (AddComponent needs a label that structurally holds
        # children; an instance/reference label doesn't). Session 25
        # then added a refusal here instead of chasing that further.
        # Both were very likely responding to this same correct
        # propagation behavior, misread as a defect -- removed in
        # Session 31. If cross-contamination between UNRELATED shared
        # assemblies is ever seen again, that would be a real, new bug
        # worth its own fresh diagnosis -- but propagation to a
        # parent's own sibling instances is the intended feature.
        parent_uid = info.get('parent_uid')
        if not parent_uid or parent_uid not in self.label_dict:
            print(f"[set_component_location] No parent found for {uid} "
                  f"-- cannot reposition a root shape this way")
            return None
        parent_info = self.label_dict[parent_uid]
        parent_entry = parent_info.get('ref_entry') or parent_info['entry']
        parent_label = self._find_label_by_entry(parent_entry)
        if parent_label is None:
            print(f"[set_component_location] Could not find parent label for {uid}")
            return None

        # DIAGNOSTIC (temporary -- Session 16's "label instead of shape"
        # fix did NOT resolve the save/reload regression in real
        # testing, despite being well-reasoned. Going back to Session
        # 14's approach: real data beats another guess. Tracing every
        # call since the dialog can apply several moves in one session
        # (2 Points, Mate/Align, Back, Reverse) and we haven't yet
        # ruled out that repeated calls behave differently from a
        # single one.
        self._sc_call_count = getattr(self, '_sc_call_count', 0) + 1
        call_n = self._sc_call_count
        print(f"[set_component_location #{call_n}] uid={uid} "
              f"comp_entry={info['entry']} name={info['name']!r} "
              f"parent_uid={info.get('parent_uid')}")
        pre_name = get_label_name(comp_label)
        print(f"[set_component_location #{call_n}] comp_label name "
              f"BEFORE remove: {pre_name!r}")
        ref_name_before = get_label_name(ref_label)
        print(f"[set_component_location #{call_n}] ref_label entry="
              f"{get_label_entry(ref_label)} name_before={ref_name_before!r}")

        shape_tool.RemoveComponent(comp_label)
        # UpdateAssemblies between remove and re-add: the exact
        # sequence validated by smoke_test_production_fix.py and
        # smoke_test_freecad_single_shot.py Case C (Session 52).
        # Cheap insurance that the document's assembly bookkeeping is
        # consistent before the new component is created.
        shape_tool.UpdateAssemblies()
        new_comp = shape_tool.AddComponent(parent_label, ref_label, new_local_loc)

        # Confirmed via file inspection (Session 17): when an
        # occurrence's own name is IDENTICAL to its referred/product
        # label's name, STEPCAFControl_Writer leaves the NAUO's
        # descriptive-name field blank on export -- every occurrence in
        # as1-oc-214.stp that round-trips correctly has a name that
        # DIFFERS from its product name (e.g. 'plate_1' vs 'plate'),
        # confirmed via a controlled test (import + save + reload with
        # NO Position move survives fine -- the bug is specific to
        # set_component_location, not general to same-named occurrences
        # on their own). Force a distinguishing suffix so this
        # component's name is never identical to ref_label's, matching
        # the convention every working component in the file already
        # follows.
        comp_name = info['name']
        if comp_name == ref_name_before:
            comp_name = f"{comp_name}_1"
            print(f"[set_component_location] name matched referred label's "
                  f"name exactly -- using {comp_name!r} instead to avoid "
                  f"the writer leaving the NAUO name blank")
        set_label_name(new_comp, comp_name)
        new_entry = get_label_entry(new_comp)

        # Read back IMMEDIATELY -- before UpdateAssemblies/parse_doc --
        # to see whether the name/location are even correct right after
        # AddComponent, before anything else touches the document.
        readback_name = get_label_name(new_comp)
        readback_loc = shape_tool.GetShape_s(new_comp).Location()
        rt = readback_loc.Transformation().TranslationPart()
        print(f"[set_component_location #{call_n}] new_comp entry={new_entry} "
              f"name_readback={readback_name!r} "
              f"loc_readback=({rt.X():.3f}, {rt.Y():.3f}, {rt.Z():.3f})")

        # Also check: did ref_label ITSELF survive intact? (RemoveComponent
        # removes the COMPONENT/reference, not the referred shape -- but
        # confirming that assumption rather than continuing to trust it.)
        ref_name_after = get_label_name(ref_label)
        print(f"[set_component_location #{call_n}] ref_label name AFTER "
              f"remove+add: {ref_name_after!r} (should be unchanged: "
              f"{ref_name_after == ref_name_before})")

        shape_tool.UpdateAssemblies()
        self.parse_doc()

        # Recover the uid parse_doc() actually assigned to new_entry.
        # NOTE: get_uid_from_entry() is a *generator* (increments a
        # counter in self._share_dict on every call), used internally
        # by parse_doc()'s own walk -- calling it again here would mint
        # a fresh, never-assigned uid rather than recover the real one
        # parse_doc() just gave this label. Search label_dict instead.
        #
        # A shared child (e.g. l-bracket, living inside the ONE shared
        # l-bracket-assembly product) is reachable through MULTIPLE
        # parent paths -- parse_doc()'s walk visits each parent
        # occurrence and generates a SEPARATE uid per path, even
        # though it's the same underlying label. Session 32: taking
        # the first match unconditionally meant this ALWAYS returned
        # whichever parent path parse_doc() visits first in document
        # order (l-bracket-assembly_1 before _2) -- confirmed this is
        # exactly why the Position dialog's breadcrumb and the
        # manipulator gizmo always "jumped" to assy_1 after a move,
        # regardless of which sibling the user actually started from.
        # Fix: when more than one candidate matches, prefer the one
        # reached through the SAME parent this call started from, so
        # the caller keeps tracking the same occurrence across
        # repeated calls instead of whichever the tree walk visits
        # first.
        matches = [c_uid for c_uid, c_info in self.label_dict.items()
                  if c_info['entry'] == new_entry]
        if not matches:
            print(f"[set_component_location] Warning: could not recover uid "
                  f"for entry {new_entry} after parse_doc()")
            return None

        chosen_uid = matches[0]
        if len(matches) > 1:
            original_parent_entry = parent_info['entry']
            for c_uid in matches:
                c_parent_uid = self.label_dict[c_uid].get('parent_uid')
                c_parent_entry = self.label_dict.get(c_parent_uid, {}).get('entry')
                if c_parent_entry == original_parent_entry:
                    chosen_uid = c_uid
                    break

        # Session 87, Doug: moving a component nested inside a shared
        # parent (e.g. nut-bolt-assembly_1 within l-bracket-assembly,
        # shared by l-bracket-assembly_1/_2) correctly propagated in
        # the DOCUMENT DATA -- this function's own parent-resolution
        # logic above (parent_entry = ref_entry or entry) has done
        # that deliberately since Session 31. But the OTHER occurrence
        # never visibly moved, because nothing was telling its display
        # to redraw: PositionDialog._refresh_display's default fast
        # path explicitly assumed (per this function's own docstring,
        # now stale for this exact case) that other shared instances
        # are untouched, and skipped every surviving uid accordingly.
        # Same shape of bug as the earlier fillet/shell propagation
        # fix -- correct data, no signal telling the display to catch
        # up. Recorded the same way that fix's signal was recorded
        # (dm._shape_replaced_entries): if propagation happened here
        # (the parent was resolved through its OWN shared/referred
        # entry, not its direct one), record that shared entry so the
        # caller can force-redraw every current instance sharing it.
        if parent_info.get('ref_entry'):
            if not hasattr(self, '_shared_parent_moves'):
                self._shared_parent_moves = []
            self._shared_parent_moves.append(parent_entry)

        post_name = self.label_dict[chosen_uid].get('name')
        post_loc = (self.label_dict[chosen_uid].get('world_loc')
                    if self.label_dict[chosen_uid].get('is_assy')
                    else self.part_dict.get(chosen_uid, {}).get('loc'))
        pt = post_loc.Transformation().TranslationPart() if post_loc else None
        print(f"[set_component_location #{call_n}] AFTER parse_doc: "
              f"uid={chosen_uid} name={post_name!r} "
              f"world_loc="
              f"{(round(pt.X(),3), round(pt.Y(),3), round(pt.Z(),3)) if pt else None}"
              f"{' (chosen from ' + str(len(matches)) + ' shared occurrences)' if len(matches) > 1 else ''}")
        return chosen_uid

    def get_full_path_name(self, uid):
        """Full breadcrumb path from '/' down to uid, e.g.
        '/ / as1 / manual-lathe' -- (see Session 85 fix below for the
        two-slash example this docstring used to show).

        Kodacad's XCAF model allows the same part/assembly DEFINITION
        to appear as multiple distinct instances in different places
        in the tree (see Session 13's shared-instance discussion) --
        a bare name alone doesn't disambiguate which instance is
        meant. Used by PositionDialog's top section so there's no
        ambiguity about which instance is about to be moved.

        Session 85, Doug: showed four slashes ('/ / / / wheel-axle-
        asy_1 / wheel_2') for what should have been a single '/'.
        Root cause: the walk-up loop below already naturally reaches
        and collects the document's own root label -- which is
        ITSELF named '/' by convention -- as the last real entry
        before parent_uid runs out. An unconditional names.append('/')
        used to run after the loop regardless, double-counting that
        same root every single call. Removed -- the loop's own
        termination already provides exactly one '/' for the root,
        with no separate append needed. If a session still shows more
        than one '/' after this fix, that reflects genuinely nested
        '/'-named labels baked into that specific document's own
        saved data (e.g. from before Session 85's create_new_assembly
        and build_tree fixes) rather than this function's own
        counting -- worth a separate, direct look at that file's
        structure if it recurs.
        """
        names = []
        cur = uid
        seen = set()
        while cur and cur in self.label_dict:
            if cur in seen:
                break  # safety: guard against a malformed cycle
            seen.add(cur)
            names.append(self.label_dict[cur].get('name') or '?')
            cur = self.label_dict[cur].get('parent_uid')
        return ' / '.join(reversed(names))

    def get_descendant_part_uids(self, uid):
        """Return uids of every LEAF part (part_dict entry) that is
        `uid` itself, or a descendant of it. Used by the AIS_Manipulator
        ("Dynamic" Position method) to find every displayed shape that
        needs to move live during a drag -- the manipulator gizmo is
        only ever Attach()-ed to ONE representative shape, so the rest
        of a multi-part assembly has to be moved manually in lockstep.
        """
        if uid in self.part_dict:
            return [uid]
        result = []
        for part_uid in self.part_dict:
            cur = part_uid
            seen = set()
            while cur and cur in self.label_dict:
                if cur in seen:
                    break
                seen.add(cur)
                if cur == uid:
                    result.append(part_uid)
                    break
                cur = self.label_dict[cur].get('parent_uid')
        return result

    def get_world_loc(self, uid):
        """Current world TopLoc_Location of a part or assembly uid.

        Parts and assemblies store their world location in different
        dicts (parse_components() only adds simple shapes to
        part_dict -- see Session 13) so this branches on is_assy
        rather than making every caller remember that distinction.
        """
        from OCP.TopLoc import TopLoc_Location
        if uid not in self.label_dict:
            return TopLoc_Location()
        if self.label_dict[uid].get('is_assy', False):
            return self.label_dict[uid].get('world_loc', TopLoc_Location())
        return self.part_dict.get(uid, {}).get('loc', TopLoc_Location())

    def get_parent_world_loc(self, uid):
        """World TopLoc_Location of uid's current parent assembly
        (Identity if uid is a free root shape with no parent)."""
        from OCP.TopLoc import TopLoc_Location
        parent_uid = self.label_dict.get(uid, {}).get('parent_uid')
        if parent_uid:
            return self.label_dict.get(parent_uid, {}).get(
                'world_loc', TopLoc_Location())
        return TopLoc_Location()

    def world_to_local(self, uid, world_loc):
        """Convert a world-space TopLoc_Location into the local
        (relative-to-current-parent) location set_component_location()
        expects -- same convention already proven in
        reparent_component()'s new_local computation."""
        parent_world = self.get_parent_world_loc(uid)
        if not parent_world.IsIdentity():
            return parent_world.Inverted().Multiplied(world_loc)
        return world_loc

    def create_new_assembly(self, parent_uid, name):
        """Create a new, empty assembly as a component under the item
        identified by parent_uid (Session 54, RMB tree feature).

        parent_uid=None means "create directly under the top-level
        '/' root" -- Session 85, Doug: right-clicking the tree's own
        '/' failed outright in a fresh, empty session (its uid isn't
        in label_dict at all, since nothing has ever been parsed into
        it yet), and even a genuinely-once-was-an-assembly label that
        had all its children deleted then failed the IsAssembly_s()
        check below (OCCT's XDE model treats "being an assembly" as
        structural -- dependent on CURRENTLY having at least one
        child -- not as a persistent flag; an assembly with zero
        children simply isn't recognized as one, regardless of its
        history). This mirrors add_component's own, already-proven
        fix for the identical problem: check GetFreeShapes first, and
        if there's nothing there yet, create the root '/' before
        proceeding, rather than requiring the caller to already have
        a valid assembly to target.

        The parent may be the root (a free shape) or a component
        (reference) -- a reference is resolved to its referred label
        first. The target must be an assembly. The new assembly is an
        empty compound created via AddShape(compound, True) -- the
        exact construction of the '/' root, the healthiest structure
        this project knows (Session 51) -- added at identity via the
        label-based AddComponent overload.

        NOTE: an assembly with NO children may not survive a STEP
        save/reload -- a product with no geometry can be dropped by
        the writer. The intended workflow is create-then-populate
        (drag parts in, or add shared instances) before saving; a
        reminder prints on creation.
        """
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TDF import TDF_Label
        from OCP.TopoDS import TopoDS_Compound
        from OCP.BRep import BRep_Builder
        from OCP.TopLoc import TopLoc_Location
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        if parent_uid is None:
            # Same "ensure the root exists" logic as add_component --
            # GetFreeShapes first; if empty, create the '/' root the
            # same way this function already creates any other new,
            # empty assembly.
            free_labels = TDF_LabelSequence()
            shape_tool.GetFreeShapes(free_labels)
            if free_labels.Length() == 0:
                root_shape = TopoDS_Compound()
                BRep_Builder().MakeCompound(root_shape)
                root_label = shape_tool.AddShape(root_shape, True)
                set_label_name(root_label, "/")
                # Session 86: same fix as add_component's identical
                # pattern -- AddShape here and AddComponent below
                # both touch root_label's own shape attribute within
                # one transaction, matching the reasoned (not live-
                # verified) cause of Doug's reported Redo failure.
                # Splitting into two committed transactions so each
                # touches it only once. Only runs the very first
                # time EITHER add_component or create_new_assembly
                # creates the root -- unaffected once it exists.
                if self.doc.HasOpenCommand():
                    self.doc.CommitCommand()
                    self.doc.NewCommand()
                shape_tool.GetFreeShapes(free_labels)
            target_assy = free_labels.Value(1)
        else:
            if parent_uid not in self.label_dict:
                print(f"[create_new_assembly] Unknown uid {parent_uid}")
                return False
            parent_label = self._find_label_by_entry(
                self.label_dict[parent_uid]['entry'])
            if parent_label is None:
                print(f"[create_new_assembly] Could not find label for "
                      f"{parent_uid}")
                return False
            # Resolve a component reference to its referred label
            target_assy = parent_label
            ref = TDF_Label()
            if shape_tool.GetReferredShape_s(parent_label, ref):
                target_assy = ref
            if not shape_tool.IsAssembly_s(target_assy):
                print(f"[create_new_assembly] "
                      f"'{get_label_name(target_assy)}' is not an assembly -- "
                      f"a new assembly can only be created under an assembly.")
                return False
        new_shape = TopoDS_Compound()
        BRep_Builder().MakeCompound(new_shape)
        new_label = shape_tool.AddShape(new_shape, True)
        set_label_name(new_label, name)
        comp = shape_tool.AddComponent(target_assy, new_label,
                                       TopLoc_Location())
        # Suffix convention (Session 17 guard: identical occurrence/
        # product names get blanked by the STEP writer)
        set_label_name(comp, f"{name}_1")
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        print(f"[create_new_assembly] '{name}' created under "
              f"'{get_label_name(target_assy)}'. NOTE: populate it "
              f"before saving -- an EMPTY assembly may not survive a "
              f"STEP save/reload.")
        return True

    def create_shared_instance(self, uid):
        """Create a shared instance of the component identified by uid,
        at exactly the same location as the original (Session 54, RMB
        tree feature) -- superimposed, ready to be moved via the
        Position dialog.

        Mechanism: a new component under the SAME parent assembly,
        referencing the SAME underlying shape label, at the SAME
        location -- one more NAUO pointing at one product, exactly the
        structure as1-oc-214.stp uses for its two l-bracket-assembly
        instances (confirmed round-trip-safe for the whole life of
        this project). Works identically for parts and assemblies.

        RESOLVED (Session 54): smoke_test_shared_reposition.py PASSED
        for both a shared leaf part and a shared assembly-with-
        children -- repositioning one of multiple shared instances
        round-trips cleanly with sharing preserved. The Session 22
        unshare step has been REMOVED from set_component_location, so
        Create Shared Instance -> Position now yields genuine
        persistent sharing end to end: move the new instance wherever
        it belongs, and both instances keep referencing one underlying
        product, in the session and through STEP save/reload.
        """
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TDF import TDF_Label, TDF_LabelSequence
        if uid not in self.label_dict:
            print(f"[create_shared_instance] Unknown uid {uid}")
            return False
        if not self.label_dict[uid].get('parent_uid'):
            print("[create_shared_instance] The root cannot be instanced.")
            return False
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        comp_label = self._find_label_by_entry(self.label_dict[uid]['entry'])
        if comp_label is None:
            print(f"[create_shared_instance] Could not find label for {uid}")
            return False
        ref_label = TDF_Label()
        if not shape_tool.GetReferredShape_s(comp_label, ref_label):
            print(f"[create_shared_instance] "
                  f"'{get_label_name(comp_label)}' is not a component "
                  f"reference -- cannot instance it.")
            return False
        # Same parent, same referred shape, same location
        parent_assy = comp_label.Father()
        loc = shape_tool.GetShape_s(comp_label).Location()
        users = TDF_LabelSequence()
        n_users = shape_tool.GetUsers_s(ref_label, users, False)
        new_comp = shape_tool.AddComponent(parent_assy, ref_label, loc)
        ref_name = get_label_name(ref_label)
        set_label_name(new_comp, f"{ref_name}_{n_users + 1}")
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        print(f"[create_shared_instance] '{ref_name}_{n_users + 1}' "
              f"created, superimposed on the original -- use the "
              f"Position dialog to move it. ({n_users + 1} instances "
              f"now share one underlying "
              f"{'assembly' if shape_tool.IsAssembly_s(ref_label) else 'part'}.)")
        return True

    def _find_label_by_entry(self, entry):
        """Find a TDF_Label by its entry string.

        Searches both root shape labels AND component labels (depth 5+)
        by walking the full document tree.
        """
        if not entry:
            return None
        from OCP.TDF import TDF_LabelSequence, TDF_ChildIterator
        from OCP.XCAFDoc import XCAFDoc_DocumentTool

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())

        # First try root shapes
        labels = TDF_LabelSequence()
        shape_tool.GetShapes(labels)
        for i in range(1, labels.Length() + 1):
            lbl = labels.Value(i)
            if get_label_entry(lbl) == entry:
                return lbl
            # Search component labels (children of root shape labels)
            result = self._search_children(lbl, entry)
            if result is not None:
                return result
        return None

    def _search_children(self, label, entry):
        """Recursively search child labels for matching entry."""
        from OCP.TDF import TDF_ChildIterator
        itr = TDF_ChildIterator(label, False)
        while itr.More():
            child = itr.Value()
            if get_label_entry(child) == entry:
                return child
            result = self._search_children(child, entry)
            if result is not None:
                return result
            itr.Next()
        return None

    def save_step_doc(self):
        """Export self.doc to STEP file."""
        prompt = 'Specify name for saved step file.'
        fname, __ = QFileDialog.getSaveFileName(None, prompt, './',
                                                "STEP files (*.stp *.STP *.step)")
        if not fname:
            print("Save step cancelled.")
            return

        # DIAGNOSTIC (temporary, reinstated from Session 14 -- the
        # Session 16 fix did not resolve the regression in real
        # testing). Dump every component under '/', recursively this
        # time (Session 14 only went one level deep -- the name
        # corruption this round may be at any depth, not just top-level).
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TDF import TDF_LabelSequence
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())

        def _dump(label, depth):
            name = get_label_name(label)
            loc = shape_tool.GetShape_s(label).Location()
            t = loc.Transformation().TranslationPart()
            print(f"{'  ' * depth}{name!r} entry={get_label_entry(label)} "
                  f"loc=({t.X():.3f}, {t.Y():.3f}, {t.Z():.3f})")
            children = TDF_LabelSequence()
            shape_tool.GetComponents_s(label, children, False)
            for i in range(1, children.Length() + 1):
                _dump(children.Value(i), depth + 1)

        free_labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free_labels)
        print(f"[save_step_doc] pre-write dump ({free_labels.Length()} free shape(s)):")
        for i in range(1, free_labels.Length() + 1):
            _dump(free_labels.Value(i), 0)

        # Tripwire + repair before writing (Session 57 cont'd): an
        # unnamed product would get the writer's translator-string
        # placeholder, showing namelessly in CAD Assistant/FreeCAD
        # (which display PRODUCT names). Repairing self.doc here
        # covers BOTH write branches -- the temp-doc rebuild copies
        # names from self.doc. If this ever prints for content
        # created THIS session, its output identifies a live
        # name-leak path worth fixing at source.
        repair_unnamed_products(self.doc, context=" save")

        WS = XSControl_WorkSession()
        # Disable PCURVE writing (Session 73, Doug's 2.5x STEP-save
        # bloat report). OCCT's STEPCAFControl_Writer DEFAULTS to
        # writing a redundant 2D parametric-curve representation
        # (PCURVE) for every edge, alongside the 3D curve that's
        # already being written -- geometrically REDUNDANT (fully
        # reconstructable from the 3D curve + surface data present
        # either way), but adds a large number of extra points. No
        # Interface_Static configuration existed anywhere in this
        # save path before -- meaning every save has always used
        # OCCT's verbose default, independent of anything this
        # document/pipeline does (confirmed: an explicit shape-copy
        # fix that WOULD have mattered if the cause were display-
        # prep mutation had ZERO effect on the bloat; the original
        # file has no embedded tessellation to explain it either --
        # both ruled out with real entity-count data before landing
        # here). Setting this to 0 is a pure writer-verbosity knob,
        # not a document-correctness change -- Onshape's and CAD
        # Assistant's own writers most likely already default this
        # off, which is the actual source of the size gap.
        try:
            from OCP.Interface import Interface_Static
            Interface_Static.SetIVal_s("write.surfacecurve.mode", 0)
        except Exception as pe:
            print(f"[save_step_doc] could not disable PCURVE writing "
                 f"({pe}) -- file will save with OCCT's default "
                 f"(more verbose) geometry representation; harmless, "
                 f"the file is still correct, just larger")
        step_writer = STEPCAFControl_Writer(WS, False)

        # Export-side unwrap (Session 56, Basicad item 30 ported):
        # if the root is a '/'-wrapper chain -- each level named '/',
        # with exactly ONE child sitting at IDENTITY location --
        # descend to the first REAL assembly and export THAT as the
        # file root, by rebuilding it into a temporary document via
        # rebuild_imported_structure (the validated Session 52
        # machinery: names, locations, sharing, and colors all carry).
        # The written file then contains e.g. 'as1' at top, no '/'
        # wrapper at all -- and because the descent walks the WHOLE
        # chain, one re-save fully cleans a legacy multi-wrapped file
        # ('/'->'/'->'/'->as1 exports as just as1). Any deviation from
        # the safe pattern (multiple children, non-identity location,
        # nothing but wrappers) falls through to writing the document
        # as-is, unchanged behavior.
        from OCP.TDF import TDF_Label
        export_root_ref = None
        export_root_name = None
        if free_labels.Length() == 1:
            cur = free_labels.Value(1)
            descended = False
            last_occ_name = None
            while (cur is not None and get_label_name(cur) == '/'
                   and shape_tool.IsAssembly_s(cur)):
                children = TDF_LabelSequence()
                shape_tool.GetComponents_s(cur, children, False)
                if children.Length() != 1:
                    cur = None
                    break
                child = children.Value(1)
                child_loc = shape_tool.GetShape_s(child).Location()
                if not child_loc.IsIdentity():
                    cur = None
                    break
                ref = TDF_Label()
                if not shape_tool.GetReferredShape_s(child, ref):
                    cur = None
                    break
                last_occ_name = get_label_name(child)
                cur = ref
                descended = True
            if (descended and cur is not None
                    and get_label_name(cur) != '/'):
                export_root_ref = cur
                ref_name = get_label_name(cur)
                # Session 57 (fixes a Session 56 regression): the
                # unwrap discarded the final occurrence's name -- so a
                # user's RENAME of the top assembly (which renames the
                # occurrence, e.g. 'as1_1' -> 'my-lathe') was silently
                # lost on every save. If the occurrence name is a user
                # rename rather than the auto '<ref>_<digits>' suffix
                # pattern, the exported root carries it.
                import re
                if (last_occ_name
                        and last_occ_name != ref_name
                        and not re.fullmatch(
                            re.escape(ref_name) + r"_\d+", last_occ_name)):
                    export_root_name = last_occ_name

        if export_root_ref is not None:
            real_name = export_root_name or get_label_name(export_root_ref)
            print(f"[save_step_doc] unwrapping '/' chain -- exporting "
                  f"'{real_name}' as the file root (in-memory document "
                  f"unchanged)")
            temp_doc, temp_app = create_doc()
            temp_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(temp_doc.Main())
            temp_color_tool = XCAFDoc_DocumentTool.ColorTool_s(temp_doc.Main())
            memo = {}
            rebuilt_root = rebuild_imported_structure(
                export_root_ref, temp_shape_tool, temp_color_tool, memo)
            if export_root_name:
                # Carry the user's top-assembly rename (Session 57 --
                # fixes the Session 56 regression that discarded it)
                set_label_name(rebuilt_root, export_root_name)
            temp_shape_tool.UpdateAssemblies()
            step_writer.Transfer(temp_doc, STEPControl_AsIs)
        else:
            step_writer.Transfer(self.doc, STEPControl_AsIs)

        # Customize the STEP header (Session 58, revised cont'd). The
        # first attempt produced OCCT's default header, silently --
        # so this version is self-diagnosing: per-field try blocks
        # (one bad spelling can't void the rest), both spelling
        # variants for Organisation/Authorisation, a fallback attempt
        # against the work-session model, and -- ground truth --
        # post-write readback of the written file's actual FILE_NAME
        # block, printed on every save. Whatever happens, the next
        # save's terminal output identifies the failing stage.
        try:
            from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
            from OCP.TCollection import TCollection_HAsciiString

            def _H(s):
                return TCollection_HAsciiString(s)

            def _app_version():
                try:
                    from version import APP_VERSION
                    return APP_VERSION
                except Exception:
                    return ""

            hdr = None
            for model_src, tag in ((lambda: step_writer.ChangeWriter().Model(),
                                    "ChangeWriter().Model()"),
                                   (lambda: WS.Model(), "WS.Model()")):
                try:
                    hdr = APIHeaderSection_MakeHeader(model_src())
                    print(f"[save_step_doc] header via {tag}")
                    break
                except Exception as e:
                    print(f"[save_step_doc] header model {tag} failed: {e}")
            if hdr is not None:
                for setter_names, args in (
                        (("SetName",), (_H(os.path.basename(fname)),)),
                        (("SetOriginatingSystem",),
                         (_H(f"KodaCAD {_app_version()}"),)),
                        (("SetAuthorValue",), (1, _H("Doug Blanding"))),
                        (("SetOrganizationValue", "SetOrganisationValue"),
                         (1, _H(""))),
                        (("SetAuthorisation", "SetAuthorization"),
                         (_H(""),))):
                    applied = False
                    for sname in setter_names:
                        fn = getattr(hdr, sname, None)
                        if fn is None:
                            continue
                        try:
                            fn(*args)
                            applied = True
                            break
                        except Exception as e:
                            print(f"[save_step_doc] {sname} failed: {e}")
                    if not applied:
                        print(f"[save_step_doc] no working setter among "
                              f"{setter_names}")
        except Exception as e:
            print(f"[save_step_doc] header customization skipped: {e}")

        status = step_writer.Write(fname)
        assert status == IFSelect_RetDone

        # Ground truth: what FILE_NAME actually got written
        try:
            with open(fname, errors="replace") as fh:
                head = fh.read(3000)
            start = head.find("FILE_NAME")
            if start != -1:
                end = head.find(";", start)
                print(f"[save_step_doc] written header: "
                      f"{head[start:end + 1]}")
        except Exception:
            pass

    def open_doc(self):
        """Open a previously saved .xbf file (stub -- use load_stp_at_top instead)."""
        print("open_doc: not implemented in OCP port. Use Load STEP At Top instead.")

    def save_doc(self, doc=None):
        """Save doc to file in BinXCAF format (.xbf)"""
        if not doc:
            doc = self.doc
        prompt = 'Specify name of file for saved doc.'
        fname, __ = QFileDialog.getSaveFileName(None, prompt, './',
                                                "native CAD format (*.xbf)")
        if not fname:
            print("Save cancelled.")
            return
        if not fname.endswith('.xbf'):
            fname += '.xbf'
        save_status = self.app.SaveAs(doc, TCollection_ExtendedString(fname))
        if save_status == PCDM_SS_OK:
            print(f"File {fname} saved successfully.")
        else:
            print("File save failed.")

    def replace_shape(self, uid, modshape):
        """Replace referred shape with modshape of component with uid.

        The modified part is a located instance of a referred shape stored
        at doc root. Move the modified instance back to root, then save.
        This updates ALL instances sharing the same referred shape."""
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())
        ref_entry = self.label_dict[uid]['ref_entry']
        color = self.part_dict[uid]['color']
        # Resolve the referred label DIRECTLY from its entry string
        # (Doug: fillet on a natively-created bottle failed with
        # NCollection_Sequence::Value). The OLD code took
        # n = int(ref_entry.split(':')[-1]) and indexed POSITIONALLY
        # into shape_tool.GetShapes() -- a heuristic that happens to
        # hold for STEP-imported documents (the reader's internal
        # ordering lines up with the entry's last tag) but has no
        # reason to hold for a part registered via add_component's
        # native-construction path, whose referred label can land
        # anywhere in that sequence. TDF_Tool.Label_s is the correct,
        # general OCCT idiom for resolving ANY entry string back to
        # its real label, regardless of how/where it was created --
        # the exact inverse of get_label_entry's own TDF_Tool.Entry_s
        # (which wrote the entry using a TCollection_AsciiString, so
        # the read-back is wrapped the same way defensively -- OCP's
        # strict typing bit SetOwner earlier this session the same
        # way a bare str could bite this).
        label = None
        try:
            from OCP.TDF import TDF_Tool, TDF_Label
            from OCP.TCollection import TCollection_AsciiString
            candidate = TDF_Label()
            TDF_Tool.Label_s(
                self.doc.GetData(), TCollection_AsciiString(ref_entry),
                candidate)
            # CONFIRMED BUG (Session 79, Doug's own diagnostic data):
            # this OCP binding does NOT return a usable boolean from
            # TDF_Tool.Label_s -- Doug's print showed found=None,
            # candidate.IsNull()=False, meaning the lookup had ALREADY
            # SUCCEEDED (a real, valid label) every single time since
            # this fix was first written (Session 69), and `if found
            # and not candidate.IsNull()` discarded that correct
            # result every time because `found` was never a real
            # boolean to begin with -- silently falling through to
            # the fragile positional heuristic on EVERY call, not
            # just this one. candidate.IsNull() is the only signal
            # that actually reflects whether the lookup worked.
            if not candidate.IsNull():
                label = candidate
            else:
                print(f"[replace_shape] TDF_Tool.Label_s genuinely "
                     f"found nothing for ref_entry={ref_entry!r} -- "
                     f"falling back to the positional heuristic.")
        except Exception as le:
            print(f"[replace_shape] TDF_Tool.Label_s lookup failed "
                 f"({le}); falling back to the positional heuristic")
        if label is None:
            # Fallback: the old heuristic, kept so the confirmed-
            # working STEP-import case can never regress even if the
            # new path hits something unexpected.
            n = int(ref_entry.split(':')[-1])
            labels = TDF_LabelSequence()
            shape_tool.GetShapes(labels)
            print(f"[replace_shape] fallback: ref_entry={ref_entry!r} "
                 f"-> n={n}, but shape_tool.GetShapes() returned only "
                 f"{labels.Length()} label(s) total.")
            label = labels.Value(n)
        if self.part_dict[uid]['loc']:
            modshape.Move(self.part_dict[uid]['loc'].Inverted())
        shape_tool.SetShape(label, modshape)
        color_tool.SetColor(modshape, color, XCAFDoc_ColorGen)
        shape_tool.UpdateAssemblies()
        # Session 78, Doug: undoing a fillet left the fillet visibly
        # in place -- exactly the accepted-risk boundary named when
        # _incremental_reconcile's fast undo/redo path (Session 77)
        # was built: a shape-REPLACING operation on a surviving uid
        # whose LOCATION doesn't change (fillet/shell always keep
        # the part sitting where it was) is invisible to a location-
        # only comparison. Recording the STABLE entry (not uid --
        # uids are a per-parse serial, unstable across the parse_doc()
        # a few lines below) lets a later undo/redo force-redraw
        # whatever THIS SPECIFIC prototype resolves to at that time,
        # regardless of whether its location also happened to change.
        if not hasattr(self, '_shape_replaced_entries'):
            self._shape_replaced_entries = []
        self._shape_replaced_entries.append(ref_entry)
        self.parse_doc()

    def add_component(self, shape, name, color):
        """Add new part as a component directly under '/' (the top assembly).

        '/' is the first free shape (GetFreeShapes label 1), which is the
        top-level assembly. Adding as a component gives the part a proper
        ref_entry, making fillet/shell/modify operations work correctly.
        """
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())

        # Get the '/' root assembly label (first free shape)
        # If none exists (empty session), create one
        free_labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free_labels)
        if free_labels.Length() == 0:
            # Create a root '/' assembly
            from OCP.TopoDS import TopoDS_Compound
            from OCP.BRep import BRep_Builder
            root_shape = TopoDS_Compound()
            BRep_Builder().MakeCompound(root_shape)
            root_label = shape_tool.AddShape(root_shape, True)
            set_label_name(root_label, "/")
            # Session 86, Doug: 'This label has already such an
            # attribute' on Redo, isolated by Doug's own minimal
            # test (wp, sketch, one extrude, undo, redo -- nothing
            # else) to the FIRST-EVER add_component call in a fresh
            # session -- the one that both creates the root '/' AND
            # immediately adds the first component to it, in ONE
            # transaction. AddShape (just above) and AddComponent
            # (just below) both touch root_label's own shape
            # attribute within that single transaction -- a
            # reasoned, though not live-verified, candidate for
            # OCAF's shape-attribute redo mechanism not cleanly
            # replaying a double-touch of the same attribute within
            # one command. Closing this transaction here and
            # reopening a fresh one splits root creation from the
            # first component-add, so each touches root_label's
            # shape attribute only once per transaction. This ONLY
            # runs the very first time a session creates its first
            # part ever (root not existing yet) -- every subsequent
            # add_component call is completely unaffected, since
            # free_labels.Length() == 0 is false from then on. Cost:
            # undoing the very first part in a brand-new session now
            # takes 2 clicks instead of 1 -- a minor, honest
            # tradeoff for a hypothesis that needs Doug's own
            # real-world test to confirm, not something verifiable
            # without a live OCP install.
            if self.doc.HasOpenCommand():
                self.doc.CommitCommand()
                self.doc.NewCommand()
            shape_tool.GetFreeShapes(free_labels)
        root_label = free_labels.Value(1)

        # Add as component under '/' root
        component_label = shape_tool.AddComponent(root_label, shape, True)
        entry = get_label_entry(component_label)
        ref_label = TDF_Label()
        if shape_tool.GetReferredShape_s(component_label, ref_label):
            color_tool.SetColor(ref_label, color, XCAFDoc_ColorGen)
            set_label_name(ref_label, name)
        # Occurrence gets the _1 suffix, product gets the base name --
        # NEVER the same string for both (Session 17 rule: identical
        # occurrence/product names make STEPCAFControl_Writer write
        # the NAUO's name field BLANK on export). This was exactly why
        # natively-created parts ('button') displayed namelessly in
        # CAD Assistant and FreeCAD (which show the NAUO name) while
        # Kodacad still showed them (the reader back-fills occurrence
        # names from the product when the NAUO is blank). Session 57.
        # Matches create_new_assembly's convention and as1's own file.
        set_label_name(component_label, f"{name}_1")
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        uid = self.get_uid_from_entry(entry)
        return uid

    def add_component_from_label(self, source_label, name, loc=None):
        """Add an imported STEP label (with its full sub-tree) as a
        component under '/' (the top assembly).

        add_component() only carries a bare TopoDS_Shape into the
        session, which loses any names of nested sub-assemblies/parts
        because raw geometry has no attached XCAF label structure.
        This method instead clones the complete label subtree (shape,
        name, color and every child component) from the source
        document using XCAFDoc_Editor.Extract -- OCCT's dedicated tool
        for cross-document XCAF copies -- so the names of all parts
        inside an imported assembly are preserved in the tree view.

        KNOWN LIMITATION (unresolved as of Session 30): a component
        imported this way survives save/reload correctly if it's a
        LEAF/simple shape, but NOT if it is itself an assembly with
        its own children (confirmed: manual-lathe, a hub assembly, and
        a purpose-built minimal test all show the same symptom -- blank
        NAUO name, identity location -- after a save/reload round
        trip, despite the in-memory document being confirmed correct
        right up to the STEP write).

        Sessions 14, 16-19, 26-29 tried seven different fixes for this
        (SetLocation, two AddComponent overloads, a round-trip added
        then removed, a same-document re-clone, and a full native-
        rebuild-with-recursion of the assembly structure) -- all
        failed identically on a fully isolated, headless re-test
        (minimal_repro.py). The native-rebuild attempt (Session 29)
        additionally introduced a real regression of its own -- it
        rebuilds every assembly-typed child from scratch with no
        de-duplication, so any sharing that existed WITHIN the
        imported STEP file itself (e.g. a sub-assembly reused twice in
        the same import) would be silently lost even where the
        original bug wouldn't have mattered. Reverted in Session 30
        rather than kept as a worse trade for an unfixed bug.

        RESOLVED (Session 52): the limitation above is fixed by
        replacing XCAFDoc_Editor.Extract_s with a memo-guarded NATIVE
        REBUILD of the imported structure (rebuild_imported_structure,
        module level above) -- reading the source document's labels as
        plain data and recreating them via this document's own
        AddShape/AddComponent, the same way FreeCAD's ExportOCAF works
        and the same construction STEPCAFControl_Reader itself
        produces. Validated end-to-end by smoke_test_production_fix.py
        (exact production scenario: shared leaf part, dedicated '/'
        root holding native content, import at identity, reposition
        via RemoveComponent + UpdateAssemblies + AddComponent, STEP
        round trip): name survived, location survived, and sharing
        survived -- both instances of the shared part still
        referencing one product after reload, with all NAUOs correctly
        named in the raw file. The Session 51 test chain established
        WHY: the writer handles natively-built label-based structures
        correctly (including through reposition cycles); Extract_s
        produces structures it cannot generate a proper NAUO for.

        Positioning parts and assemblies native to the session file
        (e.g. everything in as1-oc-214.stp) was always correct,
        INCLUDING shared instances (Session 22) -- imported content
        now lands in the document in exactly that same healthy,
        native form.
        """
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())

        # Get (or create) the '/' root assembly label (first free shape)
        free_labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free_labels)
        if free_labels.Length() == 0:
            root_shape = TopoDS_Compound()
            BRep_Builder().MakeCompound(root_shape)
            root_label = shape_tool.AddShape(root_shape, True)
            set_label_name(root_label, "/")
            # Session 88, Doug: 'This label has already such an
            # attribute' on Redo after Import STEP into an empty
            # session, then Undo, then Redo -- git checkout confirmed
            # this predates Session 86's fix entirely (present on
            # every recent commit checked), the identical pattern in
            # a third place. Same root cause, same fix: AddShape
            # (just above) and AddComponent (just below) both touch
            # root_label's own shape attribute within one transaction.
            # Splitting into two committed transactions so each
            # touches it only once. Only runs the very first time
            # add_component_from_label creates the root at all --
            # every subsequent call (root already existing, including
            # every later item in the same import's own worklist) is
            # completely unaffected.
            if self.doc.HasOpenCommand():
                self.doc.CommitCommand()
                self.doc.NewCommand()
            shape_tool.GetFreeShapes(free_labels)
        root_label = free_labels.Value(1)

        # NATIVE REBUILD (Session 52) -- replaces Extract_s. The
        # rebuilt structure's top label comes back directly; add it
        # under '/' at identity via the label-based AddComponent
        # overload (the construction validated by the Session 51/52
        # test chain). The memo is per-import: sharing WITHIN one
        # imported file is preserved; separate imports of the same
        # file remain independent copies (matching Extract_s's old
        # behavior in that respect).
        from OCP.TopLoc import TopLoc_Location
        memo = {}
        rebuilt_label = rebuild_imported_structure(source_label, shape_tool,
                                                   color_tool, memo)
        component_label = shape_tool.AddComponent(
            root_label, rebuilt_label,
            loc if loc is not None else TopLoc_Location())

        entry = get_label_entry(component_label)
        # Session 17 finding (same guard as set_component_location):
        # when an occurrence's name is IDENTICAL to its referred/
        # product label's name, STEPCAFControl_Writer leaves the
        # NAUO's descriptive-name field blank on export. The rebuilt
        # referred label keeps the source's own name (e.g.
        # 'manual-lathe'), and the requested component name is often
        # the same string -- force the distinguishing suffix every
        # working component in as1-oc-214.stp already follows.
        ref_name = get_label_name(rebuilt_label)
        comp_name = name
        if comp_name == ref_name:
            comp_name = f"{comp_name}_1"
        set_label_name(component_label, comp_name)
        shape_tool.UpdateAssemblies()
        self.parse_doc()

        # Recover the uid parse_doc() actually assigned to this entry.
        # NOTE: get_uid_from_entry() is a *generator* (increments a
        # counter in self._share_dict on every call), used internally
        # by parse_doc()'s own walk -- calling it again here would mint
        # a fresh, never-assigned uid rather than recover the real one
        # (Session 15's finding, applies equally here). Search
        # label_dict for the actual match instead.
        for candidate_uid, candidate_info in self.label_dict.items():
            if candidate_info['entry'] == entry:
                return candidate_uid
        print(f"[add_component_from_label] Warning: could not recover "
              f"uid for entry {entry}")
        return None

    def add_component_to_asy(self, shape, name, color, tag=1):
        """Add new shape to label at root with tag & return uid"""
        labels = TDF_LabelSequence()
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())
        shape_tool.GetShapes(labels)
        try:
            asyLabel = labels.Value(tag)
        except RuntimeError as e:
            print(e)
            return
        new_label = shape_tool.AddComponent(asyLabel, shape, True)
        entry = get_label_entry(new_label)
        ref_label = TDF_Label()
        isRef = shape_tool.GetReferredShape_s(new_label, ref_label)
        if isRef:
            color_tool.SetColor(ref_label, color, XCAFDoc_ColorGen)
        set_label_name(new_label, name)
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        uid = entry + '.0'
        return uid

    def change_label_name(self, uid, name):
        """Change the name of component with uid.

        Session 57: legacy j/k tag arithmetic replaced with
        _find_label_by_entry (crashed on 4-part root entries).

        Session 61 (Doug's rename-to-'can' report): renaming an
        OCCURRENCE alone left the PRODUCT name unchanged -- and CAD
        Assistant/FreeCAD display PRODUCT names (Session 57's
        empirical rule), so the rename never appeared there. Now a
        rename of a part with a referred product names BOTH labels per
        the add_component convention: product = base name (typed name
        stripped of any trailing _N), occurrence = typed name, or
        base_1 when the typed name equals the base -- identical
        occurrence/product names trigger the Session 17 NAUO
        blanking, which is exactly what the suffix guards against.
        Typing 'can' -> product 'can' (shows in CA/FC), tree shows
        'can_1' (consistent with every other tree entry). For shared
        products, sibling occurrences keep their old names (only the
        part's identity -- the product -- and THIS occurrence change).
        Labels without a referred product (root free shapes) keep the
        simple single-label behavior.
        """
        import re
        entry, __ = uid.split('.')
        target_label = self._find_label_by_entry(entry)
        if target_label is None:
            print(f"[change_label_name] Could not find label for {uid}")
            return
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        ref_label = TDF_Label()
        if shape_tool.GetReferredShape_s(target_label, ref_label):
            base = re.sub(r"(_\d+)+$", "", name) or name
            occ_name = name if name != base else f"{base}_1"
            set_label_name(ref_label, base)
            set_label_name(target_label, occ_name)
            print(f"Renamed: product={base!r}, occurrence={occ_name!r} "
                  f"(uid {uid})")
        else:
            set_label_name(target_label, name)
            print(f"Name {name} set for part with uid = {uid}.")
        shape_tool.UpdateAssemblies()
        self.parse_doc()


def set_label_name(label, name):
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))


def get_name_from_uid(doc, uid):
    """Get name of label with uid."""
    entry, __ = uid.split('.')
    entry_parts = entry.split(':')
    if len(entry_parts) == 4:
        j = 1
        k = None
    elif len(entry_parts) == 5:
        j = int(entry_parts[3])
        k = int(entry_parts[4])
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    label = labels.Value(j)
    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(label, comps, False)
    try:
        target_label = comps.Value(k)
        return target_label
    except RuntimeError as e:
        print(f"Index out of range {e}")
        return None


def set_name_from_uid(doc, uid, name):
    """Set name of label with uid."""
    entry, __ = uid.split('.')
    entry_parts = entry.split(':')
    if len(entry_parts) == 4:
        j = 1
        k = None
    elif len(entry_parts) == 5:
        j = int(entry_parts[3])
        k = int(entry_parts[4])
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    label = labels.Value(j)
    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(label, comps, False)
    try:
        target_label = comps.Value(k)
        set_label_name(target_label, name)
    except RuntimeError as e:
        print(f"Index out of range {e}")


def copy_label_within_doc(source_label, target_label):
    """Intra-document copy (within a document)"""
    cp_label = TDF_CopyLabel()
    cp_label.Load(source_label, target_label)
    cp_label.Perform()
    return cp_label.IsDone()


def copy_label(source_label, target_label):
    """Inter-document copy (between 2 documents)"""
    XLinkTool = TDocStd_XLinkTool()
    XLinkTool.Copy(target_label, source_label)


def save_step_doc(doc):
    """Export doc to STEP file."""
    prompt = 'Specify name for saved step file.'
    fname, __ = QFileDialog.getSaveFileName(None, prompt, './',
                                            "STEP files (*.stp *.STP *.step)")
    if not fname:
        print("Save step cancelled.")
        return
    WS = XSControl_WorkSession()
    # Same PCURVE-suppression fix as the method version above --
    # this module-level save_step_doc is a second, separate writer
    # construction site that needs the identical configuration.
    try:
        from OCP.Interface import Interface_Static
        Interface_Static.SetIVal_s("write.surfacecurve.mode", 0)
    except Exception as pe:
        print(f"[save_step_doc] could not disable PCURVE writing "
             f"({pe}) -- file will save with OCCT's default (more "
             f"verbose) geometry representation; harmless, the file "
             f"is still correct, just larger")
    step_writer = STEPCAFControl_Writer(WS, False)
    step_writer.Transfer(doc, STEPControl_AsIs)
    status = step_writer.Write(fname)
    assert status == IFSelect_RetDone


def _load_step():
    """Allow user to select step file to load, return step_file_name, doc, app

    Shows a busy dialog during the (blocking) read+transfer -- big
    STEP files can take many seconds and the app otherwise looks
    frozen (Session 58, TODO item). Honest limitation, documented so
    nobody chases the 'proper' route unaware: TRUE incremental
    progress needs OCCT's Message_ProgressIndicator, which is
    designed to be SUBCLASSED with virtual-method overrides -- and
    OCP's bindings silently ignore Python overrides of C++ virtuals
    (Basicad item 28, the OnSelectionChanged lesson). Threading the
    reader instead would enable an animated indicator but brings
    OCCT/Qt cross-thread risk out of proportion to this feature. So:
    a static modal 'Loading...' dialog, shown and painted BEFORE the
    blocking call -- the user sees what is happening, which is the
    actual point.
    """
    from PySide6.QtWidgets import QProgressDialog, QApplication
    from PySide6.QtCore import Qt
    prompt = 'Select STEP file to import'
    f_path, __ = QFileDialog.getOpenFileName(
        None, prompt, './', "STEP files (*.stp *.STP *.step *.STEP)")
    if not f_path:
        print("Load step cancelled")
        return None, None, None
    base = os.path.basename(f_path)
    step_file_name, ext = os.path.splitext(base)

    busy = QProgressDialog(None)
    busy.setLabelText(f"Loading {base} ...")
    busy.setRange(0, 0)
    busy.setCancelButton(None)  # reader can't be interrupted anyway
    busy.setWindowModality(Qt.WindowModality.ApplicationModal)
    busy.setMinimumDuration(0)
    busy.setWindowTitle("KodaCAD")
    busy.show()
    # One processEvents pass wasn't enough to paint the label before
    # the blocking read (Doug saw a blank dialog, Session 58 cont'd)
    # -- pump a few times and force a repaint.
    for _ in range(5):
        QApplication.processEvents()
    busy.repaint()
    QApplication.processEvents()
    try:
        doc, app = create_doc()
        step_reader = STEPCAFControl_Reader()
        step_reader.SetColorMode(True)
        step_reader.SetLayerMode(True)
        step_reader.SetNameMode(True)
        step_reader.SetMatMode(True)
        status = step_reader.ReadFile(f_path)
        if status == IFSelect_RetDone:
            step_reader.Transfer(doc)
    finally:
        busy.close()
    return step_file_name, doc, app


def repair_unnamed_products(doc, context=""):
    """Find product labels whose name is EMPTY or is the STEP writer's
    placeholder ('Open CASCADE STEP translator X.Y...') and name them
    from their first occurrence's name, stripped of trailing _N auto
    suffixes ('button_1_1' -> 'button').

    Why (Session 57 cont'd, from probe_names.py data on Doug's real
    file): a product label with NO name gets the translator-string
    placeholder stamped by STEPCAFControl_Writer -- and CAD Assistant
    and FreeCAD display PRODUCT names (Doug's empirical confirmation),
    while Kodacad displays occurrence names. So an unnamed product
    shows fine in Kodacad and as 'Open CASCADE STEP translator 7.9'
    in every other viewer. All three current creation/modification
    paths (add_component, reparent_component, replace_shape) verify
    as naming products correctly -- the leak that orphaned button's
    product is likely in a since-replaced code state -- so rather
    than archaeology, this repairs at two chokepoints: on session
    LOAD (fixes existing files) and before SAVE (a tripwire -- if it
    ever fires on in-session content, its printout identifies a live
    leak path by footprint).

    Returns the number of products repaired.
    """
    import re
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_LabelSequence
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    # Session 79, Doug: a hard crash (Standard_NullObject, killing the
    # whole process -- not a catchable Python exception) on reloading
    # a STEP file whose only content is a BARE PART saved directly as
    # the file's own root (save_step_doc's '/' unwrap, when there's
    # no assembly at all to unwrap around -- 'exporting Bottle as the
    # file root'). Traced to right here: GetUsers_s(label, ...) was
    # being called on EVERY unnamed-looking label, including free/
    # root shapes, with 'is this actually a free shape' checked only
    # AFTER that call, via its returned count. A free root shape with
    # no assembly ever wrapping it is exactly the case that call may
    # not handle. Fixed by checking free-shape membership FIRST, via
    # GetFreeShapes (already proven correct elsewhere in this exact
    # file, not a new/unverified call) -- a free shape's label never
    # reaches GetUsers_s at all now.
    free_labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_labels)
    free_entries = {get_label_entry(free_labels.Value(i))
                    for i in range(1, free_labels.Length() + 1)}
    repaired = 0
    for i in range(1, labels.Length() + 1):
        label = labels.Value(i)
        if shape_tool.IsReference_s(label):
            continue  # occurrences keep their own names
        if get_label_entry(label) in free_entries:
            continue  # free root shapes are named elsewhere; skip
            # (was previously detected AFTER calling GetUsers_s below,
            # via n_users < 1 -- moved earlier, before that call, since
            # a free shape with no assembly ever wrapping it at all is
            # exactly the case suspected of not handling GetUsers_s
            # safely; see this function's own docstring update above)
        name = get_label_name(label)
        if name and not name.startswith("Open CASCADE STEP translator"):
            continue
        users = TDF_LabelSequence()
        n_users = shape_tool.GetUsers_s(label, users, False)
        if n_users < 1:
            continue
        occ_name = get_label_name(users.Value(1))
        base = re.sub(r"(_\d+)+$", "", occ_name)
        if base and base != name:
            set_label_name(label, base)
            print(f"[repair_unnamed_products{context}] product "
                  f"{get_label_entry(label)} {name!r} -> {base!r}")
            repaired += 1
    return repaired


def load_stp_at_top(dm):
    """Get OCAF document from STEP file and assign it directly to dm.doc."""
    print("[load_stp_at_top] calling _load_step...")
    f_name, doc, app = _load_step()
    if doc is None:
        return
    print("[load_stp_at_top] assigning doc...")
    # CONFIRMED (Session 81, via Doug's own reproducible testing --
    # a crash that was 100% reproducible on the first reload attempt
    # every time survived six consecutive reloads across two separate
    # process launches with this fix in place): replacing dm.doc
    # drops the OLD document's reference count to zero, and CPython
    # destroys objects immediately (not deferred) the moment that
    # happens -- invoking the old TDocStd_Document's C++ destructor
    # synchronously, right at the reassignment line. That destructor
    # was throwing Standard_NullObject. Rather than fix (or fully
    # understand) whatever's failing inside the destructor itself --
    # not possible without live OCP access this sandbox doesn't have,
    # and possibly a genuine OCCT/OCP-binding-level issue beyond
    # application-code reach regardless -- every replaced document is
    # kept alive for the life of the process instead of ever reaching
    # a zero refcount. Known, accepted tradeoff: dm._retired_docs
    # grows by one entry per reload, for the life of the session --
    # a small, bounded memory cost (one reload is an explicit user
    # action, not a per-frame or per-operation event) traded
    # deliberately for not crashing.
    if hasattr(dm, 'doc') and dm.doc is not None:
        if not hasattr(dm, '_retired_docs'):
            dm._retired_docs = []
        dm._retired_docs.append(dm.doc)
    dm.doc = doc
    dm.app = app
    # Session load replaces the doc object: re-enable undo history on
    # the fresh doc (history clearing on load is correct semantics).
    dm.doc.SetUndoLimit(UNDO_LIMIT)
    repair_unnamed_products(doc, context=" load")
    print("[load_stp_at_top] calling parse_doc...")
    dm.parse_doc()
    print("[load_stp_at_top] done")


def load_stp_cmpnt(dm):
    """Import a STEP file and add it as a component under '/' root.

    Works for both simple shapes and assemblies. The imported shape
    appears under '/' in the tree, ready to be positioned and dragged
    into a sub-assembly.

    '/'-WRAPPER UNWRAP (Session 56, Basicad item 30 ported): when the
    imported file's root is named '/' -- i.e. the file is a saved
    Kodacad SESSION, whose root wrapper the writer preserved -- the
    wrapper is NOT imported. Its children are imported directly, each
    at its saved location (composed through any nested wrapper
    levels, so legacy multi-wrapped files from before this fix unwrap
    completely in one import). This was the accumulation mechanism
    behind the '//// as1_1' paths: importing a saved session nested
    its '/' under the current '/', one extra level per save+import
    cycle. The tree screenshot showing nested '/' items in the LIVE
    document was the giveaway that the nesting was created in-app
    (save/load are structure-preserving) -- and import is the only
    operation that nests a whole tree under the root.
    """
    from OCP.TopLoc import TopLoc_Location
    f_name, doc, app = _load_step()
    if doc is None:
        return
    step_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    step_shape_tool.GetFreeShapes(labels)

    # Worklist of (label, name, composed_loc) to import. Free shapes
    # named '/' get expanded into their children instead of imported.
    worklist = []
    for j in range(labels.Length()):
        label = labels.Value(j + 1)
        name = get_label_name(label) or f_name or "import"
        worklist.append((label, name, None))

    while worklist:
        label, name, loc = worklist.pop(0)
        if (get_label_name(label) == '/'
                and step_shape_tool.IsAssembly_s(label)):
            children = TDF_LabelSequence()
            step_shape_tool.GetComponents_s(label, children, False)
            print(f"[load_stp_cmpnt] unwrapping '/' session wrapper -- "
                  f"importing its {children.Length()} child(ren) directly")
            for i in range(1, children.Length() + 1):
                comp = children.Value(i)
                ref = TDF_Label()
                if not step_shape_tool.GetReferredShape_s(comp, ref):
                    continue
                comp_loc = step_shape_tool.GetShape_s(comp).Location()
                if loc is not None:
                    comp_loc = loc.Multiplied(comp_loc)
                child_name = (get_label_name(comp)
                              or get_label_name(ref) or "import")
                worklist.append((ref, child_name, comp_loc))
            continue
        # Use add_component_from_label (not add_component) so the
        # names of any nested sub-assemblies/parts inside the
        # imported STEP file are preserved rather than lost.
        dm.add_component_from_label(label, name, loc)


def load_stp_undr_top(dm):
    """Add step file as a component under Top (root) label of dm.doc

    UNUSED (no callers as of Session 52) and NOT UPDATED for the
    Session 52 fix: this still uses XCAFDoc_Editor.Extract_s, which
    produces structures the STEP writer cannot generate proper NAUOs
    for (blank name / identity location on save-reload -- the bug
    fixed in add_component_from_label). If this function is ever
    wired back in, port it to rebuild_imported_structure() first,
    the same way add_component_from_label was.
    """
    from OCP.XCAFDoc import XCAFDoc_Editor
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())

    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)
    set_label_name(root_label, "Top")

    step_file_name, step_doc, step_app = _load_step()
    if step_doc is None:
        return
    step_labels = TDF_LabelSequence()
    step_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(step_doc.Main())
    step_shape_tool.GetShapes(step_labels)
    step_root_label = step_labels.Value(1)

    ok = XCAFDoc_Editor.Extract_s(step_root_label, root_label)
    if not ok:
        print("[load_stp_undr_top] XCAFDoc_Editor.Extract failed")
        return
    component_label = get_last_component(shape_tool, root_label)
    set_label_name(component_label, step_file_name)

    shape_tool.UpdateAssemblies()
    dm.parse_doc()
