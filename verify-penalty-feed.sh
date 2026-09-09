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

say "6. the four published feed envelopes match the one feed contract (ADR-0019)"
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
for major, version in (("v1", "1.0.0"), ("v2", "2.0.0"), ("v3", "3.0.0"), ("v4", "4.0.0")):
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

# Major 4 DOES change the regimes payload, on purpose: eco-system ticket 79 item
# 1 corrects two stale figures and grades the finality of every one. What it may
# not do is change a formula while doing it -- a finality correction is not a
# rate change, and the two must not travel together unannounced.
v3_p, v4_p = seen["3.0.0"]["payload"], seen["4.0.0"]["payload"]
for regime, r4 in v4_p["regimes"].items():
    r3 = v3_p["regimes"].get(regime)
    if r3 is None:
        bad("major 4 adds regime %r; a new regime is not a finality correction" % regime)
    for vt, v4vt in r4["violation_types"].items():
        v3vt = r3["violation_types"].get(vt)
        if v3vt is None:
            bad("major 4 adds %s/%s; a new violation type is not a finality correction"
                % (regime, vt))
        if v4vt["formula"] != v3vt["formula"]:
            bad("major 4 changes the %s/%s FORMULA (%r -> %r) as well as its finality; a rate "
                "or cap change is its own release" % (regime, vt, v3vt["formula"], v4vt["formula"]))
print("ok  major 4 corrects finality and adds frequency; no formula rate or cap moved with it")

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

say "9. every real example in major 4 names its SOURCE and carries a finality status, a date and a litigation note"
python3 - "$here" <<'FINALITY'
import json, os, re, sys

root = sys.argv[1]
env = json.load(open(os.path.join(root, "penalty-schema/v4/feed.json")))
PRICES = ("final", "imposed-appeal-unchecked")
STATUSES = PRICES + ("under-appeal", "set-aside", "not-collected", "notice-of-intent",
                     "not-a-penalty", "unknown")
# The three precisions payload.schema.v4.json declares. Enforced here because
# nothing else runs jsonschema over this payload on the estate's python3
# (review N4).
FINAL_AS_OF = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def bad(msg):
    sys.stdout.flush(); print("FAIL: " + msg, flush=True)
    sys.exit(1)


seen = 0
for regime, r in env["payload"]["regimes"].items():
    for vt, v in r["violation_types"].items():
        for key in ("real_examples_gbp", "real_examples_usd"):
            for e in v.get(key, []):
                who = "%s/%s %s" % (regime, vt, e.get("org", "an unnamed example"))
                status = e.get("status")
                if status is None:
                    bad("%s carries no `status`, so a penalty under appeal prices as if it "
                        "were final -- the defect eco-system ticket 79 item 1 exists to "
                        "close" % who)
                if status not in STATUSES:
                    bad("%s carries status %r, which is not one of %s" % (who, status, list(STATUSES)))
                if "final_as_of" not in e:
                    bad("%s carries no `final_as_of`; it is null for every status but `final`" % who)
                # Review N4: the schema declares the grammar and nothing enforced it --
                # `final_as_of: '24'` passed this section while jsonschema rejects it.
                if e.get("final_as_of") and not FINAL_AS_OF.match(str(e["final_as_of"])):
                    bad("%s carries final_as_of %r, which is not YYYY, YYYY-MM or YYYY-MM-DD -- "
                        "the precisions payload.schema.v4.json declares (review N4)"
                        % (who, e["final_as_of"]))
                if status == "final" and not e.get("final_as_of"):
                    bad("%s is `final` and names no `final_as_of` date -- a disclosed limit is a "
                        "printed number or a date" % who)
                if status != "final" and e.get("final_as_of"):
                    bad("%s is %r and names a final_as_of of %r; only a final figure has one"
                        % (who, status, e["final_as_of"]))
                if not (e.get("litigation") or "").strip():
                    bad("%s carries no `litigation` note saying what is known about the "
                        "challenge and what was not looked at" % who)
                # REVIEW F1. Sourcing, not only finality. A figure that PRICES and
                # names no source is a number nobody can trace, and it prices
                # exactly as well as one everybody can: an invented GBP 5,000,000
                # with status `final` and no source moved uk-gdpr/lower-tier's
                # mode from GBP 92,000 to GBP 2,546,000 and this section said ok.
                source = str(e.get("source") or "").strip()
                priced = status in PRICES and any(k in e for k in
                                                   ("fine_gbp", "fine_usd", "notice_gbp",
                                                    "notice_usd"))
                if priced and not source:
                    bad("%s carries a figure and a status of %r but NO `source`, so it prices "
                        "from a number nobody can trace back to a regulator's own instrument "
                        "(eco-system ticket 79 review F1)" % (who, status))
                if not source:
                    bad("%s names no `source`" % who)
                # REVIEW F5. rule.yaml's whole premise is that notice figures are
                # biased ONE WAY, upward. A notice below the figure that stands
                # contradicts it, so it is refused with both numbers rather than
                # quietly kept.
                for fine_key, notice_key in (("fine_gbp", "notice_gbp"),
                                              ("fine_usd", "notice_usd")):
                    if notice_key in e and fine_key in e and e[notice_key] < e[fine_key]:
                        bad("%s carries a notice figure of %s below the figure that stands, %s. "
                            "penalty-schema/rule.yaml's rule rests on notice figures being biased "
                            "one way, UPWARD; a notice below its own final figure is either a "
                            "transposition or a case that rule does not describe (eco-system "
                            "ticket 79 review F5)"
                            % (who, format(e[notice_key], ",.0f"), format(e[fine_key], ",.0f")))
                seen += 1
                print("ok  %-46s %-24s %-11s %s"
                      % (who, status, e.get("final_as_of") or "-", source[:88]))
if seen < 8:
    bad("only %d example(s) graded; major 4 carries more than that" % seen)
print("ok  %d real example(s) in major 4, every one naming its source and carrying a status, "
      "a date field and a litigation note; %d of them price" % (
          seen, sum(1 for r in env["payload"]["regimes"].values()
                    for v in r["violation_types"].values()
                    for k in ("real_examples_gbp", "real_examples_usd")
                    for e in v.get(k, []) if e.get("status") in PRICES)))
FINALITY

say "10. every control weight and every frequency in major 4 carries a basis"
python3 - "$here" <<'BASIS'
import json, os, re, sys

root = sys.argv[1]
env = json.load(open(os.path.join(root, "penalty-schema/v4/feed.json")))
payload = env["payload"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KINDS = ("counted", "published", "editorial")


def bad(msg):
    sys.stdout.flush(); print("FAIL: " + msg, flush=True)
    sys.exit(1)


def grade(basis, who, number):
    """A number the publisher signs and cannot say the source of is a missing
    instrument (ADR-0020), never a cheaper one."""
    if not isinstance(basis, dict):
        bad("%s publishes %s with no `basis` -- a bare number. Its basis belongs beside it "
            "in the payload (eco-system ticket 79 item 3)" % (who, number))
    for key in ("kind", "statement", "as_of"):
        if not (basis.get(key) or "") if key != "as_of" else not basis.get("as_of"):
            bad("%s publishes %s with a basis carrying no %r" % (who, number, key))
    if basis["kind"] not in KINDS:
        bad("%s: basis kind %r is not one of %s" % (who, basis["kind"], list(KINDS)))
    if not DATE.match(basis["as_of"]):
        bad("%s: basis as_of %r is not a date -- a disclosed limit is a printed number or a "
            "date" % (who, basis["as_of"]))
    if basis["kind"] != "counted" and not (basis.get("could_not_look") or "").strip():
        bad("%s: basis kind is %r and it names no `could_not_look` saying what would make it "
            "counted" % (who, basis["kind"]))


freqs = 0
for regime, r in payload["regimes"].items():
    for vt, v in r["violation_types"].items():
        who = "%s/%s" % (regime, vt)
        freq = v.get("frequency")
        if not freq:
            bad("%s publishes no `frequency`, so the annualisation of its loss is whatever the "
                "converter defaults to and nothing says where its basis is" % who)
        lef = freq.get("lef")
        if not (isinstance(lef, list) and len(lef) == 3 and lef[0] <= lef[1] <= lef[2]):
            bad("%s frequency.lef is %r, not a lo<=mode<=hi triple" % (who, lef))
        grade(freq.get("basis"), who, "a frequency of %s events/yr" % (tuple(lef),))
        freqs += 1
        print("ok  %-40s frequency %-12s basis %s, read %s"
              % (who, tuple(lef), freq["basis"]["kind"], freq["basis"]["as_of"]))

weights = 0
for regime, vts in payload["control_weights"].items():
    for vt, entries in vts.items():
        for e in entries:
            who = "%s/%s %s/%s" % (regime, vt, e["source"], e["id"])
            grade(e.get("basis"), who, "a weight of %s" % e["weight"])
            weights += 1
        print("ok  %-8s %-27s %d weight(s), every one with a dated basis"
              % (regime, vt, len(entries)))
if freqs < 5 or weights < 15:
    bad("graded %d frequency and %d weight bases; major 4 carries more than that"
        % (freqs, weights))
print("ok  %d frequencies and %d control weights in major 4, every one with a basis carrying a "
      "kind, a statement and a date" % (freqs, weights))
BASIS

say "11. the converter refuses a bare number and prices only what the finality rule allows"
python3 "$schema_dir/to_fair_scenario.py" selfcheck
python3 - "$here" "$schema_dir" <<'CONVERTER'
import json, os, subprocess, sys, tempfile

root, schema_dir = sys.argv[1], sys.argv[2]
converter = os.path.join(schema_dir, "to_fair_scenario.py")
payload = json.load(open(os.path.join(root, "penalty-schema/v4/feed.json")))["payload"]
payload["schema_version"] = "v4"


def bad(msg):
    sys.stdout.flush(); print("FAIL: " + msg, flush=True)
    sys.exit(1)


def run(doc, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(doc, fh)
    try:
        return subprocess.run([sys.executable, converter, "build", fh.name, *args],
                              capture_output=True, text=True)
    finally:
        os.unlink(fh.name)


r = run(payload, "uk-gdpr", "lower-tier")
if r.returncode != 0:
    bad("the converter cannot price major 4's uk-gdpr/lower-tier: %s" % r.stderr.strip()[-300:])
sc = json.loads(r.stdout)
lm = sc["warn"]["lm"]
if 7552800 in lm or 275000 in lm:
    bad("major 4's uk-gdpr/lower-tier still prices a figure that was never collected "
        "(7,552,800) or the superseded notice figure (275,000): lm is %r" % (lm,))
if 92000.0 not in lm:
    bad("major 4's uk-gdpr/lower-tier does not price the GBP 92,000 the First-tier Tribunal "
        "set in 2021 and the Court of Appeal confirmed in 2024: lm is %r" % (lm,))
if "Clearview" not in sc["note"] or "not-collected" not in sc["note"]:
    bad("the scenario does not name the figure it refused to price: %r" % sc["note"])
if sc["warn"]["lef"] != payload["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]["frequency"]["lef"]:
    bad("the scenario annualises at %r, not the frequency major 4 publishes (%r)"
        % (sc["warn"]["lef"], payload["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]["frequency"]["lef"]))
if "COULD NOT LOOK" not in sc["note"]:
    bad("the frequency's own could-not-look is not carried onto the scenario: %r" % sc["note"])
print("ok  major 4 uk-gdpr/lower-tier prices lm %s at lef %s, names Clearview's uncollected "
      "7,552,800 as not priced, and carries its frequency's basis and its could-not-look"
      % (tuple(lm), tuple(sc["warn"]["lef"])))

# a bare number REFUSES, not defaults
import copy
stripped = copy.deepcopy(payload)
del stripped["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]["frequency"]["basis"]
r = run(stripped, "uk-gdpr", "lower-tier")
if r.returncode == 0:
    bad("a frequency with its `basis` removed still priced -- the converter defaults where it "
        "should refuse (ADR-0020)")
if "basis" not in r.stderr or "lower-tier" not in r.stderr:
    bad("the converter refused a basis-less frequency without naming it: %s" % r.stderr.strip()[-200:])
print("ok  a frequency with no basis refuses, naming the violation type and where the basis goes")

# a status-less example beside one with a status REFUSES
mixed = copy.deepcopy(payload)
del mixed["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]["real_examples_gbp"][1]["status"]
r = run(mixed, "uk-gdpr", "lower-tier")
if r.returncode == 0:
    bad("an example with no `status`, beside one that has it, priced as if it were final")
if "status" not in r.stderr or "Doorstep" not in r.stderr:
    bad("the converter refused a status-less example without naming it: %s" % r.stderr.strip()[-200:])
print("ok  an example with no status beside one that has it refuses, naming the example")

# REVIEW F1: a priceable example with no source REFUSES, and the price does not move.
sourceless = copy.deepcopy(payload)
sourceless["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]["real_examples_gbp"].append(
    {"org": "Invented Ltd", "year": 2025, "fine_gbp": 5_000_000, "status": "final",
     "final_as_of": "2025-01-01", "litigation": "final and collected."})
r = run(sourceless, "uk-gdpr", "lower-tier")
if r.returncode == 0:
    got = json.loads(r.stdout)["warn"]["lm"]
    bad("an invented figure with a status and NO source priced: uk-gdpr/lower-tier's lm became "
        "%r. Before eco-system ticket 79 review F1 this moved the mode from 92,000 to 2,546,000 "
        "and every check said PASS" % (got,))
if "source" not in r.stderr or "Invented Ltd" not in r.stderr:
    bad("the converter refused a sourceless example without naming it: %s" % r.stderr.strip()[-200:])
print("ok  an invented figure with a status and no source refuses, naming it, and moves no price")

if "ICO monetary penalty notice, 12 Dec 2019" not in sc["note"]:
    bad("the scenario prices Doorstep Dispensaree and never says what that figure rests on: %r"
        % sc["note"])
if "FIRST-TIER TRIBUNAL" not in sc["note"] or "2021" not in sc["note"]:
    bad("the scenario does not carry WHICH court moved the figure and when: %r" % sc["note"])
print("ok  the scenario names what every priced figure rests on, including which court moved "
      "Doorstep Dispensaree's and in what year")
CONVERTER

echo
echo "PASS: ico penalty schema signed+versioned, fair.py consumes it unmodified, a schema bump moves the £, a second obligation source raises it, the four published feeds match the one envelope, major 3 partitions each regime into weighted controls, major 4 grades every published fine for finality and carries a dated basis on every frequency and every control weight, the converter refuses a bare number and prices only what the finality rule allows, and the nist pin is a real tag"
