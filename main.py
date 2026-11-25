import bpy
import bmesh
import math
import os
import sys
import random
import traceback
from mathutils import Vector, Matrix


# ==============================================================================
# 1. SCENE RESET & CLEANUP
# ==============================================================================
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)

    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)

    for light in list(bpy.data.lights):
        if light.users == 0:
            bpy.data.lights.remove(light)

    for cam in list(bpy.data.cameras):
        if cam.users == 0:
            bpy.data.cameras.remove(cam)


def get_or_create_collection(name):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def link_to_collection(obj, col):
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    col.objects.link(obj)


# ==============================================================================
# 2. GLTF-SAFE PBR MATERIALS & VERTEX COLOR SHADING
# ==============================================================================
def make_gltf_pbr_material(
    name,
    base_color,
    metallic=0.0,
    roughness=0.8,
    emission_color=None,
    emission_strength=0.0,
    use_vertex_color=False,
):
    """
    Creates clean Principled BSDF materials guaranteed to export accurately to GLB.
    Avoids procedural noise nodes that glTF drops and replaces with white.
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")

    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness

    if emission_color is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = emission_color
        bsdf.inputs["Emission Strength"].default_value = emission_strength

    if use_vertex_color:
        vcol = nt.nodes.new("ShaderNodeVertexColor")
        vcol.layer_name = "Col"
        nt.links.new(vcol.outputs["Color"], bsdf.inputs["Base Color"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def create_materials():
    mats = {}

    # Dark Gothic Masonry (Vertex-colored stone variation + clean fallback)
    mats["stone"] = make_gltf_pbr_material(
        "GothicStoneDark",
        base_color=(0.065, 0.068, 0.082, 1.0),
        metallic=0.05,
        roughness=0.84,
        use_vertex_color=True,
    )

    # Lighter Trim / Buttress Stone for Architectural Contrast
    mats["stone_trim"] = make_gltf_pbr_material(
        "GothicStoneTrim",
        base_color=(0.11, 0.115, 0.135, 1.0),
        metallic=0.08,
        roughness=0.76,
        use_vertex_color=True,
    )

    # Craggy Dark Mountain Cliff (Vertex-colored rock strata)
    mats["cliff"] = make_gltf_pbr_material(
        "CraggyCliffDark",
        base_color=(0.032, 0.034, 0.044, 1.0),
        metallic=0.0,
        roughness=0.94,
        use_vertex_color=True,
    )

    # Steep Dark Slate Spire Roofs
    mats["slate"] = make_gltf_pbr_material(
        "DarkSlateRoof",
        base_color=(0.025, 0.028, 0.038, 1.0),
        metallic=0.15,
        roughness=0.58,
    )

    # Wrought Iron Railings, Portcullis & Bats
    mats["iron"] = make_gltf_pbr_material(
        "WroughtIronBlack",
        base_color=(0.022, 0.022, 0.028, 1.0),
        metallic=0.78,
        roughness=0.42,
    )

    # Gargoyle Statue Dark Basalt
    mats["gargoyle"] = make_gltf_pbr_material(
        "GargoyleBasalt",
        base_color=(0.055, 0.058, 0.072, 1.0),
        metallic=0.22,
        roughness=0.52,
    )

    # Deep Crimson Velvet Banners
    mats["crimson"] = make_gltf_pbr_material(
        "CrimsonVelvetBanner",
        base_color=(0.38, 0.008, 0.015, 1.0),
        metallic=0.0,
        roughness=0.78,
    )

    # Wet Dark Cobblestone Bridge Deck
    mats["wet_stone"] = make_gltf_pbr_material(
        "WetBridgeCobble",
        base_color=(0.045, 0.048, 0.06, 1.0),
        metallic=0.12,
        roughness=0.24,
        use_vertex_color=True,
    )

    # Rich Saturated Crimson Stained Glass (Moderate emission so mobile GLB viewers keep deep red)
    mats["window_glow"] = make_gltf_pbr_material(
        "CrimsonWindowGlow",
        base_color=(0.75, 0.005, 0.012, 1.0),
        metallic=0.0,
        roughness=0.25,
        emission_color=(0.95, 0.01, 0.02, 1.0),
        emission_strength=2.2,
    )

    # Deep Red-Orange Brazier Fire
    mats["fire_glow"] = make_gltf_pbr_material(
        "BrazierFlameGlow",
        base_color=(0.85, 0.02, 0.005, 1.0),
        metallic=0.0,
        roughness=0.2,
        emission_color=(1.0, 0.035, 0.008, 1.0),
        emission_strength=2.8,
    )

    # Dark Gnarled Dead Tree Bark
    mats["bark"] = make_gltf_pbr_material(
        "DeadTreeBark",
        base_color=(0.028, 0.024, 0.026, 1.0),
        metallic=0.0,
        roughness=0.92,
    )

    return mats


def apply_vertex_color_variation(obj, base_rgb, dark_rgb, highlight_rgb, seed=42, ao_z_min=None, ao_z_max=None):
    """
    Bakes rich stone/rock shading directly into vertex colors ('Col') so mobile GLB
    viewers show detailed masonry & rock shadows without external texture files.
    """
    mesh = obj.data
    if not isinstance(mesh, bpy.types.Mesh):
        return

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()

    color_layer = bm.loops.layers.color.get("Col")
    if color_layer is None:
        color_layer = bm.loops.layers.color.new("Col")

    world_mat = obj.matrix_world
    for face in bm.faces:
        n_world = (world_mat.to_3x3() @ face.normal).normalized()
        up_factor = max(0.0, min(1.0, (n_world.z + 1.0) * 0.5))

        for loop in face.loops:
            v_world = world_mat @ loop.vert.co
            # Deterministic spatial stone block / rock grain pattern
            grain = (
                math.sin(v_world.x * 4.3 + v_world.z * 5.7 + seed) * 0.5
                + math.cos(v_world.y * 4.9 - v_world.z * 6.1) * 0.5
            )
            grain = (grain + 1.0) * 0.5  # [0, 1]

            # Height ambient occlusion gradient
            ao = 1.0
            if ao_z_min is not None and ao_z_max is not None and ao_z_max > ao_z_min:
                t_z = max(0.0, min(1.0, (v_world.z - ao_z_min) / (ao_z_max - ao_z_min)))
                ao = 0.52 + 0.48 * t_z

            # Blend dark -> base -> highlight
            if grain < 0.45:
                t = grain / 0.45
                r = dark_rgb[0] + (base_rgb[0] - dark_rgb[0]) * t
                g = dark_rgb[1] + (base_rgb[1] - dark_rgb[1]) * t
                b = dark_rgb[2] + (base_rgb[2] - dark_rgb[2]) * t
            else:
                t = (grain - 0.45) / 0.55
                r = base_rgb[0] + (highlight_rgb[0] - base_rgb[0]) * t * 0.65
                g = base_rgb[1] + (highlight_rgb[1] - base_rgb[1]) * t * 0.65
                b = base_rgb[2] + (highlight_rgb[2] - base_rgb[2]) * t * 0.65

            # Add subtle moonlight rim boost on upward/left-facing normals
            moon_boost = 0.82 + 0.35 * up_factor + max(0.0, -n_world.x) * 0.14
            r = min(1.0, r * ao * moon_boost)
            g = min(1.0, g * ao * moon_boost)
            b = min(1.0, b * ao * moon_boost)

            loop[color_layer] = (r, g, b, 1.0)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


# ==============================================================================
# 3. ARCHITECTURAL GEOMETRY HELPERS
# ==============================================================================
def create_box(name, location, scale, material, col, rotation=(0.0, 0.0, 0.0), bevel_width=0.03):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if bevel_width > 0.0:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.bevel(
            bm,
            geom=list(bm.edges),
            offset=bevel_width,
            segments=2,
            affect='EDGES',
        )
        bm.normal_update()
        bm.to_mesh(obj.data)
        bm.free()

    if material:
        obj.data.materials.append(material)
    link_to_collection(obj, col)
    return obj


def create_cylinder(name, location, radius, depth, material, col, vertices=16, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    if material:
        obj.data.materials.append(material)
    link_to_collection(obj, col)
    return obj


def create_cone(name, location, radius1, radius2, depth, material, col, vertices=16, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices,
        radius1=radius1,
        radius2=radius2,
        depth=depth,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    if material:
        obj.data.materials.append(material)
    link_to_collection(obj, col)
    return obj


def create_gothic_pointed_arch(name, location, width, height, depth, material, col, rotation=(0.0, 0.0, 0.0)):
    """Creates a clean pointed Gothic lancet arch with crisp bevelled edges."""
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    link_to_collection(obj, col)
    obj.location = location
    obj.rotation_euler = rotation

    bm = bmesh.new()
    half_w = width * 0.5
    spring_h = height * 0.52
    steps = 12

    profile = [(-half_w, 0.0), (-half_w, spring_h)]
    for i in range(1, steps + 1):
        t = i / steps
        x = -half_w * (1.0 - t)
        z = spring_h + (height - spring_h) * math.sin(t * math.pi * 0.5)
        profile.append((x, z))
    for i in range(1, steps + 1):
        t = i / steps
        x = half_w * t
        z = spring_h + (height - spring_h) * math.cos(t * math.pi * 0.5)
        profile.append((x, z))
    profile.append((half_w, 0.0))

    front_verts = [bm.verts.new((px, -depth * 0.5, pz)) for px, pz in profile]
    back_verts = [bm.verts.new((px, depth * 0.5, pz)) for px, pz in profile]

    bm.faces.new(front_verts)
    bm.faces.new(list(reversed(back_verts)))

    n = len(profile)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([front_verts[i], front_verts[j], back_verts[j], back_verts[i]])

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    if material:
        obj.data.materials.append(material)
    return obj


def create_framed_gothic_window(name, location, width, height, mats, col, rotation=(0.0, 0.0, 0.0)):
    """Builds a recessed stone Gothic window frame with vertical mullion & glowing crimson glass."""
    # Outer dark stone surround
    create_gothic_pointed_arch(
        f"{name}_Frame",
        location,
        width + 0.14,
        height + 0.14,
        0.22,
        mats["stone_trim"],
        col,
        rotation=rotation,
    )
    # Recessed glowing crimson glass pane (shifted slightly forward along local -Y)
    rot_mat = Matrix.Rotation(rotation[2], 3, 'Z')
    fwd_offset = rot_mat @ Vector((0.0, -0.04, 0.04))
    create_gothic_pointed_arch(
        f"{name}_Glass",
        Vector(location) + fwd_offset,
        width * 0.84,
        height * 0.88,
        0.18,
        mats["window_glow"],
        col,
        rotation=rotation,
    )
    # Central vertical stone mullion bar
    bar_offset = rot_mat @ Vector((0.0, -0.07, height * 0.44))
    create_box(
        f"{name}_Mullion",
        Vector(location) + bar_offset,
        (0.045, 0.16, height * 0.82),
        mats["stone_trim"],
        col,
        rotation=rotation,
        bevel_width=0.005,
    )


def add_battlements_row(prefix, start_pos, end_pos, height, merlon_w, merlon_d, count, material, col):
    p0 = Vector(start_pos)
    p1 = Vector(end_pos)
    for i in range(count):
        t = i / max(1, count - 1)
        pos = p0.lerp(p1, t)
        create_box(
            f"{prefix}_Merlon_{i}",
            (pos.x, pos.y, pos.z + height * 0.5),
            (merlon_w, merlon_d, height),
            material,
            col,
            bevel_width=0.02,
        )


def add_buttress_column(name, location, width, depth, height, mats, col):
    """Adds a stepped Gothic wall buttress to break up flat masonry surfaces."""
    x, y, z = location
    create_box(f"{name}_Lower", (x, y, z + height * 0.25), (width * 1.25, depth * 1.35, height * 0.5), mats["stone_trim"], col, bevel_width=0.025)
    create_box(f"{name}_Upper", (x, y + depth * 0.12, z + height * 0.72), (width, depth, height * 0.46), mats["stone_trim"], col, bevel_width=0.02)


# ==============================================================================
# 4. CRAGGY CLIFF & MOUNTAIN TERRAIN (PROPERLY CLEARED FOR BRIDGE)
# ==============================================================================
def build_cliff_and_mountains(mats, col):
    mesh = bpy.data.meshes.new("CastleCliff_Mesh")
    cliff = bpy.data.objects.new("CastleCliff", mesh)
    link_to_collection(cliff, col)

    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=64, y_segments=64, size=14.5)

    for v in bm.verts:
        x, y = v.co.x, v.co.y

        # Castle sits on a steep rocky crag centered around (0, 2.2)
        dx = x / 7.6
        dy = (y - 2.4) / 6.2
        radial = math.hypot(dx, dy)

        # Sharp angular rock crags
        crag1 = math.sin(x * 1.35 + y * 0.95) * 0.85
        crag2 = math.cos(x * 2.9 - y * 2.4) * 0.45
        crag3 = abs(math.sin(x * 4.8 + y * 4.1)) * 0.35
        ridge = crag1 + crag2 - crag3

        base_h = 6.8 - radial * 7.6 + ridge

        # Carve a deep chasm under the bridge (y < -1.8) so the bridge spans cleanly above empty air!
        if y < -1.6:
            chasm_depth = min(6.5, (-1.6 - y) * 1.35)
            center_gorge = math.exp(-(x * x) / 14.0) * 3.8
            base_h -= (chasm_depth + center_gorge)

        # Flat castle foundation plateau at z = 3.2 for y >= -1.8
        if y >= -1.8 and base_h > 3.2:
            base_h = 3.2

        v.co.z = max(-5.5, base_h)

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    cliff.data.materials.append(mats["cliff"])
    apply_vertex_color_variation(
        cliff,
        base_rgb=(0.045, 0.048, 0.062),
        dark_rgb=(0.015, 0.016, 0.022),
        highlight_rgb=(0.11, 0.12, 0.145),
        seed=17,
        ao_z_min=-4.0,
        ao_z_max=3.2,
    )

    # Distant Jagged Mountain Peaks on Left & Right Horizon
    peak_specs = [
        ("DistantPeak_Left1", (-18.5, 19.0, -2.5), 8.2, 16.0),
        ("DistantPeak_Left2", (-13.0, 23.0, -3.0), 6.2, 12.5),
        ("DistantPeak_Right1", (19.0, 18.5, -2.5), 8.6, 17.0),
        ("DistantPeak_Right2", (13.5, 22.5, -3.0), 6.5, 12.2),
    ]
    for idx, (name, loc, rad, h) in enumerate(peak_specs):
        cone = create_cone(name, loc, rad, 0.18, h, mats["cliff"], col, vertices=12)
        cone.scale = (1.25, 0.85, 1.0)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        apply_vertex_color_variation(
            cone,
            base_rgb=(0.035, 0.04, 0.055),
            dark_rgb=(0.012, 0.014, 0.02),
            highlight_rgb=(0.09, 0.105, 0.135),
            seed=90 + idx,
            ao_z_min=-3.0,
            ao_z_max=8.0,
        )


# ==============================================================================
# 5. GOTHIC TOWERS, SPIRES & CASTLE KEEP
# ==============================================================================
def build_gothic_tower(
    name,
    base_xy,
    base_z,
    radius,
    shaft_height,
    spire_height,
    mats,
    col,
    has_pinnacles=True,
    window_rows=2,
):
    bx, by = base_xy

    # Stepped Octagonal Stone Plinth
    create_cylinder(
        f"{name}_Plinth",
        (bx, by, base_z + 0.4),
        radius * 1.18,
        0.8,
        mats["stone_trim"],
        col,
        vertices=8,
    )

    # Main Octagonal Tower Shaft
    shaft_z = base_z + 0.8 + shaft_height * 0.5
    shaft = create_cylinder(
        f"{name}_Shaft",
        (bx, by, shaft_z),
        radius,
        shaft_height,
        mats["stone"],
        col,
        vertices=8,
    )
    apply_vertex_color_variation(
        shaft,
        base_rgb=(0.075, 0.078, 0.095),
        dark_rgb=(0.028, 0.03, 0.038),
        highlight_rgb=(0.15, 0.158, 0.185),
        seed=int(abs(bx * 13 + by * 7)),
        ao_z_min=base_z,
        ao_z_max=base_z + shaft_height,
    )

    # Vertical Corner Rib Pilasters around Octagonal Shaft
    for i in range(8):
        ang = math.radians(22.5 + i * 45)
        rx = bx + math.cos(ang) * (radius * 0.98)
        ry = by + math.sin(ang) * (radius * 0.98)
        create_box(
            f"{name}_Rib_{i}",
            (rx, ry, shaft_z),
            (radius * 0.14, radius * 0.14, shaft_height),
            mats["stone_trim"],
            col,
            rotation=(0.0, 0.0, ang),
            bevel_width=0.01,
        )

    # Corbelled Belfry Crown
    crown_z = base_z + 0.8 + shaft_height + 0.32
    create_cylinder(
        f"{name}_Crown",
        (bx, by, crown_z),
        radius * 1.22,
        0.64,
        mats["stone_trim"],
        col,
        vertices=8,
    )

    # Battlement Merlons around Crown
    num_merlons = 8
    for i in range(num_merlons):
        ang = (2.0 * math.pi * i) / num_merlons
        mx = bx + math.cos(ang) * (radius * 1.14)
        my = by + math.sin(ang) * (radius * 1.14)
        create_box(
            f"{name}_Merlon_{i}",
            (mx, my, crown_z + 0.48),
            (radius * 0.28, radius * 0.22, 0.38),
            mats["stone_trim"],
            col,
            rotation=(0.0, 0.0, ang),
            bevel_width=0.015,
        )

    # Tall Steep Octagonal Slate Spire
    spire_z = crown_z + 0.32 + spire_height * 0.5
    create_cone(
        f"{name}_Spire",
        (bx, by, spire_z),
        radius * 1.12,
        0.025,
        spire_height,
        mats["slate"],
        col,
        vertices=8,
    )

    # Iron Spire Finial Needle
    create_cylinder(
        f"{name}_Finial",
        (bx, by, spire_z + spire_height * 0.5 + 0.38),
        0.028,
        0.76,
        mats["iron"],
        col,
        vertices=6,
    )

    # Four Corner Pinnacles around Spire Base
    if has_pinnacles:
        for i in range(4):
            ang = math.radians(45 + i * 90)
            px = bx + math.cos(ang) * (radius * 1.08)
            py = by + math.sin(ang) * (radius * 1.08)
            create_cone(
                f"{name}_Pinnacle_{i}",
                (px, py, crown_z + 1.02),
                radius * 0.14,
                0.012,
                1.45,
                mats["slate"],
                col,
                vertices=6,
            )

    # Framed Glowing Red Gothic Windows
    for r in range(window_rows):
        wz = base_z + 1.3 + (r + 0.52) * (shaft_height / max(1, window_rows))
        for ang_deg in (-90, -45, -135):
            ang = math.radians(ang_deg)
            wx = bx + math.cos(ang) * (radius * 0.94)
            wy = by + math.sin(ang) * (radius * 0.94)
            create_framed_gothic_window(
                f"{name}_Win_{r}_{ang_deg}",
                (wx, wy, wz - 0.36),
                radius * 0.30,
                0.78,
                mats,
                col,
                rotation=(0.0, 0.0, ang + math.pi * 0.5),
            )


def build_castle_architecture(mats, col):
    plateau_z = 3.2

    # 1. Outer Curtain Walls with Buttresses & Battlements
    front_wall = create_box("OuterWall_Front", (0.0, -1.55, plateau_z + 1.75), (9.4, 0.95, 3.5), mats["stone"], col)
    left_wall = create_box("OuterWall_Left", (-4.85, 1.35, plateau_z + 1.75), (0.95, 6.4, 3.5), mats["stone"], col)
    right_wall = create_box("OuterWall_Right", (4.85, 1.35, plateau_z + 1.75), (0.95, 6.4, 3.5), mats["stone"], col)
    back_wall = create_box("OuterWall_Back", (0.0, 4.3, plateau_z + 1.95), (9.8, 0.95, 3.9), mats["stone"], col)

    for idx, wall_obj in enumerate((front_wall, left_wall, right_wall, back_wall)):
        apply_vertex_color_variation(
            wall_obj,
            base_rgb=(0.072, 0.075, 0.092),
            dark_rgb=(0.025, 0.028, 0.036),
            highlight_rgb=(0.145, 0.152, 0.18),
            seed=30 + idx,
            ao_z_min=plateau_z,
            ao_z_max=plateau_z + 3.8,
        )

    # Wall Buttresses along Front Curtain Wall
    for bx in (-4.1, -2.8, 2.8, 4.1):
        add_buttress_column(f"FrontButtress_{bx}", (bx, -2.05, plateau_z), 0.36, 0.38, 3.4, mats, col)

    # Crenellated Battlements along Front Wall
    add_battlements_row("FrontWallLeft", (-4.4, -1.92, plateau_z + 3.5), (-1.75, -1.92, plateau_z + 3.5), 0.44, 0.36, 0.30, 6, mats["stone_trim"], col)
    add_battlements_row("FrontWallRight", (1.75, -1.92, plateau_z + 3.5), (4.4, -1.92, plateau_z + 3.5), 0.44, 0.36, 0.30, 6, mats["stone_trim"], col)

    # 2. Main Inner Keep & Central Cathedral Nave
    keep_body = create_box("MainKeepBody", (0.0, 1.35, plateau_z + 2.9), (6.8, 4.5, 5.8), mats["stone"], col)
    central_nave = create_box("CentralNave", (0.0, 0.70, plateau_z + 4.65), (3.2, 3.5, 5.5), mats["stone"], col)
    upper_belfry = create_box("UpperBelfry", (0.0, 1.50, plateau_z + 7.55), (2.2, 2.1, 4.3), mats["stone"], col)

    for idx, body_obj in enumerate((keep_body, central_nave, upper_belfry)):
        apply_vertex_color_variation(
            body_obj,
            base_rgb=(0.078, 0.082, 0.098),
            dark_rgb=(0.028, 0.03, 0.04),
            highlight_rgb=(0.155, 0.165, 0.195),
            seed=50 + idx,
            ao_z_min=plateau_z,
            ao_z_max=plateau_z + 9.5,
        )

    # Steep Pitched Gothic Roofs
    gable_roof = create_cone(
        "CentralNaveRoof",
        (0.0, 0.70, plateau_z + 8.75),
        2.62,
        0.04,
        2.9,
        mats["slate"],
        col,
        vertices=4,
        rotation=(0.0, 0.0, math.radians(45)),
    )
    gable_roof.scale = (0.96, 1.25, 1.0)

    belfry_roof = create_cone(
        "UpperBelfryRoof",
        (0.0, 1.50, plateau_z + 11.3),
        1.82,
        0.03,
        3.3,
        mats["slate"],
        col,
        vertices=4,
        rotation=(0.0, 0.0, math.radians(45)),
    )
    belfry_roof.scale = (1.0, 0.95, 1.0)

    # Framed Glowing Gothic Windows on Central Nave & Belfry
    for idx, wx in enumerate((-0.76, 0.0, 0.76)):
        h = 2.15 if idx == 1 else 1.72
        create_framed_gothic_window(
            f"NaveFacadeWin_{idx}",
            (wx, -1.06, plateau_z + 4.35),
            0.48,
            h,
            mats,
            col,
        )

    for idx, wx in enumerate((-0.46, 0.46)):
        create_framed_gothic_window(
            f"BelfryFacadeWin_{idx}",
            (wx, 0.44, plateau_z + 7.35),
            0.36,
            1.62,
            mats,
            col,
        )

    # Wing Windows on Main Keep
    for side_sign in (-1.0, 1.0):
        for i in range(3):
            wx = side_sign * (1.92 + i * 0.85)
            create_framed_gothic_window(
                f"KeepWingWin_{side_sign}_{i}",
                (wx, -0.92, plateau_z + 3.70),
                0.35,
                1.30,
                mats,
                col,
            )

    # 3. Asymmetric Gothic Towers & Spires
    tower_configs = [
        ("Tower_FarLeft_Outpost", (-5.55, -0.55), plateau_z - 0.2, 0.70, 4.5, 2.5, False, 1),
        ("Tower_FrontLeft_Main", (-3.55, -1.35), plateau_z, 0.96, 6.3, 3.3, True, 2),
        ("Tower_FrontRight_Main", (3.55, -1.35), plateau_z, 0.96, 6.3, 3.3, True, 2),
        ("Tower_FarRight_Turret", (5.45, -0.35), plateau_z - 0.15, 0.90, 5.7, 3.1, True, 2),
        ("Tower_InnerLeft_Spire", (-1.98, -0.15), plateau_z + 1.2, 0.80, 7.7, 3.9, True, 2),
        ("Tower_InnerRight_Spire", (1.98, -0.15), plateau_z + 1.2, 0.80, 7.7, 3.9, True, 2),
        ("Tower_CrownLeft", (-1.18, 1.40), plateau_z + 4.5, 0.54, 5.5, 3.0, True, 1),
        ("Tower_CrownRight", (1.18, 1.40), plateau_z + 4.5, 0.54, 5.5, 3.0, True, 1),
        ("Tower_RearLeft", (-3.85, 3.65), plateau_z + 0.5, 0.92, 6.9, 3.5, True, 2),
        ("Tower_RearRight", (3.85, 3.65), plateau_z + 0.5, 0.92, 6.9, 3.5, True, 2),
    ]
    for cfg in tower_configs:
        build_gothic_tower(cfg[0], cfg[1], cfg[2], cfg[3], cfg[4], cfg[5], mats, col, cfg[6], cfg[7])

    # 4. Grand Pointed Entrance Gatehouse & Crimson Banners
    gatehouse = create_box("GatehouseFrame", (0.0, -1.85, plateau_z + 2.05), (2.75, 1.05, 4.1), mats["stone"], col)
    apply_vertex_color_variation(
        gatehouse,
        base_rgb=(0.075, 0.078, 0.095),
        dark_rgb=(0.025, 0.028, 0.036),
        highlight_rgb=(0.15, 0.158, 0.185),
        seed=77,
        ao_z_min=plateau_z,
        ao_z_max=plateau_z + 4.0,
    )

    # Layered Pointed Stone Arch Mouldings
    create_gothic_pointed_arch(
        "GrandGateArchOuter",
        (0.0, -2.38, plateau_z + 0.05),
        2.10,
        3.45,
        0.36,
        mats["stone_trim"],
        col,
    )
    create_gothic_pointed_arch(
        "GrandGateArchInner",
        (0.0, -2.44, plateau_z + 0.05),
        1.78,
        3.12,
        0.28,
        mats["stone"],
        col,
    )
    create_gothic_pointed_arch(
        "GrandGateGlowPortal",
        (0.0, -2.48, plateau_z + 0.05),
        1.52,
        2.82,
        0.16,
        mats["window_glow"],
        col,
    )

    # Wrought-Iron Portcullis Grille
    for i in range(-4, 5):
        create_cylinder(
            f"PortcullisVert_{i}",
            (i * 0.16, -2.54, plateau_z + 1.35),
            0.022,
            2.45,
            mats["iron"],
            col,
            vertices=6,
        )
    for j in range(4):
        create_cylinder(
            f"PortcullisHoriz_{j}",
            (0.0, -2.54, plateau_z + 0.55 + j * 0.52),
            0.020,
            1.42,
            mats["iron"],
            col,
            vertices=6,
            rotation=(0.0, math.radians(90), 0.0),
        )

    # Two Large Crimson Banners Flanking the Gatehouse
    for side_sign, label in ((-1.0, "Left"), (1.0, "Right")):
        bx = side_sign * 1.98
        by = -2.14
        bz = plateau_z + 2.40

        create_cylinder(
            f"BannerRod_{label}",
            (bx, by, bz + 1.18),
            0.036,
            0.98,
            mats["iron"],
            col,
            vertices=8,
            rotation=(0.0, math.radians(90), 0.0),
        )

        mesh = bpy.data.meshes.new(f"CrimsonBanner_{label}_Mesh")
        banner = bpy.data.objects.new(f"CrimsonBanner_{label}", mesh)
        link_to_collection(banner, col)
        banner.location = (bx, by, bz)

        bm = bmesh.new()
        w = 0.42
        top_z = 1.14
        bot_z = -1.18
        notch_z = -0.84
        v1 = bm.verts.new((-w, 0.0, top_z))
        v2 = bm.verts.new((w, 0.0, top_z))
        v3 = bm.verts.new((w, -0.04, bot_z))
        v4 = bm.verts.new((0.0, -0.02, notch_z))
        v5 = bm.verts.new((-w, -0.04, bot_z))
        bm.faces.new([v1, v2, v3, v4, v5])
        bm.normal_update()
        bm.to_mesh(mesh)
        bm.free()
        banner.data.materials.append(mats["crimson"])


# ==============================================================================
# 6. STONE ARCHED BRIDGE, GARGOYLE STATUES & FIRE BRAZIERS
# ==============================================================================
def build_gargoyle_statue(name, location, mats, col):
    """Builds a dark basalt winged gargoyle perched on a carved stone plinth."""
    gx, gy, gz = location
    create_box(f"{name}_PlinthBase", (gx, gy, gz + 0.55), (1.08, 1.18, 1.1), mats["stone_trim"], col)
    create_box(f"{name}_PlinthCap", (gx, gy, gz + 1.16), (1.24, 1.34, 0.20), mats["stone_trim"], col)

    torso_z = gz + 1.68
    create_cone(
        f"{name}_Torso",
        (gx, gy, torso_z),
        0.35,
        0.22,
        0.88,
        mats["gargoyle"],
        col,
        vertices=10,
        rotation=(math.radians(18), 0.0, 0.0),
    )
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.22, location=(gx, gy - 0.18, torso_z + 0.50))
    head = bpy.context.active_object
    head.name = f"{name}_Head"
    head.data.materials.append(mats["gargoyle"])
    link_to_collection(head, col)

    for h_sign in (-1.0, 1.0):
        create_cone(
            f"{name}_Horn_{h_sign}",
            (gx + h_sign * 0.14, gy - 0.16, torso_z + 0.72),
            0.05,
            0.008,
            0.34,
            mats["gargoyle"],
            col,
            vertices=6,
            rotation=(math.radians(-20), h_sign * math.radians(25), 0.0),
        )

    # Solid Thickened Bat Wings
    for w_sign in (-1.0, 1.0):
        wing_mesh = bpy.data.meshes.new(f"{name}_Wing_{w_sign}_Mesh")
        wing = bpy.data.objects.new(f"{name}_Wing_{w_sign}", wing_mesh)
        link_to_collection(wing, col)
        wing.location = (gx + w_sign * 0.22, gy + 0.10, torso_z + 0.26)

        bm = bmesh.new()
        pts = [
            (0.0, 0.0, 0.0),
            (w_sign * 0.68, 0.26, 0.78),
            (w_sign * 1.18, 0.16, 0.46),
            (w_sign * 0.94, 0.08, -0.15),
            (w_sign * 0.54, 0.04, -0.26),
        ]
        front_v = [bm.verts.new((p[0], p[1] - 0.03, p[2])) for p in pts]
        back_v = [bm.verts.new((p[0], p[1] + 0.03, p[2])) for p in pts]
        bm.faces.new(front_v)
        bm.faces.new(list(reversed(back_v)))
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            bm.faces.new([front_v[i], front_v[j], back_v[j], back_v[i]])
        bm.normal_update()
        bm.to_mesh(wing_mesh)
        bm.free()
        wing.data.materials.append(mats["gargoyle"])


def build_brazier(name, location, scale_mult, mats, col):
    bx, by, bz = location
    # Carved Stone Pedestal
    create_box(
        f"{name}_Pillar",
        (bx, by, bz + 0.32 * scale_mult),
        (0.48 * scale_mult, 0.48 * scale_mult, 0.64 * scale_mult),
        mats["stone_trim"],
        col,
        bevel_width=0.02,
    )
    # Dark Iron Fire Bowl
    create_cone(
        f"{name}_Bowl",
        (bx, by, bz + 0.76 * scale_mult),
        0.18 * scale_mult,
        0.44 * scale_mult,
        0.26 * scale_mult,
        mats["iron"],
        col,
        vertices=12,
    )
    # Rich Crimson-Orange Flame Core
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.24 * scale_mult, location=(bx, by, bz + 0.98 * scale_mult))
    flame = bpy.context.active_object
    flame.name = f"{name}_Flame"
    flame.scale = (0.92, 0.92, 1.55)
    flame.data.materials.append(mats["fire_glow"])
    link_to_collection(flame, col)


def build_bridge_and_foreground(mats, col):
    plateau_z = 3.2
    slope_deg = -7.2
    slope_rad = math.radians(slope_deg)

    # Sloped Stone Bridge Deck spanning cleanly over the carved chasm
    deck = create_box(
        "StoneBridgeDeck",
        (0.0, -6.5, plateau_z - 0.62),
        (2.65, 9.0, 0.48),
        mats["wet_stone"],
        col,
        rotation=(slope_rad, 0.0, 0.0),
        bevel_width=0.025,
    )
    apply_vertex_color_variation(
        deck,
        base_rgb=(0.055, 0.06, 0.075),
        dark_rgb=(0.02, 0.022, 0.03),
        highlight_rgb=(0.12, 0.13, 0.16),
        seed=88,
    )

    # Deep Stone Support Piers & Side Arches under the Bridge
    for idx, py in enumerate((-3.8, -6.8, -9.8)):
        pz = plateau_z - 2.65 - idx * 0.40
        pier = create_box(f"BridgePier_{idx}", (0.0, py, pz), (2.55, 0.90, 4.4), mats["stone"], col)
        apply_vertex_color_variation(
            pier,
            base_rgb=(0.065, 0.068, 0.085),
            dark_rgb=(0.022, 0.024, 0.032),
            highlight_rgb=(0.13, 0.138, 0.165),
            seed=110 + idx,
        )

    # Stone Parapet Walls & Wrought-Iron Spiked Railings
    for side_sign, label in ((-1.0, "Left"), (1.0, "Right")):
        px = side_sign * 1.20
        create_box(
            f"BridgeParapet_{label}",
            (px, -6.5, plateau_z - 0.24),
            (0.24, 9.0, 0.50),
            mats["stone_trim"],
            col,
            rotation=(slope_rad, 0.0, 0.0),
            bevel_width=0.015,
        )
        # Top iron rail bar
        create_box(
            f"BridgeTopRail_{label}",
            (px, -6.5, plateau_z + 0.24),
            (0.05, 8.8, 0.05),
            mats["iron"],
            col,
            rotation=(slope_rad, 0.0, 0.0),
            bevel_width=0.005,
        )
        for i in range(15):
            fy = -2.4 - i * 0.58
            fz = plateau_z + 0.26 - (i * 0.58) * math.tan(abs(slope_rad))
            create_cylinder(f"BridgeRailPost_{label}_{i}", (px, fy, fz), 0.022, 0.52, mats["iron"], col, vertices=6)

    # Twin Gargoyle Guardians Flanking the Bridge Entrance
    build_gargoyle_statue("Gargoyle_Left", (-1.75, -2.55, plateau_z - 0.15), mats, col)
    build_gargoyle_statue("Gargoyle_Right", (1.75, -2.55, plateau_z - 0.15), mats, col)

    # Six Fire Braziers Along the Bridge
    brazier_specs = [
        ("Brazier_GateLeft", (-1.18, -2.65, plateau_z - 0.05), 0.72),
        ("Brazier_GateRight", (1.18, -2.65, plateau_z - 0.05), 0.72),
        ("Brazier_MidLeft", (-1.20, -5.35, plateau_z - 0.39), 0.86),
        ("Brazier_MidRight", (1.20, -5.35, plateau_z - 0.39), 0.86),
        ("Brazier_ForeLeft", (-1.24, -8.35, plateau_z - 0.78), 1.06),
        ("Brazier_ForeRight", (1.24, -8.35, plateau_z - 0.78), 1.22),
    ]
    for b_name, loc, sc in brazier_specs:
        build_brazier(b_name, loc, sc, mats, col)


# ==============================================================================
# 7. ATMOSPHERIC SILHOUETTES: DEAD TREES & FLYING BATS
# ==============================================================================
def build_dead_tree(name, root_loc, seed_val, mats, col):
    rng = random.Random(seed_val)
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    link_to_collection(obj, col)
    obj.location = root_loc

    bm = bmesh.new()

    def grow_branch(p_start, direction, length, radius, depth):
        if depth <= 0 or radius < 0.015:
            return
        p_end = p_start + direction.normalized() * length

        perp1 = direction.orthogonal().normalized()
        perp2 = direction.cross(perp1).normalized()
        sides = 6
        ring0 = []
        ring1 = []
        for s in range(sides):
            ang = (2.0 * math.pi * s) / sides
            offset = perp1 * math.cos(ang) + perp2 * math.sin(ang)
            ring0.append(bm.verts.new(p_start + offset * radius))
            ring1.append(bm.verts.new(p_end + offset * (radius * 0.66)))

        for s in range(sides):
            ns = (s + 1) % sides
            bm.faces.new([ring0[s], ring0[ns], ring1[ns], ring1[s]])

        for _ in range(2):
            jitter = Vector((
                rng.uniform(-0.58, 0.58),
                rng.uniform(-0.35, 0.35),
                rng.uniform(0.18, 0.68),
            ))
            new_dir = (direction.normalized() + jitter).normalized()
            grow_branch(p_end, new_dir, length * rng.uniform(0.68, 0.84), radius * 0.65, depth - 1)

    grow_branch(Vector((0.0, 0.0, 0.0)), Vector((0.12, 0.04, 1.0)), 1.85, 0.24, 5)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj.data.materials.append(mats["bark"])


def build_bat(name, location, scale_val, rotation_euler, mats, col):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bat = bpy.data.objects.new(name, mesh)
    link_to_collection(bat, col)
    bat.location = location
    bat.rotation_euler = rotation_euler
    bat.scale = (scale_val, scale_val, scale_val)

    bm = bmesh.new()
    v_head = bm.verts.new((0.0, -0.18, 0.04))
    v_tail = bm.verts.new((0.0, 0.22, -0.02))
    v_l_shoulder = bm.verts.new((-0.08, -0.05, 0.02))
    v_r_shoulder = bm.verts.new((0.08, -0.05, 0.02))
    bm.faces.new([v_head, v_r_shoulder, v_tail, v_l_shoulder])

    for s in (-1.0, 1.0):
        w_elbow = bm.verts.new((s * 0.36, -0.12, 0.14))
        w_tip = bm.verts.new((s * 0.84, -0.02, 0.08))
        w_mid_scallop = bm.verts.new((s * 0.54, 0.14, 0.02))
        w_inner_scallop = bm.verts.new((s * 0.22, 0.16, 0.0))
        shoulder = v_r_shoulder if s > 0 else v_l_shoulder
        bm.faces.new([shoulder, w_elbow, w_tip, w_mid_scallop, w_inner_scallop, v_tail])

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    bat.data.materials.append(mats["iron"])


def build_atmosphere_props(mats, col):
    # Gnarled Dead Trees Framing Left & Right Foreground
    build_dead_tree("DeadTree_Left", (-5.8, -7.2, -1.2), 101, mats, col)
    build_dead_tree("DeadTree_Right", (6.0, -6.8, -1.0), 202, mats, col)

    # Flock of Bats Silhouetted Across the Sky
    bat_specs = [
        ("Bat_HeroMoon", (-4.4, -3.5, 9.2), 1.35, (math.radians(15), math.radians(-12), math.radians(18))),
        ("Bat_HeroRight", (4.8, -4.2, 9.8), 1.25, (math.radians(18), math.radians(15), math.radians(-22))),
        ("Bat_Swarm_1", (-4.8, -2.0, 7.9), 0.55, (math.radians(10), 0.0, math.radians(12))),
        ("Bat_Swarm_2", (-5.3, -1.8, 7.4), 0.45, (math.radians(12), 0.0, math.radians(8))),
        ("Bat_Swarm_3", (-3.9, -2.2, 8.3), 0.50, (math.radians(8), 0.0, math.radians(20))),
        ("Bat_Swarm_4", (3.2, -1.5, 8.8), 0.52, (math.radians(14), 0.0, math.radians(-15))),
        ("Bat_Swarm_5", (3.8, -1.8, 8.2), 0.60, (math.radians(10), 0.0, math.radians(-25))),
        ("Bat_Swarm_6", (2.6, -1.2, 9.4), 0.42, (math.radians(12), 0.0, math.radians(-10))),
    ]
    for b_name, loc, sc, rot in bat_specs:
        build_bat(b_name, loc, sc, rot, mats, col)


# ==============================================================================
# 8. LIGHTING, WORLD SKY & CAMERA FRAMING
# ==============================================================================
def setup_lighting_and_camera(col):
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("GothicNightWorld")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.018, 0.024, 0.038, 1.0)
        bg.inputs["Strength"].default_value = 0.75

    # Cold Blue Moonlight Key Light
    bpy.ops.object.light_add(type='SUN', location=(-9.0, 6.0, 14.0))
    moon_sun = bpy.context.active_object
    moon_sun.name = "MoonDirectionalLight"
    moon_sun.data.energy = 2.8
    moon_sun.data.color = (0.58, 0.74, 1.0)
    moon_sun.rotation_euler = (math.radians(54), math.radians(-22), math.radians(-38))
    link_to_collection(moon_sun, col)

    # Crimson Portal & Brazier Point Lights
    point_lights = [
        ("CrimsonGateLight", (0.0, -2.8, 4.6), 380.0, (1.0, 0.02, 0.04)),
        ("BridgeFireLight_Mid", (0.0, -5.35, 3.6), 150.0, (1.0, 0.08, 0.02)),
        ("BridgeFireLight_Fore", (0.8, -8.35, 3.2), 190.0, (1.0, 0.06, 0.015)),
        ("UpperKeepCrimsonGlow", (0.0, -0.5, 8.5), 240.0, (1.0, 0.02, 0.04)),
    ]
    for l_name, loc, energy, color in point_lights:
        bpy.ops.object.light_add(type='POINT', location=loc)
        pt = bpy.context.active_object
        pt.name = l_name
        pt.data.energy = energy
        pt.data.color = color
        link_to_collection(pt, col)

    # Hero Perspective Camera
    bpy.ops.object.camera_add(location=(2.85, -13.2, 4.95))
    cam = bpy.context.active_object
    cam.name = "GothicCastleCamera"
    cam.data.lens = 28.0
    cam.data.clip_end = 250.0

    target = Vector((-0.15, 0.5, 6.2))
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    link_to_collection(cam, col)


# ==============================================================================
# 9. MAIN EXECUTION & GLB EXPORT
# ==============================================================================
def main():
    try:
        clear_scene()

        col_terrain = get_or_create_collection("01_Cliff_And_Terrain")
        col_castle = get_or_create_collection("02_Gothic_Castle")
        col_bridge = get_or_create_collection("03_Bridge_And_Guardians")
        col_props = get_or_create_collection("04_Trees_And_Bats")
        col_lights = get_or_create_collection("05_Lights_And_Camera")

        mats = create_materials()

        build_cliff_and_mountains(mats, col_terrain)
        build_castle_architecture(mats, col_castle)
        build_bridge_and_foreground(mats, col_bridge)
        build_atmosphere_props(mats, col_props)
        setup_lighting_and_camera(col_lights)

        os.makedirs("out", exist_ok=True)
        bpy.ops.export_scene.gltf(
            filepath="out/model.glb",
            export_format='GLB',
            use_selection=False,
            export_apply=True,
            export_attributes=True,
        )
        print("Successfully generated fixed Gothic Castle scene and exported out/model.glb")

    except Exception as e:
        print(f"Blender script failed: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
