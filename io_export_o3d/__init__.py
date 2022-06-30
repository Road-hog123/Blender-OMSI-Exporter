"""OMSI Mesh Exporter for Blender

Modules:
This file: Registers a Blender Import-Export Operator for OMSI Meshes.
`exporter`: Convert Blender Objects to OMSI Mesh files and write them.
`node_shader`: Convert Blender Materials to OMSI Mesh Materials.
`meshio`: Store and Encode OMSI Mesh Files to binary.


Copyright 2022 Nathan Burnham

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

# <pep8-80 compliant>

import re
from pathlib import Path
from bpy.types import (
    Operator,
    Panel,
    AddonPreferences,
    Context,
    Event,
    TOPBAR_MT_file_export,
)
from bpy.utils import register_class, unregister_class
from bpy.props import BoolProperty, EnumProperty, StringProperty
from .exporter import Exporter
from .meshio import LongIndexesNotSupportedError


bl_info = {
    "name": "O3D Exporter",
    "description": "Export selected object(s) to an OMSI Mesh file",
    "author": "Nathan Burnham (Road-hog123)",
    "version": (3, 0, 2),
    "blender": (3, 0, 0),
    "location": "File > Export > OMSI Mesh (.o3d)",
    "warning": "",
    "doc_url": "https://github.com/Road-hog123/blender-omsi-exporter",
    "tracker_url": (
        "https://github.com/Road-hog123/blender-omsi-exporter/issues"
    ),
    "support": 'COMMUNITY',
    "category": 'Import-Export',
}


class ExportO3D(Operator):
    """Export selection to OMSI Mesh file (.o3d)"""
    bl_idname = "export_scene.o3d"
    bl_label = "Export O3D"
    bl_options = {'PRESET'}

    filename_ext = ".o3d"
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.o3d", options={'HIDDEN'})
    check_existing: BoolProperty(default=True, options={'HIDDEN'})
    compatibility: BoolProperty(
        name="SDK Compatibility",
        description="Maintain compatibility with OMSI 1",
        default=False,
    )
    transforms: EnumProperty(
        name="Apply Transforms",
        description="Which transforms affect the export result",
        items=(
            ('LOC', "Location", ""),
            ('ROT', "Rotation", ""),
            ('SCA', "Scale", ""),
        ),
        default={'LOC', 'ROT', 'SCA'},
        options={'ENUM_FLAG'},
    )
    origin: BoolProperty(
        name="Animation Origin",
        description="Include the transformation matrix for origin_from_mesh",
        default=True,
    )
    merge_within: BoolProperty(
        name="Merge Materials Within Objects",
        description="Merges duplicate material slots within objects",
        default=True,
    )
    merge_between: BoolProperty(
        name="Merge Materials Between Objects",
        description="Merges duplicate material slots between objects",
        default=True,
    )
    uv_layer: EnumProperty(
        name="UV Layer",
        description="Whether the selected or active for render UV map is used",
        items=(
            ('active', "Selected", "", 'RESTRICT_SELECT_OFF', 0),
            ('active_render', "Render", "", 'RESTRICT_RENDER_OFF', 1)
        ),
        default='active_render',
    )
    weights: BoolProperty(
        name="Skin Weights",
        description="Include vertex weights for smoothskin mesh deformation",
        default=False,
    )
    material_output_node_target: EnumProperty(
        name="Material Output Node Render Target",
        description="Only use material outputs that target this render engine",
        items=(
            ('ALL', "All", ""),
            ('EEVEE', "Eevee", ""),
            ('CYCLES', "Cycles", ""),
        ),
        default='ALL',
    )
    material_output_node_name: StringProperty(
        name="Material Output Node Name",
        description="The name of the material output node to be exported",
        default="Export",
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        if not Exporter.filter_objects(context.selected_objects):
            cls.poll_message_set(
                "Selection does not contain any exportable objects"
            )
            return False
        return True

    def invoke(self, context: Context, _: Event) -> set[str]:
        if self.filepath:
            # use previous export path if this is not the first export
            path = Path(self.filepath)
        elif context.blend_data.filepath:
            # use blend file path if this is the first export
            path = Path(context.blend_data.filepath)
        else:
            # blend file is untitled if it hasn't been saved
            path = Path("untitled.blend")
        # ensure suffix
        path = path.with_suffix(self.filename_ext)

        if context.preferences.addons[__package__].preferences.use_object_name:
            stem: str = context.active_object.name
            # object names are unrestricted UTF-8 strings, which are
            # unsafe for use as a filename - invalid characters are
            # removed and leading/trailing spaces/periods are stripped
            stem = re.sub(r"[\0-\x1F<>:\"\\/|?*]", "", stem).strip(". ")
            # if nothing remains, a placeholder is used instead
            if not stem:
                stem = "mesh"
            # change stem
            path = path.with_stem(stem)

        # set filepath
        self.filepath = str(path)
        # show the file selector
        context.window_manager.fileselect_add(self)
        # prevent the operator terminating while in the file selector
        return {'RUNNING_MODAL'}

    def draw(self, _: Context) -> None:
        pass

    def execute(self, context: Context) -> set[str]:
        # create an Exporter instance with our desired properties
        exporter = Exporter(
            compatibility=self.compatibility,
            transforms=self.transforms,
            origin=self.origin,
            weights=self.weights,
            merge_within=self.merge_within,
            merge_between=self.merge_between,
            uv_layer=self.uv_layer,
            material_output_node_target=self.material_output_node_target,
            material_output_node_name=self.material_output_node_name,
        )
        # get exportable objects with deforming modifiers applied
        objects = [o.evaluated_get(context.view_layer.depsgraph)
                   for o in Exporter.filter_objects(context.selected_objects)]
        # while the list of objects in the file is alphabetical,
        # the list of objects in a scene is in insertion order
        # the order of the objects affects the render order,
        # so it is important that it is consistent and predictable
        if len(objects) > 1:
            objects = Exporter.sort_objects(objects)
        try:
            exporter.export(objects, Path(self.filepath))
        except LongIndexesNotSupportedError:
            self.report({'ERROR'}, ("Number of vertices or triangles in "
                                    "optimised mesh is too many for OMSI 1."))
            return {'CANCELLED'}
        return {'FINISHED'}


class O3D_PT_export_basic(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Basic"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        operator = context.space_data.active_operator
        return operator.bl_idname == "EXPORT_SCENE_OT_o3d"

    def draw(self, context: Context) -> None:
        layout = self.layout
        operator = context.space_data.active_operator

        layout.label(text="Apply Transforms")
        layout.prop(operator, 'transforms')
        layout.label(text="Merge Materials")
        row = layout.row(align=True)
        row.prop(operator, 'merge_within', toggle=1, text="Within Objects")
        row.prop(operator, 'merge_between', toggle=1, text="Between Objects")
        col = layout.column(heading="Include")
        col.separator(factor=0.5)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(operator, 'origin')
        col.prop(operator, 'weights')


class O3D_PT_export_advanced(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Advanced"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        operator = context.space_data.active_operator
        return operator.bl_idname == "EXPORT_SCENE_OT_o3d"

    def draw(self, context: Context) -> None:
        layout = self.layout
        operator = context.space_data.active_operator

        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column()
        col.prop(operator, 'compatibility')
        col.separator(factor=0.5)
        col.prop(operator, 'uv_layer', text="UV Map")
        col.separator()
        col = layout.column()
        col.label(text="Material Output Node")
        col.prop(operator, 'material_output_node_name', text="Name")
        col.prop(operator, 'material_output_node_target', text="Render Target")


class OMSI_Exporter_Preferences(AddonPreferences):
    bl_idname = __package__

    use_object_name: BoolProperty(
        name="Get export filename from active object",
        description=(
            "Use the active object's name as the export filename"
            " instead of the blend file's name"
        ),
        default=False,
    )

    def draw(self, _: Context) -> None:
        layout = self.layout
        layout.prop(self, 'use_object_name')


def menu_func_export(self, _: Context) -> None:
    self.layout.operator(ExportO3D.bl_idname, text="OMSI Mesh (.o3d)")


def register() -> None:
    register_class(ExportO3D)
    register_class(O3D_PT_export_basic)
    register_class(O3D_PT_export_advanced)
    register_class(OMSI_Exporter_Preferences)
    TOPBAR_MT_file_export.append(menu_func_export)


def unregister() -> None:
    TOPBAR_MT_file_export.remove(menu_func_export)
    unregister_class(ExportO3D)
    unregister_class(O3D_PT_export_basic)
    unregister_class(O3D_PT_export_advanced)
    unregister_class(OMSI_Exporter_Preferences)


if __name__ == "__main__":
    register()
