#!/usr/bin/env python3
"""declared-bump-gate.py -- ticket 43, ticket 18 Answer 5.

ico declares the bump for a release in one reviewed file,
`penalty-schema/bump.yaml` (ticket 21 shipped it; ico has no versions.yaml
array to hang the field on). Nothing read it. This is the gate that does:
before cut-release.yml creates the tag, it computes the bump between the
feed version being cut and the one below it, under the feed's OWN rule
(`penalty-schema/rule.yaml`, ADR-0023 decision D2), and REFUSES when the
declaration and the computation disagree.

It never rewrites either number. A publisher who meant `minor` and shipped a
removed regime learns it here, before a tag exists, not from a subscriber.

The ladder is the estate's one feed ladder (feeds/bump.py, ADR-0019),
reproduced here rather than imported: this repository is a separate org with
no dependency on the feeds repo, and a release gate that cannot run without
another org's checkout is not a gate. Kept to the four rules an ico feed can
actually hit; if it ever needs the numeric-tolerance half as well, vendor
feeds/bump.py wholesale and delete this copy.
  ponytail: four rules, not the whole ladder. Upgrade path named above.

    declared-bump-gate.py v3.0.0     # the tag cut-release.yml is about to cut
    declared-bump-gate.py --tree     # ...the same question, without naming a tag
    declared-bump-gate.py --selfcheck
"""
import json
import re
import sys
from pathlib import Path

FEED_DIR = Path(__file__).resolve().parents[2] / "penalty-schema"
LADDER = ("none", "patch", "minor", "major")


def read_flat(path, key):
    """Flat `key: value` YAML, standard library only -- the same shape and
    the same reason as every rule.yaml and bump.yaml in the estate."""
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith(f"{key}:"):
            return line.partition(":")[2].strip().strip('"').strip("'")
    return None


def compute(old, new, entries_key):
    """The bump between two feed envelopes. `version` and `published_at` are
    the release's own facts, not the feed's content, so they are ignored."""
    if old.get("payload_schema") != new.get("payload_schema"):
        return "major"
    old_entries = old.get("payload", {}).get(entries_key, {})
    new_entries = new.get("payload", {}).get(entries_key, {})
    if set(old_entries) - set(new_entries):
        return "major"
    if set(new_entries) - set(old_entries):
        return "minor"
    if old.get("payload") == new.get("payload"):
        return "none"
    return "patch"


def feed_path(major):
    return FEED_DIR / f"v{major}" / "feed.json"


def published_majors():
    found = []
    for path in FEED_DIR.glob("v*/feed.json"):
        m = re.fullmatch(r"v(\d+)", path.parent.name)
        if m:
            found.append(int(m.group(1)))
    return sorted(found)


def main(argv):
    if len(argv) == 2 and argv[1] == "--selfcheck":
        return selfcheck()
    if len(argv) != 2:
        print("usage: declared-bump-gate.py <tag>|--selfcheck", file=sys.stderr)
        return 2
    tag = argv[1]
    if tag == "--tree":
        # What the tree currently claims: the newest published feed version
        # against the one below it. The same question cut-release.yml asks,
        # asked without naming a tag, so a verify script can ask it forever.
        majors = published_majors()
        if not majors:
            print("SKIP: no penalty-schema/v<N>/feed.json in this repository")
            return 3
        tag = f"v{majors[-1]}.0.0"
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    if not m:
        print(f"FAIL: {tag!r} is not a vX.Y.Z tag", file=sys.stderr)
        return 1
    major = int(m.group(1))

    declared = read_flat(FEED_DIR / "bump.yaml", "bump")
    if declared not in LADDER:
        print(f"FAIL: penalty-schema/bump.yaml declares {declared!r}, not one of {LADDER}",
              file=sys.stderr)
        return 1

    new_path = feed_path(major)
    if not new_path.exists():
        print(f"FAIL: {new_path} does not exist -- the tag names a feed version this "
              f"repository has not published", file=sys.stderr)
        return 1
    below = [v for v in published_majors() if v < major]
    if not below:
        print(f"OK: v{major} is the first published feed version -- no predecessor to compute "
              f"a bump against, so the declared bump {declared!r} stands unchallenged")
        return 0

    entries_key = read_flat(FEED_DIR / "rule.yaml", "entries")
    computed = compute(json.loads(feed_path(below[-1]).read_text()),
                       json.loads(new_path.read_text()), entries_key)
    if computed != declared:
        print(f"FAIL: penalty-schema/bump.yaml declares {declared!r} but the computed bump "
              f"from v{below[-1]} to v{major} is {computed!r} (rule: "
              f"{read_flat(FEED_DIR / 'rule.yaml', 'changed_when')!r}). The gate has two "
              f"declarations of one fact and no rule for choosing between them.", file=sys.stderr)
        return 1
    print(f"OK: declared bump {declared!r} == computed bump {computed!r} (v{below[-1]} -> v{major})")
    return 0


def selfcheck():
    def feed(entries, schema="penalty-schema/payload.schema.json"):
        return {"kind": "feed", "name": "penalty-schema", "version": "1.0.0",
                "published_by": "ico", "payload_schema": schema,
                "payload": {"note": "x", "regimes": entries}}

    base = feed({"uk_gdpr": {"cap": 1}, "pecr": {"cap": 2}})
    cases = [
        ("unchanged", base, "none"),
        ("regime added", feed({**base["payload"]["regimes"], "fca": {"cap": 3}}), "minor"),
        ("regime removed", feed({"uk_gdpr": {"cap": 1}}), "major"),
        ("payload schema changed", feed(base["payload"]["regimes"], schema="other.json"), "major"),
        ("a cap moved", feed({"uk_gdpr": {"cap": 9}, "pecr": {"cap": 2}}), "patch"),
    ]
    for name, candidate, expected in cases:
        got = compute(base, candidate, "regimes")
        assert got == expected, f"{name}: expected {expected}, got {got}"
        print(f"ok  {name} -> {expected}")
    assert read_flat(FEED_DIR / "bump.yaml", "bump") in LADDER, "the real bump.yaml must parse"
    assert read_flat(FEED_DIR / "rule.yaml", "entries") == "regimes", "the real rule.yaml must parse"
    print("ok  the real penalty-schema/bump.yaml and rule.yaml parse with the standard library")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
