import bpy
import bmesh
import math
import os
import sys
import random
import traceback
from mathutils import Vector, Euler


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
# 2. PROCEDURAL GOTHIC MATERIALS
# ==============================================================================
def create_materials():
    mats = {}

    # Dark Gothic Masonry Stone
    stone = bpy.data.materials.new("GothicMasonryStone")
    stone.use_nodes = True
    nt = stone.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.85

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    noise_macro = nt.nodes.new("ShaderNodeTexNoise")
    noise_macro.inputs["Scale"].default_value = 6.5
    noise_macro.inputs["Detail"].default_value = 10.0
    noise_macro.inputs["Roughness"].default_value = 0.68

    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
    voronoi.feature = 'DISTANCE_TO_EDGE'
    voronoi.inputs["Scale"].default_value = 16.0

    mix_factor = nt.nodes.new("ShaderNodeMath")
    mix_factor.operation = 'MULTIPLY_ADD'
    mix_factor.inputs[1].default_value = 0.45

    color_mix = nt.nodes.new("ShaderNodeMix")
    color_mix.data_type = 'RGBA'
    color_mix.inputs["A"].default_value = (0.075, 0.078, 0.09, 1.0)
    color_mix.inputs["B"].default_value = (0.18, 0.185, 0.21, 1.0)

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.42
    bump.inputs["Distance"].default_value = 0.06

    nt.links.new(tex_coord.outputs["Object"], noise_macro.inputs["Vector"])
    nt.links.new(tex_coord.outputs["Object"], voronoi.inputs["Vector"])
    nt.links.new(voronoi.outputs["Distance"], mix_factor.inputs[0])
    nt.links.new(noise_macro.outputs["Fac"], mix_factor.inputs[2])
    nt.links.new(mix_factor.outputs["Value"], color_mix.inputs["Factor"])
    nt.links.new(color_mix.outputs["Result"], bsdf.inputs["Base Color"])
    nt.links.new(mix_factor.outputs["Value"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mats["stone"] = stone

    # Craggy Cliff Rock
    cliff = bpy.data.materials.new("CraggyCliffRock")
    cliff.use_nodes = True
    nt = cliff.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.93

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 4.2
    noise.inputs["Detail"].default_value = 12.0
    noise.inputs["Roughness"].default_value = 0.72

    color_mix = nt.nodes.new("ShaderNodeMix")
    color_mix.data_type = 'RGBA'
    color_mix.inputs["A"].default_value = (0.04, 0.042, 0.05, 1.0)
    color_mix.inputs["B"].default_value = (0.14, 0.145, 0.165, 1.0)

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.65
    bump.inputs["Distance"].default_value = 0.12

    nt.links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], color_mix.inputs["Factor"])
    nt.links.new(color_mix.outputs["Result"], bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mats["cliff"] = cliff

    # Slate Spire Roof
    slate = bpy.data.materials.new("DarkSlateRoof")
    slate.use_nodes = True
    bsdf = slate.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.055, 0.06, 0.075, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.62
    mats["slate"] = slate

    # Wrought Iron / Gargoyle Bronze-Stone
    iron = bpy.data.materials.new("WroughtIronDark")
    iron.use_nodes = True
    bsdf = iron.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.05, 0.058, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.75
    bsdf.inputs["Roughness"].default_value = 0.45
    mats["iron"] = iron

    # Gargoyle Statue Material
    gargoyle = bpy.data.materials.new("GargoyleBasalt")
    gargoyle.use_nodes = True
    bsdf = gargoyle.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.11, 0.115, 0.13, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.15
    bsdf.inputs["Roughness"].default_value = 0.58
    mats["gargoyle"] = gargoyle

    # Crimson Velvet Banners
    crimson = bpy.data.materials.new("CrimsonBannerCloth")
    crimson.use_nodes = True
    bsdf = crimson.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.48, 0.015, 0.03, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.80
    mats["crimson"] = crimson

    # Wet Cobblestone Bridge Deck
    wet_stone = bpy.data.materials.new("WetCobblestone")
    wet_stone.use_nodes = True
    bsdf = wet_stone.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.09, 0.095, 0.11, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.28
    mats["wet_stone"] = wet_stone

    # Red Stained Glass Window Emission
    window_glow = bpy.data.materials.new("CrimsonWindowGlow")
    window_glow.use_nodes = True
    bsdf = window_glow.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (1.0, 0.03, 0.05, 1.0)
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.025, 0.04, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 18.0
    mats["window_glow"] = window_glow

    # Brazier Fire Emission
    fire_glow = bpy.data.materials.new("BrazierFlameGlow")
    fire_glow.use_nodes = True
    bsdf = fire_glow.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (1.0, 0.09, 0.02, 1.0)
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.06, 0.015, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 28.0
    mats["fire_glow"] = fire_glow

    # Dead Tree Bark
    bark = bpy.data.materials.new("DeadTreeBark")
    bark.use_nodes = True
    bsdf = bark.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.045, 0.04, 0.042, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.92
    mats["bark"] = bark

    return mats


# ==============================================================================
# 3. HELPER GEOMETRY BUILDERS (BMESH & PROCEDURAL)
# ==============================================================================
def create_box(name, location, scale, material, col, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
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
    """Creates a pointed Gothic arch block using BMesh."""
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    link_to_collection(obj, col)
    obj.location = location
    obj.rotation_euler = rotation

    bm = bmesh.new()
    half_w = width * 0.5
    spring_h = height * 0.55
    steps = 10

    profile = []
    profile.append((-half_w, 0.0))
    profile.append((-half_w, spring_h))

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


def add_battlements_row(prefix, start_pos, end_pos, height, merlon_w, merlon_d, count, material, col):
    """Places crenellated battlements evenly between start_pos and end_pos."""
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
        )


# ==============================================================================
# 4. CRAGGY CLIFF & MOUNTAIN TERRAIN
# ==============================================================================
def build_cliff_and_mountains(mats, col):
    # Main Craggy Castle Cliff
    mesh = bpy.data.meshes.new("CastleCliff_Mesh")
    cliff = bpy.data.objects.new("CastleCliff", mesh)
    link_to_collection(cliff, col)

    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=56, y_segments=56, size=14.0)

    for v in bm.verts:
        x, y = v.co.x, v.co.y
        # Elliptical mountain footprint concentrated under the castle (y around 1.5)
        dx = x / 8.8
        dy = (y - 1.5) / 7.5
        radial = math.hypot(dx, dy)

        # Stratified rock crags
        crag1 = math.sin(x * 1.15 + y * 0.85) * 0.95
        crag2 = math.cos(x * 2.6 - y * 2.1) * 0.42
        crag3 = math.sin(x * 5.2 + y * 4.7) * 0.18
        ridge = crag1 + crag2 + crag3

        base_h = 7.4 - radial * 6.8 + ridge
        # Carve bridge approach channel in front (-y)
        if y < -2.2 and abs(x) < 2.4:
            channel_blend = max(0.0, 1.0 - abs(x) / 2.4)
            base_h -= channel_blend * 2.8

        # Flatten summit plateau at z = 3.2
        if base_h > 3.2:
            base_h = 3.2 + (base_h - 3.2) * 0.12

        v.co.z = max(-4.5, base_h)

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    cliff.data.materials.append(mats["cliff"])

    # Distant Gothic Mountain Peaks (Left & Right Silhouettes)
    peak_specs = [
        ("DistantPeak_Left", (-19.0, 18.0, -2.0), 8.5, 16.5),
        ("DistantPeak_LeftMid", (-13.5, 22.0, -2.5), 6.5, 13.0),
        ("DistantPeak_Right", (19.5, 17.5, -2.0), 9.0, 17.5),
        ("DistantPeak_RightMid", (14.0, 21.5, -2.5), 6.8, 12.8),
    ]
    for name, loc, rad, h in peak_specs:
        cone = create_cone(name, loc, rad, 0.25, h, mats["cliff"], col, vertices=14)
        cone.scale = (1.2, 0.9, 1.0)


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
    # Plinth
    create_cylinder(
        f"{name}_Plinth",
        (bx, by, base_z + 0.35),
        radius * 1.14,
        0.7,
        mats["stone"],
        col,
        vertices=12,
    )

    # Main Octagonal/Dodecagonal Shaft
    shaft_z = base_z + 0.7 + shaft_height * 0.5
    create_cylinder(
        f"{name}_Shaft",
        (bx, by, shaft_z),
        radius,
        shaft_height,
        mats["stone"],
        col,
        vertices=12,
    )

    # Corbelled Crown / Belfry Gallery
    crown_z = base_z + 0.7 + shaft_height + 0.3
    create_cylinder(
        f"{name}_Crown",
        (bx, by, crown_z),
        radius * 1.18,
        0.6,
        mats["stone"],
        col,
        vertices=12,
    )

    # Crenellations around Crown
    num_merlons = 10
    for i in range(num_merlons):
        ang = (2.0 * math.pi * i) / num_merlons
        mx = bx + math.cos(ang) * (radius * 1.12)
        my = by + math.sin(ang) * (radius * 1.12)
        create_box(
            f"{name}_Merlon_{i}",
            (mx, my, crown_z + 0.45),
            (radius * 0.24, radius * 0.24, 0.36),
            mats["stone"],
            col,
            rotation=(0.0, 0.0, ang),
        )

    # Tall Pointed Gothic Spire
    spire_z = crown_z + 0.3 + spire_height * 0.5
    create_cone(
        f"{name}_Spire",
        (bx, by, spire_z),
        radius * 1.08,
        0.03,
        spire_height,
        mats["slate"],
        col,
        vertices=12,
    )

    # Finial Needle on Tip
    create_cylinder(
        f"{name}_Finial",
        (bx, by, spire_z + spire_height * 0.5 + 0.35),
        0.03,
        0.7,
        mats["iron"],
        col,
        vertices=8,
    )

    # Corner Pinnacles around Spire Base
    if has_pinnacles:
        for i in range(4):
            ang = math.radians(45 + i * 90)
            px = bx + math.cos(ang) * (radius * 1.05)
            py = by + math.sin(ang) * (radius * 1.05)
            create_cone(
                f"{name}_Pinnacle_{i}",
                (px, py, crown_z + 0.95),
                radius * 0.14,
                0.015,
                1.35,
                mats["slate"],
                col,
                vertices=8,
            )

    # Red Glowing Gothic Lancet Windows
    for r in range(window_rows):
        wz = base_z + 1.2 + (r + 0.55) * (shaft_height / max(1, window_rows))
        for ang_deg in (-90, -45, -135, 0, 180):
            ang = math.radians(ang_deg)
            wx = bx + math.cos(ang) * (radius * 0.96)
            wy = by + math.sin(ang) * (radius * 0.96)
            create_gothic_pointed_arch(
                f"{name}_Win_{r}_{ang_deg}",
                (wx, wy, wz - 0.32),
                radius * 0.28,
                0.72,
                0.18,
                mats["window_glow"],
                col,
                rotation=(0.0, 0.0, ang + math.pi * 0.5),
            )


def build_castle_architecture(mats, col):
    plateau_z = 3.2

    # 1. Outer Curtain Walls & Bastions
    create_box("OuterWall_Front", (0.0, -1.65, plateau_z + 1.65), (9.2, 0.85, 3.3), mats["stone"], col)
    create_box("OuterWall_Left", (-4.8, 1.2, plateau_z + 1.65), (0.85, 6.2, 3.3), mats["stone"], col)
    create_box("OuterWall_Right", (4.8, 1.2, plateau_z + 1.65), (0.85, 6.2, 3.3), mats["stone"], col)
    create_box("OuterWall_Back", (0.0, 4.1, plateau_z + 1.85), (9.6, 0.9, 3.7), mats["stone"], col)

    # Battlements along Outer Front Wall
    add_battlements_row("FrontWallLeft", (-4.4, -1.95, plateau_z + 3.3), (-1.65, -1.95, plateau_z + 3.3), 0.42, 0.34, 0.28, 6, mats["stone"], col)
    add_battlements_row("FrontWallRight", (1.65, -1.95, plateau_z + 3.3), (4.4, -1.95, plateau_z + 3.3), 0.42, 0.34, 0.28, 6, mats["stone"], col)

    # 2. Main Inner Keep & Central Cathedral-Style Great Hall
    create_box("MainKeepBody", (0.0, 1.25, plateau_z + 2.8), (6.6, 4.4, 5.6), mats["stone"], col)
    create_box("CentralNave", (0.0, 0.65, plateau_z + 4.5), (3.1, 3.4, 5.4), mats["stone"], col)

    # Steep Pitched Gothic Gable Roof over Central Nave
    gable_roof = create_cone(
        "CentralNaveRoof",
        (0.0, 0.65, plateau_z + 8.55),
        2.55,
        0.04,
        2.8,
        mats["slate"],
        col,
        vertices=4,
        rotation=(0.0, 0.0, math.radians(45)),
    )
    gable_roof.scale = (0.95, 1.25, 1.0)

    # High Upper Belfry Keep
    create_box("UpperBelfry", (0.0, 1.45, plateau_z + 7.4), (2.1, 2.0, 4.2), mats["stone"], col)
    belfry_roof = create_cone(
        "UpperBelfryRoof",
        (0.0, 1.45, plateau_z + 11.1),
        1.75,
        0.03,
        3.2,
        mats["slate"],
        col,
        vertices=4,
        rotation=(0.0, 0.0, math.radians(45)),
    )
    belfry_roof.scale = (1.0, 0.95, 1.0)

    # Grand Glowing Gothic Rose/Lancet Windows on Front Facade
    for idx, wx in enumerate((-0.72, 0.0, 0.72)):
        h = 2.05 if idx == 1 else 1.65
        create_gothic_pointed_arch(
            f"NaveFacadeWindow_{idx}",
            (wx, -1.08, plateau_z + 4.35),
            0.46,
            h,
            0.22,
            mats["window_glow"],
            col,
        )

    for idx, wx in enumerate((-0.45, 0.45)):
        create_gothic_pointed_arch(
            f"BelfryFacadeWindow_{idx}",
            (wx, 0.42, plateau_z + 7.25),
            0.34,
            1.55,
            0.22,
            mats["window_glow"],
            col,
        )

    # Wing Windows on Main Keep
    for side_sign in (-1.0, 1.0):
        for i in range(3):
            wx = side_sign * (1.85 + i * 0.85)
            create_gothic_pointed_arch(
                f"KeepWingWindow_{side_sign}_{i}",
                (wx, -0.98, plateau_z + 3.65),
                0.34,
                1.25,
                0.20,
                mats["window_glow"],
                col,
            )

    # 3. Array of Gothic Towers & Spires (Matching Asymmetric Silhouette)
    tower_configs = [
        ("Tower_FarLeft_Outpost", (-5.5, -0.6), plateau_z - 0.3, 0.68, 4.4, 2.4, False, 1),
        ("Tower_FrontLeft_Main", (-3.5, -1.4), plateau_z, 0.95, 6.2, 3.2, True, 2),
        ("Tower_FrontRight_Main", (3.5, -1.4), plateau_z, 0.95, 6.2, 3.2, True, 2),
        ("Tower_FarRight_Turret", (5.4, -0.4), plateau_z - 0.2, 0.88, 5.6, 3.0, True, 2),
        ("Tower_InnerLeft_Spire", (-1.95, -0.2), plateau_z + 1.2, 0.78, 7.6, 3.8, True, 2),
        ("Tower_InnerRight_Spire", (1.95, -0.2), plateau_z + 1.2, 0.78, 7.6, 3.8, True, 2),
        ("Tower_CrownLeft", (-1.15, 1.35), plateau_z + 4.5, 0.52, 5.4, 2.9, True, 1),
        ("Tower_CrownRight", (1.15, 1.35), plateau_z + 4.5, 0.52, 5.4, 2.9, True, 1),
        ("Tower_RearLeft", (-3.8, 3.6), plateau_z + 0.5, 0.90, 6.8, 3.4, True, 2),
        ("Tower_RearRight", (3.8, 3.6), plateau_z + 0.5, 0.90, 6.8, 3.4, True, 2),
    ]
    for cfg in tower_configs:
        build_gothic_tower(cfg[0], cfg[1], cfg[2], cfg[3], cfg[4], cfg[5], mats, col, cfg[6], cfg[7])

    # 4. Grand Pointed Entrance Gate & Crimson Banners
    create_box("GatehouseFrame", (0.0, -1.88, plateau_z + 1.95), (2.6, 0.95, 3.9), mats["stone"], col)
    create_gothic_pointed_arch(
        "GrandGateArchOuter",
        (0.0, -2.36, plateau_z + 0.15),
        1.95,
        3.25,
        0.35,
        mats["stone"],
        col,
    )
    create_gothic_pointed_arch(
        "GrandGateGlowPortal",
        (0.0, -2.42, plateau_z + 0.15),
        1.55,
        2.85,
        0.18,
        mats["window_glow"],
        col,
    )

    # Wrought-Iron Portcullis Bars
    for i in range(-4, 5):
        create_cylinder(
            f"PortcullisBar_{i}",
            (i * 0.16, -2.48, plateau_z + 1.35),
            0.022,
            2.4,
            mats["iron"],
            col,
            vertices=6,
        )

    # Two Large Crimson Banners Flanking the Gatehouse
    for side_sign, label in ((-1.0, "Left"), (1.0, "Right")):
        bx = side_sign * 1.92
        by = -2.14
        bz = plateau_z + 2.35

        # Banner Crossbar
        create_cylinder(
            f"BannerRod_{label}",
            (bx, by, bz + 1.15),
            0.035,
            0.95,
            mats["iron"],
            col,
            vertices=8,
            rotation=(0.0, math.radians(90), 0.0),
        )

        # Pennant Mesh with V-Notch Bottom
        mesh = bpy.data.meshes.new(f"CrimsonBanner_{label}_Mesh")
        banner = bpy.data.objects.new(f"CrimsonBanner_{label}", mesh)
        link_to_collection(banner, col)
        banner.location = (bx, by, bz)

        bm = bmesh.new()
        w = 0.40
        top_z = 1.12
        bot_z = -1.15
        notch_z = -0.82
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
def build_gargoyle_statue(name, location, facing_sign, mats, col):
    """Builds a stylized winged gargoyle perched on a stone plinth."""
    gx, gy, gz = location
    # Pedestal Base
    create_box(f"{name}_Pedestal", (gx, gy, gz + 0.55), (1.05, 1.15, 1.1), mats["stone"], col)
    create_box(f"{name}_PedestalCap", (gx, gy, gz + 1.15), (1.20, 1.30, 0.18), mats["stone"], col)

    # Crouching Torso & Head
    torso_z = gz + 1.65
    create_cone(
        f"{name}_Torso",
        (gx, gy, torso_z),
        0.34,
        0.22,
        0.85,
        mats["gargoyle"],
        col,
        vertices=10,
        rotation=(math.radians(18), 0.0, 0.0),
    )
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.22, location=(gx, gy - 0.18, torso_z + 0.48))
    head = bpy.context.active_object
    head.name = f"{name}_Head"
    head.data.materials.append(mats["gargoyle"])
    link_to_collection(head, col)

    # Horns
    for h_sign in (-1.0, 1.0):
        create_cone(
            f"{name}_Horn_{h_sign}",
            (gx + h_sign * 0.14, gy - 0.16, torso_z + 0.70),
            0.05,
            0.008,
            0.32,
            mats["gargoyle"],
            col,
            vertices=6,
            rotation=(math.radians(-20), h_sign * math.radians(25), 0.0),
        )

    # Swept Bat-Like Stone Wings
    for w_sign in (-1.0, 1.0):
        wing_mesh = bpy.data.meshes.new(f"{name}_Wing_{w_sign}_Mesh")
        wing = bpy.data.objects.new(f"{name}_Wing_{w_sign}", wing_mesh)
        link_to_collection(wing, col)
        wing.location = (gx + w_sign * 0.22, gy + 0.10, torso_z + 0.25)

        bm = bmesh.new()
        pts = [
            (0.0, 0.0, 0.0),
            (w_sign * 0.65, 0.25, 0.75),
            (w_sign * 1.15, 0.15, 0.45),
            (w_sign * 0.92, 0.08, -0.15),
            (w_sign * 0.52, 0.04, -0.25),
        ]
        verts = [bm.verts.new(p) for p in pts]
        bm.faces.new(verts)
        bm.normal_update()
        bm.to_mesh(wing_mesh)
        bm.free()
        wing.data.materials.append(mats["gargoyle"])


def build_brazier(name, location, scale_mult, mats, col):
    bx, by, bz = location
    # Stone Pillar
    create_box(f"{name}_Pillar", (bx, by, bz + 0.32 * scale_mult), (0.48 * scale_mult, 0.48 * scale_mult, 0.64 * scale_mult), mats["stone"], col)
    # Iron Bowl
    create_cone(
        f"{name}_Bowl",
        (bx, by, bz + 0.76 * scale_mult),
        0.18 * scale_mult,
        0.42 * scale_mult,
        0.26 * scale_mult,
        mats["iron"],
        col,
        vertices=12,
    )
    # Glowing Flame Core
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.25 * scale_mult, location=(bx, by, bz + 0.98 * scale_mult))
    flame = bpy.context.active_object
    flame.name = f"{name}_Flame"
    flame.scale = (0.95, 0.95, 1.55)
    flame.data.materials.append(mats["fire_glow"])
    link_to_collection(flame, col)


def build_bridge_and_foreground(mats, col):
    plateau_z = 3.2
    # Sloped Stone Bridge Deck leading forward (-Y)
    deck = create_box(
        "StoneBridgeDeck",
        (0.0, -6.4, plateau_z - 0.58),
        (2.55, 8.6, 0.45),
        mats["wet_stone"],
        col,
        rotation=(math.radians(-7.5), 0.0, 0.0),
    )

    # Support Piers & Arches under the Bridge
    for idx, py in enumerate((-4.2, -7.2, -10.0)):
        pz = plateau_z - 2.35 - idx * 0.42
        create_box(f"BridgePier_{idx}", (0.0, py, pz), (2.45, 0.85, 3.6), mats["stone"], col)

    # Low Stone Parapets & Iron Railings along Bridge Edges
    for side_sign, label in ((-1.0, "Left"), (1.0, "Right")):
        px = side_sign * 1.16
        create_box(
            f"BridgeParapet_{label}",
            (px, -6.4, plateau_z - 0.22),
            (0.24, 8.6, 0.48),
            mats["stone"],
            col,
            rotation=(math.radians(-7.5), 0.0, 0.0),
        )
        # Iron Fence Spikes
        for i in range(14):
            fy = -2.6 - i * 0.58
            fz = plateau_z + 0.22 - (i * 0.58) * math.tan(math.radians(7.5))
            create_cylinder(f"BridgeRailPost_{label}_{i}", (px, fy, fz), 0.02, 0.48, mats["iron"], col, vertices=6)

    # Twin Gargoyle Guardians Flanking the Bridge Entrance
    build_gargoyle_statue("Gargoyle_Left", (-1.68, -2.55, plateau_z - 0.15), -1.0, mats, col)
    build_gargoyle_statue("Gargoyle_Right", (1.68, -2.55, plateau_z - 0.15), 1.0, mats, col)

    # Fire Braziers Along the Bridge
    brazier_specs = [
        ("Brazier_GateLeft", (-1.15, -2.65, plateau_z - 0.05), 0.72),
        ("Brazier_GateRight", (1.15, -2.65, plateau_z - 0.05), 0.72),
        ("Brazier_MidLeft", (-1.18, -5.20, plateau_z - 0.38), 0.85),
        ("Brazier_MidRight", (1.18, -5.20, plateau_z - 0.38), 0.85),
        ("Brazier_ForeLeft", (-1.22, -8.10, plateau_z - 0.76), 1.05),
        ("Brazier_ForeRight", (1.22, -8.10, plateau_z - 0.76), 1.18),
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

        # Create tapered prism segment
        perp1 = direction.orthogonal().normalized()
        perp2 = direction.cross(perp1).normalized()
        sides = 6
        ring0 = []
        ring1 = []
        for s in range(sides):
            ang = (2.0 * math.pi * s) / sides
            offset = (perp1 * math.cos(ang) + perp2 * math.sin(ang))
            ring0.append(bm.verts.new(p_start + offset * radius))
            ring1.append(bm.verts.new(p_end + offset * (radius * 0.68)))

        for s in range(sides):
            ns = (s + 1) % sides
            bm.faces.new([ring0[s], ring0[ns], ring1[ns], ring1[s]])

        # Split into 2 gnarled sub-branches
        for _ in range(2):
            jitter = Vector((
                rng.uniform(-0.55, 0.55),
                rng.uniform(-0.35, 0.35),
                rng.uniform(0.15, 0.65),
            ))
            new_dir = (direction.normalized() + jitter).normalized()
            grow_branch(p_end, new_dir, length * rng.uniform(0.68, 0.84), radius * 0.66, depth - 1)

    grow_branch(Vector((0.0, 0.0, 0.0)), Vector((0.15, 0.05, 1.0)), 1.75, 0.22, 5)
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
    # Body diamond
    v_head = bm.verts.new((0.0, -0.18, 0.04))
    v_tail = bm.verts.new((0.0, 0.22, -0.02))
    v_l_shoulder = bm.verts.new((-0.08, -0.05, 0.02))
    v_r_shoulder = bm.verts.new((0.08, -0.05, 0.02))
    bm.faces.new([v_head, v_r_shoulder, v_tail, v_l_shoulder])

    # Left & Right Spread Wings
    for s in (-1.0, 1.0):
        w_elbow = bm.verts.new((s * 0.35, -0.12, 0.14))
        w_tip = bm.verts.new((s * 0.82, -0.02, 0.08))
        w_mid_scallop = bm.verts.new((s * 0.52, 0.14, 0.02))
        w_inner_scallop = bm.verts.new((s * 0.22, 0.16, 0.0))
        shoulder = v_r_shoulder if s > 0 else v_l_shoulder
        bm.faces.new([shoulder, w_elbow, w_tip, w_mid_scallop, w_inner_scallop, v_tail])

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    bat.data.materials.append(mats["iron"])


def build_atmosphere_props(mats, col):
    # Gnarled Dead Trees Framing Left & Right Foreground
    build_dead_tree("DeadTree_Left", (-5.6, -7.8, 0.2), 101, mats, col)
    build_dead_tree("DeadTree_Right", (5.8, -7.4, 0.3), 202, mats, col)

    # Flock of Bats Silhouetted Across the Sky
    bat_specs = [
        ("Bat_HeroMoon", (-4.4, -3.5, 8.8), 1.35, (math.radians(15), math.radians(-12), math.radians(18))),
        ("Bat_HeroRight", (4.8, -4.2, 9.6), 1.25, (math.radians(18), math.radians(15), math.radians(-22))),
        ("Bat_Swarm_1", (-4.8, -2.0, 7.6), 0.55, (math.radians(10), 0.0, math.radians(12))),
        ("Bat_Swarm_2", (-5.3, -1.8, 7.1), 0.45, (math.radians(12), 0.0, math.radians(8))),
        ("Bat_Swarm_3", (-3.9, -2.2, 8.0), 0.50, (math.radians(8), 0.0, math.radians(20))),
        ("Bat_Swarm_4", (3.2, -1.5, 8.5), 0.52, (math.radians(14), 0.0, math.radians(-15))),
        ("Bat_Swarm_5", (3.8, -1.8, 7.9), 0.60, (math.radians(10), 0.0, math.radians(-25))),
        ("Bat_Swarm_6", (2.6, -1.2, 9.2), 0.42, (math.radians(12), 0.0, math.radians(-10))),
    ]
    for b_name, loc, sc, rot in bat_specs:
        build_bat(b_name, loc, sc, rot, mats, col)


# ==============================================================================
# 8. LIGHTING, WORLD SKY & CAMERA FRAMING
# ==============================================================================
def setup_lighting_and_camera(col):
    # Dark Stormy Night World Background
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("GothicNightWorld")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.025, 0.032, 0.048, 1.0)
        bg.inputs["Strength"].default_value = 0.85

    # Cold Blue Moonlight Key Light (From Upper-Left Moon Direction)
    bpy.ops.object.light_add(type='SUN', location=(-9.0, 6.0, 14.0))
    moon_sun = bpy.context.active_object
    moon_sun.name = "MoonDirectionalLight"
    moon_sun.data.energy = 3.2
    moon_sun.data.color = (0.62, 0.76, 1.0)
    moon_sun.rotation_euler = (math.radians(54), math.radians(-22), math.radians(-38))
    link_to_collection(moon_sun, col)

    # Crimson Portal & Brazier Point Lights
    point_lights = [
        ("CrimsonGateLight", (0.0, -2.8, 4.6), 420.0, (1.0, 0.04, 0.06)),
        ("BridgeFireLight_Mid", (0.0, -5.2, 3.6), 160.0, (1.0, 0.12, 0.03)),
        ("BridgeFireLight_Fore", (0.8, -8.1, 3.2), 210.0, (1.0, 0.10, 0.02)),
        ("UpperKeepCrimsonGlow", (0.0, -0.5, 8.5), 260.0, (1.0, 0.03, 0.05)),
    ]
    for l_name, loc, energy, color in point_lights:
        bpy.ops.object.light_add(type='POINT', location=loc)
        pt = bpy.context.active_object
        pt.name = l_name
        pt.data.energy = energy
        pt.data.color = color
        link_to_collection(pt, col)

    # Hero Perspective Camera Matching Image Composition
    bpy.ops.object.camera_add(location=(2.85, -12.8, 4.85))
    cam = bpy.context.active_object
    cam.name = "GothicCastleCamera"
    cam.data.lens = 28.0
    cam.data.clip_end = 250.0

    # Aim camera toward the central gate & keep
    target = Vector((-0.2, 0.5, 6.3))
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
        )
        print("Successfully generated Gothic Castle scene and exported out/model.glb")

    except Exception as e:
        print(f"Blender script failed: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
