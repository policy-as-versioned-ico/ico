#!/usr/bin/env python3
"""to_fair_scenario.py — turn an ico penalty-schema entry into a fair.py scenario.

Reads the ico penalty schema (regime -> violation-type -> fine formula/cap + real
public examples) and emits a scenario JSON in the same (min,mode,max) shape
`platform/fair/fair.py` already consumes (see estate/platform/fair/scenarios/
driftwood-cart-pii.json) — so bumping the schema version is the whole diff needed
to move the £ fair.py reports; no change to fair.py itself.

Loss-magnitude (lm) triple per formula type:
  - pct_of_global_turnover / pct_of_relevant_revenue_plus_discretion:
      min = smallest real example, mode = median of real examples, max = cap
      (or, absent a cap, 1.2x the largest example -- FCA has no statutory cap).
  - per_violation_tier (HIPAA): min/max straight from the statutory tier,
      mode = median of real examples clipped into [min, max].
  - per_month_escalating (PCI): steady-state (7+ months) monthly band annualised
      by the ponytail LEF below, mode = midpoint of that band.

Loss-event-frequency (lef) is NOT in the schema -- the schema prices "when it
lands", not "how often". ponytail: a flat editorial per-regime warn-LEF, tune per
institution if a scenario needs it; deny collapses LEF the same way every other
scenario in this estate does (deny.lef ~ (0,0,1)).

One breach can draw more than one regime's consequence (an ICO fine *and* a PCI
penalty on the same incident, say) -- pass `--also REGIME:VIOLATION_TYPE`
(repeatable) to `build` to fold further obligation sources into the same
scenario's lm. fair.py prices them additively and correlated, never as separate
risks (ticket 18). Which regimes actually apply to which workload stays an
open, separate gap (ticket 17) -- this only combines regimes named explicitly.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys

DEFAULT_WARN_LEF = (1, 2, 4)   # plausible regulatory-incident frequency, events/yr
DEFAULT_DENY_LEF = (0, 0, 1)   # admission blocks the loss path (matches driftwood-cart-pii.json)


def _examples(vt: dict, currency_key: str) -> list[float]:
    key = f"real_examples_{currency_key.lower()}"
    return [e[f"fine_{currency_key.lower()}"] for e in vt.get(key, []) if f"fine_{currency_key.lower()}" in e]


def lm_triple(regime: dict, vt: dict, turnover: float | None = None) -> tuple[float, float, float]:
    currency = regime["currency"]
    f = vt["formula"]
    ex = _examples(vt, currency)
    t = f["type"]

    if t in ("pct_of_global_turnover", "pct_of_relevant_revenue_plus_discretion"):
        if not ex:
            sys.exit(f"no real_examples for formula type {t}; cannot derive a grounded lm")
        lo = min(ex)
        mode = statistics.median(ex)
        # the statutory cap is a floor on the ceiling, not a hard override: a real
        # example can exceed today's cap (e.g. BA/Marriott were fined under the
        # pre-Brexit EU GDPR cap) -- the triple must still satisfy lo<=mode<=hi.
        hi = max(f.get("cap_gbp") or 0, max(ex) * 1.2, mode)
        # SIZED. The real examples are fines on other, much larger balance
        # sheets. Given the subscriber's own signed turnover, the percentage
        # formula gives THAT party's exposure, and the published examples scale
        # by the same ratio -- one factor, so lo<=mode<=hi survives it. With no
        # turnover (unsigned, or signed too long ago to stand) the triple is
        # left at the statutory cap: a stale size widens, it never refuses.
        cap, rate = float(f.get("cap_gbp") or 0), f.get("rate")
        if turnover is not None and cap and rate:
            scale = (float(rate) * float(turnover)) / cap
            lo, mode, hi = lo * scale, mode * scale, hi * scale
        return (float(lo), float(mode), float(hi))

    if t == "per_violation_tier":
        lo, hi = float(f["min_usd" if currency == "USD" else "min_gbp"]), float(f["max_usd" if currency == "USD" else "max_gbp"])
        mode = statistics.median(ex) if ex else (lo + hi) / 2
        mode = min(max(mode, lo), hi)
        return (lo, mode, hi)

    if t == "per_month_escalating":
        steady = f["tiers"][-1]["gbp_per_month"]
        lo, hi = float(steady[0]) * 12, float(steady[1]) * 12  # ponytail: annualised steady-state band
        return (lo, (lo + hi) / 2, hi)

    sys.exit(f"unknown formula type: {t}")


def build_scenario(schema: dict, regime_name: str, vt_name: str, also=(),
                    warn_lef=DEFAULT_WARN_LEF, deny_lef=DEFAULT_DENY_LEF,
                    turnover: float | None = None) -> dict:
    """also: further (regime_name, vt_name) pairs whose consequence the SAME
    breach can also draw -- an ICO fine and a PCI penalty on one incident, say
    (ticket 18). Emits a single lm triple for one source (unchanged shape), or
    a list of triples for several; fair.py's simulate() prices the multi-source
    case additively and correlated (shared lef), never as independent risks.
    Which regimes actually apply to which workload is not decided here -- that
    scoping is a separate, still-open gap (ticket 17)."""
    sources = [(regime_name, vt_name), *also]
    lms, names, regimes_used = [], [], []
    for r_name, v_name in sources:
        regime = schema["regimes"][r_name]
        vt = regime["violation_types"][v_name]
        lms.append(lm_triple(regime, vt, turnover))
        names.append(f"{r_name}/{v_name}")
        regimes_used.append(regime)
    lm = lms[0] if len(lms) == 1 else [list(t) for t in lms]
    if len(lms) == 1:
        r = regimes_used[0]
        note = (f"lm sourced from {r['authority']} real public fines ({r['statute']}). "
                f"warn/deny lef are editorial (schema doesn't carry frequency)."
                + (f" Scaled to a subscriber turnover of {turnover:,.2f} {r['currency']}."
                   if turnover is not None else
                   " Not sized to any subscriber: priced at the statutory cap."))
    else:
        cites = "; ".join(f"{r['authority']} ({r['statute']})" for r in regimes_used)
        note = (f"lm sourced from real public fines, cited per source: {cites}. "
                f"warn/deny lef are editorial (schema doesn't carry frequency). "
                f"{len(lms)} obligation sources on one breach ({', '.join(names)}), priced "
                f"additively and correlated (shared lef) -- see fair.py.")
    return {
        "version": schema["schema_version"],
        "name": f"ico:{schema['schema_version']} " + " + ".join(names),
        "note": note,
        "warn": {"lef": list(warn_lef), "lm": lm},
        "deny": {"lef": list(deny_lef), "lm": lm},
    }


def selfcheck():
    """Every (regime, violation_type) in every schema version must yield a valid
    lo<=mode<=hi triple -- the one invariant fair.py's pert() needs to not blow up."""
    import glob
    import os

    checked = 0
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "v*/penalty-schema.json"))):
        with open(path) as fh:
            schema = json.load(fh)
        for regime_name, regime in schema["regimes"].items():
            for vt_name in regime["violation_types"]:
                lo, mode, hi = lm_triple(regime, regime["violation_types"][vt_name])
                assert lo <= mode <= hi, (path, regime_name, vt_name, lo, mode, hi)
                checked += 1
    assert checked >= 8, f"expected to check every regime x violation-type, only checked {checked}"
    print(f"ok  {checked} (schema-version, regime, violation-type) triples are all lo<=mode<=hi")

    # One breach can draw more than one regime's consequence (ticket 18):
    # combining two real regimes must yield a list of triples, each still
    # lo<=mode<=hi, not a single flattened one.
    v2 = json.load(open(os.path.join(os.path.dirname(__file__), "v2", "penalty-schema.json")))
    combined = build_scenario(v2, "uk-gdpr", "lower-tier", also=[("pci-dss", "non-compliance-escalating")])
    lm = combined["warn"]["lm"]
    assert isinstance(lm, list) and len(lm) == 2 and isinstance(lm[0], list), combined
    for lo, mode, hi in lm:
        assert lo <= mode <= hi, (combined, lo, mode, hi)
    print("ok  combining uk-gdpr + pci-dss on one breach yields 2 lo<=mode<=hi triples, not 1")

    # SIZED. A subscriber's own turnover moves the triple, and a party with a
    # smaller balance sheet than the statutory cap prices smaller -- the whole
    # point of shipping the converter beside the feed (spec, the £ seam).
    gdpr = v2["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]
    unsized = lm_triple(v2["regimes"]["uk-gdpr"], gdpr)
    small = lm_triple(v2["regimes"]["uk-gdpr"], gdpr, turnover=86_000_000)
    big = lm_triple(v2["regimes"]["uk-gdpr"], gdpr, turnover=5_000_000_000)
    for lo, mode, hi in (unsized, small, big):
        assert lo <= mode <= hi, (lo, mode, hi)
    assert small[2] < unsized[2], (small, unsized)
    assert big[2] > unsized[2], (big, unsized)
    assert small != unsized and big != small
    rate = gdpr["formula"]["rate"]
    cap = gdpr["formula"]["cap_gbp"]
    assert abs(small[2] - unsized[2] * (rate * 86_000_000) / cap) < 1e-6
    print("ok  a subscriber's own turnover scales the lm triple; no turnover stays at the cap")



# --------------------------------------------------------------------------
# eco-system ticket 79 -- planted cases, written before the logic changed.
# Each runs the REAL functions against a planted payload and reports what it
# saw; every case is reported, not the first to fail, so one red run names
# everything. Items 1 (status/final_as_of/litigation), 3 (a basis for every
# frequency) and 7/5 (the cap rule).
# --------------------------------------------------------------------------

_T79_LOWER = {
    "authority": "ICO", "statute": "UK GDPR s157", "currency": "GBP",
    "violation_types": {
        "lower-tier": {
            "description": "planted",
            "formula": {"type": "pct_of_global_turnover", "rate": 0.02, "cap_gbp": 8_700_000},
            "real_examples_gbp": [
                {"org": "Clearview AI Inc", "year": 2022, "fine_gbp": 7_552_800,
                 "source": "ICO monetary penalty notice, 23 May 2022"},
                {"org": "Doorstep Dispensaree Ltd", "year": 2019, "fine_gbp": 275_000,
                 "source": "ICO monetary penalty notice, 12 Dec 2019"},
            ],
        }
    },
}


def _t79_payload(**over):
    import copy
    doc = {"schema_version": "v79", "note": "planted",
           "regimes": {"uk-gdpr": copy.deepcopy(_T79_LOWER)}}
    doc.update(over)
    return doc


def _t79_vt(doc):
    return doc["regimes"]["uk-gdpr"]["violation_types"]["lower-tier"]


def ticket79_cases():
    """Returns (reds, greens). A red is (n, title, what was observed)."""
    reds, greens = [], []

    def case(n, title, fn):
        try:
            fn()
        except AssertionError as e:
            reds.append((n, title, str(e)))
        except Exception as e:            # a case that cannot even run is red, never silent
            reds.append((n, title, "raised %s: %s" % (type(e).__name__, e)))
        else:
            greens.append((n, title))

    # (a) a fine with no `status` prices as final
    def a1():
        doc = _t79_payload()
        vt = _t79_vt(doc)
        vt["real_examples_gbp"][0]["status"] = "under-appeal"
        vt["real_examples_gbp"][0]["final_as_of"] = None
        vt["real_examples_gbp"][0]["litigation"] = "never collected"
        # the second example carries no status at all
        try:
            got = lm_triple(doc["regimes"]["uk-gdpr"], vt)
        except SystemExit as e:
            assert "status" in str(e) and "Doorstep" in str(e), \
                "refused, but not naming the example and the missing field: %s" % e
            return
        raise AssertionError(
            "an example with no `status` beside one that has it priced anyway: "
            "lm_triple returned %r" % (got,))

    def a2():
        doc = _t79_payload()
        sc = build_scenario(doc, "uk-gdpr", "lower-tier")
        assert "could not" in sc["note"].lower() or "no `status`" in sc["note"], \
            ("a payload in which NO example carries a status priced with no named "
             "could-not-look on the scenario; the note reads: %r" % sc["note"])

    def a3():
        doc = _t79_payload()
        for e, st in zip(_t79_vt(doc)["real_examples_gbp"],
                          ("not-collected", "final")):
            e["status"] = st
            e["final_as_of"] = None if st != "final" else "2024-12-09"
            e["litigation"] = "planted"
        lo, mode, hi = lm_triple(doc["regimes"]["uk-gdpr"], _t79_vt(doc))
        assert mode == 275_000.0, (
            "a `not-collected` penalty of 7,552,800 still entered the triple: the mode is "
            "%r and the only final figure in the payload is 275,000" % mode)

    # (b) a frequency with no basis
    def b1():
        doc = _t79_payload()
        _t79_vt(doc)["frequency"] = {"lef": [0, 2, 4]}   # no basis
        try:
            build_scenario(doc, "uk-gdpr", "lower-tier")
        except SystemExit as e:
            assert "basis" in str(e) and "lower-tier" in str(e), \
                "refused, but not naming the violation type and the basis: %s" % e
            return
        raise AssertionError(
            "a published `frequency` of [0, 2, 4] events/yr with NO `basis` was used to "
            "annualise the loss; its basis belongs on "
            "regimes.uk-gdpr.violation_types.lower-tier.frequency.basis in the ico "
            "penalty-schema payload")

    def b2():
        doc = _t79_payload()
        sc = build_scenario(doc, "uk-gdpr", "lower-tier")
        assert str(tuple(sc["warn"]["lef"])) in sc["note"] or "(1, 2, 4)" in sc["note"], \
            ("the scenario annualises at %r events/yr and its note never names that number "
             "or where its basis must go: %r" % (sc["warn"]["lef"], sc["note"]))

    def b3():
        doc = _t79_payload()
        _t79_vt(doc)["frequency"] = {
            "lef": [0, 3, 7],
            "basis": {"kind": "editorial", "statement": "planted basis statement",
                      "as_of": "2026-09-09"}}
        sc = build_scenario(doc, "uk-gdpr", "lower-tier")
        assert sc["warn"]["lef"] == [0, 3, 7], \
            ("the payload publishes frequency [0, 3, 7] and the scenario annualises at %r: "
             "the publisher's own field is not read" % (sc["warn"]["lef"],))
        assert "planted basis statement" in sc["note"] and "2026-09-09" in sc["note"], \
            "the published basis and its date are not on the scenario: %r" % sc["note"]

    # (d) the cap rule
    def d1():
        doc = _t79_payload()
        regime, vt = doc["regimes"]["uk-gdpr"], _t79_vt(doc)
        turnover = 5_000_000_000.0
        rate, cap = vt["formula"]["rate"], float(vt["formula"]["cap_gbp"])
        statutory_max = max(cap, rate * turnover)
        lo, mode, hi = lm_triple(regime, vt, turnover=turnover)
        assert hi <= statutory_max + 1e-6, (
            "the sized loss magnitude tops out at %.2f GBP, above the statutory maximum of "
            "%.2f GBP (UK GDPR Art 83: the GREATER of the fixed sum %.2f and %g x turnover "
            "%.2f) -- the converter prices a fine the statute does not permit"
            % (hi, statutory_max, cap, rate, turnover))

    case("a", "an example with no `status` beside one that has it is refused by name", a1)
    case("a", "a payload where no example carries a status is a NAMED could-not-look", a2)
    case("a", "a penalty that was never collected does not enter the loss triple", a3)
    case("b", "a published frequency with no `basis` is refused, naming where the basis goes", b1)
    case("b", "a frequency with no published basis names its own number on the scenario", b2)
    case("b", "a published frequency and its dated basis are read and carried", b3)
    case("d", "the sized triple never tops the statutory maximum max(cap, rate x turnover)", d1)
    return reds, greens


def ticket79_selfcheck() -> int:
    reds, greens = ticket79_cases()
    for n, title in greens:
        print("ok  (%s) %s" % (n, title))
    for n, title, what in reds:
        print("FAIL (%s) %s: %s" % (n, title, what))
    if reds:
        print("FAIL: %d ticket-79 selfcheck case(s) red" % len(reds))
        return 1
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")

    pc = sub.add_parser("build", help="emit a fair.py scenario for one regime/violation-type (default)")
    pc.add_argument("schema", help="path to a penalty-schema.json")
    pc.add_argument("regime")
    pc.add_argument("violation_type")
    pc.add_argument("--also", action="append", default=[], metavar="REGIME:VIOLATION_TYPE",
                     help="fold another obligation source's consequence into the same breach "
                          "(repeatable) -- ticket 18")
    pc.add_argument("--turnover", type=float, default=None,
                     help="the SUBSCRIBER's own signed annual turnover, in the regime's own "
                          "currency. Percent-of-turnover formulas scale to it, so the price is "
                          "that party's and no fixture's. Omit it (or pass a stale size, which "
                          "the caller omits for you) and the triple stays at the statutory cap.")
    pc.add_argument("-o", "--out", help="write scenario JSON here (default: stdout)")

    sub.add_parser("selfcheck", help="assert every schema entry yields a valid lm triple")

    # allow the old positional form (no subcommand) to keep working
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in ("build", "selfcheck", "-h", "--help"):
        argv = ["build"] + list(argv)

    args = p.parse_args(argv)
    if args.cmd == "selfcheck":
        selfcheck()
        sys.exit(ticket79_selfcheck())

    with open(args.schema) as fh:
        schema = json.load(fh)
    also = [tuple(a.split(":", 1)) for a in args.also]
    scenario = build_scenario(schema, args.regime, args.violation_type, also=also,
                               turnover=args.turnover)
    out = json.dumps(scenario, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out + "\n")
    else:
        print(out)


if __name__ == "__main__":
    main()
