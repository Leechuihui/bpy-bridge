# -*- coding: utf-8 -*-
"""Make the project importable from the test suite.

pytest's default import mode puts the *test file's* directory on ``sys.path``,
not the project root, so ``import bpy_bridge`` would fail on a plain checkout.
Inserting the root here makes ``pytest`` work with no install step at all,
which is what a first-time contributor expects.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
