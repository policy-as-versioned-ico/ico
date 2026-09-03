# Disclaimer

A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.

`policy-as-versioned-ico` is a party in the *Policy as Versioned Code* demonstration estate. It is
**not** the Information Commissioner's Office, the Financial Conduct Authority, the US Department
of Health and Human Services, any card scheme or acquiring bank, or any other regulator or
authority named in its files. Nobody at any of those bodies has reviewed, approved or contributed
to this repository.

## What the `authority` field means

The signed penalty schema (`penalty-schema/v*/feed.json`) carries an `authority` value on each
regime, for example `ICO (Information Commissioner's Office)`. That value is a **citation of the
body that levied the real fines the schema's magnitudes are drawn from** — the provenance of the
number — and not a claim that this party is, represents or publishes on behalf of that body. Every
magnitude is sourced from a public enforcement notice, final notice or resolution agreement, and
each entry names its source.

Each real example records the organisation, the year, the figure as levied in the notice (and,
where the notice itself reduced a proposed figure, that proposed figure) and its source. That is
all it records. No version of the schema records whether a figure was later reduced on appeal,
overturned or never collected, so a figure here is the notice figure on the date cited and may
be stale. The hub's ticket 79 plans to add a `status` and a `final_as_of` per example and to
correct the stale figures it has identified in a new major version; until that lands, a stale
figure here is a defect to correct, not a statement by the authority.

## What the signature means

Versions are signed under this repository's own keys and gitsign tags. A signature here attests
that *this demonstration party* published the file, nothing more. It attests nothing about any
regulator, and no regulator's key signs anything in this estate.

## What this is for

The estate shows how a penalty schedule can travel as a signed, versioned, machine-readable
dependency that a regulated institution pins and a risk engine prices from. The figures are
real magnitudes used to keep the demonstration honest about scale; the party publishing them is
a stand-in. Do not rely on this repository for legal, regulatory or compliance advice.

The wrapper — the schema, scripts, party artefact and documentation — is licensed under
[Apache-2.0](LICENSE). Enforcement notices and other public records cited in the schema remain
the works of their respective authors and are cited under their own terms.
