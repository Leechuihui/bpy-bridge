# -*- coding: utf-8 -*-
"""Check the GitHub metadata files: issue forms and contact links.

Why this exists
---------------
Two real defects shipped here, and neither could be caught by anything that
already existed:

1. The issue templates used the old ``.md``-template keys (``about`` at the top,
   free-form markdown below) in files named ``.yml``. GitHub therefore read them
   as issue *forms*, failed to find ``name``/``description``/``body``, and the
   community profile reported ``issue_template: MISSING`` -- with health 100% on
   every other check and no error anywhere to point at the real file.

2. ``config.yml`` still contained ``YOUR-USER`` placeholders after every other
   file had been rewritten. Its two contact links pointed at a non-existent
   user, so the security-advisory route was a 404 for anyone who needed it.

Both are metadata-only breakage: tests stay green, the package installs, and the
failure mode is that people cannot report things. That is exactly why this needs
to be a check rather than an aspiration.

Run: ``python tests/check_repo_metadata.py``
"""

import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML is required: pip install pyyaml\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE_DIR = os.path.join(ROOT, ".github", "ISSUE_TEMPLATE")

#: Top-level keys a GitHub issue *form* must define. Files ending in ``.yml``
#: are forms; free-form ``.md`` templates use the older ``about`` key instead.
FORM_REQUIRED_KEYS = ("name", "description", "body")

#: The stale key from the old-style template. Legal in a ``.md`` template,
#: wrong in a ``.yml`` form -- GitHub ignores the form and reports it missing.
STALE_FORM_KEY = "about"

#: Placeholder strings that must never survive into metadata that users click.
PLACEHOLDER_STRINGS = ("YOUR-USER", "YOUR_NAME", "YOUR_USERNAME")

#: Files that are metadata for the repository, checked for placeholders.
METADATA_GLOBS = (
    ("*.md", (".",)),
    ("*.yml", (".github",)),
    ("*.yaml", (".github",)),
    ("*.toml", (".",)),
    ("*.cff", (".",)),
)


def form_problems(path):
    """One issue form's structural problems, if any."""
    problems = []
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        return ["%s: not a YAML mapping" % os.path.basename(path)]

    missing = [key for key in FORM_REQUIRED_KEYS if key not in data]
    if missing:
        problems.append(
            "%s: missing required key(s) %s -- GitHub will treat the form as "
            "invalid and the community profile will report it missing"
            % (os.path.basename(path), ", ".join(missing))
        )
    if STALE_FORM_KEY in data:
        problems.append(
            "%s: uses the old-style template key %r; issue *forms* use "
            "'description' at the top level and a 'body' list"
            % (os.path.basename(path), STALE_FORM_KEY)
        )

    body = data.get("body")
    if body is not None and not isinstance(body, list):
        problems.append("%s: 'body' must be a list" % os.path.basename(path))
    return problems


def check_issue_forms():
    """Every .yml template is a valid issue form; config.yml has its keys."""
    if not os.path.isdir(TEMPLATE_DIR):
        return [".github/ISSUE_TEMPLATE is missing"]

    problems = []
    forms = sorted(glob.glob(os.path.join(TEMPLATE_DIR, "*.yml")))
    forms = [f for f in forms if os.path.basename(f) != "config.yml"]
    if not forms:
        problems.append("no issue forms (.yml) found in .github/ISSUE_TEMPLATE")

    print()
    print("issue forms:")
    for path in forms:
        issues = form_problems(path)
        name = os.path.basename(path)
        if issues:
            problems.extend(issues)
            print("  %-24s BAD" % name)
        else:
            with open(path, "r", encoding="utf-8") as handle:
                count = len(yaml.safe_load(handle).get("body", []))
            print("  %-24s OK  (%d fields)" % (name, count))

    config = os.path.join(TEMPLATE_DIR, "config.yml")
    if os.path.exists(config):
        with open(config, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        keys_ok = "blank_issues_enabled" in data and "contact_links" in data
        print("  %-24s %s" % ("config.yml", "OK" if keys_ok else "BAD"))
        if not keys_ok:
            problems.append("config.yml: missing blank_issues_enabled/contact_links")
        for index, link in enumerate(data.get("contact_links") or []):
            for key in ("name", "url", "about"):
                if not link.get(key):
                    problems.append(
                        "config.yml: contact_links[%d] missing %r" % (index, key)
                    )
    return problems


def check_placeholders():
    """No placeholder survives in any metadata file users click through."""
    problems = []
    hits = []
    print()
    print("placeholders:")
    for pattern, directories in METADATA_GLOBS:
        for directory in directories:
            for path in glob.glob(os.path.join(ROOT, directory, pattern)):
                rel = os.path.relpath(path, ROOT)
                if os.sep + ".git" in path:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
                for token in PLACEHOLDER_STRINGS:
                    if token in content:
                        hits.append("%s contains %r" % (rel, token))
    if hits:
        problems.extend(hits)
        for hit in hits:
            print("  " + hit)
    else:
        print("  none in %s" % ", ".join(token for token in PLACEHOLDER_STRINGS))
    return problems


def main():
    problems = check_issue_forms()
    problems.extend(check_placeholders())

    print()
    if problems:
        for problem in problems:
            print("FAIL: %s" % problem)
        return 1
    print("OK: issue forms are valid forms and no placeholders remain in metadata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
