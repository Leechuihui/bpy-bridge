# -*- coding: utf-8 -*-
"""Check that the bilingual docs cross-link and every relative link resolves.

Why this exists
---------------
The language switcher is pure convention: GitHub renders whatever ``README.md``
says, and a relative link to a file that was renamed or never committed produces
a 404 with no other signal. The same is true of every screenshot in the tutorial
-- an image path typo renders as a broken icon and nobody notices until a reader
complains.

This turns both conventions into checked invariants:

1. Each bilingual pair links to its counterpart near the top of the file.
2. Every relative link in every doc resolves to a real path, including images.

It deliberately does not verify that the two languages say the same thing -- no
script can. CONTRIBUTING states that rule for humans.

Run directly: ``python tests/check_readme_links.py``
"""

import os
import re
import sys

# The labels and image paths include CJK text. A Windows console defaults to a
# legacy code page where those characters raise or print as mojibake, which makes
# a *passing* check look broken. Reconfigure stdout when supported (3.7+).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: Every bilingual pair: (english file, chinese file, label in EN, label in ZH).
#: Adding a translated doc means adding a row here, which is the point -- a new
#: doc that forgets its switcher fails CI instead of shipping half-bilingual.
LANGUAGE_PAIRS = (
    ("README.md", "README.zh-CN.md", "简体中文", "English"),
    ("docs/tutorial.md", "docs/tutorial.zh-CN.md", "简体中文", "English"),
    ("docs/configuration.md", "docs/configuration.zh-CN.md", "简体中文", "English"),
)

#: Files whose relative links are checked. Docs only; source comments are not
#: rendered anywhere and would just produce false positives.
LINKED_FILES = (
    "README.md",
    "README.zh-CN.md",
    "docs/tutorial.md",
    "docs/tutorial.zh-CN.md",
    "docs/configuration.md",
    "docs/configuration.zh-CN.md",
    "docs/install.md",
    "docs/protocol.md",
    "docs/security.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
)

#: Matches `[label](target)` and `[![alt](img)](target)`, capturing the final
#: target. Good enough for the links this project actually writes.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

#: Fenced code blocks, including the fence lines themselves.
FENCE_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)

#: Inline code spans. Markdown does not render links inside these, so neither
#: should this checker.
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def _blank(text):
    """Replace text with spaces, keeping its length and newlines.

    Offsets and line numbers have to survive the substitution: every message this
    checker prints quotes a line number, and a number that points at the wrong
    line is worse than no number.
    """
    return "".join(character if character == "\n" else " " for character in text)


def _strip_code(text):
    """Blank out code so prose links are checked and code is not.

    Without this, ordinary Python such as ``namespace["start"](port=9999)``
    matches the link pattern and is reported as a broken link to ``port=9999``
    -- a false positive that would teach everyone to ignore the checker. Markdown
    never renders a link inside a code span or a fenced block, so ignoring them
    is the correct rule, not a workaround.
    """
    text = FENCE_RE.sub(lambda match: _blank(match.group(0)), text)
    return INLINE_CODE_RE.sub(lambda match: _blank(match.group(0)), text)

#: How far into a file to look for the language switcher. Generous enough for a
#: title, a blank line, a badge row, and the switcher.
SWITCHER_WINDOW = 12


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def check_switcher(english, chinese, label_en, label_zh):
    """Both files must link to the other within the first few lines.

    The comparison uses the *basename*, not the repo-relative path. Markdown
    links are resolved relative to the file that contains them, so the tutorial's
    switcher correctly says ``tutorial.zh-CN.md`` rather than
    ``docs/tutorial.zh-CN.md``. Comparing full paths would flag every switcher in
    ``docs/`` as broken -- which is exactly what the first run of this checker
    did.
    """
    problems = []
    for path, label, target in (
        (english, label_en, chinese),
        (chinese, label_zh, english),
    ):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            problems.append("missing file: %s" % path)
            continue
        head = "".join(_read(full).splitlines(True)[:SWITCHER_WINDOW])
        expected_basename = os.path.basename(target)
        if expected_basename not in head:
            problems.append(
                "%s: first %d lines do not link to %s"
                % (path, SWITCHER_WINDOW, expected_basename)
            )
        if label not in head:
            problems.append(
                "%s: first %d lines do not contain the label %r"
                % (path, SWITCHER_WINDOW, label)
            )
    return problems


def check_relative_links(path):
    """Every relative link in *path* must resolve to a real file."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return ["missing file: %s" % path]

    problems = []
    # Blank out code *in place* so line numbers stay accurate in messages.
    for line_number, line in enumerate(_strip_code(_read(full)).splitlines(), 1):
        for target in LINK_RE.findall(line):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            # Strip an optional #fragment before resolving.
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(full), relative))
            if not os.path.exists(resolved):
                problems.append(
                    "%s:%d links to %r, which does not exist"
                    % (path, line_number, target)
                )
    return problems


def check_images_referenced_exist():
    """Every image referenced by any doc must exist on disk.

    Checks *both* tutorial languages and the READMEs. The English tutorial was
    the only file checked at first, which meant a broken image in the Chinese
    tutorial would ship unnoticed -- the exact asymmetry the bilingual rule
    exists to prevent.
    """
    image_re = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
    problems = []
    for relative_path in LINKED_FILES:
        full = os.path.join(ROOT, relative_path)
        if not os.path.exists(full):
            continue
        for target in image_re.findall(_strip_code(_read(full))):
            if target.startswith(("http://", "https://")):
                continue
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(full), target.split("#", 1)[0])
            )
            if not os.path.exists(resolved):
                problems.append("%s: image missing: %s" % (relative_path, target))
    return problems


def main():
    problems = []

    for english, chinese, label_en, label_zh in LANGUAGE_PAIRS:
        problems.extend(check_switcher(english, chinese, label_en, label_zh))

    for path in LINKED_FILES:
        problems.extend(check_relative_links(path))

    problems.extend(check_images_referenced_exist())

    if problems:
        for problem in problems:
            print("FAIL: %s" % problem)
        return 1

    print("OK: %d bilingual pairs cross-link, %d docs have resolving links"
          % (len(LANGUAGE_PAIRS), len(LINKED_FILES)))
    for english, chinese, _label_en, _label_zh in LANGUAGE_PAIRS:
        print("  - %s <-> %s" % (english, chinese))
    return 0


if __name__ == "__main__":
    sys.exit(main())
