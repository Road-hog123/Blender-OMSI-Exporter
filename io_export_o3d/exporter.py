"""OMSI Mesh Exporter Module

This module provides a class for converting and writing OMSI Mesh files.

Classes:
`Exporter`: For exporting Blender Objects to OMSI Mesh files.


Copyright 2023 Nathan Burnham

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

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from itertools import groupby
from operator import attrgetter, methodcaller
from pathlib import Path
from bpy.types import (
    Object,
    Mesh,
    MeshLoopTriangle,
    Material,
    MaterialSlot,
    VertexGroup,
)
from mathutils import Matrix
from .indexdict import IndexDict
from .node_shader import MaterialWrapper
from . import meshio


MATRIX_0213 = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


class Exporter:
    """
    Export Blender Objects to OMSI Mesh files.

    Classmethods:
    `filter_objects()`: Filters out unexportable Objects
    `sort_objects()`: Sorts Objects by name

    Methods:
    `export()`: Exports Blender Objects to an OMSI Mesh file
    """

    def __init__(self, /, *,
                 compatibility: bool = False,
                 transforms: set = {'LOC', 'ROT', 'SCA'},
                 origin: bool = True,
                 weights: bool = False,
                 merge_within: bool = True,
                 merge_between: bool = True,
                 uv_layer: str = 'active_render',
                 material_output_node_target: str = 'ALL',
                 material_output_node_name: str = 'Export',
                 ) -> None:
        """
        Create an `Exporter`

        Keyword-Only Arguments:
        `compatibility`: maintain compatbility with OMSI 1 (default
        `False`)
        `transforms`: transforms to be applied to the objects (default
        `{'LOC', 'ROT', 'SCA'}`)
        `origin`: include animation origin (default `True`)
        `weights`: include vertex weights (default `False`)
        `merge_within`: merge duplicate materials within objects
        (default `True`)
        `merge_between`: merge duplicate materials between objects
        (default `False`)
        `uv_layer`: UV layer filter attribute (default
        `'active_render'`)
        `material_output_node_target`: use only material output nodes
        targetting this render engine (default `'ALL'`)
        `material_output_node_name`: use only material output nodes with
        this name (default `"Export"`)
        """
        # create format spec based on OMSI 1 compatibility setting
        self._fs = meshio.MeshFormatSpec(1 if compatibility else 7)
        self._transforms = transforms
        self._origin = origin
        self._weights = weights
        self._merge_within = merge_within
        self._merge_between = merge_between
        self._uv_layer_filter = attrgetter(uv_layer)
        self._mo_target = material_output_node_target
        self._mo_name = material_output_node_name

    @classmethod
    def filter_objects(cls, objects: Iterable[Object]) -> list[Object]:
        """Return `objects` with unexportable Objects removed."""
        return [o for o in objects if o.type == 'MESH']

    @classmethod
    def sort_objects(cls, objects: Iterable[Object]) -> list[Object]:
        """Return `objects` in a predictable order."""
        return sorted(objects, key=lambda o: o.name)

    def export(self, objects: Iterable[Object], path: Path) -> None:
        """
        Convert Blender Objects to an OMSI Mesh and write to disk.

        Arguments:
        `objects`: The Objects to be converted
        `path`: The filepath to write the file to

        Converts the Blender Objects into an OMSI Mesh, encodes it and
        writes it to `path`, based on the instance's settings.

        The order the Objects are provided is the order they will be
        written to the file, and by extension the order they will be
        rendered.

        If path points to a file in a directory that does not yet exist,
        the directory and any required parents will be created.

        `LongIndexesNotSupportedError` is raised if the resulting
        optimised Mesh has more than 65535 vertices or triangles but the
        `compatibility` setting is `True`.
        """
        # create the mesh object to fill with converted mesh data
        mesh = meshio.Mesh()

        def meshes() -> Iterator[
            tuple[Mesh, Matrix, list[MaterialSlot], list[VertexGroup]]
        ]:
            # iterate only over exportable objects
            for obj in self.filter_objects(objects):
                # calculate this object's transformation matrix
                # with only the desired transforms
                matrix = Matrix.LocRotScale(
                    obj.location if 'LOC' in self._transforms else None,
                    obj.rotation_euler if 'ROT' in self._transforms else None,
                    obj.scale if 'SCA' in self._transforms else None,
                )
                # combine with reflection matrix across the y=z plane
                # (right-handed Z-up to left-handed Y-up)
                matrix = MATRIX_0213 @ matrix
                # write animation origin if desired and not already set
                if self._origin and mesh.matrix is None:
                    # IMPORTANT: meshio matrices additionally have the
                    # middle rows swapped, and are also transposed!
                    origin = (matrix @ MATRIX_0213).transposed()
                    # each row is a Vector with a to_tuple() method
                    mesh.matrix = tuple(map(methodcaller("to_tuple"),
                                            origin.row))
                # extract mesh from object
                me = obj.to_mesh()
                # make sure normal data is up-to-date
                me.calc_normals_split()
                # meshio only supports triangles, so we need to ensure
                # we have the triangle data available to work with
                me.calc_loop_triangles()
                # yield mesh, matrix, material slots and vertex groups
                # for conversion - by using slots, objects can override
                # a mesh's materials
                yield (
                    me,
                    matrix,
                    list(obj.material_slots),
                    list(obj.vertex_groups) if self._weights else [],
                )
                # clear extracted mesh now we've finished with it
                obj.to_mesh_clear()

        wrappers: dict[Material | None, MaterialWrapper] = {}

        Vertex = tuple[tuple[float, ...],
                       tuple[float, ...],
                       tuple[float, ...],
                       tuple[tuple[str, float], ...]]

        vertices: IndexDict[Vertex] = IndexDict()
        materials: IndexDict[tuple[Material | None, int]] = IndexDict()
        bones: defaultdict[str, dict[int, float]] = defaultdict(dict)

        def triangles() -> Iterator[tuple[tuple[int, int, int], int]]:
            key = attrgetter('material_index')

            # exceptions can't be handled inside dict comprehensions
            def get_weight(vg: VertexGroup, vi: int) -> float:
                try:
                    return vg.weight(vi)
                except RuntimeError as e:
                    # error that is raised is annoyingly vague,
                    # so we check the error message
                    if e.args[0] == "Error: Vertex not in group\n":
                        return 0.0
                    raise
            # this dictionary keeps track of the material repeat index,
            # which is used when merging materials
            counter: Counter[Material | None] = Counter()

            for me, matrix, slots, vertex_groups in meshes():
                # groupyby requires its input to be sorted
                # grouping allows for material processing to occur
                # once per material, not once per triangle
                k: int
                g: Iterator[MeshLoopTriangle]
                for k, g in groupby(sorted(me.loop_triangles, key=key), key):
                    try:
                        # extract current material from its slot
                        material = slots[k].material
                    except IndexError:
                        # the object has no slots
                        material = None
                    # get material wrapper for current material
                    wrapper = wrappers.setdefault(
                        material, MaterialWrapper(
                            material, self._mo_target, self._mo_name,
                        )
                    )
                    if me.uv_layers:
                        uv_layer = me.uv_layers.get(
                            # attempt to use material-specified uv layer
                            wrapper.uv_map,
                            # otherwise fall back to active uv layer
                            next(
                                filter(self._uv_layer_filter, me.uv_layers),
                                # use 0th uv layer as last-ditch option
                                me.uv_layers[0]
                            ),
                        )
                    else:
                        # if there are no uv layers, create a new one
                        uv_layer = me.uv_layers.new()
                    # acquire deformation function
                    deform = wrapper.uv_deform

                    def vertex_index(li: int) -> int:
                        vi = me.loops[li].vertex_index
                        # get weights for this vertex
                        weights = {vg.name: get_weight(vg, vi)
                                   for vg in vertex_groups}
                        # get new index for this vertex
                        index = vertices[
                            (matrix @ me.vertices[vi].co).to_tuple(),
                            (matrix @ me.loops[li].normal).to_tuple(),
                            deform(uv_layer.uv[li].vector).to_tuple(),
                            tuple(weights.items()),
                        ]
                        # store non-zero weights if this vertex is new
                        for name, weight in weights.items():
                            if weight and index not in bones[name]:
                                bones[name][index] = weight
                        # return new index
                        return index

                    # iterate over triangles and yield with new indices
                    for tri in g:
                        # have to reverse winding for negative scales
                        loops = (reversed(tri.loops) if matrix.is_negative
                                 else tri.loops)
                        yield (
                            # get vertex indices
                            tuple(map(vertex_index, loops)),
                            # get index for material, repeat index pair
                            materials[material, counter[material]],
                        )
                    # increment material counter, but only if we don't
                    # want to merge within this mesh, otherwise each key
                    # is incremented at the end of this mesh
                    counter[material] += int(not self._merge_within)

                # reset the counts at the start of each mesh, but only
                # if we want the materials to be merged between them
                if self._merge_between:
                    counter.clear()
                elif self._merge_within:
                    # increment counts if we're merging only within
                    for material in counter:
                        counter[material] += 1

        # convert triangles
        mesh.triangles = [meshio.Triangle(vs, m) for vs, m in triangles()]

        # convert vertices
        mesh.vertices = [meshio.Vertex(
                             meshio.Vector3._make(co),
                             meshio.Vector3._make(no),
                             meshio.Vector2._make(uv),
                        )
                        for co, no, uv, _ in vertices]

        # convert materials
        mesh.materials = [meshio.Material(
                              wrappers[m].diffuse,
                              wrappers[m].specular,
                              wrappers[m].emissive,
                              wrappers[m].power,
                              wrappers[m].texture,
                        )
                        for m, _ in materials]

        # convert weights
        if self._weights and bones:
            mesh.bones = [meshio.Bone(name, tuple(meshio.SkinWeight(i, w)
                                                  for i, w in weights.items()))
                          for name, weights in bones.items()]

        # encode mesh into binary
        b = meshio.dump(mesh, self._fs)
        # ensure destination folder exists
        path.parent.mkdir(parents=True, exist_ok=True)
        # write the file
        path.write_bytes(b)
