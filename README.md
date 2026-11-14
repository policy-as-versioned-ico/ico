# ico

*A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.* See [DISCLAIMER.md](DISCLAIMER.md).

This repository publishes one feed: `penalty-schema/feed.json`. The feed holds the UK GDPR penalty regime. It has two tiers, each with a rate, a cap and the fines that bear on it. Every fine carries its status, its source and a note on its litigation.

The feed is one input to a loop that prices a party's losses against its tolerance. The loop reads the feed from a pinned commit or tag. It does not call this repository at run time.

## What the feed says

- `penalty_rate` is the chance that one breach draws a penalty. It is `null` until someone counts the regulator's register. A reader takes `null` as 1.
- A fine prices only if its status is `final` or `imposed-appeal-unchecked`. A fine that was set aside or never collected is listed and does not price.
- The mean penalty at a turnover is worked out by the reader from the tier's rate and cap and from the pricing fines.

## How a change lands

1. Change `penalty-schema/feed.json` and its `version` in the same pull request. A change to the numbers with the same `version` is refused when the tag is cut.
2. The `test` job runs `test_feed.py` on every pull request and every push to `main`. The tests check the shape of the file.
3. The GitHub App `pavc-other-hand` approves and merges the pull request.
4. The `cut` job signs and pushes the tag `v<version>` from `main`. It runs on dispatch. It runs on a merge too once the repository variable `CUT_ON_MERGE` is `true`. A tag that exists is never moved.

To run the tests: `python3 -m unittest -v test_feed`.

The licence is Apache-2.0, in [LICENSE](LICENSE).
