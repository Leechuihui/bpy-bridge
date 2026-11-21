# -*- coding: utf-8 -*-
"""Report per-collection object counts as JSON.

    bpy-bridge exec --file examples/collection_report.py

Why this prints instead of returning
------------------------------------
An ``exec`` returns the ``repr`` of its trailing expression, so the obvious
version of this script -- ending in ``json.dumps(report)`` -- yields a result
like ``'{"scene": ...}'``: a Python string literal with outer quotes, which is
*not* parseable JSON. That is documented behaviour, and it trips people up
constantly.

The clean pattern is to ``print`` the JSON and let it land in ``stdout``, which
bpy-bridge returns verbatim::

    bpy-bridge exec --file examples/collection_report.py --json

then read ``stdout`` from the envelope. Machine-consumable output belongs on
stdout; ``result`` is for looking at.
"""

import json

import bpy

report = {
    "scene": bpy.context.scene.name,
    "total_objects": len(bpy.data.objects),
    "collections": {
        collection.name: len(collection.objects)
        for collection in bpy.data.collections
    },
}

print(json.dumps(report, sort_keys=True))
