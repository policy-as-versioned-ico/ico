"""Synthetic unsigned Git fixtures: public release-gate CLI, no signing/network."""
from pathlib import Path
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import textwrap

PARTY = 'ico'
ROOT = Path(__file__).resolve().parents[2]
HELPER = '.github/scripts/publisher-release-gate.py'
NATIVE = '.github/scripts/declared-bump-gate.py' if PARTY == 'ico' else 'bump.py'
FEED = 'penalty-schema' if PARTY == 'ico' else 'threat-register'
PREFIX = '' if PARTY == 'ico' else FEED + '/'

class ReleaseGateCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_DATE='2026-10-17T00:00:00Z', GIT_COMMITTER_DATE='2026-10-17T00:00:00Z')
        self.git('init', '-q')
        self.git('config', 'user.email', 'synthetic@fixture.invalid')
        self.git('config', 'user.name', 'Synthetic fixture')
        for name in (NATIVE, HELPER):
            source = ROOT / name
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copyfile(source, destination)
        self.write(FEED + '/rule.yaml', 'entries: entries\nnumeric_tolerance: 0\nchanged_when: fixture\n')
        self.write(FEED + '/bump.yaml', 'bump: patch\n')
        self.payload = {'kind': 'feed', 'name': FEED, 'published_by': PARTY, 'version': '3.0.0',
                        'payload_schema': 'synthetic/payload.json', 'payload': {'entries': {'same': {'lm': 9}}}}
        self.save()
        self.foreign = copy.deepcopy(self.payload)
        self.foreign['name'] = 'unpublished-feed'
        self.write('unpublished-feed/v3/feed.json', self.foreign)
        self.write('unpublished-feed/rule.yaml', 'entries: entries\nnumeric_tolerance: 0\nchanged_when: fixture\n')
        self.write('unpublished-feed/bump.yaml', 'bump: patch\n')
        self.commit('synthetic predecessor')
        self.git('tag', '-a', PREFIX + 'v3.0.0', '-m', 'Synthetic unsigned predecessor')
        self.env.update(GIT_AUTHOR_DATE='2026-10-18T00:00:00Z', GIT_COMMITTER_DATE='2026-10-18T00:00:00Z')
        self.payload['version'] = '3.0.1'
        self.payload['payload']['entries']['same']['lm'] = 10
        self.save()
        self.foreign['version'] = '3.0.1'
        self.foreign['payload']['entries']['same']['lm'] = 10
        self.write('unpublished-feed/v3/feed.json', self.foreign)
        self.commit('synthetic target inputs')

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'commit.gpgSign=false', '-c', 'tag.gpgSign=false',
                                        '-c', 'log.showSignature=false', *args], cwd=self.root, env=self.env, text=True).strip()

    def write(self, path, data):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data))

    def save(self):
        self.write(FEED + '/v3/feed.json', self.payload)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-q', '-m', message)

    def invoke(self, *args):
        return subprocess.run([sys.executable, '-I', HELPER, *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True)

    def build(self, tag=None):
        return self.invoke('build', FEED, tag or PREFIX + 'v3.0.1', 'native.json', 'cage.json')

    def enroll(self, tag=None):
        tag = tag or PREFIX + 'v3.0.1'
        result = self.build(tag)
        self.assertEqual(result.returncode, 0, result.stderr)
        blob = self.git('hash-object', 'cage.json')
        self.payload['payload']['release_cage'] = {'path': 'cage.json', 'git_blob': blob}
        self.save()
        self.commit('synthetic proof enrollment')
        return tag

    def assert_refused(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('REFUSED:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_build_and_replay_actual_native_computation(self):
        tag = self.enroll()
        cage = json.loads((self.root / 'cage.json').read_text())
        self.assertEqual((cage['outcome'], cage['tier'], cage['declared_bump'], cage['computed_bump'], cage['suffix']),
                         ('passed', 'baseline', 'patch', 'patch', None))
        self.git('tag', '-a', tag, '-m', 'Synthetic unsigned target')
        result = self.invoke('verify', 'cage.json', tag)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('VERIFIED', result.stdout)

    def test_only_successfully_computed_weaker_declaration_degrades(self):
        del self.payload['payload']['entries']['same']
        self.payload['version'] = '3.0.1-quarantine.1'
        self.save()
        self.commit('synthetic actual major underdeclared patch')
        tag = self.enroll(PREFIX + 'v3.0.1-quarantine.1')
        cage = json.loads((self.root / 'cage.json').read_text())
        self.assertEqual((cage['outcome'], cage['tier'], cage['computed_bump'], cage['suffix']),
                         ('degraded', 'quarantine', 'major', 'quarantine'))
        result = self.invoke('verify', 'cage.json', tag)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stronger_declaration_passes_but_wrong_increment_and_none_refuse(self):
        self.write(FEED + '/bump.yaml', 'bump: minor\n')
        self.payload['version'] = '3.1.0'
        self.save()
        self.commit('synthetic stronger declaration')
        tag = self.enroll(PREFIX + 'v3.1.0')
        self.assertEqual(self.invoke('verify', 'cage.json', tag).returncode, 0)
        self.assert_refused(self.build(PREFIX + 'v3.0.1'))
        self.write(FEED + '/bump.yaml', 'bump: none\n')
        self.commit('synthetic no release declaration')
        self.assert_refused(self.build())

    def test_clean_underdeclaration_and_spurious_quarantine_refuse(self):
        self.payload['payload']['entries'] = {}
        self.save()
        self.commit('synthetic major removal')
        self.assert_refused(self.build())
        self.payload['payload']['entries'] = {'same': {'lm': 10}}
        self.payload['version'] = '3.0.1-quarantine.1'
        self.save()
        self.commit('synthetic ordinary patch requesting quarantine')
        self.assert_refused(self.build(PREFIX + 'v3.0.1-quarantine.1'))

    def test_bound_native_evidence_and_target_semantics_are_load_bearing(self):
        tag = self.enroll()
        original = (self.root / 'native.json').read_bytes()
        native = json.loads(original)
        native['bump']['computed'] = 'major'
        self.write('native.json', native)
        self.commit('synthetic tampered evidence')
        self.assert_refused(self.invoke('verify', 'cage.json', tag))
        (self.root / 'native.json').write_bytes(original)
        self.commit('restore evidence')
        self.payload['payload']['entries']['same']['lm'] = 11
        self.save()
        self.commit('synthetic semantic mutation')
        self.assert_refused(self.invoke('verify', 'cage.json', tag))

    def test_later_descendant_release_does_not_rewrite_replay(self):
        tag = self.enroll()
        selected = self.git('rev-parse', 'HEAD')
        self.env.update(GIT_AUTHOR_DATE='2026-10-19T00:00:00Z', GIT_COMMITTER_DATE='2026-10-19T00:00:00Z')
        self.payload['version'] = '3.0.2'
        self.save()
        self.commit('synthetic later release')
        self.git('tag', '-a', PREFIX + 'v3.0.2', '-m', 'Synthetic later unsigned release')
        self.git('checkout', '-q', selected)
        result = self.invoke('verify', 'cage.json', tag)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_maximal_history_and_regular_files_are_required(self):
        tag = self.enroll()
        self.git('tag', '-a', PREFIX + 'v3.0.2', '-m', 'Synthetic conflicting served baseline')
        self.assert_refused(self.invoke('verify', 'cage.json', tag))
        self.git('tag', '-d', PREFIX + 'v3.0.2')
        (self.root / 'native.json').unlink()
        (self.root / 'native.json').symlink_to(self.root / 'cage.json')
        self.assert_refused(self.invoke('verify', 'cage.json', tag))

    def test_structural_fault_is_refused_not_degraded_and_outputs_never_overwritten(self):
        self.write(FEED + '/v3/feed.json', '{"payload":{},"payload":{}}')
        self.commit('synthetic duplicate field')
        self.assert_refused(self.build())
        self.save()
        self.commit('restore legitimate target')
        self.write('native.json', 'existing file must survive')
        self.assert_refused(self.build())
        self.assertEqual((self.root / 'native.json').read_text(), 'existing file must survive')

    def test_actual_pre_sign_workflow_reproduces_opt_in_and_keeps_legacy_path(self):
        workflow = (ROOT / '.github/workflows/cut-release.yml').read_text()
        heading = ('      - name: "the declared bump must agree' if PARTY == 'ico' else
                   '      - name: reproduce an explicitly enrolled native release cage')
        block = workflow[workflow.index(heading):].split('\n      - name:', 1)[0]
        script = textwrap.dedent(block.split('        run: |\n', 1)[1])
        tag = PREFIX + 'v3.0.1'
        environment = dict(self.env, VERSION_INPUT=tag if PARTY == 'ico' else '3.0.1', FEED_INPUT=FEED)
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=self.root,
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.enroll(tag)
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=self.root,
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.write('native.json', '{}')
        self.commit('synthetic tampered native proof before signing')
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=self.root,
                                env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('REFUSED:', result.stderr)

    def test_pre_sign_selected_feed_cannot_use_reproducible_foreign_cage(self):
        # Construct an untrusted but genuinely reproducible foreign-feed proof
        # from the public native build; no production guard is mocked/disabled.
        built = self.build()
        self.assertEqual(built.returncode, 0, built.stderr)
        record = json.loads((self.root / 'native.json').read_text())
        cage = json.loads((self.root / 'cage.json').read_text())
        record['target_name'] = 'unpublished-feed'
        record['target_semantic']['path'] = 'unpublished-feed/v3/feed.json'
        record['target_semantic']['sha256'] = hashlib.sha256(json.dumps(
            self.foreign, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        for previous in [record['predecessor'], *record['captured_releases']]:
            previous['path'] = 'unpublished-feed/v3/feed.json'
            previous['git_blob'] = self.git('rev-parse', previous['commit'] + ':' + previous['path'])
        for path in list(record['inputs']):
            if path.startswith('penalty-schema/'):
                ref = record['inputs'].pop(path)
                new_path = path.replace('penalty-schema/', 'unpublished-feed/', 1)
                record['inputs'][new_path] = {'path': new_path, 'git_blob': ref['git_blob']}
        self.write('native.json', record)
        cage['target_name'] = 'unpublished-feed'
        cage['native_evidence']['git_blob'] = self.git('hash-object', 'native.json')
        self.write('cage.json', cage)
        ref = {'path': 'cage.json', 'git_blob': self.git('hash-object', 'cage.json')}
        self.foreign['payload']['release_cage'] = ref
        self.write('unpublished-feed/v3/feed.json', self.foreign)
        self.payload['payload']['entries'] = {}  # Actual selected computation is MAJOR.
        self.payload['payload']['release_cage'] = ref
        self.save()
        self.commit('synthetic foreign proof over selected underdeclared major')
        workflow = (ROOT / '.github/workflows/cut-release.yml').read_text()
        heading = '      - name: "the declared bump must agree'
        block = workflow[workflow.index(heading):].split('\n      - name:', 1)[0]
        script = textwrap.dedent(block.split('        run: |\n', 1)[1])
        actual = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=self.root,
                                env=dict(self.env, VERSION_INPUT='v3.0.1'), capture_output=True, text=True)
        legacy = subprocess.run([sys.executable, NATIVE, 'v3.0.1'], cwd=self.root,
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(legacy.returncode, 0, legacy.stdout)
        self.assertIn("computed bump for the next release is 'major'", legacy.stderr)
        direct = self.invoke('verify', 'cage.json', 'v3.0.1')
        print(json.dumps({'synthetic_wrong_target': {label: {'exit': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
            for label, r in [('pre_sign', actual), ('direct_verify', direct), ('original_selected_gate', legacy)]}}))
        for label, result in [('actual pre-sign step', actual), ('direct verify', direct)]:
            with self.subTest(boundary=label):
                self.assert_refused(result)

    def test_explicit_selected_target_path_and_pointer_blob_are_bound(self):
        tag = self.enroll()
        result = self.invoke('verify', 'cage.json', tag, 'penalty-schema/v3/feed.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke('verify', 'cage.json', tag, 'unpublished-feed/v3/feed.json')
        self.assert_refused(result)
        self.assertIn('workflow-selected payload path', result.stderr)
        self.payload['payload']['release_cage']['git_blob'] = '0' * 40
        self.save()
        self.commit('synthetic wrong selected cage pointer blob')
        self.assert_refused(self.invoke('verify', 'cage.json', tag, 'penalty-schema/v3/feed.json'))

if __name__ == '__main__':
    unittest.main()
