# Rulesets

`observation-lane.json` is the server-side half of ADR-0024's cage: a **push ruleset** that refuses
a push containing any declaration path. The owner applies it, because no agent in this build has
(or should have) the `admin:repo` credential that creates a ruleset:

    gh api --method POST -H "Accept: application/vnd.github+json" \
      /repos/<owner>/<repo>/rulesets --input .github/rulesets/observation-lane.json

Re-applying an existing ruleset is `--method PUT /repos/<owner>/<repo>/rulesets/<id>`; find the id
with `gh api /repos/<owner>/<repo>/rulesets`.

## Amended 2026-08-28: this leg is NOT in force, and cannot be until the repos are private

Two things were wrong with the first version of this file, and the review of 2026-08-28 found both
by trying to apply it:

1. It declared `"target": "branch"` with `conditions.ref_name.include: ["~DEFAULT_BRANCH"]` and a
   `file_path_restriction` rule. `file_path_restriction` is a **push**-ruleset rule; push rulesets
   have no `ref_name` condition and do not target branches. The shape GitHub accepts is the one now
   in the file. **And GitHub only allows push rulesets on private or internal repositories.** Every
   repository in this estate is public (`gh api /repos/<owner>/<repo> --jq .visibility` -> `public`)
   and no ruleset exists on any of them (`gh api /repos/<owner>/<repo>/rulesets` -> `[]`).
2. Its first rule was `required_signatures`, justified as "the scheduled jobs sign with gitsign".
   GitHub does not recognise a gitsign signature as verified -- the sigstore CA root is not in
   GitHub's trust root, and the ephemeral certificate reads as expired without a Rekor lookup
   GitHub does not do. `required_signatures` refuses a commit it cannot verify, so applying that
   rule would have made the two clocks that push the default branch (the hub's `truth` and
   driftwood's `twin-sweep`) fail on push every single day. The rule is removed.

So, honestly: **today the cage's load-bearing halves are the client-side cage step in each
scheduled job and the gate that parses it** (`verify/schedules/verify-schedules.sh` in the hub).
The server-side half is this prepared artefact and nothing more. It becomes real by either

- making the repositories private or internal under a plan that allows push rulesets, and applying
  this file as-is; or
- keeping them public and replacing this with a required status check on the default branch that
  runs the same path assertion, plus a dedicated app or deploy key for the clock identity scoped to
  the `observations` branch.

Note also that the five publisher clocks push the `observations` branch, which a push ruleset does
cover (it applies to every ref), where the old branch-targeted shape covered none of it.

## What it says, and why

A clock may **append observations** to the repository and may **never commit a declaration**
(ADR-0024, decision D1). One rule carries that:

- `file_path_restriction` — the declaration paths are refused: tiers (`deploy/**`), pins and Flux
  sources (`gitops/**`), the composed artefact and its priced evidence (`composed/**`), the floor
  and the overlay (`selection-policy/**`, `twin/**`), the published feeds (`**/feed.json`,
  `**/bump.yaml`, `**/rule.yaml`), the served cage (`graded/**`, `distribution/**`), the party
  artefact itself, and the workflows, so a clock cannot rewrite its own cage.

GitHub rulesets have no "this identity may touch only these paths" rule, so the cage is written as
the complement: everything a declaration lives in is restricted, and the observation paths
(`talk/truth.log`, `drift/samples.jsonl`, `talk/captures/**`, `observations/**`) are simply not on
the list. `bypass_actors` grants the organisation admin an always-bypass, so a **human** still
merges a reviewed tier or pin pull request; the scheduled identity has no bypass and cannot. The
identity separation is what makes it a cage rather than a lock nobody can open.

The client-side half is the `the observation cage` step in every scheduled workflow: it stages only
the paths in that job's `OBSERVATION_LANE`, refuses anything else in the index or the tree, and
fails the run. `verify/schedules/verify-schedules.sh` in the hub checks that half offline and looks
at the live ruleset state on the remote.
