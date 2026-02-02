"""
Model Icon Generator for Blender

Renders isometric preview icons for all GLB models.
Applies the game's shared texture atlas.

Usage:
  blender --background --python scripts/generate_icons.py
"""

import bpy
import mathutils
import os
import math
from pathlib import Path

# Configuration
PROJECT_ROOT = "/home/siah/creative/city"
MODELS_DIR = "src/public/models"
TEXTURES_DIR = "src/public/textures"
OUTPUT_DIR = "src/public/icons/models"
ICON_SIZE = 256  # Render at 2x for better quality when scaled down

# Global texture reference
base_texture = None

def clear_scene():
    """Remove all objects from the scene"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Clear orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)

def load_game_texture():
    """Load the game's shared texture"""
    global base_texture
    texture_path = os.path.join(PROJECT_ROOT, TEXTURES_DIR, "base.png")

    if os.path.exists(texture_path):
        base_texture = bpy.data.images.load(texture_path)
        print(f"Loaded texture: {texture_path}")
    else:
        print(f"WARNING: Texture not found: {texture_path}")
        base_texture = None

def setup_camera():
    """Create orthographic camera for icon rendering"""
    cam_data = bpy.data.cameras.new("IconCamera")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 2.0  # Will be overridden per model

    camera = bpy.data.objects.new("IconCamera", cam_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera

def setup_lighting():
    """Create lighting for icons"""
    # Key light
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    key = bpy.context.object
    key.data.energy = 2.5
    key.rotation_euler = (math.radians(45), 0, math.radians(45))

    # Fill light
    bpy.ops.object.light_add(type='SUN', location=(-3, 3, 5))
    fill = bpy.context.object
    fill.data.energy = 1.0
    fill.rotation_euler = (math.radians(60), 0, math.radians(-135))

def setup_render_settings():
    """Configure render settings"""
    scene = bpy.context.scene

    scene.render.resolution_x = ICON_SIZE
    scene.render.resolution_y = ICON_SIZE
    scene.render.film_transparent = True

    # Use Eevee
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in dir(bpy.types) else 'BLENDER_EEVEE'

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

def apply_texture_to_objects(objects):
    """Apply the game's texture to all mesh objects"""
    global base_texture

    if not base_texture:
        return

    for obj in objects:
        if obj.type != 'MESH':
            continue

        # Create a new material with the texture
        mat = bpy.data.materials.new(name="GameMaterial")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Clear default nodes
        nodes.clear()

        # Create nodes
        output = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        tex_node = nodes.new('ShaderNodeTexImage')

        # Set texture
        tex_node.image = base_texture

        # Position nodes
        output.location = (300, 0)
        bsdf.location = (0, 0)
        tex_node.location = (-300, 0)

        # Link nodes
        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

        # Apply material to mesh
        obj.data.materials.clear()
        obj.data.materials.append(mat)

def import_model(filepath):
    """Import a GLB model"""
    bpy.ops.import_scene.gltf(filepath=filepath)
    return list(bpy.context.selected_objects)

def get_model_bounds(objects):
    """Get bounding box of all mesh objects"""
    min_co = [float('inf')] * 3
    max_co = [float('-inf')] * 3

    for obj in objects:
        if obj.type == 'MESH':
            for corner in obj.bound_box:
                world_corner = obj.matrix_world @ mathutils.Vector(corner)
                for i in range(3):
                    min_co[i] = min(min_co[i], world_corner[i])
                    max_co[i] = max(max_co[i], world_corner[i])

    if min_co[0] == float('inf'):
        return None, None

    center = [(min_co[i] + max_co[i]) / 2 for i in range(3)]
    return center, [max_co[i] - min_co[i] for i in range(3)]

def get_bounding_sphere(objects):
    """Return center and radius of bounding sphere encompassing all objects."""
    all_corners = []

    for obj in objects:
        if obj.type != 'MESH':
            continue
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ mathutils.Vector(corner)
            all_corners.append(world_corner)

    if not all_corners:
        return mathutils.Vector((0, 0, 0)), 1.0

    # Calculate bounding box
    min_corner = mathutils.Vector((
        min(c.x for c in all_corners),
        min(c.y for c in all_corners),
        min(c.z for c in all_corners)
    ))
    max_corner = mathutils.Vector((
        max(c.x for c in all_corners),
        max(c.y for c in all_corners),
        max(c.z for c in all_corners)
    ))

    # Center is midpoint of bounding box
    center = (min_corner + max_corner) / 2

    # Radius is distance from center to farthest corner
    radius = max((corner - center).length for corner in all_corners)

    # Ensure minimum radius to avoid issues with flat/tiny models
    radius = max(radius, 0.01)

    return center, radius

def fit_camera_to_model(camera, objects):
    """Position and configure orthographic camera to frame objects using bounding sphere."""
    # Reset camera shift
    camera.data.shift_x = 0
    camera.data.shift_y = 0

    # Get bounding sphere
    center, radius = get_bounding_sphere(objects)

    # For orthographic camera, ortho_scale = diameter with padding
    padding = 1.15
    camera.data.ortho_scale = radius * 2 * padding

    # Position camera at isometric angle, at safe distance from center
    # Using spherical coordinates: elevation ~35° (true isometric), azimuth -45°
    elevation = math.radians(35.264)  # arctan(1/sqrt(2)) for true isometric
    azimuth = math.radians(-45)  # Rotated 90° counter-clockwise from 45°
    distance = radius * 4  # Safe distance for orthographic (doesn't affect size)

    camera.location = mathutils.Vector((
        center.x + distance * math.cos(elevation) * math.cos(azimuth),
        center.y + distance * math.cos(elevation) * math.sin(azimuth),
        center.z + distance * math.sin(elevation)
    ))

    # Aim camera at center using track quaternion
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    # Set clip planes based on actual distance
    camera.data.clip_start = max(0.01, distance - radius * 2)
    camera.data.clip_end = distance + radius * 3

def delete_objects(objects):
    """Delete objects and their materials"""
    for obj in objects:
        # Remove materials
        if obj.type == 'MESH':
            for mat in obj.data.materials:
                if mat:
                    bpy.data.materials.remove(mat)
        bpy.data.objects.remove(obj, do_unlink=True)

def render_icon(output_path):
    """Render to file"""
    bpy.context.scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)

def generate_all_icons():
    """Main function"""
    models_path = os.path.join(PROJECT_ROOT, MODELS_DIR)
    output_path = os.path.join(PROJECT_ROOT, OUTPUT_DIR)

    print(f"Models: {models_path}")
    print(f"Output: {output_path}")

    os.makedirs(output_path, exist_ok=True)

    # Setup
    clear_scene()
    load_game_texture()
    camera = setup_camera()
    setup_lighting()
    setup_render_settings()

    # Process models
    glb_files = sorted(Path(models_path).glob("*.glb"))
    total = len(glb_files)
    print(f"Found {total} models")

    for i, glb_file in enumerate(glb_files):
        model_name = glb_file.stem
        icon_path = os.path.join(output_path, f"{model_name}.png")

        print(f"[{i+1}/{total}] {model_name}")

        try:
            objects = import_model(str(glb_file))

            if objects:
                apply_texture_to_objects(objects)
                fit_camera_to_model(camera, objects)
                render_icon(icon_path)
                delete_objects(objects)

        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nDone! {total} icons in {output_path}")

if __name__ == "__main__":
    generate_all_icons()
