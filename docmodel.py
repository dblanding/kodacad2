#!/usr/bin/env python
#
# Copyright 2022 Doug Blanding (dblanding@gmail.com)
# Ported to OCP/PySide6 2026
#
# This file is part of kodacad2.
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
                    color = Quantity_Color()
                    color_tool.GetColor(ref_shape, XCAFDoc_ColorSurf, color)
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
            else:
                print(f"Oops! Component is not a reference: {c_uid}")
        self.assy_entry_stack.pop()
        self.assy_loc_stack.pop()
        self.parent_uid_stack.pop()


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

        # Get the part's world location and color
        part_world_loc = self.part_dict.get(uid, {}).get('loc', TopLoc_Location())
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
        # just confirmed, Session 16, to lose names/substructure on
        # compounds/assemblies since raw geometry carries none of that
        # XCAF metadata). This function hadn't been reported broken,
        # but it had the identical pattern -- fixed proactively rather
        # than leaving a known-bad pattern for it to be rediscovered
        # independently. Please re-test drag/reparenting an assembly
        # (not just a leaf part) with save/reload before trusting this.
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
        same part/assembly elsewhere in the tree are unaffected). A
        free root shape (no parent) is removed with RemoveShape.
        Mirrors the removal step already used in reparent_component().
        """
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
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
            shape_tool.RemoveComponent(comp_label)
        else:
            shape_tool.RemoveShape(comp_label, True)
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

        # UNSHARE if needed (Session 22). Confirmed via direct STEP
        # file inspection: repositioning ONE instance of a shape that's
        # shared by multiple occurrences (e.g. l-bracket-assembly_1 and
        # _2, both referencing the same product definition -- confirmed
        # by their NAUOs pointing at the same child entity) corrupts on
        # export: the moved instance comes back with a blank name and
        # identity location, while its untouched sibling round-trips
        # fine. This matches a documented OCCT writer limitation with
        # "partner shapes" (multiple occurrences of one shape) at
        # different locations. Rather than fight the writer, give the
        # instance being repositioned an independent, unshared copy of
        # its geometry first -- the same principle as "make unique" /
        # "break the link" in mainstream CAD tools. This is a
        # deliberate behavior change, confirmed acceptable with Doug:
        # once repositioned, this instance no longer shares edits with
        # any sibling that stays linked to the original.
        from OCP.TDF import TDF_Label, TDF_LabelSequence
        from OCP.XCAFDoc import XCAFDoc_Editor
        users = TDF_LabelSequence()
        n_users = shape_tool.GetUsers_s(ref_label, users, False)
        if n_users > 1:
            print(f"[set_component_location] {info['name']!r} is shared "
                  f"({n_users} users) -- unsharing before repositioning")
            free_labels_for_unshare = TDF_LabelSequence()
            shape_tool.GetFreeShapes(free_labels_for_unshare)
            unshare_root = (free_labels_for_unshare.Value(1)
                            if free_labels_for_unshare.Length() > 0 else None)
            if unshare_root is None:
                print("[set_component_location] Warning: no '/' found "
                      "for unsharing -- proceeding with shared reference")
            elif not XCAFDoc_Editor.Extract_s(ref_label, unshare_root):
                print("[set_component_location] Warning: unshare clone "
                      "failed -- proceeding with shared reference")
            else:
                temp_comp = get_last_component(shape_tool, unshare_root)
                cloned_ref_label = TDF_Label()
                if (shape_tool.GetReferredShape_s(temp_comp, cloned_ref_label)
                        and not cloned_ref_label.IsNull()):
                    shape_tool.RemoveComponent(temp_comp)
                    ref_label = cloned_ref_label
                    print("[set_component_location] unshared -- using "
                          "independent clone")
                else:
                    print("[set_component_location] Warning: could not "
                          "resolve clone's referred label -- proceeding "
                          "with shared reference")

        # Parent assembly label (component's CURRENT parent -- we are
        # repositioning in place, not reparenting).
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
        for candidate_uid, candidate_info in self.label_dict.items():
            if candidate_info['entry'] == new_entry:
                post_name = candidate_info.get('name')
                post_loc = (self.label_dict[candidate_uid].get('world_loc')
                            if candidate_info.get('is_assy')
                            else self.part_dict.get(candidate_uid, {}).get('loc'))
                pt = post_loc.Transformation().TranslationPart() if post_loc else None
                print(f"[set_component_location #{call_n}] AFTER parse_doc: "
                      f"uid={candidate_uid} name={post_name!r} "
                      f"world_loc="
                      f"{(round(pt.X(),3), round(pt.Y(),3), round(pt.Z(),3)) if pt else None}")
                return candidate_uid
        print(f"[set_component_location] Warning: could not recover uid "
              f"for entry {new_entry} after parse_doc()")
        return None

    def get_full_path_name(self, uid):
        """Full breadcrumb path from '/' down to uid, e.g.
        '/ / as1 / manual-lathe'.

        Kodacad's XCAF model allows the same part/assembly DEFINITION
        to appear as multiple distinct instances in different places
        in the tree (see Session 13's shared-instance discussion) --
        a bare name alone doesn't disambiguate which instance is
        meant. Used by PositionDialog's top section so there's no
        ambiguity about which instance is about to be moved.
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
        names.append('/')
        return ' / '.join(reversed(names))

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

        WS = XSControl_WorkSession()
        step_writer = STEPCAFControl_Writer(WS, False)
        step_writer.Transfer(self.doc, STEPControl_AsIs)
        status = step_writer.Write(fname)
        assert status == IFSelect_RetDone

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
        n = int(self.label_dict[uid]['ref_entry'].split(':')[-1])
        color = self.part_dict[uid]['color']
        labels = TDF_LabelSequence()
        shape_tool.GetShapes(labels)
        label = labels.Value(n)
        if self.part_dict[uid]['loc']:
            modshape.Move(self.part_dict[uid]['loc'].Inverted())
        shape_tool.SetShape(label, modshape)
        color_tool.SetColor(modshape, color, XCAFDoc_ColorGen)
        shape_tool.UpdateAssemblies()
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
            shape_tool.GetFreeShapes(free_labels)
        root_label = free_labels.Value(1)

        # Add as component under '/' root
        component_label = shape_tool.AddComponent(root_label, shape, True)
        entry = get_label_entry(component_label)
        set_label_name(component_label, name)
        ref_label = TDF_Label()
        if shape_tool.GetReferredShape_s(component_label, ref_label):
            color_tool.SetColor(ref_label, color, XCAFDoc_ColorGen)
            set_label_name(ref_label, name)
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        uid = self.get_uid_from_entry(entry)
        return uid

    def add_component_from_label(self, source_label, name):
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

        NORMALIZATION (Session 19): after extensive testing across
        Sessions 14-18, confirmed that a component built via Extract_s
        here is perfectly correct in isolation (displays fine, names
        read back fine, even survives its OWN independent save/reload
        untouched) -- but corrupts (blank NAUO name, identity location
        in the written STEP file) the NEXT time it's referenced by a
        fresh AddComponent call, e.g. via Position's
        set_component_location(). Components built entirely by
        STEPCAFControl_Reader (never imported via this method) never
        show this problem -- repositioning one always round-trips
        correctly. So: round-trip the WHOLE document through a temp
        STEP file RIGHT HERE, immediately after Extract_s, before the
        user ever gets a chance to reposition the freshly-imported
        component. This normalizes the Extract_s-built structure into
        Reader-native form before anything else ever references it.
        (Round-tripping at SAVE time instead -- tried in Session 18 --
        does NOT work: the corruption is already present by the time
        of the FIRST write, so it has to happen before any AddComponent
        call ever references the Extract_s-built label, not after.)
        """
        from OCP.XCAFDoc import XCAFDoc_Editor
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())

        # Get (or create) the '/' root assembly label (first free shape)
        free_labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free_labels)
        if free_labels.Length() == 0:
            root_shape = TopoDS_Compound()
            BRep_Builder().MakeCompound(root_shape)
            root_label = shape_tool.AddShape(root_shape, True)
            set_label_name(root_label, "/")
            shape_tool.GetFreeShapes(free_labels)
        root_label = free_labels.Value(1)

        # Extract_s returns True/False (success), NOT the new label --
        # it adds the copied content as the newest component of
        # root_label, so retrieve it via get_last_component().
        ok = XCAFDoc_Editor.Extract_s(source_label, root_label)
        if not ok:
            print("[add_component_from_label] XCAFDoc_Editor.Extract failed")
            return None
        component_label = get_last_component(shape_tool, root_label)
        set_label_name(component_label, name)
        shape_tool.UpdateAssemblies()

        # Round-trip to normalize (see docstring above for why).
        try:
            import tempfile
            tmp_fname = tempfile.mktemp(suffix='.stp')
            tmp_WS = XSControl_WorkSession()
            tmp_writer = STEPCAFControl_Writer(tmp_WS, False)
            tmp_writer.Transfer(self.doc, STEPControl_AsIs)
            tmp_status = tmp_writer.Write(tmp_fname)
            if tmp_status == IFSelect_RetDone:
                fresh_doc, fresh_app = create_doc()
                reader = STEPCAFControl_Reader()
                reader.SetColorMode(True)
                reader.SetLayerMode(True)
                reader.SetNameMode(True)
                reader.SetMatMode(True)
                r_status = reader.ReadFile(tmp_fname)
                if r_status == IFSelect_RetDone:
                    reader.Transfer(fresh_doc)
                    self.doc = fresh_doc
                    print("[add_component_from_label] normalized via "
                          "round-trip")
                else:
                    print("[add_component_from_label] normalize: reader "
                          "failed, keeping un-normalized doc")
            else:
                print("[add_component_from_label] normalize: temp write "
                      "failed, keeping un-normalized doc")
            os.remove(tmp_fname)
        except Exception as e:
            print(f"[add_component_from_label] normalize round-trip "
                  f"errored ({e}) -- keeping un-normalized doc")

        self.parse_doc()

        # Recover the freshly-imported component's uid. The round-trip
        # may have renumbered entries throughout the WHOLE document
        # (Read() reassigns tags from scratch), so re-find root_label
        # fresh in the (possibly new) self.doc and take its newest
        # component, rather than trusting any label/entry captured
        # before the round-trip.
        new_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        new_free_labels = TDF_LabelSequence()
        new_shape_tool.GetFreeShapes(new_free_labels)
        if new_free_labels.Length() == 0:
            print("[add_component_from_label] Warning: no free shapes "
                  "after normalize")
            return None
        new_root_label = new_free_labels.Value(1)
        new_component_label = get_last_component(new_shape_tool, new_root_label)
        new_entry = get_label_entry(new_component_label)
        found_name = get_label_name(new_component_label)
        if found_name != name:
            print(f"[add_component_from_label] Warning: post-normalize "
                  f"name mismatch (expected {name!r}, got {found_name!r})")
        for candidate_uid, candidate_info in self.label_dict.items():
            if candidate_info['entry'] == new_entry:
                return candidate_uid
        print(f"[add_component_from_label] Warning: could not recover "
              f"uid for entry {new_entry}")
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
        """Change the name of component with uid."""
        entry, __ = uid.split('.')
        entry_parts = entry.split(':')
        if len(entry_parts) == 4:
            j = 1
            k = None
        elif len(entry_parts) == 5:
            j = int(entry_parts[3])
            k = int(entry_parts[4])
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        labels = TDF_LabelSequence()
        shape_tool.GetShapes(labels)
        label = labels.Value(j)
        comps = TDF_LabelSequence()
        subchilds = False
        shape_tool.GetComponents_s(label, comps, subchilds)
        target_label = comps.Value(k)
        set_label_name(target_label, name)
        shape_tool.UpdateAssemblies()
        print(f"Name {name} set for part with uid = {uid}.")
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
    step_writer = STEPCAFControl_Writer(WS, False)
    step_writer.Transfer(doc, STEPControl_AsIs)
    status = step_writer.Write(fname)
    assert status == IFSelect_RetDone


def _load_step():
    """Allow user to select step file to load, return step_file_name, doc, app"""
    prompt = 'Select STEP file to import'
    f_path, __ = QFileDialog.getOpenFileName(
        None, prompt, './', "STEP files (*.stp *.STP *.step)")
    if not f_path:
        print("Load step cancelled")
        return None, None, None
    base = os.path.basename(f_path)
    step_file_name, ext = os.path.splitext(base)
    doc, app = create_doc()
    step_reader = STEPCAFControl_Reader()
    step_reader.SetColorMode(True)
    step_reader.SetLayerMode(True)
    step_reader.SetNameMode(True)
    step_reader.SetMatMode(True)
    status = step_reader.ReadFile(f_path)
    if status == IFSelect_RetDone:
        step_reader.Transfer(doc)
    return step_file_name, doc, app


def load_stp_at_top(dm):
    """Get OCAF document from STEP file and assign it directly to dm.doc."""
    print("[load_stp_at_top] calling _load_step...")
    f_name, doc, app = _load_step()
    if doc is None:
        return
    print("[load_stp_at_top] assigning doc...")
    dm.doc = doc
    dm.app = app
    print("[load_stp_at_top] calling parse_doc...")
    dm.parse_doc()
    print("[load_stp_at_top] done")


def load_stp_cmpnt(dm):
    """Import a STEP file and add it as a component under '/' root.

    Works for both simple shapes and assemblies. The imported shape
    appears under '/' in the tree, ready to be positioned and dragged
    into a sub-assembly.
    """
    f_name, doc, app = _load_step()
    if doc is None:
        return
    step_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    step_shape_tool.GetFreeShapes(labels)
    for j in range(labels.Length()):
        label = labels.Value(j+1)
        name = get_label_name(label) or f_name or "import"
        # Use add_component_from_label (not add_component) so the
        # names of any nested sub-assemblies/parts inside the
        # imported STEP file are preserved rather than lost.
        dm.add_component_from_label(label, name)


def load_stp_undr_top(dm):
    """Add step file as a component under Top (root) label of dm.doc"""
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
