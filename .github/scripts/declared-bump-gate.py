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

CORRECTED 2026-09-06 (eco-system ticket 67 item (b)). `--tree` used to compute the bump between
the two newest PUBLISHED majors. That is a fact about the LAST release and stays `major` for as
long as v3 is the newest directory, while bump.yaml declares the bump for the NEXT one -- so
setting the file back to `none`, which its own 2026-08-29 note instructed once v3.0.0 was tagged,
would have turned the gate red for asking the wrong question. `tree()` now asks about the next
release: against the major below on disk when an untagged major is queued, and against what the
newest tag published when it is not. It refuses rather than shrugs; see tree().
"""
import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FEED_DIR = REPO / "penalty-schema"
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


def _semver(tag):
    return tuple(int(p) for p in tag.lstrip("v").split("."))


def released_tags():
    """Every vX.Y.Z tag this checkout holds, or None when it cannot read tags at all.

    Read from git, like nist's copy of this gate, because "what did we publish last time" is a
    tag and nothing else. cut-release.yml already asks git the same question one step later
    ("reject a tag that already exists"), so this needs no instrument the release path lacks.
    """
    try:
        out = subprocess.run(["git", "-C", str(REPO), "tag", "-l", "v*.*.*"],
                             capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return None
    return [t for t in out if re.fullmatch(r"v\d+\.\d+\.\d+", t)]


def feed_at(ref, rel_path):
    proc = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{rel_path}"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)


def grade(tag, declared):
    """Does `declared` agree with the bump the release `tag` would carry?

    CORRECTED 2026-09-06 (eco-system ticket 67 item (b)). Both entry points used to compute the
    bump between the two newest published MAJORS on disk. That is a fact about the LAST release
    and stays `major` for as long as v3 is the newest directory, while bump.yaml declares the
    bump for the NEXT one. Two consequences, both real: setting the file back to `none` -- which
    its own 2026-08-29 note instructed once v3.0.0 was tagged -- turned the gate red, and a patch
    release of an already-published major (v3.0.1) was refused for carrying the v2 -> v3 major.

    The predecessor is now the release this one follows, which is a tag where one exists:

      * a released tag of the SAME major, below this one -> the bump is computed against what
        that tag published, so an unchanged tree computes `none`;
      * no released tag of this major -> this is the major's first release, and the predecessor
        is the major below it on disk.

    Nothing here shrugs. A checkout that cannot read its tags, and a predecessor it cannot read
    at the tag it names, are red with a reason: the hub's talk/verify-manifest.txt declares no
    could-not-look for this row, so an exit 3 would grade FAIL anyway, and a named refusal says
    more than a shrug that is failed for being one.
    """
    if declared not in LADDER:
        print(f"FAIL: penalty-schema/bump.yaml declares {declared!r}, not one of {LADDER}",
              file=sys.stderr)
        return 1
    major = _semver(tag)[0]
    new_path = feed_path(major)
    if not new_path.exists():
        print(f"FAIL: {new_path} does not exist -- the tag names a feed version this "
              f"repository has not published", file=sys.stderr)
        return 1
    released = released_tags()
    if released is None:
        print("FAIL: this checkout cannot read its own tags, so which release this one follows "
              "cannot be read here. cut-release.yml asks git the same question one step later; "
              "a checkout without tags is a red, not a shrug", file=sys.stderr)
        return 1

    entries_key = read_flat(FEED_DIR / "rule.yaml", "entries")
    same_major = [t for t in released if _semver(t)[0] == major and _semver(t) < _semver(tag)]
    if same_major:
        prev = max(same_major, key=_semver)
        rel_path = f"penalty-schema/v{major}/feed.json"
        old = feed_at(prev, rel_path)
        if old is None:
            print(f"FAIL: could not read {rel_path} at {prev} -- the gate cannot compute a bump "
                  f"it cannot read the predecessor for", file=sys.stderr)
            return 1
        span = f"{prev} -> {tag}"
    else:
        below = [v for v in published_majors() if v < major]
        if not below:
            print(f"OK: v{major} is the first published feed version -- no predecessor to "
                  f"compute a bump against, so the declared bump {declared!r} stands "
                  f"unchallenged")
            return 0
        old = json.loads(feed_path(below[-1]).read_text())
        span = f"v{below[-1]} -> {tag}"

    return _verdict(declared, compute(old, json.loads(new_path.read_text()), entries_key), span)


def next_tag():
    """The tag a release cut today would carry: the next patch of the newest released tag of the
    newest feed major on disk, or that major's .0.0 when it has never been released."""
    majors = published_majors()
    if not majors:
        return None
    newest = majors[-1]
    released = released_tags()
    if released is None:
        return f"v{newest}.0.0"          # grade() refuses on the unreadable tags, with a reason
    mine = [t for t in released if _semver(t)[0] == newest]
    if not mine:
        return f"v{newest}.0.0"
    x, y, z = _semver(max(mine, key=_semver))
    return f"v{x}.{y}.{z + 1}"


def tree(declared):
    """`--tree`: the same question, without naming a tag -- asked of the release that would be
    cut next."""
    tag = next_tag()
    if tag is None:
        print("FAIL: no penalty-schema/v<N>/feed.json in this repository -- there is no feed to "
              "compute a bump for", file=sys.stderr)
        return 1
    return grade(tag, declared)


def _verdict(declared, computed, span):
    if computed != declared:
        print(f"FAIL: penalty-schema/bump.yaml declares {declared!r} but the computed bump for "
              f"the next release is {computed!r} ({span}; rule: "
              f"{read_flat(FEED_DIR / 'rule.yaml', 'changed_when')!r}). The gate has two "
              f"declarations of one fact and no rule for choosing between them.", file=sys.stderr)
        return 1
    print(f"OK: declared bump {declared!r} == computed bump {computed!r} ({span})")
    return 0


def main(argv):
    if len(argv) == 2 and argv[1] == "--selfcheck":
        return selfcheck()
    if len(argv) != 2:
        print("usage: declared-bump-gate.py <tag>|--selfcheck", file=sys.stderr)
        return 2
    tag = argv[1]
    if tag == "--tree":
        return tree(read_flat(FEED_DIR / "bump.yaml", "bump"))
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag):
        print(f"FAIL: {tag!r} is not a vX.Y.Z tag", file=sys.stderr)
        return 1
    return grade(tag, read_flat(FEED_DIR / "bump.yaml", "bump"))


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
    # ticket 67 item (b): --tree refuses rather than shrugs. A declaration off the ladder is the
    # one refusal reachable without git, and it must be a refusal, not an exit 3.
    with contextlib.redirect_stderr(io.StringIO()) as planted:
        refused = tree("nonsense")
    assert refused == 1, "--tree must refuse a declaration that is not on the ladder"
    assert "nonsense" in planted.getvalue(), "the refusal must name what it refused"
    print("ok  --tree refuses a declaration off the ladder rather than shrugging at it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
