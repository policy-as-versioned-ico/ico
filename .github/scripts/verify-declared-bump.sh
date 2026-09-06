#!/usr/bin/env bash
# verify-declared-bump.sh -- ticket 43 (ticket 18 Answer 5), ico's half.
# The declared bump lives in a reviewed file (bump.yaml); this asserts that
# the file and the tree agree, offline, with no tag and no network:
#   1. the ladder itself, on fixtures (--selfcheck);
#   2. the REAL declaration against the REAL tree (--tree) -- the same
#      question .github/workflows/cut-release.yml asks before it tags.
#
# CORRECTED 2026-09-06 (eco-system ticket 67 item (b)): --tree asks about the
# NEXT release, not the gap between the two newest published majors, and it
# REFUSES rather than shrugs. The hub's talk/verify-manifest.txt declares no
# could-not-look for this row, so an exit 3 here grades FAIL in the gate anyway;
# a named refusal says more than a shrug that is failed for being one. The
# exit-3 branch below is kept for a future --tree that has a real reason not to
# look, and says so if it is ever taken.
# Exit 0 observed true, 3 could-not-look (nothing takes it today), non-zero
# observed false.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$here"

gate=.github/scripts/declared-bump-gate.py

echo "== the bump ladder, on fixtures =="
python3 "$gate" --selfcheck

echo
echo "== the real declaration against the real tree =="
set +e
out=$(python3 "$gate" --tree 2>&1); code=$?
set -e
echo "$out"
if [ "$code" -eq 3 ]; then
  echo "SKIP: $(echo "$out" | tail -1)"
  exit 3
fi
if [ "$code" -ne 0 ]; then
  echo "FAIL: the declared bump in bump.yaml and the bump computed from the tree disagree"
  exit 1
fi

echo
echo "PASS: the bump ladder holds on fixtures, and ico's own declared bump agrees with the"
echo "bump computed from its published tree under its own rule.yaml -- so a release cut"
echo "today would publish the number the reviewed file declares."
