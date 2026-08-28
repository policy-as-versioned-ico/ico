#!/usr/bin/env bash
# Beat: "the ico penalty schema is signed + versioned, and a schema bump changes
# the £ fair.py reports -- without touching fair.py."
#
# Sections 1-5 are the original beat over schema/v1 and schema/v2, which stay
# exactly as they were signed. Sections 6-8 are the feed contract (ticket 21,
# ADR-0019): the three published envelopes under penalty-schema/, major 3's
# regulator-published control weights (ticket 15 Answer 1), and the nist
# controls pin. Envelope validation is stdlib only -- estate python3 has pyyaml
# but no jsonschema.
#
# Sections 1-7 are offline, no cluster required. Section 8 reaches the nist
# remote and exits 3 (could-not-look) if it cannot.
# ponytail: git ls-remote cannot tell a network failure from a 404, so a
# renamed nist repo reads as could-not-look rather than a fail. Upgrade path:
# curl the GitHub API and branch on the status code, once a rename is a real
# risk.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
schema_dir="$here/schema"
fair="$here/../platform/fair/fair.py"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() { echo "FAIL: $*"; exit 1; }
# exit 3 = could-not-look (talk/verify-all.sh grades it SKIP), reason on the last line.
skip() { echo "SKIP: $*"; exit 3; }

[ -f "$fair" ] || fail "platform FAIR engine not found at $fair"

say() { echo; echo "== $* =="; }

say "1. schema signature + version verify offline (v1, v2)"
"$schema_dir/verify.sh" v1
"$schema_dir/verify.sh" v2

say "2. a tampered schema fails signature verification"
cp "$schema_dir/v1/penalty-schema.json" "$work/tampered.json"
python3 - "$work/tampered.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["regimes"]["uk-gdpr"]["violation_types"]["higher-tier"]["formula"]["cap_gbp"] = 1
json.dump(d, open(p, "w"))
PY
if openssl pkeyutl -verify -pubin -inkey "$schema_dir/keys/ico-signing-key.pub.pem" \
    -rawin -in "$work/tampered.json" -sigfile "$schema_dir/v1/penalty-schema.json.sig" >/dev/null 2>&1; then
  fail "tampered schema still verified against v1's signature"
fi
echo "ok  tampered schema correctly rejected"

say "3. fair.py consumes the schema as a loss-magnitude input (unmodified fair.py)"
python3 "$schema_dir/to_fair_scenario.py" "$schema_dir/v1/penalty-schema.json" uk-gdpr lower-tier -o "$work/v1.json"
python3 "$schema_dir/to_fair_scenario.py" "$schema_dir/v2/penalty-schema.json" uk-gdpr lower-tier -o "$work/v2.json"
ale_v1=$(python3 "$fair" summary "$work/v1.json" --mode warn | python3 -c "import json,sys; print(json.load(sys.stdin)['ale'])")
ale_v2=$(python3 "$fair" summary "$work/v2.json" --mode warn | python3 -c "import json,sys; print(json.load(sys.stdin)['ale'])")
echo "ale(v1 uk-gdpr/lower-tier warn) = £$(printf '%.0f' "$ale_v1")"
echo "ale(v2 uk-gdpr/lower-tier warn) = £$(printf '%.0f' "$ale_v2")"

say "4. the schema bump (v1 -> v2) actually moved the £ -- one added real fine, no fair.py edit"
python3 - "$ale_v1" "$ale_v2" <<'PY'
import sys
a, b = float(sys.argv[1]), float(sys.argv[2])
assert a != b, f"schema bump did not change the £ (both {a})"
print(f"ok  £ moved by £{b - a:,.0f} on a version-only schema diff")
PY

say "5. one breach can draw several obligation sources; the £ is worst case, not one at a time (ticket 18)"
python3 "$schema_dir/to_fair_scenario.py" build "$schema_dir/v2/penalty-schema.json" uk-gdpr lower-tier \
    --also pci-dss:non-compliance-escalating -o "$work/combined.json"
ale_solo=$(python3 "$fair" summary "$work/v2.json" --mode warn | python3 -c "import json,sys; print(json.load(sys.stdin)['ale'])")
ale_combined=$(python3 "$fair" summary "$work/combined.json" --mode warn | python3 -c "import json,sys; print(json.load(sys.stdin)['ale'])")
echo "ale(uk-gdpr/lower-tier alone)               = £$(printf '%.0f' "$ale_solo")"
echo "ale(uk-gdpr/lower-tier + pci-dss, combined)  = £$(printf '%.0f' "$ale_combined")"
python3 - "$ale_solo" "$ale_combined" <<'PY'
import sys
solo, combined = float(sys.argv[1]), float(sys.argv[2])
assert combined > solo, f"a second obligation source on the same breach did not raise the £ ({combined} <= {solo})"
print(f"ok  £ rose by £{combined - solo:,.0f} once a second regime can draw on the same breach -- fatter, not thinner")
PY

say "6. the three published feed envelopes match the one feed contract (ADR-0019)"
python3 - "$here" <<'ENVELOPE'
import json, os, re, sys

root = sys.argv[1]
ENVELOPE_KEYS = {"kind", "name", "version", "published_by", "published_at",
                 "payload_schema", "payload"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def bad(msg):
    sys.stdout.flush(); print("FAIL: " + msg, flush=True)
    sys.exit(1)


seen = {}
for major, version in (("v1", "1.0.0"), ("v2", "2.0.0"), ("v3", "3.0.0")):
    where = "penalty-schema/%s/feed.json" % major
    env = json.load(open(os.path.join(root, where)))
    if set(env) != ENVELOPE_KEYS:
        bad("%s top-level keys are %s, the envelope is %s"
            % (where, sorted(env), sorted(ENVELOPE_KEYS)))
    if env["kind"] not in ("feed", "controls", "implementations"):
        bad("%s kind %r is not a parent kind" % (where, env["kind"]))
    if env["name"] != "penalty-schema":
        bad("%s name is %r" % (where, env["name"]))
    if env["published_by"] != "ico":
        bad("%s published_by is %r" % (where, env["published_by"]))
    if not SEMVER.match(env["version"]):
        bad("%s version %r is not a semver string without a leading v"
            % (where, env["version"]))
    if env["version"] != version:
        bad("%s declares version %s, expected %s" % (where, env["version"], version))
    if not RFC3339.match(env["published_at"]):
        bad("%s published_at %r is not RFC3339" % (where, env["published_at"]))
    if not isinstance(env["payload"], dict):
        bad("%s payload is not an object" % where)
    ps = env["payload_schema"]
    if not ps.startswith(("http://", "https://")):
        abs_ps = os.path.join(root, ps)
        if not os.path.isfile(abs_ps):
            bad("%s payload_schema %s does not resolve to a file in this repo" % (where, ps))
        schema = json.load(open(abs_ps))
        missing = [k for k in schema.get("required", []) if k not in env["payload"]]
        if missing:
            bad("%s payload is missing %s, required by %s" % (where, missing, ps))
        if schema.get("additionalProperties") is False:
            extra = [k for k in env["payload"] if k not in schema.get("properties", {})]
            if extra:
                bad("%s payload carries %s, unknown to %s" % (where, extra, ps))
    seen[env["version"]] = env
    print("ok  %s  %s v%s by %s at %s, payload validates against %s"
          % (where, env["name"], env["version"], env["published_by"],
             env["published_at"], ps))

# the migrated majors wrap the schema/ payloads they came from, unchanged
for major, src in (("v1", "schema/v1/penalty-schema.json"),
                   ("v2", "schema/v2/penalty-schema.json")):
    env = json.load(open(os.path.join(root, "penalty-schema", major, "feed.json")))
    old = json.load(open(os.path.join(root, src)))
    if env["payload"]["regimes"] != old["regimes"]:
        bad("penalty-schema/%s/feed.json regimes differ from %s" % (major, src))
print("ok  v1 and v2 envelopes carry the schema/ regimes payloads unchanged")

v2_src = json.load(open(os.path.join(root, "schema/v2/penalty-schema.json")))
if seen["3.0.0"]["payload"]["regimes"] != v2_src["regimes"]:
    bad("major 3 changed the regimes payload; it is a payload_schema major, not a rate change")
print("ok  major 3 adds control_weights and leaves the regimes payload alone")

# the discovery record points at what is actually here (ADR-0019 point 5)
import yaml
party = yaml.safe_load(open(os.path.join(root, "party.yaml")))
pub = [e for e in party.get("publishes", []) if e.get("name") == "penalty-schema"]
if len(pub) != 1:
    bad("party.yaml publishes[] does not declare penalty-schema exactly once")
pub = pub[0]
if pub["kind"] != "feed":
    bad("party.yaml declares penalty-schema as kind %r" % pub["kind"])
for key in ("path", "payload_schema"):
    if not os.path.exists(os.path.join(root, pub[key])):
        bad("party.yaml publishes[].%s %s does not exist" % (key, pub[key]))
if pub.get("revoked", []) != []:
    bad("party.yaml revokes %s but no withdrawal payload exists" % pub["revoked"])
print("ok  party.yaml publishes[] resolves: %s -> %s, schema %s"
      % (pub["name"], pub["path"], pub["payload_schema"]))
ENVELOPE

say "7. major 3's control weights partition each regime, never add to it"
python3 - "$here" <<'WEIGHTS'
import json, os, sys

root = sys.argv[1]
env = json.load(open(os.path.join(root, "penalty-schema/v3/feed.json")))
regimes = env["payload"]["regimes"]
weights = env["payload"]["control_weights"]


def bad(msg):
    sys.stdout.flush(); print("FAIL: " + msg, flush=True)
    sys.exit(1)


if not weights:
    bad("major 3 carries no control_weights")
for regime, vts in weights.items():
    if regime not in regimes:
        bad("control_weights names regime %r, which has no entry under regimes" % regime)
    for vt, entries in vts.items():
        if vt not in regimes[regime]["violation_types"]:
            bad("control_weights names %s/%s, which is not a violation type" % (regime, vt))
        ids = [(e["source"], e["id"]) for e in entries]
        if len(set(ids)) != len(ids):
            bad("%s/%s weights the same (source, id) twice" % (regime, vt))
        for e in entries:
            if not 0 < e["weight"] <= 1:
                bad("%s/%s weight for %s is %r, outside (0, 1]"
                    % (regime, vt, e["id"], e["weight"]))
        total = sum(e["weight"] for e in entries)
        if abs(total - 1.0) > 1e-9:
            bad("%s/%s weights sum to %r, not 1.0 -- a hole would add to the regime "
                "exposure instead of partitioning it" % (regime, vt, total))
        print("ok  %-8s %-27s %d controls, sum 1.0 (%s)"
              % (regime, vt, len(entries), ", ".join(i for _, i in ids)))
WEIGHTS

say "8. the controls parent ico pins is a real tag on the real nist remote"
nist_remote="https://github.com/policy-as-versioned-nist/nist"
pin=$(python3 -c '
import sys, yaml
p = yaml.safe_load(open(sys.argv[1]))
hits = [i for i in p.get("inherits", []) if i.get("party") == "nist" and i.get("kind") == "controls"]
if len(hits) != 1:
    sys.exit("ico party.yaml does not pin nist controls exactly once")
print(hits[0]["version"])' "$here/party.yaml") || fail "could not read the nist pin from party.yaml"
echo "ico pins nist controls at $pin"
if ! remote_tags=$(GIT_TERMINAL_PROMPT=0 git ls-remote --tags "$nist_remote" 2>/dev/null); then
  skip "cannot reach $nist_remote to check that the nist pin $pin is a real tag"
fi
tags=$(echo "$remote_tags" | sed 's|.*refs/tags/||; s|\^{}$||' | sort -u)
if ! echo "$tags" | grep -qx -e "$pin" -e "v$pin"; then
  fail "ico pins nist $pin but that remote has no such tag (it has: $(echo $tags))"
fi
echo "ok  nist tag v$pin is on the remote -- major 3's control ids key on a real catalogue version"

echo
echo "PASS: ico penalty schema signed+versioned, fair.py consumes it unmodified, a schema bump moves the £, a second obligation source raises it, the three published feeds match the one envelope, major 3 partitions each regime into weighted controls, and the nist pin is a real tag"
