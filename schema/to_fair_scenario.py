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

Loss-event-frequency (lef). From payload major 4 (eco-system ticket 79 item 3)
the PUBLISHER ships it: each violation type carries `frequency.lef` and a
`frequency.basis` naming what the number rests on and the date it was read.
A `frequency` with no `basis` is REFUSED (ADR-0020: an unsourced number is a
missing instrument, not a cheap one). A payload version published before the
field existed (majors 1 to 3) still prices at this module's editorial default,
and the scenario's own `note` then says so, names the number and names where its
basis must go -- a NAMED could-not-look, never a bare number. deny collapses LEF
the same way every other scenario in this estate does (deny.lef ~ (0,0,1)).

Finality and sourcing (eco-system ticket 79 item 1, review F1 and F2). From
payload major 4 every real example carries `source`, `status`, `final_as_of` and
`litigation`. TWO statuses price: `final`, and `imposed-appeal-unchecked` --
which prices AND says on every scenario it reaches that no register was read for
it. Everything else does not. The publisher's rule, recorded in
penalty-schema/rule.yaml, is THE FINAL COLLECTED FIGURE, NOT THE NOTICE FIGURE.
A priceable example with NO `source` is refused by name: before review F1, an
invented GBP 5,000,000 with a status and no source moved uk-gdpr/lower-tier's
priced mode from GBP 92,000 to GBP 2,546,000 and every check said PASS.
Two of this schema's own examples say why -- Doorstep Dispensaree's GBP 275,000
notice was cut to GBP 92,000 by the FIRST-TIER TRIBUNAL in 2021, and confirmed
at that figure when the Court of Appeal dismissed the further appeal in 2024;
and Clearview AI's GBP 7,552,800 has never been collected. (Review N2: this
paragraph used to say the Court of Appeal made the reduction, on 2024-12-09 --
the wrong body and a day no source this estate holds carries. It is corrected
here because THIS MODULE IS VENDORED into every adopter's composed/feeds/ tree
under eco-system ticket 45, so a wrong sentence in it travels into signed
artefacts.) An example carrying no `status`
beside one that does is refused by name. A payload in which NOTHING carries a
status predates the field: it prices as it always did and the scenario says
plainly that no example in it could be checked for finality.

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

# The editorial fallback for a payload published before major 4 carried a
# frequency. It is NOT a basis and it never travels alone: every scenario that
# annualises on it says so, names the number and names where the basis belongs
# (eco-system ticket 79 item 3).
DEFAULT_WARN_LEF = (1, 2, 4)
UNSOURCED_LEF_NOTE = (
    "FREQUENCY UNSOURCED: this line annualises at {lef} events/yr, which is this "
    "converter's editorial default and not a counted rate. Payload version {version} "
    "predates the publisher's `frequency` field, so no basis and no denominator could be "
    "read for it; from major 4 the basis belongs on "
    "regimes.{regime}.violation_types.{vt}.frequency.basis. A named could-not-look "
    "(eco-system ticket 79 item 3), never a bare number.")
DEFAULT_DENY_LEF = (0, 0, 1)   # admission blocks the loss path (matches driftwood-cart-pii.json)

# Which `status` values are a penalty that was actually imposed and collected.
# Everything else is a notice figure, a figure under challenge, or a figure that
# was set aside -- none of them a published fine (penalty-schema/rule.yaml).
# `final`                       the figure was imposed and the challenge window is
#                               closed or the challenge is decided; `final_as_of`
#                               says on what date, and `litigation` says how.
# `imposed-appeal-unchecked`    the regulator IMPOSED this figure (a penalty
#                               notice, an FCA final notice, an HHS OCR
#                               resolution agreement), no adverse litigation about
#                               it is known to this repository, and NO tribunal or
#                               court register was read FOR THAT EXAMPLE -- which
#                               is a statement about that example and not about
#                               the payload, so a figure whose finality IS sourced
#                               from published reporting recorded in this estate
#                               is `final` and says where (review F2). It prices,
#                               and every scenario it prices into says exactly
#                               that -- a named could-not-look on the APPEAL, not
#                               a claim of finality (eco-system ticket 79 item 1).
# Everything else -- `under-appeal`, `set-aside`, `not-collected`,
# `notice-of-intent`, `not-a-penalty`, `unknown` -- never prices.
PRICING_STATUS = ("final", "imposed-appeal-unchecked")
UNCHECKED_STATUS = "imposed-appeal-unchecked"
NO_STATUS_NOTE = (
    "FINALITY UNCHECKED: no example in payload version {version} carries a `status`, so "
    "whether any of the {n} figure(s) below is the FINAL collected penalty or a notice "
    "figure since reduced, set aside or never collected could not be looked at. From "
    "major 4 every example carries `status`, `final_as_of` and `litigation` "
    "(eco-system ticket 79 item 1). A named could-not-look.")


def _example_entries(vt: dict, currency_key: str) -> list[dict]:
    return list(vt.get(f"real_examples_{currency_key.lower()}", []))


def _final_examples(vt: dict, currency_key: str, where: str) -> tuple[list[float], str]:
    """The fines this converter may price from, and the sentence that says which
    of the published examples it left out and why.

    Three shapes, all derived from the bytes in front of it and never from a
    version string:

    * NO example carries `status` -- the payload predates the field. Every
      example prices, as it always did, and the caller carries NO_STATUS_NOTE.
    * SOME carry it and some do not -- refuses, naming the example that does
      not. A dataset half-checked for finality is worse than one not checked
      at all, because the half that was checked makes the other half look
      checked too.
    * ALL carry it -- only `final` figures price, and the rest are named.
    """
    fine_key = f"fine_{currency_key.lower()}"
    entries = _example_entries(vt, currency_key)
    priced = [e[fine_key] for e in entries if fine_key in e]
    with_status = [e for e in entries if "status" in e]
    if not with_status:
        return priced, NO_STATUS_NOTE.format(version="{version}", n=len(priced))
    missing = [e for e in entries if "status" not in e]
    if missing:
        named = ", ".join(str(e.get("org", "an unnamed example")) for e in missing)
        sys.exit(f"{where}: {named} carries no `status`, and other examples here do -- a "
                 f"penalty with no status prices as if it were final. Give it `status`, "
                 f"`final_as_of` and `litigation`, or remove it (eco-system ticket 79 item 1)")
    final, dropped, unchecked, sources = [], [], [], []
    for e in entries:
        if fine_key not in e:
            continue
        who = str(e.get("org", "an unnamed example"))
        # REVIEW F1. Finality without sourcing grades half the question: a figure
        # nobody can trace prices exactly as well as one everybody can. A priced
        # example with no `source` is a missing instrument (ADR-0020), refused by
        # name -- never dropped quietly, which would move the price too.
        if e.get("status") in PRICING_STATUS and not str(e.get("source") or "").strip():
            sys.exit(f"{where}: {who} would price {e[fine_key]:,.0f} {currency_key} and names no "
                     f"`source`. A figure with a status and no source is a number nobody can "
                     f"trace; give it the regulator's own instrument and where any later decision "
                     f"is recorded (eco-system ticket 79 review F1)")
        if e.get("status") in PRICING_STATUS:
            final.append(e[fine_key])
            sources.append(f"{who} ({e[fine_key]:,.0f} {currency_key}): {e['source']}")
            if e.get("status") == UNCHECKED_STATUS:
                unchecked.append(f"{who} ({e[fine_key]:,.0f} {currency_key})")
        else:
            dropped.append(f"{who} ({e[fine_key]:,.0f} {currency_key}, status "
                            f"{e.get('status')!r}: "
                            f"{e.get('litigation') or 'no litigation note'})")
    parts = []
    if dropped:
        parts.append("Not priced, because the publisher's rule is the FINAL COLLECTED FIGURE "
                     "and not the notice figure (penalty-schema/rule.yaml): "
                     + "; ".join(dropped) + ".")
    if unchecked:
        parts.append("APPEAL UNCHECKED: " + "; ".join(unchecked) + " price(s) here as a figure "
                     "the regulator imposed, with no tribunal or court register read by this "
                     "repository and no adverse litigation known to it. A named could-not-look "
                     "(eco-system ticket 79 item 1), never a claim that the figure is final.")
    if sources:
        parts.append("Priced from, with what each rests on: " + " | ".join(sources) + ".")
    return final, " ".join(parts)


def _frequency(vt: dict, where: str) -> tuple[tuple | None, str]:
    """The publisher's own published frequency and the sentence that carries its
    basis. `(None, "")` where the payload publishes none -- the caller then
    falls back to DEFAULT_WARN_LEF and says so. A frequency with no basis
    REFUSES: a number the publisher signs and cannot say the source of is a
    missing instrument, not a cheaper one (ADR-0020)."""
    freq = vt.get("frequency")
    if not freq:
        return None, ""
    basis = freq.get("basis")
    if not isinstance(basis, dict) or not basis.get("statement") or not basis.get("as_of"):
        sys.exit(f"{where}: publishes a frequency {freq.get('lef')!r} with no `basis` carrying "
                 f"a `statement` and an `as_of` date. A frequency the publisher signs and "
                 f"cannot say the source of is a missing instrument (ADR-0020); its basis "
                 f"belongs on {where}.frequency.basis (eco-system ticket 79 item 3)")
    lef = freq.get("lef")
    if not (isinstance(lef, (list, tuple)) and len(lef) == 3
            and lef[0] <= lef[1] <= lef[2]):
        sys.exit(f"{where}: frequency.lef is {lef!r}, not a lo<=mode<=hi triple")
    denominator = basis.get("denominator")
    could = basis.get("could_not_look")
    note = (f"Frequency {tuple(lef)} events/yr, basis ({basis.get('kind', 'unlabelled')}, read "
            f"{basis['as_of']}): {basis['statement']}"
            + (f" Denominator: {denominator}." if denominator else "")
            + (f" COULD NOT LOOK: {could}" if could else ""))
    return tuple(lef), note


def lm_triple(regime: dict, vt: dict, turnover: float | None = None,
              where: str = "this violation type") -> tuple[float, float, float]:
    currency = regime["currency"]
    f = vt["formula"]
    ex, _ = _final_examples(vt, currency, where)
    t = f["type"]

    if t in ("pct_of_global_turnover", "pct_of_relevant_revenue_plus_discretion"):
        if not ex:
            sys.exit(f"{where}: no FINAL real example for formula type {t}; every published "
                     f"figure here is a notice figure, under challenge, set aside or never "
                     f"collected, so there is nothing grounded to price from (ADR-0020)")
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
            # THE CAP RULE (eco-system ticket 79 items 5 and 7, delegated).
            # UK GDPR Art 83(4)/(5) and DPA 2018 s157 set the maximum at the
            # GREATER of the fixed sum and the percentage of turnover -- not the
            # lesser. So `statutory_max = max(cap, rate x turnover)` is the
            # ceiling, and the ratio scaling above only shapes the evidence
            # INSIDE it. Without this clamp the scale factor rate*turnover/cap
            # runs past 1 for any firm bigger than cap/rate and the ceiling
            # `1.2 x largest example` scales with it: at a turnover of
            # GBP 5,000,000,000 the old rule topped out at GBP 104,176,551.72
            # against a statutory maximum of GBP 100,000,000.00, i.e. it priced
            # a fine the statute does not permit.
            statutory_max = max(cap, float(rate) * float(turnover))
            hi = min(hi, statutory_max)
            mode = min(mode, hi)
            lo = min(lo, mode)
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
    version = schema["schema_version"]
    sources = [(regime_name, vt_name), *also]
    lms, names, regimes_used, finality, freqs = [], [], [], [], []
    for r_name, v_name in sources:
        regime = schema["regimes"][r_name]
        vt = regime["violation_types"][v_name]
        where = f"regimes.{r_name}.violation_types.{v_name}"
        lms.append(lm_triple(regime, vt, turnover, where=where))
        _, fin = _final_examples(vt, regime["currency"], where)
        finality.append(fin.replace("{version}", str(version)))
        freqs.append(_frequency(vt, where))
        names.append(f"{r_name}/{v_name}")
        regimes_used.append(regime)
    lm = lms[0] if len(lms) == 1 else [list(t) for t in lms]

    # THE FREQUENCY, and where it came from (eco-system ticket 79 item 3). The
    # publisher's own, when the payload publishes one -- the first source's,
    # because one breach drawing several regimes' consequences happens at ONE
    # rate (fair.py prices `also` sources additively on a shared lef). Where it
    # publishes none, the caller's default, and the note says so by name.
    published_lef, freq_note = freqs[0]
    if published_lef is not None and warn_lef == DEFAULT_WARN_LEF:
        warn_lef = published_lef
    elif published_lef is None:
        freq_note = UNSOURCED_LEF_NOTE.format(
            lef=tuple(warn_lef), version=version, regime=regime_name, vt=vt_name)
    if len(freqs) > 1:
        others = [f"{n}: {t or 'publishes no frequency'}"
                  for n, (_, t) in zip(names[1:], freqs[1:])]
        freq_note += (" The further obligation source(s) draw on this one frequency, not their "
                      "own (fair.py, shared lef); what each publishes is recorded here and not "
                      "used: " + " | ".join(others))

    if len(lms) == 1:
        r = regimes_used[0]
        note = (f"lm sourced from {r['authority']} real public fines ({r['statute']}). "
                + (f"Scaled to a subscriber turnover of {turnover:,.2f} {r['currency']}, "
                   f"clamped at the statutory maximum max(cap, rate x turnover)."
                   if turnover is not None else
                   "Not sized to any subscriber: priced at the statutory cap."))
    else:
        cites = "; ".join(f"{r['authority']} ({r['statute']})" for r in regimes_used)
        note = (f"lm sourced from real public fines, cited per source: {cites}. "
                f"{len(lms)} obligation sources on one breach ({', '.join(names)}), priced "
                f"additively and correlated (shared lef) -- see fair.py.")
    note = " ".join(x for x in ([note] + [f for f in finality if f] + [freq_note]) if x)
    return {
        "version": version,
        "name": f"ico:{version} " + " + ".join(names),
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
                lo, mode, hi = lm_triple(
                    regime, regime["violation_types"][vt_name],
                    where=f"{path}: regimes.{regime_name}.violation_types.{vt_name}")
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
            e["final_as_of"] = None if st != "final" else "2024"
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
    def f1():
        doc = _t79_payload()
        for e in _t79_vt(doc)["real_examples_gbp"]:
            e["status"] = "final"
            e["final_as_of"] = "2024"
            e["litigation"] = "planted"
        _t79_vt(doc)["real_examples_gbp"].append(
            {"org": "Invented Ltd", "year": 2025, "fine_gbp": 5_000_000, "status": "final",
             "final_as_of": "2025-01-01", "litigation": "final and collected."})
        try:
            got = lm_triple(doc["regimes"]["uk-gdpr"], _t79_vt(doc))
        except SystemExit as e:
            assert "source" in str(e) and "Invented Ltd" in str(e), \
                "refused, but not naming the example and the missing source: %s" % e
            return
        raise AssertionError(
            "an example with a `status` and NO `source` priced: lm_triple returned %r. A figure "
            "nobody can trace prices exactly as well as one everybody can" % (got,))

    def f1b():
        doc = _t79_payload()
        for e in _t79_vt(doc)["real_examples_gbp"]:
            e["status"] = "final"
            e["final_as_of"] = "2024"
            e["litigation"] = "planted"
        sc = build_scenario(doc, "uk-gdpr", "lower-tier")
        assert "ICO monetary penalty notice, 23 May 2022" in sc["note"], \
            ("the scenario prices from published fines and never says what each rests on: %r"
             % sc["note"])

    case("f1", "an example with a status and no source is refused by name", f1)
    case("f1", "the scenario names what each priced figure rests on", f1b)
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
