"""Synthetic public CLI fixtures only: no production declaration or signature claim."""
from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import unittest

PARTY = 'ico'
AUTHORITY = 'regulator-conservative-exposure'
CONVERTER = Path(__file__).with_name('to_fair_scenario.py')

class AdapterCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payload = {'schema_version': 'synthetic', 'feed_version': 'synthetic'}
        lm = [[1, 2, 3], [10, 20, 30]] if PARTY == 'ico' else [1, 2, 3]
        target_lm = [[2, 3, 4], [10, 25, 35]] if PARTY == 'ico' else [2, 3, 4]
        self.base = {'version': 'synthetic', 'name': PARTY + ':synthetic-fixture',
                     'warn': {'lef': [1, 1, 1], 'lm': lm}, 'deny': {'lef': [0, 0, 1], 'lm': lm}}
        self.target = copy.deepcopy(self.base)
        for state in ('warn', 'deny'):
            self.target[state]['lm'] = copy.deepcopy(target_lm)
        affected = [f'/{state}/lm/{i}' for state in ('warn', 'deny') for i in range(2)] if PARTY == 'ico' else ['/warn/lm', '/deny/lm']
        self.declaration = {'schema': 'publisher-reliability/widening-v1', 'id': 'synthetic-target/v1',
            'profile_id': 'synthetic-profile/v1', 'unit': {'currency': 'GBP', 'basis': 'synthetic nominal'},
            'authority': AUTHORITY, 'authoritative_value_action': 'preserve', 'affected_sources': affected,
            'citation': 'Synthetic source fixture, not a real exposure.',
            'release_cage': {'path': 'synthetic-cage.json', 'git_blob': 'd' * 40}, 'target': self.target}
        def ref(party, path, commit='a' * 40):
            return {'party': party, 'tag': 'synthetic/v1', 'commit': commit, 'path': path, 'git_blob': 'b' * 40}
        self.context = {'schema': 'publisher-reliability/widen-context-v1', 'target': ref(PARTY, 'payload.json'),
            'profile': ref('nist', 'profile.json'), 'widening': ref(PARTY, 'declared/target.json', 'c' * 40),
            'adopter_party': 'synthetic-adopter', 'adopter_context': ref('synthetic-adopter', 'party.json'),
            'base_scenario': self.base, 'state': 'warn', 'financial_as_of': '2026-10-18'}
        self.save()

    def save(self):
        self.write('payload.json', self.payload)
        self.write('declared/target.json', self.declaration)
        digest = subprocess.check_output(['git', 'hash-object', str(self.root / 'declared/target.json')], text=True).strip()
        self.context['widening']['git_blob'] = digest
        self.context['widening']['tag'] = 'synthetic-widening/v2'
        self.write('context.json', self.context)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def invoke(self, mode='widen-to'):
        return subprocess.run([sys.executable, '-I', str(CONVERTER), mode, 'payload.json', 'context.json'],
                              cwd=self.root, capture_output=True, text=True)

    def test_full_publisher_target_crosses_actual_standalone_cli(self):
        standalone = self.root / 'standalone.py'
        standalone.write_bytes(CONVERTER.read_bytes())
        result = subprocess.run([sys.executable, '-I', str(standalone), 'widen-to', 'payload.json', 'context.json'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'schema': 'publisher-reliability/widen-result-v1',
            'target_id': 'synthetic-target/v1', 'profile_id': 'synthetic-profile/v1', 'scenario': self.target,
            'authority_action': 'preserve', 'affected_sources': self.declaration['affected_sources']})

    def test_prospective_adopter_context_accepts_exact_same_tree_reference(self):
        self.context['adopter_context']['party'] = 'wrong-adopter'
        self.write('context.json', self.context)
        self.assert_refused()
        self.context['adopter_context'] = {'path': 'party.yaml', 'git_blob': 'e' * 40}
        self.write('context.json', self.context)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        for value in ({'path': '../party.yaml', 'git_blob': 'e' * 40},
                      {'path': 'party.yaml', 'git_blob': 'bad'},
                      {'path': 'party.yaml', 'git_blob': 'e' * 40, 'admitted': True}):
            self.context['adopter_context'] = value
            self.write('context.json', self.context)
            self.assert_refused()

    def test_forecast_base_derives_native_scenario_from_full_context(self):
        document = {'party': 'synthetic-adopter', 'inherits': [{'party': 'ico', 'kind': 'feed', 'name': 'penalty-schema', 'version': 'synthetic'}], 'size': {'turnover': {'amount': 1000, 'currency': 'GBP'}}}
        if PARTY == 'ico':
            self.payload = {'schema_version': 'synthetic', 'regimes': {'uk-gdpr': {'currency': 'GBP',
                'authority': 'Synthetic authority', 'statute': 'Synthetic fixture only',
                'violation_types': {'lower-tier': {'formula': {'type': 'pct_of_global_turnover', 'rate': 0.02, 'cap_gbp': 100},
                    'real_examples_gbp': [{'fine_gbp': 20}, {'fine_gbp': 40}]}}}}}
            expected_lef, expected_lm = [1, 2, 4], [4.0, 6.0, 20.0]
            expected_name = 'ico:synthetic uk-gdpr/lower-tier'
        else:
            self.payload = {'feed_version': 'synthetic', 'currency': 'GBP', 'institutions': {'synthetic-adopter': {
                'lef': [1, 2, 3], 'threat': 'Synthetic loss', 'flavour': 'source fixture only', 'source': 'Synthetic fixture',
                'lm_gbp': [10, 20, 30], 'lm_basis': {'statement': 'Synthetic fixture only', 'as_of': '2026-10-18'}}}}
            expected_lef, expected_lm = [1.0, 2.0, 3.0], [10.0, 20.0, 30.0]
            expected_name = 'threat-register:synthetic synthetic-adopter'
        self.context = {'schema': 'publisher-reliability/generator-context-v1',
                        'source': self.context['adopter_context'], 'document': document}
        self.write('payload.json', self.payload)
        self.write('context.json', self.context)
        result = self.invoke('forecast-base')
        self.assertEqual(result.returncode, 0, result.stderr)
        scenario = json.loads(result.stdout)
        self.assertEqual(scenario['name'], expected_name)
        self.assertEqual(scenario['warn'], {'lef': expected_lef, 'lm': expected_lm})
        self.assertEqual(scenario['deny']['lm'], expected_lm)
        self.assertNotIn('schema', scenario)

    def assert_refused(self, mode='widen-to'):
        result = self.invoke(mode)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('invalid publisher instrument', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result.stderr

    def test_declared_git_blob_and_closed_json_are_load_bearing(self):
        self.context['widening']['git_blob'] = 'f' * 40
        self.write('context.json', self.context)
        self.assertIn('Git blob', self.assert_refused())
        self.save()
        self.context['ignored-admission'] = True
        self.write('context.json', self.context)
        self.assertIn('unknown fields', self.assert_refused())

    def test_declaration_cannot_read_outside_or_through_links(self):
        import os
        original = copy.deepcopy(self.context)
        for path in ('../target.json', '/target.json', 'declared/../target.json', 'declared//target.json'):
            with self.subTest(path=path):
                self.context = copy.deepcopy(original)
                self.context['widening']['path'] = path
                self.write('context.json', self.context)
                self.assert_refused()
        (self.root / 'linked').symlink_to(self.root / 'declared', target_is_directory=True)
        self.context = copy.deepcopy(original)
        self.context['widening']['path'] = 'linked/target.json'
        self.write('context.json', self.context)
        self.assert_refused()
        (self.root / 'declared/alias.json').symlink_to(self.root / 'declared/target.json')
        self.context['widening']['path'] = 'declared/alias.json'
        self.write('context.json', self.context)
        self.assert_refused()
        os.mkfifo(self.root / 'declared/pipe')
        self.context['widening']['path'] = 'declared/pipe'
        self.write('context.json', self.context)
        self.assertIn('regular file', self.assert_refused())

    def test_target_preserves_identity_frequency_authority_and_source_arrangement(self):
        original = copy.deepcopy(self.declaration)
        mutations = [
            ('identity', lambda d: d['target'].__setitem__('name', 'another-scenario')),
            ('frequency', lambda d: d['target']['warn'].__setitem__('lef', [2, 2, 2])),
            ('authority', lambda d: d.__setitem__('authoritative_value_action', 'replace')),
            ('unaccounted', lambda d: d.__setitem__('affected_sources', [])),
            ('unknown field', lambda d: d['target'].__setitem__('admitted', True)),
            ('narrowing', lambda d: d['target']['warn'].__setitem__('lm', [[0, 1, 2], [10, 25, 35]] if PARTY == 'ico' else [0, 1, 2])),
            ('source arrangement', lambda d: d['target']['warn'].__setitem__('lm', [1, 2, 3] if PARTY == 'ico' else [[1, 2, 3]])),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                self.declaration = copy.deepcopy(original)
                mutate(self.declaration)
                self.save()
                self.assert_refused()

    def test_boolean_nonfinite_unordered_and_unrepresentable_money_refuse(self):
        original = copy.deepcopy(self.declaration)
        for triple in ([True, 3, 4], [2, float('nan'), 4], [2, 5, 4], [10**500, 10**500, 10**500], [-0.0, 3, 4]):
            with self.subTest(value=repr(triple)[:60]):
                self.declaration = copy.deepcopy(original)
                self.declaration['target']['warn']['lm'] = [triple, [10, 25, 35]] if PARTY == 'ico' else triple
                self.save()
                self.assert_refused()

    def test_duplicate_keys_and_record_byte_budget_refuse(self):
        path = self.root / 'declared/target.json'
        raw = path.read_text().replace('"id":', '"id": "duplicate", "id":', 1)
        path.write_text(raw)
        self.context['widening']['git_blob'] = subprocess.check_output(['git', 'hash-object', str(path)], text=True).strip()
        self.write('context.json', self.context)
        self.assertIn('duplicate', self.assert_refused())
        with (self.root / 'context.json').open('wb') as stream:
            stream.seek(33554432)
            stream.write(b' ')
        self.assertIn('resource-limit', self.assert_refused())

    def test_forecast_context_is_not_an_arbitrary_scenario_or_identity_override(self):
        self.context = {'schema': 'publisher-reliability/generator-context-v1',
                        'source': self.context['adopter_context'], 'document': {'party': 'another-adopter'}}
        self.write('context.json', self.context)
        self.assertIn('party', self.assert_refused('forecast-base'))
        self.context['document']['party'] = 'synthetic-adopter'
        self.context['args'] = ['--turnover', '1']
        self.write('context.json', self.context)
        self.assertIn('unknown fields', self.assert_refused('forecast-base'))

    def test_forecast_native_currency_and_required_context_refuse_by_name(self):
        document = {'party': 'synthetic-adopter', 'inherits': [{'party': 'ico', 'kind': 'feed', 'name': 'penalty-schema', 'version': 'synthetic'}]}
        self.context = {'schema': 'publisher-reliability/generator-context-v1',
                        'source': self.context['adopter_context'], 'document': document}
        if PARTY == 'ico':
            self.payload = {'schema_version': 'synthetic', 'regimes': {'uk-gdpr': {'currency': 'GBP'}}}
            cases = [({}, 'turnover'),
                     ({'turnover': {'amount': True, 'currency': 'GBP'}}, 'booleans'),
                     ({'turnover': {'amount': 1000, 'currency': 'USD'}}, 'FX')]
            for size, diagnostic in cases:
                with self.subTest(diagnostic=diagnostic):
                    document['size'] = size
                    self.write('payload.json', self.payload)
                    self.write('context.json', self.context)
                    self.assertIn(diagnostic, self.assert_refused('forecast-base'))
        else:
            for currency in (None, 'not-a-currency'):
                with self.subTest(currency=currency):
                    self.payload = {'feed_version': 'synthetic', 'currency': currency}
                    self.write('payload.json', self.payload)
                    self.write('context.json', self.context)
                    self.assertIn('native currency', self.assert_refused('forecast-base'))

if __name__ == '__main__':
    unittest.main()
