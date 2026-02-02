I needed to have some glb files converted into icons for a game, and needed to process a ton of models fast. I attempted to do so by hand and kept running into problems. So i had Claude Opus 4.5 do research on the best practices for an absoultely foolproof method. Well this is what we got, and so far, it works great. 

enjoy


# Rendering 3D icons from GLB files in headless Blender

The key to foolproof icon rendering lies in **mathematically deriving camera position from a bounding sphere**, setting clip planes based on actual object distances, and using universal lighting that requires no manual adjustment. This guide provides production-ready Python code with the exact formulas that guarantee your 3D model is always visible, centered, and properly lit—regardless of its size, position, or orientation.

The core camera distance formula for perspective projection is **`distance = radius / tan(FOV/2)`**, where radius is the bounding sphere radius and FOV is the camera's field of view in radians. For orthographic cameras, you instead set **`ortho_scale = diameter × padding`** since distance doesn't affect visible size. Both approaches require computing an accurate world-space bounding box first, then deriving all other values mathematically.

## Loading GLB files with correct texture handling

The official glTF 2.0 importer in Blender uses `bpy.ops.import_scene.gltf()`. For GLB files with embedded textures, the critical parameter is **`import_pack_images=True`**, which ensures textures are properly extracted and linked to materials.

```python
import bpy

def import_glb(filepath):
    """Import GLB with proper texture and material handling."""
    bpy.ops.import_scene.gltf(
        filepath=filepath,
        import_pack_images=True,           # Extract embedded textures
        merge_vertices=False,              # Preserve original topology
        import_shading='NORMALS',          # Keep original normals
        import_select_created_objects=True # Auto-select for post-processing
    )
    return bpy.context.selected_objects
```

Materials import as Principled BSDF shader nodes, which are compatible with both EEVEE and Cycles. If textures don't appear, the issue is typically viewport shading mode (must be Material Preview or Rendered) or color space misconfiguration (base color should be sRGB, normal maps Non-Color).

Before importing, clear the default scene to avoid interference:

```python
def clear_scene():
    """Remove all objects and orphan data for clean batch processing."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # Purge orphan data to free memory
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)
    for block in bpy.data.images:
        if block.users == 0:
            bpy.data.images.remove(block)
```

## Computing accurate world-space bounding boxes

The fundamental challenge is that `obj.bound_box` returns coordinates in **local object space**, which ignores rotation, scale, and position transforms. You must multiply each corner by `obj.matrix_world` to get true world-space positions.

```python
from mathutils import Vector

def get_world_bounding_box(objects):
    """Calculate combined bounding box for all mesh objects in world space."""
    all_corners = []
    
    for obj in objects:
        if obj.type != 'MESH':
            continue
        # Transform each of the 8 bounding box corners to world space
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ Vector(corner)
            all_corners.append(world_corner)
    
    if not all_corners:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    
    min_corner = Vector((
        min(c.x for c in all_corners),
        min(c.y for c in all_corners),
        min(c.z for c in all_corners)
    ))
    max_corner = Vector((
        max(c.x for c in all_corners),
        max(c.y for c in all_corners),
        max(c.z for c in all_corners)
    ))
    
    return min_corner, max_corner
```

For models with modifiers (subdivision, mirror, etc.), use the evaluated depsgraph to account for modified geometry:

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
obj_evaluated = obj.evaluated_get(depsgraph)
# Use obj_evaluated.bound_box instead
```

The bounding sphere is more useful for camera framing because it's view-independent—the same radius works from any angle. Calculate it from the bounding box:

```python
def get_bounding_sphere(objects):
    """Return center and radius of bounding sphere encompassing all objects."""
    min_corner, max_corner = get_world_bounding_box(objects)
    center = (min_corner + max_corner) / 2
    
    # Radius = distance from center to farthest corner
    all_corners = []
    for obj in objects:
        if obj.type == 'MESH':
            for corner in obj.bound_box:
                all_corners.append(obj.matrix_world @ Vector(corner))
    
    radius = max((corner - center).length for corner in all_corners)
    return center, radius
```

## The mathematics of perspective camera positioning

For a perspective camera, the relationship between field of view, object size, and required distance follows from basic trigonometry. If you have a bounding sphere of radius **r** and a camera with field of view **θ**, the minimum distance **d** to fit the entire sphere is:

**`d = r / tan(θ/2)`**

Blender doesn't directly expose FOV—it uses focal length and sensor size. The conversion is:

**`FOV = 2 × arctan(sensor_width / (2 × focal_length))`**

```python
import math

def calculate_camera_distance_perspective(camera, bounding_radius, padding=1.1):
    """Calculate distance to frame bounding sphere with given padding."""
    cam_data = camera.data
    
    # Calculate FOV from focal length and sensor
    # sensor_fit determines which dimension constrains the view
    if cam_data.sensor_fit == 'VERTICAL':
        fov = 2 * math.atan(cam_data.sensor_height / (2 * cam_data.lens))
    else:  # HORIZONTAL or AUTO
        fov = 2 * math.atan(cam_data.sensor_width / (2 * cam_data.lens))
    
    # Core formula: distance = radius / tan(half_angle)
    distance = (bounding_radius * padding) / math.tan(fov / 2)
    return distance
```

The **padding multiplier** (typically 1.1 for 10% margin) ensures the object doesn't touch frame edges. For square icon renders, use `sensor_fit = 'HORIZONTAL'` with equal resolution dimensions.

Clip planes must be set based on actual object distance to prevent clipping:

```python
def set_clip_planes(camera, distance, bounding_radius):
    """Set near/far clip planes to encompass the entire object."""
    # Near clip: closest point of sphere with safety margin
    camera.data.clip_start = max(0.001, distance - bounding_radius * 1.5)
    # Far clip: farthest point of sphere with margin
    camera.data.clip_end = distance + bounding_radius * 2.0
```

## Orthographic camera setup differs fundamentally

Orthographic projection eliminates perspective distortion—distance from camera doesn't change apparent object size. Instead, **`ortho_scale`** defines the visible width in Blender units.

```python
def setup_orthographic_camera(camera, objects, padding=1.1):
    """Configure orthographic camera to frame objects."""
    center, radius = get_bounding_sphere(objects)
    
    camera.data.type = 'ORTHO'
    # ortho_scale = visible width, so diameter × padding
    camera.data.ortho_scale = radius * 2 * padding
    
    # Distance is arbitrary for framing, but needed for clipping
    safe_distance = radius * 3
    camera.data.clip_start = safe_distance - radius * 2
    camera.data.clip_end = safe_distance + radius * 2
    
    return center, safe_distance
```

For orthographic rendering, consider aspect ratio when the render isn't square:

```python
def ortho_scale_with_aspect(bbox_width, bbox_height, render_aspect, padding=1.1):
    """Calculate ortho_scale accounting for render aspect ratio."""
    object_aspect = bbox_width / bbox_height if bbox_height > 0 else 1
    
    if object_aspect > render_aspect:
        # Object wider than frame—fit to width
        return bbox_width * padding
    else:
        # Object taller than frame—fit to height, scale by aspect
        return bbox_height * render_aspect * padding
```

## Aiming the camera mathematically

Once you have the target center and required distance, position the camera on a sphere around the target and aim it using Blender's `to_track_quat()` method:

```python
def position_and_aim_camera(camera, target_center, distance, 
                            elevation_deg=30, azimuth_deg=45):
    """Position camera at specified angles and aim at target."""
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg)
    
    # Spherical to Cartesian coordinates
    camera.location = Vector((
        target_center.x + distance * math.cos(elevation) * math.cos(azimuth),
        target_center.y + distance * math.cos(elevation) * math.sin(azimuth),
        target_center.z + distance * math.sin(elevation)
    ))
    
    # Aim camera using track quaternion
    # -Z is camera forward, Y is camera up
    direction = target_center - camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
```

## Universal lighting that works for any model

HDRI environment lighting provides the most universally flattering illumination without manual adjustment. Create it programmatically:

```python
def setup_hdri_environment(hdri_path, strength=1.0):
    """Create HDRI world lighting from an environment map."""
    world = bpy.data.worlds.new("IconWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    
    # Build node tree
    output = nodes.new('ShaderNodeOutputWorld')
    background = nodes.new('ShaderNodeBackground')
    env_texture = nodes.new('ShaderNodeTexEnvironment')
    mapping = nodes.new('ShaderNodeMapping')
    tex_coord = nodes.new('ShaderNodeTexCoord')
    
    # Load HDRI image
    env_texture.image = bpy.data.images.load(hdri_path)
    background.inputs['Strength'].default_value = strength
    
    # Connect nodes
    links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], env_texture.inputs['Vector'])
    links.new(env_texture.outputs['Color'], background.inputs['Color'])
    links.new(background.outputs['Background'], output.inputs['Surface'])
```

If no HDRI is available, a **three-point lighting rig** works reliably for icon-style renders. Position a key light at 45° front-left, fill light at 45° front-right with lower intensity, and rim light behind the subject:

```python
def create_three_point_lighting(target, distance=5.0):
    """Create classic 3-point lighting setup."""
    def make_area_light(name, location, energy, size):
        light_data = bpy.data.lights.new(name, 'AREA')
        light_data.energy = energy
        light_data.size = size
        light_obj = bpy.data.objects.new(name, light_data)
        bpy.context.collection.objects.link(light_obj)
        light_obj.location = location
        # Aim at target
        direction = target - light_obj.location
        light_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
        return light_obj
    
    height = distance * 0.6
    # Key: main light, 45° left
    make_area_light("Key", (distance * 0.7, -distance * 0.7, height), 1000, 2.0)
    # Fill: softer, 45° right  
    make_area_light("Fill", (-distance * 0.7, -distance * 0.7, height * 0.7), 400, 3.0)
    # Rim: behind subject, creates edge definition
    make_area_light("Rim", (0, distance, height * 1.5), 600, 1.5)
```

## Headless rendering configuration

Run Blender without GUI using the `-b` flag, with Python script via `-P`. **Argument order matters**—set output path before triggering render:

```bash
blender -b --factory-startup -P render_icon.py -- input.glb output.png
```

The complete script structure for headless operation:

```python
#!/usr/bin/env python3
"""Headless Blender icon renderer with mathematical camera positioning."""
import sys
import math
import bpy
from mathutils import Vector

def configure_render_settings(width=512, height=512):
    """Set up render output for transparent PNG icons."""
    scene = bpy.context.scene
    render = scene.render
    
    render.engine = 'CYCLES'  # Use CYCLES for true headless
    render.resolution_x = width
    render.resolution_y = height
    render.resolution_percentage = 100
    render.film_transparent = True  # CRITICAL for transparent background
    
    render.image_settings.file_format = 'PNG'
    render.image_settings.color_mode = 'RGBA'  # Must be RGBA, not RGB
    render.image_settings.color_depth = '8'
    
    # Cycles quality settings
    scene.cycles.samples = 128
    scene.cycles.use_denoising = True

def get_renderable_objects():
    """Get only objects that will actually appear in render."""
    return [obj for obj in bpy.context.scene.objects 
            if obj.type == 'MESH' and not obj.hide_render]

def frame_objects_in_camera(camera, objects, padding=1.1, 
                            elevation=30, azimuth=45):
    """Complete camera setup: position, aim, and clip planes."""
    center, radius = get_bounding_sphere(objects)
    
    if camera.data.type == 'PERSP':
        fov = 2 * math.atan(camera.data.sensor_width / (2 * camera.data.lens))
        distance = (radius * padding) / math.tan(fov / 2)
    else:
        camera.data.ortho_scale = radius * 2 * padding
        distance = radius * 3
    
    # Position on sphere around target
    elev_rad = math.radians(elevation)
    azim_rad = math.radians(azimuth)
    camera.location = Vector((
        center.x + distance * math.cos(elev_rad) * math.cos(azim_rad),
        center.y + distance * math.cos(elev_rad) * math.sin(azim_rad),
        center.z + distance * math.sin(elev_rad)
    ))
    
    # Aim at center
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    
    # Set clip planes with margin
    camera.data.clip_start = max(0.01, distance - radius * 2)
    camera.data.clip_end = distance + radius * 3

def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    
    glb_path = args[0] if len(args) > 0 else None
    output_path = args[1] if len(args) > 1 else "//icon.png"
    
    # Clear and import
    clear_scene()
    imported = import_glb(glb_path)
    
    # Create camera
    cam_data = bpy.data.cameras.new("IconCamera")
    camera = bpy.data.objects.new("IconCamera", cam_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    
    # Configure and render
    configure_render_settings()
    setup_hdri_environment("/path/to/studio.hdr")  # Or use 3-point lighting
    frame_objects_in_camera(camera, get_renderable_objects())
    
    bpy.context.scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)

if __name__ == "__main__":
    main()
```

For GPU rendering on headless servers, EEVEE requires a display (use Xvfb virtual framebuffer), while Cycles can run CPU-only without one:

```bash
# EEVEE on headless server
Xvfb :99 -screen 0 1024x720x16 &
DISPLAY=:99.0 blender -b -E BLENDER_EEVEE -P script.py

# Cycles with GPU
blender -b -P script.py -- --cycles-device CUDA
```

## Why renders fail and how to prevent it

**Camera clip planes are the most common cause of invisible objects.** If `clip_start` is larger than the distance to the nearest object surface, or `clip_end` is smaller than the distance to the farthest surface, geometry gets clipped. Always calculate clip planes from actual bounding sphere distance, not fixed values.

**Object origins at unexpected positions** cause bounding box miscalculation. A model's origin might be at world (0,0,0) while the mesh is meters away. The solution is always using `matrix_world @ Vector(corner)` for every bounding box corner—never assume origin placement.

**Hidden objects pollute bounding box calculations** when you iterate over all scene objects. An invisible helper mesh at extreme coordinates will expand your bounding box incorrectly. Filter with `obj.hide_render` and check collection visibility:

```python
def is_actually_renderable(obj):
    """Check object and all parent collections."""
    if obj.hide_render or obj.type != 'MESH':
        return False
    for collection in obj.users_collection:
        if collection.hide_render:
            return False
    return True
```

**Extreme scale differences** (microscopic or enormous models) cause numerical precision issues. If calculating very small or very large scale factors, normalize the model first:

```python
def normalize_model_size(obj, target_size=1.0):
    """Scale model to consistent size range."""
    dimensions = max(obj.dimensions)
    if dimensions < 1e-6:
        return  # Degenerate geometry
    scale_factor = target_size / dimensions
    obj.scale = (scale_factor,) * 3
    bpy.ops.object.transform_apply(scale=True)
```

## Conclusion

The mathematical foundation for reliable icon rendering centers on the bounding sphere and camera FOV relationship. By computing world-space bounds accurately, deriving camera distance from **`radius / tan(FOV/2)`**, and setting clip planes dynamically, you eliminate the guesswork that causes clipping and framing issues. The complete pipeline—GLB import with `import_pack_images=True`, world-space bounding calculation via `matrix_world` transforms, FOV-based camera positioning, and HDRI or 3-point lighting—produces consistent results across any model geometry without manual intervention.
