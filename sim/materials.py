"""Small UsdPreviewSurface helpers; textures remain relative to the USD file."""
import os
from pathlib import Path
from pxr import Gf, Sdf, UsdShade


def material(stage, name, color, roughness=0.6, metallic=0.0, textures=None,
             uv_scale=(1, 1), emission=None):
    path = '/World/Hall/Materials/' + name
    result = UsdShade.Material.Define(stage, path)
    surface = UsdShade.Shader.Define(stage, path + '/Surface')
    surface.CreateIdAttr('UsdPreviewSurface')
    surface.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    surface.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(roughness)
    surface.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(metallic)
    if emission:
        surface.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emission))
    result.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), 'surface')
    if not textures:
        return result
    reader = UsdShade.Shader.Define(stage, path + '/UV')
    reader.CreateIdAttr('UsdPrimvarReader_float2')
    reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
    transform = UsdShade.Shader.Define(stage, path + '/TransformUV')
    transform.CreateIdAttr('UsdTransform2d')
    transform.CreateInput('in', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
    transform.CreateInput('scale', Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(*uv_scale))
    anchor = Path(stage.GetRootLayer().realPath).parent if stage.GetRootLayer().realPath else Path.cwd()
    for channel, file in textures.items():
        sampler = UsdShade.Shader.Define(stage, path + '/' + channel)
        sampler.CreateIdAttr('UsdUVTexture')
        sampler.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(os.path.relpath(file, anchor)))
        sampler.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(transform.ConnectableAPI(), 'result')
        sampler.CreateInput('wrapS', Sdf.ValueTypeNames.Token).Set('repeat')
        sampler.CreateInput('wrapT', Sdf.ValueTypeNames.Token).Set('repeat')
        sampler.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB' if channel == 'diffuseColor' else 'raw')
        if channel == 'normal':
            sampler.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2, 2, 2, 1))
            sampler.CreateInput('bias', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1, -1, -1, 0))
        value_type = Sdf.ValueTypeNames.Color3f if channel == 'diffuseColor' else Sdf.ValueTypeNames.Normal3f
        if channel in ('roughness','opacity'):
            value_type = Sdf.ValueTypeNames.Float
        # Generated opacity maps are single-channel PNGs: alpha would always be 1.
        output = 'r' if channel in ('opacity','roughness') else 'rgb'
        surface.CreateInput(channel, value_type).ConnectToSource(sampler.ConnectableAPI(), output)
    if 'opacity' in textures:
        surface.CreateInput('opacityThreshold',Sdf.ValueTypeNames.Float).Set(.2)
    return result
