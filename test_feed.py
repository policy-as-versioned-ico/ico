import json
import unittest
from pathlib import Path

PRICING = {"final", "imposed-appeal-unchecked"}
STATUSES = PRICING | {"not-collected"}
FEED = json.loads((Path(__file__).parent / "penalty-schema" / "feed.json").read_text())
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
            self.assertGreater(tier["rate"], 0)
            self.assertGreater(tier["cap"], 0)

    def test_penalty_rate(self):
        rate, basis = REGIME["penalty_rate"], REGIME["penalty_rate_basis"]
        self.assertTrue(basis["text"])
        self.assertRegex(basis["as_of"], r"^\d{4}-\d{2}-\d{2}$")
        if rate is None:
            self.assertEqual(basis["kind"], "not-counted")
        else:
            self.assertTrue(0 < rate <= 1)
            self.assertEqual(basis["kind"], "counted")

    def test_each_fine(self):
        for name, fine in fines():
            with self.subTest(tier=name, org=fine["org"]):
                self.assertIn(fine["status"], STATUSES)
                self.assertIsInstance(fine["year"], int)
                self.assertGreater(fine["amount"], 0)
                self.assertTrue(fine["litigation"])
                if fine["status"] in PRICING:
                    self.assertTrue(fine["source"])

    def test_each_tier_has_a_pricing_fine(self):
        for name, tier in REGIME["tiers"].items():
            with self.subTest(tier=name):
                self.assertTrue(any(f["status"] in PRICING for f in tier["fines"]))
