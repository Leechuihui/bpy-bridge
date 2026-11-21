# -*- coding: utf-8 -*-
"""Check that the bilingual READMEs actually link to each other and to files
that exist.

The language switcher is the one feature in this repo that is pure convention:
GitHub renders whatever ``README.md`` says, and a relative link to a file that
was renamed or never committed produces a 404 with no other signal. This script
turns that convention into a checked invariant.

Run directly: ``python tests/check_readme_links.py``
"""

import os
import re
import sys

# The labels being checked include CJK text. A Windows console defaults to a
# legacy code page where those characters either raise or print as mojibake,
# which makes a *passing* check look broken. Reconfigure stdout when the
# interpreter supports it (3.7+); older ones just print what they can.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: (readme filename, the label that should point at the *other* readme)
LANGUAGE_PAIRS = (
    ("README.md", "简体中文", "README.zh-CN.md"),
    ("README.zh-CN.md", "English", "README.md"),
)

#: Matches `[label](target)` and `[![alt](img)](target)`, capturing the final
#: target. Enough for the links this project actually writes.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def check_switcher(readme, label, expected_target):
    """The other language must be reachable from the first few lines."""
    path = os.path.join(ROOT, readme)
    if not os.path.exists(path):
        return ["missing file: %s" % readme]
    with open(path, "r", encoding="utf-8") as handle:
        head = "".join(handle.readlines()[:8])
    if expected_target not in head:
        return ["%s: first 8 lines do not link to %s" % (readme, expected_target)]
    if label not in head:
        return ["%s: first 8 lines do not contain the label %r" % (readme, label)]
    return []


def check_relative_links(readme):
    """Every relative link in *readme* must resolve to a real file."""
    path = os.path.join(ROOT, readme)
    if not os.path.exists(path):
        return ["missing file: %s" % readme]
    problems = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            for target in LINK_RE.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                # Strip an optional #fragment before resolving.
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                resolved = os.path.normpath(os.path.join(ROOT, relative))
                if not os.path.exists(resolved):
                    problems.append(
                        "%s:%d links to %r, which does not exist"
                        % (readme, line_number, target)
                    )
    return problems


def main():
    problems = []
    for readme, label, target in LANGUAGE_PAIRS:
        problems.extend(check_switcher(readme, label, target))
    for readme, _label, _target in LANGUAGE_PAIRS:
        problems.extend(check_relative_links(readme))

    if problems:
        for problem in problems:
            print("FAIL: %s" % problem)
        return 1

    print("OK: both READMEs cross-link and every relative link resolves")
    for readme, label, target in LANGUAGE_PAIRS:
        print("  - %s -> %s (%s)" % (readme, target, label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
