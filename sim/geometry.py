"""UV-mapped, low-poly meshes. All coordinates and dimensions are metres."""
import math
from pxr import Gf, Sdf, UsdGeom, UsdPhysics, UsdShade


def mesh(stage, path, points, faces, uv, material, center=(0, 0, 0), rotation=None):
    result = UsdGeom.Mesh.Define(stage, path)
    result.CreatePointsAttr(points)
    result.CreateFaceVertexCountsAttr([len(face) for face in faces])
    result.CreateFaceVertexIndicesAttr([index for face in faces for index in face])
    result.CreateSubdivisionSchemeAttr('none')
    result.CreateDoubleSidedAttr(True)
    UsdGeom.PrimvarsAPI(result).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, 'faceVarying').Set(uv)
    transform = UsdGeom.Xformable(result)
    transform.AddTranslateOp().Set(Gf.Vec3d(*center))
    if rotation:
        transform.AddRotateXYZOp().Set(Gf.Vec3f(*rotation))
    UsdShade.MaterialBindingAPI.Apply(result.GetPrim()).Bind(material)
    return result


def box(stage, path, center, size, material, collision=False, rotation=None):
    x, y, z = [value / 2 for value in size]
    points = [(-x,-y,-z), (x,-y,-z), (x,y,-z), (-x,y,-z),
              (-x,-y,z), (x,-y,z), (x,y,z), (-x,y,z)]
    faces = [(0,3,2,1), (4,5,6,7), (0,1,5,4), (1,2,6,5), (2,3,7,6), (3,0,4,7)]
    result = mesh(stage, path, points, faces, [(0,0),(1,0),(1,1),(0,1)] * 6,
                  material, center, rotation)
    if collision:
        UsdPhysics.CollisionAPI.Apply(result.GetPrim())
    return result


def cylinder(stage, path, center, radius, height, material, rotation=None, segments=20):
    ring = [(math.cos(i * 2 * math.pi / segments), math.sin(i * 2 * math.pi / segments)) for i in range(segments)]
    points = [(radius*x, radius*y, z) for z in (-height/2, height/2) for x,y in ring]
    faces, uv = [], []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, j+segments, i+segments))
        uv.extend([(i/segments,0), ((i+1)/segments,0), ((i+1)/segments,1), (i/segments,1)])
    for indices in (list(reversed(range(segments))), list(range(segments, 2*segments))):
        faces.append(indices)
        uv.extend([(0.5 + ring[i % segments][0]/2, 0.5 + ring[i % segments][1]/2) for i in indices])
    return mesh(stage, path, points, faces, uv, material, center, rotation)


def panel(stage, path, center, width, height, normal, material):
    up = Gf.Vec3d(0, 0, 1)
    right = Gf.Cross(up, Gf.Vec3d(*normal)).GetNormalized()
    points = [tuple(right*x*width/2 + up*y*height/2) for x,y in [(-1,-1),(1,-1),(1,1),(-1,1)]]
    return mesh(stage, path, points, [(0,1,2,3)], [(0,0),(1,0),(1,1),(0,1)], material, center)
