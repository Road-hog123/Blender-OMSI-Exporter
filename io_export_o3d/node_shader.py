"""Blender Node Shader to OMSI Mesh Material Converter

Classes:
`MaterialWrapper`: wraps a Blender Material, providing high-level access


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

from collections import defaultdict
from pathlib import PureWindowsPath
from typing import Callable, NamedTuple, Optional
from bpy.types import (
    Material,
    NodeLink,
    NodeSocket,
    NodeSocketColor,
    NodeSocketFloat,
    ShaderNode,
    ShaderNodeTree,
    ShaderNodeGroup,
    ShaderNodeOutputMaterial,
    ShaderNodeBsdfPrincipled,
    ShaderNodeRGB,
    ShaderNodeValue,
    ShaderNodeTexImage,
    ShaderNodeMapping,
    ShaderNodeUVMap,
)
from bpy.path import abspath
from mathutils import Matrix, Vector

from . import meshio


_NODES: dict[str, str] = {
    'ShaderNodeGroup': 'group',
    'NodeGroupInput': 'input',
    'NodeGroupOutput': 'output',
}


_SOCKETS: dict[tuple[str, str], str] = {
    ('ShaderNodeOutputMaterial', 'Surface'): 'surface',
    ('ShaderNodeBsdfPrincipled', 'BSDF'): 'bsdf',
    ('ShaderNodeBsdfPrincipled', 'Alpha'): 'alpha',
    ('ShaderNodeBsdfPrincipled', 'Base Color'): 'base',
    ('ShaderNodeBsdfPrincipled', 'Emission'): 'emission',
    ('ShaderNodeBsdfPrincipled', 'Roughness'): 'roughness',
    ('ShaderNodeBsdfPrincipled', 'Specular'): 'specular',
    ('ShaderNodeTexImage', 'Color'): 'texture',
    ('ShaderNodeTexImage', 'Vector'): 'uv',
    ('ShaderNodeUVMap', 'UV'): 'uv_map',
    ('ShaderNodeMapping', 'Vector'): 'mapping',
    ('ShaderNodeRGB', 'Color'): 'color',
    ('ShaderNodeValue', 'Value'): 'value',
}


_LINKS: dict[tuple[str, str], str] = {
    ('bsdf', 'surface'): 'bsdf',
    ('texture', 'base'): 'texture_base',
    ('color', 'base'): 'color_base',
    ('color', 'emission'): 'color_emission',
    ('value', 'specular'): 'value_specular',
    ('value', 'roughness'): 'value_roughness',
    ('value', 'alpha'): 'value_alpha',
    ('mapping', 'uv'): 'mapping',
    ('uv_map', 'uv'): 'uv_map',
    ('uv_map', 'mapping'): 'uv_map',
}


class _Link(NamedTuple):
    from_socket: NodeSocket
    to_socket: NodeSocket


def _socket_key(socket: NodeSocket) -> str:
    try:
        return _NODES[socket.node.bl_idname]
    except KeyError:
        return _SOCKETS[socket.node.bl_idname, socket.identifier]


def _get_links(tree: ShaderNodeTree) -> dict[str, list[_Link]]:
    links: defaultdict[str, list[_Link]] = defaultdict(list)
    trees: dict[ShaderNodeGroup, tuple[list[_Link], list[_Link]]] = {}

    link: NodeLink
    for link in tree.links:
        # links that cross a group boundary are two links in Blender,
        # but we only consider them as one - as such the sockets may not
        # actually belong to this NodeLink and we need to be able to
        # overwrite them
        fs = link.from_socket
        ts = link.to_socket

        try:
            # get keys for these sockets
            fk: str = _socket_key(fs)
            tk: str = _socket_key(ts)
        except KeyError:
            # unless we're interested in both sockets we're not
            # interested in this link
            continue

        # if link is from a group node, we need to descend into the
        # child tree and find out what socket the link is actually from
        if fk == 'group':
            try:
                # retrieving the list of output links for this group
                # will fail if this is the first link to/from this group
                _, o = trees[link.from_node]
            except KeyError:
                # recurse into child tree
                sub_links = _get_links(link.from_node.node_tree)
                # store and remove the lists of partial links
                trees[link.from_node] = (sub_links.pop('input', []),
                                         sub_links.pop('output', []))
                # add the complete links to the main links dictionary
                for k, v in sub_links.items():
                    links[k].extend(v)
                # now we can safely retrieve the list of output links
                _, o = trees[link.from_node]
            # now to match the external link to the internal one
            for ofs, ots in o:
                # the sockets should have the same name
                if ots.name == fs.name:
                    # overwrite the from socket and get new key
                    fs = ofs
                    fk = _socket_key(fs)
                    # we're done here
                    break
            else:
                # if we can't find a matching input link (either because
                # the input socket isn't connected or is mis-named), we
                # don't care about this link
                continue

        # repeat for when the link is to a group node, appropriately
        # inverted
        if tk == 'group':
            try:
                i, _ = trees[link.to_node]
            except KeyError:
                sub_links = _get_links(link.to_node.node_tree)
                trees[link.from_node] = (sub_links.pop('input', []),
                                         sub_links.pop('output', []))
                for k, v in sub_links.items():
                    links[k].extend(v)
                i, _ = trees[link.from_node]
            for ifs, its in i:
                if ifs.name == ts.name:
                    ts = its
                    tk = _socket_key(ts)
                    break
            else:
                continue

        try:
            # get key for this socket pair
            key: str = _LINKS[fk, tk]
        except KeyError:
            # all links to i/o sockets go in their respective categories
            if fk == 'input':
                key = fk
            elif tk == 'output':
                key = tk
            else:
                # this link is between interesting sockets but not in an
                # interesting combination, so we don't care about it
                continue

        # we're interested in this link
        links[key].append(_Link(fs, ts))

    return links


class MaterialWrapper():
    """
    Provides high-level access to Blender Material properties.

    Properties:
    `diffuse`: OMSI Mesh Material diffuse colour
    `emissive`: OMSI Mesh Material emissive colour
    `specular`: OMSI Mesh Material specular colour
    `power`: OMSI Mesh Material power value
    `texture`: OMSI Mesh Material texture string
    `uv_map`: Name of the UV Map the node shader targets
    `uv_deform`: Apply Material UV deformation to individual coordinates
    """
    def __init__(self,
                 material: Optional[Material],
                 target: str = 'ALL',
                 name: str = 'Export',
                 ) -> None:
        """
        Wrap a Material.

        Arguments:
        `material`: The Blender Material to wrap, or None
        `target`: Material Output Node must target this render engine
        `name`: Material Output Node must have this name
        """
        self._material: Optional[Material] = material
        self._bsdf: Optional[ShaderNodeBsdfPrincipled] = None
        self._color_base: Optional[ShaderNodeRGB] = None
        self._color_emission: Optional[ShaderNodeRGB] = None
        self._value_specular: Optional[ShaderNodeValue] = None
        self._value_roughness: Optional[ShaderNodeValue] = None
        self._value_alpha: Optional[ShaderNodeValue] = None
        self._image: Optional[ShaderNodeTexImage] = None
        self._mapping: Optional[ShaderNodeMapping] = None
        self._uvmap: Optional[ShaderNodeUVMap] = None

        # we don't want to try interpreting a node-less material's nodes
        if not (self._material and self._material.use_nodes):
            return
        # get node tree
        tree: ShaderNodeTree = self._material.node_tree
        # get output node
        output: ShaderNodeOutputMaterial
        try:
            # try to get node by name
            output = tree.nodes[name]
            # getting a node by name from a list of all nodes could
            # conceivably return a node of a different type
            if output.bl_idname != 'ShaderNodeOutputMaterial':
                raise KeyError()
        except KeyError:
            # try to get node by target
            output = tree.get_output_node(target)
            # no usable output node, can't proceed further
            if not output:
                return
        # extract links from the tree and any subtrees
        links: dict[str, list[_Link]] = _get_links(tree)

        def get_node(category: str, node: ShaderNode,
                     ) -> Optional[ShaderNode]:
            """Return from node for the first link to node in category"""
            return next(
                (link.from_socket.node for link in links[category]
                 if link.to_socket.node == node),
                None
            )
        # try to get a bsdf node
        self._bsdf = get_node('bsdf', output)
        # can't go further without a bsdf node
        if not self._bsdf:
            return
        # try to get emission, specular, roughness and alpha nodes
        self._color_emission = get_node('color_emission', self._bsdf)
        self._value_specular = get_node('value_specular', self._bsdf)
        self._value_roughness = get_node('value_roughness', self._bsdf)
        self._value_alpha = get_node('value_alpha', self._bsdf)
        # try to get a base colour node
        self._color_base = get_node('color_base', self._bsdf)
        # if we find a base colour node there can't be an image node
        if self._color_base:
            return
        # try to get an image node
        self._image = get_node('texture_base', self._bsdf)
        # can't go further without an image node
        if not self._image:
            return
        # try to get a mapping node
        self._mapping = get_node('mapping', self._image)
        # try to get a uv map node
        self._uvmap = get_node('uv_map',
                               self._mapping if self._mapping else self._image)

    @property
    def diffuse(self) -> meshio.ColorRGBA:
        """
        Return OMSI Mesh Material diffuse colour.

        Fallbacks are implemented such that a colour is always returned,
        even if the material doesn't use nodes or is None.
        """
        if not self._material:
            return meshio.ColorRGBA(1.0, 1.0, 1.0, 1.0)
        if not self._bsdf:
            return meshio.ColorRGBA._make(self._material.diffuse_color)

        socket_color: NodeSocketColor
        if self._color_base:
            socket_color = self._color_base.outputs['Color']
        else:
            socket_color = self._bsdf.inputs['Base Color']

        socket_float: NodeSocketFloat
        if self._value_alpha:
            socket_float = self._value_alpha.outputs['Value']
        else:
            socket_float = self._bsdf.inputs['Alpha']

        return meshio.ColorRGBA._make(socket_color.default_value[:3]
                                      + (socket_float.default_value,))

    @property
    def emissive(self) -> meshio.ColorRGB:
        """
        Return OMSI Mesh Material emissive colour.

        Fallbacks are implemented such that a colour is always returned,
        even if the material doesn't use nodes or is None.
        """
        if not self._bsdf:
            return meshio.ColorRGB(0.0, 0.0, 0.0)

        socket: NodeSocketColor
        if self._color_emission:
            socket = self._color_emission.outputs['Color']
        else:
            socket = self._bsdf.inputs['Emission']
        return meshio.ColorRGB._make(socket.default_value[:3])

    @property
    def specular(self) -> meshio.ColorRGB:
        """
        Return OMSI Mesh Material specular colour.

        Fallbacks are implemented such that a colour is always returned,
        even if the material doesn't use nodes or is None.
        """
        if not self._material:
            return meshio.ColorRGB(0.5, 0.5, 0.5)
        if not self._bsdf:
            return meshio.ColorRGB._make(self._material.specular_color)

        socket: NodeSocketFloat
        if self._value_specular:
            socket = self._value_specular.outputs['Value']
        else:
            socket = self._bsdf.inputs['Specular']
        return meshio.ColorRGB._make([socket.default_value]*3)

    @property
    def power(self) -> float:
        """
        Return OMSI Mesh Material power value.

        Fallbacks are implemented such that a value is always returned,
        even if the material doesn't use nodes or is None.
        """
        if self._bsdf:
            socket: NodeSocketFloat
            if self._value_roughness:
                socket = self._value_roughness.outputs['Value']
            else:
                socket = self._bsdf.inputs['Roughness']
            roughness = socket.default_value
        else:
            if self._material:
                roughness = self._material.roughness
            else:
                roughness = 0
        return 1000 - roughness * 1000

    @property
    def texture(self) -> str:
        """Return OMSI Mesh Material texture string."""
        if self._image:
            path = PureWindowsPath(abspath(self._image.image.filepath))
            return str(path.relative_to(
                next((p for p in reversed(path.parents)
                      if p.name and p == p.with_name("texture")),
                     path.parent)
            ))
        return ""

    @property
    def uv_map(self) -> str:
        """Return UV map name for wrapped Material."""
        if self._uvmap:
            return self._uvmap.uv_map
        return ""

    @property
    def uv_deform(self) -> Callable[[Vector], Vector]:
        """
        Return UV coordinate deform callable for Material.

        Computes a transformation matrix that includes both the
        deformation specified by a mapping node and the Blender UV to
        OMSI Mesh UV transformation, then returns a Callable that
        applies that matrix transformation to a 2D UV Vector.
        """
        # reflection matrix across y=0.5
        # (bottom-left origin to top-left origin)
        # the matrix has to be 4x4 as the mapping node performs a 3D
        # transformation, even when the input is a 2D UV vector
        matrix: Matrix = (Matrix.Translation((0, 1, 0)).to_4x4()
                          @ Matrix.Diagonal((1, -1)).to_4x4())

        if self._mapping:
            loc = Matrix.Translation(
                self._mapping.inputs['Location'].default_value
            )
            rot = (
                self._mapping.inputs['Rotation'].default_value
                .to_matrix().to_4x4()
            )
            sca = Matrix.Diagonal(
                self._mapping.inputs['Scale'].default_value
            ).to_4x4()

            # POINT: transform the UVs
            # TEXTURE: transform the texture
            # VECTOR: POINT with no translate
            # NORMAL: Shouldn't be used with UVs, ignored
            if self._mapping.vector_type == 'POINT':
                matrix = matrix @ sca @ rot @ loc
            elif self._mapping.vector_type == 'TEXTURE':
                matrix = matrix @ (loc @ rot @ sca).inverted_safe()
            elif self._mapping.vector_type == 'VECTOR':
                matrix = matrix @ sca @ rot

        # the mapping node performs a 3D transformation of the UVs
        # they have to be resized to 4D, transformed, then back to 2D
        def deform(uv: Vector) -> Vector:
            return (matrix @ uv.to_4d()).to_2d()

        return deform
