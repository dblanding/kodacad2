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

        # Find the referred shape (root geometry) for the part being moved
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

        ref_shape = shape_tool.GetShape_s(ref_label)

        # Find target assembly's ROOT label (ref_entry) so both shared
        # instances of the target assembly receive the new component
        new_parent_info = self.label_dict[new_parent_uid]
        target_entry = new_parent_info.get('ref_entry') or new_parent_info['entry']
        target_label = self._find_label_by_entry(target_entry)
        if target_label is None:
            print(f"[reparent] Could not find target label")
            return

        # Add component to target with correct local transform
        located_shape = ref_shape.Located(new_local)
        new_comp = shape_tool.AddComponent(target_label, located_shape, True)
        part_name = self.label_dict[uid]['name']
        set_label_name(new_comp, part_name)
        # Also name the referred shape so it shows correctly in all viewers
        new_ref = TDF_Label()
        if shape_tool.GetReferredShape_s(new_comp, new_ref):
            set_label_name(new_ref, part_name)

        # Set color on the new component's referred shape
        if part_color:
            from OCP.XCAFDoc import XCAFDoc_ColorGen
            color_tool.SetColor(ref_shape, part_color, XCAFDoc_ColorGen)
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

        (Earlier versions of this codebase used TDocStd_XLinkTool.Copy
        followed by a STEP export/import round-trip (doc_linter) to
        work around known XLinkTool inconsistencies in shape-managing
        documents -- see docs/DEVELOPMENT_LOG.md, Session 10. Using
        XCAFDoc_Editor.Extract directly avoids the round-trip.)
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
        entry = get_label_entry(component_label)
        set_label_name(component_label, name)
        shape_tool.UpdateAssemblies()
        self.parse_doc()
        uid = self.get_uid_from_entry(entry)
        return uid

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
