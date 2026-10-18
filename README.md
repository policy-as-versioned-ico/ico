# policy-as-versioned-ico

**GitHub org:** [`policy-as-versioned-ico`](https://github.com/policy-as-versioned-ico) ·
**Role:** regulator — publisher · **Licence:** [Apache-2.0](LICENSE)

*A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.* See [DISCLAIMER.md](DISCLAIMER.md).

Part of the *Policy as Versioned Code* estate: a shared platform, two regulators, three regulated
institutions, each its own independent GitHub organisation, exchanging signed, versioned
dependencies. A regulator publishes controls or penalties as a signed, versioned artefact and bears
no risk of its own here. Full thesis, design decisions (ADRs) and the other five parties:
[policy-as-versioned-flux](https://github.com/policy-as-versioned-flux/policy-as-versioned-flux).

**Regulator (real magnitudes, repackaged).** A small, signed, versioned penalty
schema — `regime → violation-type → fine formula/cap` — sourced from real public
UK fine magnitudes. It feeds the FAIR loss-magnitude directly and is deliberately
**not** force-fit into OSCAL (which models controls/assessment, not fine
schedules).

Consumed by: `platform` FAIR engine (loss magnitude). *(ticket 07)*

## What's here

```
schema/
  v1/penalty-schema.json(.sig)   versioned schema + detached signature
  v2/penalty-schema.json(.sig)   a real bump: +1 real fine (Doorstep Dispensaree, £275k, 2019)
  keys/ico-signing-key(.pub).pem ed25519 keypair (ponytail: repo-local demo key, see sign.sh)
  sign.sh / verify.sh            offline sign / verify a version dir
  to_fair_scenario.py            schema entry -> fair.py scenario (unmodified fair.py consumes it)
verify-penalty-feed.sh           the whole beat: sign+verify, tamper rejection, £ moves on a bump
```

Four regimes, each `regime -> violation-type -> fine formula/cap`, grounded in real public
enforcement notices with cited sources: `uk-gdpr` (ICO), `pci-dss` (card-scheme acquiring banks),
`hipaa` (US HHS OCR), `fca` (UK FCA). Run `./verify-penalty-feed.sh` (offline, no cluster) to see
a schema-version bump move the £ that `platform/fair/fair.py` reports, with no edit to `fair.py`.

One breach can draw more than one regime's consequence at once (an ICO fine *and* a PCI penalty on
the same incident, say) — `to_fair_scenario.py build ... --also REGIME:VIOLATION_TYPE` (repeatable)
folds further obligation sources into one scenario, and `fair.py` prices them additively and
correlated (one shared frequency, not independent risks), so the £ gets bigger, never diluted.
Which regimes actually apply to which workload is still open. *(ticket 18)*


## Publisher reliability converter modes

The standalone `schema/to_fair_scenario.py` adds two explicit modes; existing
converter commands and published payloads keep their behavior:

```
python3 schema/to_fair_scenario.py forecast-base payload.json context.json
python3 schema/to_fair_scenario.py widen-to payload.json context.json
```

Both inputs are JSON; the payload is unwrapped with the existing converter version-key normalization (preserve a supplied key; otherwise use the authenticated selected edge version). `forecast-base` accepts only the
closed `publisher-reliability/generator-context-v1` wrapper (`schema`, exact
`source` reference, and complete parsed `document`). It returns the existing
headline FAIR scenario using that document's party and native-currency turnover. Missing turnover or a required FX conversion refuses by name.
The complete document must select this publisher/feed exactly once. No caller-selected scenario, institution or extra converter flags enter this mode.

`widen-to` accepts the closed `publisher-reliability/widen-context-v1` context.
Its adopter context is an exact cross-source reference or an exact same-tree
`{path, git_blob}` under the enclosing adopter source; historical generator
contexts still require the complete signed source reference.
Run it in the authenticated publisher snapshot: `context.widening.path` selects
the declaration, read as a regular file without symbolic links and checked
against its actual Git blob. The widening may be a different immutable release
from the target under the same publisher. The complete declared bounded-PERT
scenario must preserve identity, state frequencies and LM source arrangement;
LM components cannot narrow and every changed source must be declared. The
result carries the declaration's actual profile ID and preserves authority.
The consumer independently admits signatures, profile/unit bindings, release-cage
proof and applicability; a context or result is no authentication receipt.

There is no production target, forecast, outcome, bar or new feed release here.
A portable widening closure includes its selected declaration beside the copied
converter and input files; ordinary legacy replay still needs no sibling module.

The source-only opt-in native proof uses `.github/scripts/publisher-release-gate.py`:

```sh
python3 .github/scripts/publisher-release-gate.py build penalty-schema v3.0.1 native.json cage.json
python3 .github/scripts/publisher-release-gate.py verify cage.json v3.0.1
```

Commit the semantic target, existing native code, rule and bump declaration before
building. The build writes only new proof files. After inspecting them, a future
enrollment adds the exact cage path/Git blob to `payload.release_cage`, commits
the proof and pointer, and uses the ordinary signed release path. The new
`penalty-schema/payload.release-cage.schema.v1.json` permits this optional pointer; no
existing payload selects it. Changing `payload_schema` still computes a major.
The pre-sign workflow reproduces an enrolled proof; without a pointer its
existing release gates apply unchanged.

The proof uses the publisher's actual existing native computation. An input,
history, structural or tag-legality fault refuses. Only a successfully computed
bump above the declared rung is degraded: the exact requested tag must then be
`-quarantine.N`, with quarantine tier/suffix. Equal or stronger declarations
produce a clean baseline release. The tag must still be the exact declared
increment of the maximal clean predecessor. Complete first-parent Git history
and annotated tags are required; Git tag dates/order are publisher assertions,
not an independent clock. Later descendant tags do not change replay.

Native evidence binds code/rule/declaration blobs, captured release history and
predecessor, and a canonical target semantic hash excluding **only**
`payload.release_cage` to avoid a pointer/hash cycle. That projection hash is not
a raw Git blob. The outer proof separately binds actual native-evidence and
gate-code Git blobs. The consumer must authenticate the full publisher source,
its release tags and closure before executing the public replay CLI. Neither
this helper nor an input descriptor is signature admission. No current financial
value, proof, tag or enrollment is manufactured by this capability.
