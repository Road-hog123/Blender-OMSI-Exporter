"""OMSI Mesh IO Module

This module provides a method for encoding OMSI Mesh files.

Classes:
`ColorRGB`: Storage class for RGB colours
`ColorRGBA`: Storage class for RGBA colours
`Vector2`: Storage class for 2D vectors
`Vector3`: Storage class for 3D vectors
`Vertex`: Storage class for mesh vertices
`Material`: Storage class for mesh materials
`Triangle`: Storage class for mesh triangles
`SkinWeight`: Storage class for mesh skin weights
`Bone`: Storage class for mesh bones
`Mesh`: Storage class for meshes
`MeshFormatSpec`: Storage class for mesh file format description

Methods:
`dump()`: Encodes a Mesh into binary

Exceptions:
`MeshIOError`: Base class, not raised itself
`LongIndexesNotSupportedError`: When using unsupported long indexes
`EqualityBitNotSupportedError`: When using unsupported equality bit
`EncryptionNotSupportedError`: When using unsupported encryption


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

from struct import calcsize, pack
from typing import NamedTuple, TypeAlias

_KNOWN_VERSIONS = (1, 3, 4, 5, 6, 7)


class MeshIOError(Exception):
    """Base class for exceptions in this module."""
    pass


class LongIndexesNotSupportedError(MeshIOError):
    """
    Exception raised if long indexes are not supported.

    Attributes:
    `version`: the version that doesn't support extended addressing
    """

    def __init__(self, version: int) -> None:
        """
        Initialise a new `LongIndexesNotSupportedError`.

        Arguments:
        `version`: the version that doesn't support extended addressing
        """
        super().__init__(f'Long indexes unsupported in version {version}')
        self.version = version


class EqualityBitNotSupportedError(MeshIOError):
    """
    Exception raised if the equality bit is not supported.

    Attributes:
    `version`: the version that doesn't support the equality bit
    """

    def __init__(self, version: int) -> None:
        """
        Initialise a new `EqualityBitNotSupportedError`.

        Arguments:
        `version`: the version that doesn't support the equality bit
        """
        super().__init__(f'Equality bit unsupported in version {version}')
        self.version = version


class EncryptionNotSupportedError(MeshIOError):
    """
    Exception raised if encryption is not supported.

    Attributes:
    `version`: the version that doesn't support encryption
    """

    def __init__(self, version: int) -> None:
        """
        Initialise a new `EncryptionNotSupportedError`.

        Arguments:
        `version`: the version that doesn't support encryption
        """
        super().__init__(f'Encryption unsupported in version {version}')
        self.version = version


class _Format:
    def __init__(self, fmt: str) -> None:
        self.fmt = fmt
        self.len = calcsize('<' + fmt)


class MeshFormatSpec:
    """
    Describes the format of a mesh file, separate from the mesh data.

    Attributes:
    `version`: Mesh version
    `supportsLongIndexes`: Indicates extended addressing availability
    `supportsEqualityBit`: Indicates "equality bit" availability
    `supportsEncryption`: Indicates encryption availability
    `isEncrypted`: Indicates encryption state
    `longIndexes`: Indicates extended addressing utilisation
    `equalityBit`: Indicates "equality bit" state
    `encryptionKey`: The encryption key
    """
    _idBytes = b'\x84\x19'
    _idByteVertexList = b'\x17'
    _idByteTriangleList = b'\x49'
    _idByteMaterialList = b'\x26'
    _idByteMatrix = b'\x79'
    _idByteBoneList = b'\x54'

    _versionFormat = _Format('B')
    _extraByteFormat = _Format('B')
    _encryptionKeyFormat = _Format('I')
    _stringLengthFormat = _Format('B')
    _stringFormat = 'cp1252'

    def __init__(self,
                 version: int,
                 longIndexes: bool = False,
                 equalityBit: bool = False,
                 encryptionKey: int | None = None,
                 ) -> None:
        """
        Initialise a new `MeshFormatSpec`.

        Arguments:
        `version`: Mesh version number (1 for OMSI 1, 7 for OMSI 2)
        `longIndexes`: Enable/disable long indexes (default `False`)
        `equalityBit`: Enable/disable "equality bit" (default `False`)
        `encryptionKey`: Encryption key, or `None` for no encryption
        (default `None`)

        `ValueError` is raised if `version` is unknown
        `LongIndexesNotSupportedError` is raised if `longIndexes` is
        `True` but extended addressing isn't supported
        `EqualityBitNotSupportedError` is raised if `equalityBit` is
        `True` but the "equality bit" is not supported
        `EncryptionNotSupportedError` is raised if `encryptionKey` is
        not `None` but encryption is not supported
        """
        if version not in _KNOWN_VERSIONS:
            raise ValueError(f'Mesh version {version} is unknown')
        self._version = version

        self.longIndexes = longIndexes
        self.equalityBit = equalityBit
        self.encryptionKey = encryptionKey

        if self.supportsLongIndexes:
            self._vertexCount = self._triangleCount = _Format('I')
        else:
            self._vertexCount = self._triangleCount = _Format('H')
        self._materialCount = _Format('H')
        self._boneCount = _Format('H')
        self._skinWeightCount = _Format('H')
        self._vertex = _Format('8f')
        self._material = _Format('11f')
        self._matrix = _Format('16f')

    def __eq__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return (
            (self.version, self.longIndexes,
             self.equalityBit, self.encryptionKey) ==
            (other.version, other.longIndexes,
             other.equalityBit, other.encryptionKey)
        )

    def __str__(self) -> str:
        return (
            f'version:   {self.version}\n'
            f'indexes:   {"long" if self.longIndexes else "short"}\n'
            f'equality:  {self.equalityBit}\n'
            f'encrypted: {"yes" if self.isEncrypted else "no"}'
        )

    @property
    def supportsLongIndexes(self) -> bool:
        """Get extended addressing support for this mesh version."""
        return self.version in _KNOWN_VERSIONS[1:]

    @property
    def supportsEqualityBit(self) -> bool:
        """Get "equality bit" support for this mesh version."""
        return self.version in _KNOWN_VERSIONS[1:]

    @property
    def supportsEncryption(self) -> bool:
        """Get encryption support for this mesh version."""
        return self.version in _KNOWN_VERSIONS[2:]

    @property
    def isEncrypted(self) -> bool:
        """Get encryption state for this mesh file."""
        return self._encryptionKey not in (None, 0xffffffff)

    @property
    def version(self) -> int:
        """Get mesh version for this mesh file."""
        return self._version

    @property
    def longIndexes(self) -> bool:
        """Get or set extended addressing state for this mesh file."""
        return self._longIndexes

    @longIndexes.setter
    def longIndexes(self, value: bool) -> None:
        if not self.supportsLongIndexes and value:
            raise LongIndexesNotSupportedError(self.version)

        self._longIndexes = value
        self._triangle = _Format('3IH') if value else _Format('4H')
        self._skinWeight = _Format('If') if value else _Format('Hf')

    @property
    def equalityBit(self) -> bool:
        """Get or set "equality bit" state for this mesh file."""
        return self._equalityBit

    @equalityBit.setter
    def equalityBit(self, value: bool) -> None:
        if not self.supportsEqualityBit and value:
            raise EqualityBitNotSupportedError(self.version)

        self._equalityBit = value

    @property
    def encryptionKey(self) -> int | None:
        """Get or set encryption key for this mesh file."""
        return self._encryptionKey

    @encryptionKey.setter
    def encryptionKey(self, value: int | None) -> None:
        if self.supportsEncryption:
            if value is None:
                value = 0xffffffff
        else:
            if value is not None:
                raise EncryptionNotSupportedError(self.version)

        self._encryptionKey = value


class ColorRGB(NamedTuple):
    r: float = 1.0
    g: float = 1.0
    b: float = 1.0


class ColorRGBA(NamedTuple):
    r: float = 1.0
    g: float = 1.0
    b: float = 1.0
    a: float = 1.0


class Vector2(NamedTuple):
    x: float = 0.0
    y: float = 0.0


class Vector3(NamedTuple):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Vertex(NamedTuple):
    co: Vector3 = Vector3()
    no: Vector3 = Vector3()
    uv: Vector2 = Vector2()


class Triangle(NamedTuple):
    vertices: tuple[int, int, int] = (0, 0, 0)
    material: int = 0


class Material(NamedTuple):
    diffuse: ColorRGBA = ColorRGBA()
    specular: ColorRGB = ColorRGB(0.5, 0.5, 0.5)
    emissive: ColorRGB = ColorRGB(0.0, 0.0, 0.0)
    power: float = 1000.0
    texture: str = ''


Matrix: TypeAlias = tuple[tuple[float, float, float, float],
                          tuple[float, float, float, float],
                          tuple[float, float, float, float],
                          tuple[float, float, float, float]]


class SkinWeight(NamedTuple):
    vertex: int = 0
    weight: float = 0.0


class Bone(NamedTuple):
    name: str = 'Bone'
    weights: list[SkinWeight] = []


class Mesh:
    """
    Storage class for whole meshes.

    Attributes:
    `vertices`: List of mesh vertices
    `materials`: List of mesh materials
    `triangles`: List of mesh triangles
    `matrix`: Mesh matrix, or `None`
    `bones`: List of mesh bones, or `None`
    """
    def __init__(self) -> None:
        """Initialise a new empty `Mesh`."""
        self.vertices: list[Vertex] = []
        self.materials: list[Material] = []
        self.triangles: list[Triangle] = []
        self.matrix: Matrix | None = None
        self.bones: list[Bone] | None = None

    @property
    def requiresLongIndexes(self) -> bool:
        """Get extended addressing requirement for writing this mesh."""
        return max(len(self.vertices), len(self.triangles)) > 0xffff


def dump(mesh: Mesh, fs: MeshFormatSpec) -> bytearray:
    """
    Encode a `Mesh` into binary.

    Arguments:
    `mesh`: The mesh to be encoded
    `fs`: The mesh file format specification

    Returns a `bytearray` object containing the encoded `Mesh`, in the
    format described by the `MeshFormatSpec` object.

    If the `MeshFormatSpec` provides an encryption key, it will be
    written  to the file but no encryption is performed on the `Mesh`
    content.

    `LongIndexesNotSupportedError` is raised if the input mesh has more
    than 65535 vertices or triangles but the mesh version does not
    support long indexes.
    """
    # shorthand for MeshFormatSpec
    mfs = MeshFormatSpec

    # shorthand function for encoding values from a format to bytes
    def ef(fmt: _Format, *v) -> bytes:
        return pack('<' + fmt.fmt, *v)

    # shorthand function for encoding a string
    def es(s: str) -> bytes:
        return ef(fs._stringLengthFormat, len(s)) + s.encode(fs._stringFormat)

    # appending to a bytearray is faster than b''.join() on a list of
    # bytes objects
    ba: bytearray = bytearray()

    # all o3d files start with the same two bytes
    ba += mfs._idBytes

    # version number
    ba += ef(mfs._versionFormat, fs.version)

    # enforce extended indexing when required
    # this will raise an exception if required but not supported
    fs.longIndexes = fs.longIndexes or mesh.requiresLongIndexes

    # extended addressing and equality bit
    if fs.supportsLongIndexes or fs.supportsEqualityBit:
        ba += ef(mfs._extraByteFormat,
                 int(fs.longIndexes) + (int(fs.equalityBit) * 2))

    # encryption
    if fs.supportsEncryption:
        ba += ef(mfs._encryptionKeyFormat, fs.encryptionKey)

    # start of vertices definition
    ba += mfs._idByteVertexList

    # number of vertices
    ba += ef(fs._vertexCount, len(mesh.vertices))

    # list of vertices
    for v in mesh.vertices:
        ba += ef(fs._vertex, *v.co, *v.no, *v.uv)

    # start of triangles definition
    ba += mfs._idByteTriangleList

    # number of triangles
    ba += ef(fs._triangleCount, len(mesh.triangles))

    # list of triangles
    for t in mesh.triangles:
        ba += ef(fs._triangle, *t.vertices, t.material)

    # start of materials definition
    ba += mfs._idByteMaterialList

    # number of materials
    ba += ef(fs._materialCount, len(mesh.materials))

    # list of materials
    for m in mesh.materials:
        ba += ef(fs._material, *m.diffuse, *m.specular, *m.emissive, m.power)
        ba += es(m.texture)

    # only add matrix definition if a matrix is defined
    if mesh.matrix is not None:
        # start of transform matrix definition
        ba += mfs._idByteMatrix

        # matrix
        ba += ef(fs._matrix, *(i for s in mesh.matrix for i in s))

    # only add bones definition if a list of bones is defined
    if mesh.bones is not None:
        # start of bones definition
        ba += mfs._idByteBoneList

        # number of bones
        ba += ef(fs._boneCount, len(mesh.bones))

        # list of bones
        for b in mesh.bones:
            ba += es(b.name) + ef(fs._skinWeightCount, len(b.weights))
            for w in b.weights:
                ba += ef(fs._skinWeight, w.vertex, w.weight)

    return ba
