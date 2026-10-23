#!/usr/bin/env python3
"""Exercise the registered envelope verifier against disposable source copies."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class FeedEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ico-envelope-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("penalty-schema", "schema"):
            shutil.copytree(ROOT / directory, self.root / directory)
        shutil.copyfile(ROOT / "party.yaml", self.root / "party.yaml")
        # Keep rejection controls independent of the pending release version.
        self.change(4, lambda env: env.update(version="4.0.0"))

    def change(self, major, mutate):
        path = self.root / f"penalty-schema/v{major}/feed.json"
        env = json.loads(path.read_text())
        mutate(env)
        path.write_text(json.dumps(env))

    def verify(self):
        wrapper = (ROOT / "verify-penalty-feed.sh").read_text()
        marker = "python3 - \"$here\" <<'ENVELOPE'\n"
        self.assertEqual(wrapper.count(marker), 1)
        code = wrapper.split(marker, 1)[1].split("\nENVELOPE\n", 1)[0]
        return subprocess.run([sys.executable, "-", str(self.root)], input=code,
                              text=True, capture_output=True, timeout=15)

    def assert_accepted(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no formula rate or cap moved", result.stdout)

    def assert_refused(self, reason):
        result = self.verify()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(reason, result.stdout + result.stderr)

    def test_existing_envelopes(self):
        self.assert_accepted()

    def test_patch_and_minor_versions_in_all_major_directories(self):
        for major in range(1, 5):
            for suffix in ("0.1", "1.0"):
                with self.subTest(major=major, suffix=suffix):
                    self.change(major, lambda env: env.update(version=f"{major}.{suffix}"))
                    try:
                        self.assert_accepted()
                    finally:
                        self.change(major, lambda env: env.update(version=f"{major}.0.0"))

    def test_wrong_directory_major_is_refused(self):
        self.change(4, lambda env: env.update(version="5.0.0"))
        self.assert_refused("declares version")

    def test_malformed_versions_are_refused(self):
        for version in ("v4.0.1", "4.01.0", "4.0", "4.0.1-rc.1", "4.0.1\n",
                        "4.1\u0662.0", "4.0.1\u0662", 4, None):
            with self.subTest(version=version):
                self.change(4, lambda env: env.update(version=version))
                self.assert_refused("not a semver string")

    def test_publisher_identity_is_preserved(self):
        self.change(4, lambda env: env.update(published_by="other"))
        self.assert_refused("published_by")

    def test_payload_schema_requirements_are_preserved(self):
        self.change(4, lambda env: env["payload"].pop("regimes"))
        self.assert_refused("missing")

    def test_migrated_regimes_are_preserved(self):
        self.change(3, lambda env: env["payload"].update(regimes={}))
        self.assert_refused("major 3 changed the regimes payload")

    def test_financial_formula_invariant_is_preserved(self):
        self.change(4, lambda env: env["payload"]["regimes"]["uk-gdpr"]["violation_types"]["higher-tier"]["formula"].update(rate=0.05))
        self.assert_refused("FORMULA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
