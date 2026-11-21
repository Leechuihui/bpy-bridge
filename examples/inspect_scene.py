# -*- coding: utf-8 -*-
"""Print a summary of the open Blender scene.

This is the script from the tutorial, kept runnable so the tutorial's output can
be reproduced rather than trusted::

    bpy-bridge exec --file examples/inspect_scene.py

It works on any scene. Nothing here is specific to the grass project.
"""

import bpy

scene = bpy.context.scene

print("file:      %s" % (bpy.data.filepath or "<unsaved>"))
print("blender:   %s" % bpy.app.version_string)
print("scene:     %s" % scene.name)
print("engine:    %s" % scene.render.engine)
print("camera:    %s" % (scene.camera.name if scene.camera else "<none>"))
print("resolution %dx%d" % (scene.render.resolution_x, scene.render.resolution_y))
print("frames:    %d-%d" % (scene.frame_start, scene.frame_end))
print("objects:   %d" % len(bpy.data.objects))
print("meshes:    %d" % len(bpy.data.meshes))
print("materials: %d" % len(bpy.data.materials))
print("images:    %d" % len(bpy.data.images))

collections = sorted(
    ((collection.name, len(collection.objects)) for collection in bpy.data.collections),
    key=lambda row: -row[1],
)
if collections:
    print("\ntop collections by object count:")
    for name, count in collections[:8]:
        print("  %-28s %6d" % (name, count))
