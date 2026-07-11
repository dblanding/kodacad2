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
    
    Uses XCAFDoc_Location.GetLoc_s() static method which is safer than
    FindAttribute in OCP.
    """
    from OCP.XCAFDoc import XCAFDoc_Location
    from OCP.TopLoc import TopLoc_Location
    try:
        return XCAFDoc_Location.GetLoc_s(label)
    except Exception:
        return TopLoc_Location()


def get_label_entry(label):
    """Get the entry string of a TDF_Label (replaces PythonOCC's EntryDumpToString())."""
    from OCP.TDF import TDF_Tool
    from OCP.TCollection import TCollection_AsciiString
    entry = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry)
    return entry.ToCString()


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
        else:
            print("Something went wrong while parsing document.")

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
                    self.label_dict[c_uid].update({'inv_loc': inv_loc})
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
        shape_tool.SetShape_s(label, modshape)
        color_tool.SetColor(modshape, color, XCAFDoc_ColorGen)
        shape_tool.UpdateAssemblies()
        self.parse_doc()

    def add_component(self, shape, name, color):
        """Add new shape to top assembly of self.doc & return uid"""
        labels = TDF_LabelSequence()
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(self.doc.Main())
        shape_tool.GetShapes(labels)
        try:
            root_label = labels.Value(1)
        except RuntimeError as e:
            print(e)
            return
        component_label = shape_tool.AddComponent_s(root_label, shape, True)
        entry = get_label_entry(component_label)
        ref_label = TDF_Label()
        isRef = shape_tool.GetReferredShape_s(component_label, ref_label)
        if isRef:
            color_tool.SetColor(ref_label, color, XCAFDoc_ColorGen)
        set_label_name(component_label, name)
        shape_tool.UpdateAssemblies()
        self.doc = doc_linter(self.doc)
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
        new_label = shape_tool.AddComponent_s(asyLabel, shape, True)
        entry = get_label_entry(new_label)
        ref_label = TDF_Label()
        isRef = shape_tool.GetReferredShape_s(new_label, ref_label)
        if isRef:
            color_tool.SetColor(ref_label, color, XCAFDoc_ColorGen)
        set_label_name(new_label, name)
        shape_tool.UpdateAssemblies()
        self.doc = doc_linter(self.doc)
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


def doc_linter(doc):
    """Clean doc by cycling through a STEP save/load cycle."""
    fname = "deleteme.step"
    WS = XSControl_WorkSession()
    step_writer = STEPCAFControl_Writer(WS, False)
    step_writer.Transfer(doc, STEPControl_AsIs)
    status = step_writer.Write(fname)
    assert status == IFSelect_RetDone

    temp_doc, app = create_doc()
    step_reader = STEPCAFControl_Reader()
    step_reader.SetColorMode(True)
    step_reader.SetLayerMode(True)
    step_reader.SetNameMode(True)
    step_reader.SetMatMode(True)
    status = step_reader.ReadFile(fname)
    if status == IFSelect_RetDone:
        step_reader.Transfer(temp_doc)
        os.remove(fname)
    return temp_doc


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
    """Get OCAF document from STEP file and add (as component) to doc root."""
    f_name, doc, app = _load_step()
    if doc is None:
        return
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    for j in range(labels.Length()):
        label = labels.Value(j+1)
        shape = shape_tool.GetShape_s(label)
        color = Quantity_Color()
        name = label
        color_tool.GetColor(shape, XCAFDoc_ColorSurf, color)
        if shape_tool.IsSimpleShape_s(label):
            dm.add_component(shape, name, color)


def load_stp_undr_top(dm):
    """Add step file as a component under Top (root) label of dm.doc"""
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())

    target_shape = TopoDS_Compound()
    t_builder = BRep_Builder()
    t_builder.MakeCompound(target_shape)
    target_proto = Prototype(target_shape, shape_tool.AddShape_s(target_shape, True))

    root_shape = TopoDS_Compound()
    r_builder = BRep_Builder()
    r_builder.MakeCompound(root_shape)
    r_builder.Add(root_shape, target_proto.shape)
    root_proto = Prototype(root_shape, shape_tool.AddShape_s(root_shape, True))
    TDataStd_Name.Set_s(root_proto.label, TCollection_ExtendedString("Top"))

    step_file_name, step_doc, step_app = _load_step()
    if step_doc is None:
        return
    step_labels = TDF_LabelSequence()
    step_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(step_doc.Main())
    step_shape_tool.GetShapes(step_labels)
    step_root_label = step_labels.Value(1)

    copy_label(step_root_label, target_proto.label)

    itr = TDF_ChildIterator(root_proto.label, False)
    while itr.More():
        component_label = itr.Value()
        TDataStd_Name.Set_s(component_label,
                            TCollection_ExtendedString(step_file_name))
        itr.Next()
    shape_tool.UpdateAssemblies()
    dm.doc = doc_linter(dm.doc)
    dm.parse_doc()
