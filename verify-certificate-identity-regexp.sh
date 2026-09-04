#!/usr/bin/env bash
# Ticket cs-14: EXPECTED_IDENTITY_REGEXP (release.yml) must accept main and
# release/<major>.<minor>.x maintenance branches for THIS org/repo, and
# reject any foreign org, repo, workflow path, or unanchored suffix/prefix.
# Offline: reads the pattern straight out of release.yml, no cluster, no gitsign.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workflow="$here/.github/workflows/release.yml"

fail() { echo "FAIL: $*" >&2; exit 1; }
say() { echo; echo "== $* =="; }

pattern=$(sed -n 's/^  EXPECTED_IDENTITY_REGEXP: //p' "$workflow")
[ -n "$pattern" ] || fail "EXPECTED_IDENTITY_REGEXP not found in $workflow"
echo "pattern: $pattern"

matches() { [[ "$1" =~ $pattern ]]; }

say "1. this repo's own identities match"
for good in \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/main" \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/release/1.0.x" \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/release/2.0.x"
do
  matches "$good" || fail "expected identity did not match: $good"
  echo "ok  matched: $good"
done

say "2. foreign org/repo, foreign workflow path, and unanchored ref shapes are rejected"
for bad in \
  "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main" \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/other.yml@refs/heads/main" \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/maint/1.0" \
  "https://evil.example/https://github.com/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/main" \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/mainX" \
  "https://githubXcom/policy-as-versioned-ico/ico/.github/workflows/cut-release.yml@refs/heads/main" \
  "https://github.com/policy-as-versioned-ico/ico/.github/workflows/propose-tier.yml@refs/heads/main"
do
  matches "$bad" && fail "foreign/malformed identity incorrectly matched: $bad"
  echo "ok  rejected: $bad"
done

echo
echo "PASS: EXPECTED_IDENTITY_REGEXP accepts this repo's main and release/<major>.<minor>.x,"
echo "and rejects every foreign org/repo/path and unanchored variant tried."
