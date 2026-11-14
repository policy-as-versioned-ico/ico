import json
import unittest
from pathlib import Path

PRICING = {"final", "imposed-appeal-unchecked"}


def unique(pairs):
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys)), f"duplicate key in {keys}"
    return dict(pairs)


def number(x):
    return type(x) in (int, float) and 0 < x < float("inf")


FEED = json.loads((Path(__file__).parent / "penalty-schema" / "feed.json").read_text(), object_pairs_hook=unique)
REGIME = FEED["regimes"]["uk-gdpr"]


def fines():
    for name, tier in REGIME["tiers"].items():
        for fine in tier["fines"]:
            yield name, fine


class FeedShape(unittest.TestCase):
    def test_header(self):
        self.assertEqual(FEED["feed"], "penalty-schema")
        self.assertEqual(FEED["published_by"], "ico")
        self.assertRegex(FEED["version"], r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(list(FEED["regimes"]), ["uk-gdpr"])

    def test_regime(self):
        self.assertEqual(REGIME["currency"], "GBP")
        self.assertEqual(list(REGIME["tiers"]), ["higher", "lower"])
        for tier in REGIME["tiers"].values():
            self.assertTrue(number(tier["rate"]) and number(tier["cap"]))

    def test_penalty_rate(self):
        rate, basis = REGIME["penalty_rate"], REGIME["penalty_rate_basis"]
        self.assertTrue(basis["text"])
        self.assertRegex(basis["as_of"], r"^\d{4}-\d{2}-\d{2}$")
        if rate is None:
            self.assertEqual(basis["kind"], "not-counted")
        else:
            self.assertTrue(number(rate) and rate <= 1)
            self.assertEqual(basis["kind"], "counted")

    def test_each_fine(self):
        for name, fine in fines():
            with self.subTest(tier=name, org=fine["org"]):
                self.assertTrue(fine["status"])
                self.assertIsInstance(fine["year"], int)
                self.assertTrue(number(fine["amount"]))
                self.assertTrue(fine["litigation"])
                if fine["status"] in PRICING:
                    self.assertTrue(fine["source"])
