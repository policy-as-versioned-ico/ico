#!/usr/bin/env python3
"""Opt-in publisher release proof. No signing, tag creation, or network access.

build FEED FULL_TAG NATIVE_PATH CAGE_PATH writes proposed proof files only.
verify CAGE_PATH FULL_TAG [TARGET_PATH] reconstructs the native decision from Git inputs.
Git dates/order are publisher assertions, not an independently measured clock.
"""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

PARTY = 'ico'
LADDER = ('none', 'patch', 'minor', 'major')
LIMIT = 32 * 1024 * 1024
CODE = '.github/scripts/publisher-release-gate.py'
NATIVE = '.github/scripts/declared-bump-gate.py' if PARTY == 'ico' else 'bump.py'


class Refused(Exception):
    """An input/instrument fault cannot be converted into a degraded release."""


def relative(path):
    if not isinstance(path, str) or any(p in ('', '.', '..', '.git') for p in path.split('/')) or '\\' in path or '\0' in path or re.match(r'^[A-Za-z]:', path):
        raise Refused('a strict relative publisher path is required')
    return path


def read(path):
    parts = relative(path).split('/')
    descriptor = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
                raise Refused('a bounded regular file is required')
            raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise Refused('input exceeds the byte budget')
            return raw
    finally:
        os.close(descriptor)


def git(*args):
    result = subprocess.run(['git', '-c', 'log.showSignature=false', *args], capture_output=True)
    if result.returncode:
        raise Refused('Git source unavailable: ' + ' '.join(args[:2]))
    return result.stdout


def oid(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise Refused('an exact Git object is required')
    return value


def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def tree_bytes(commit, path):
    oid(commit)
    relative(path)
    row = git('ls-tree', '-z', commit, '--', path).split(b'\0')
    if len(row) != 2 or not row[0]:
        raise Refused('source path is not one exact regular Git blob: ' + path)
    meta, actual_path = row[0].split(b'\t', 1)
    mode, kind, object_id = meta.split()
    if actual_path.decode() != path or mode not in (b'100644', b'100755') or kind != b'blob':
        raise Refused('source path is not a regular Git blob: ' + path)
    raw = git('cat-file', 'blob', object_id.decode())
    if len(raw) > LIMIT:
        raise Refused('Git blob exceeds the byte budget')
    return raw


def bound(path, commit):
    raw = read(path)
    if raw != tree_bytes(commit, path):
        raise Refused('working file differs from the selected Git source: ' + path)
    return {'path': path, 'git_blob': blob(raw)}


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refused('duplicate JSON field: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise Refused('nonfinite JSON number: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    def walk(item, depth=0):
        if depth > 48:
            raise Refused('JSON nesting budget exceeded')
        if isinstance(item, float) and not math.isfinite(item):
            raise Refused('nonfinite JSON number')
        if isinstance(item, (list, dict)):
            for child in item.values() if isinstance(item, dict) else item:
                walk(child, depth + 1)
    walk(value)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def closed(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise Refused(where + ' has missing or unknown fields')
    return value


def projection(envelope):
    if not isinstance(envelope, dict) or not isinstance(envelope.get('payload'), dict):
        raise Refused('target must be a feed envelope with an object payload')
    value = dict(envelope)
    value['payload'] = {k: v for k, v in envelope['payload'].items() if k != 'release_cage'}
    return value


def tag_version(feed, tag):
    prefix = '' if PARTY == 'ico' else feed + '/'
    match = re.fullmatch(re.escape(prefix) + r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-quarantine\.([1-9]\d*))?', tag)
    if not match:
        raise Refused('published_as is not this publisher feed\'s canonical full tag')
    numbers = tuple(int(match[i]) for i in (1, 2, 3))
    return numbers, int(match[4]) if match[4] else None


def captured_releases(feed, head, requested):
    history = set(git('rev-list', '--first-parent', head).decode().splitlines())
    cutoff = int(git('show', '-s', '--format=%ct', head))
    records = []
    for tag in git('tag', '--list').decode().splitlines():
        if tag == requested:
            continue
        prefix = '' if PARTY == 'ico' else feed + '/'
        if not tag.startswith(prefix + 'v'):
            continue
        try:
            version, quarantine = tag_version(feed, tag)
        except Refused:
            raise Refused('unsupported tag in the selected feed release history: ' + tag)
        tag_object = git('rev-parse', 'refs/tags/' + tag).decode().strip()
        commit = git('rev-parse', 'refs/tags/' + tag + '^{commit}').decode().strip()
        if commit not in history:
            continue
        # Do not let later tags attached to older commits rewrite historical replay.
        if git('cat-file', '-t', tag_object).strip() != b'tag':
            raise Refused('eligible publisher release is not an annotated tag: ' + tag)
        tag_raw = git('cat-file', 'tag', tag_object).decode()
        clocks = re.findall(r'^tagger .* (\d+) [+-]\d{4}$', tag_raw, re.MULTILINE)
        if len(clocks) != 1:
            raise Refused('release tag has no unique publisher-asserted Git clock')
        if int(clocks[0]) > cutoff:
            continue
        if quarantine is not None:
            continue  # quarantined releases never replace the clean baseline
        path = f'{feed}/v{version[0]}/feed.json'
        raw = tree_bytes(commit, path)
        old = parse(raw)
        expected = tag[len(prefix) + 1:]
        if old.get('name') != feed or old.get('published_by') != PARTY or old.get('version') != expected:
            raise Refused('predecessor envelope does not match its tag')
        records.append({'party': PARTY, 'tag': tag, 'commit': commit, 'path': path,
                        'git_blob': blob(raw), 'tag_object': tag_object, 'tagger_time': int(clocks[0])})
    return sorted(records, key=lambda record: tag_version(feed, record['tag'])[0])


def flat(path):
    result = {}
    for line in read(path).decode().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if ':' not in line:
            raise Refused('malformed native flat rule/declaration')
        key, value = line.split(':', 1)
        key = key.strip()
        if key in result:
            raise Refused('duplicate native rule/declaration field')
        result[key] = value.strip().strip('\"').strip("'")
    return result


def decision(feed, published_as, source_anchor):
    if feed != 'penalty-schema':
        raise Refused('ICO publishes only penalty-schema; another cage target cannot authorize this release')
    head = git('rev-parse', 'HEAD').decode().strip()
    if git('rev-parse', '--is-shallow-repository').strip() != b'false':
        raise Refused('native history requires a complete non-shallow publisher clone')
    oid(source_anchor)
    if subprocess.run(['git', 'merge-base', '--is-ancestor', source_anchor, head], capture_output=True).returncode:
        raise Refused('captured source anchor is not an ancestor of selected source')
    version, quarantine = tag_version(feed, published_as)
    path = f'{feed}/v{version[0]}/feed.json'
    envelope = parse(read(path))
    current = parse(tree_bytes(head, path))
    if canonical(projection(envelope)) != canonical(projection(current)):
        raise Refused('target semantic payload is not the selected Git source')
    if envelope.get('kind') != 'feed' or envelope.get('name') != feed or envelope.get('published_by') != PARTY:
        raise Refused('target feed identity differs from publisher')
    prefix = '' if PARTY == 'ico' else feed + '/'
    if envelope.get('version') != published_as[len(prefix) + 1:]:
        raise Refused('target envelope version differs from published_as')
    semantic = projection(envelope)
    if canonical(semantic) != canonical(projection(parse(tree_bytes(source_anchor, path)))):
        raise Refused('target semantic projection changed after source capture')
    inputs = {name: bound(name, head) for name in (CODE, NATIVE, feed + '/rule.yaml', feed + '/bump.yaml')}
    for name, ref in inputs.items():
        if blob(tree_bytes(source_anchor, name)) != ref['git_blob']:
            raise Refused('native code/rule/declaration changed after source capture')
    declared = flat(feed + '/bump.yaml').get('bump')
    if declared not in LADDER or declared == 'none':
        raise Refused('declared none/unknown bump does not authorize a release')
    releases = captured_releases(feed, head, published_as)
    if not releases:
        raise Refused('no captured eligible predecessor; native comparison is unobserved')
    previous = releases[-1]
    old_version, _ = tag_version(feed, previous['tag'])
    expected = {'patch': (old_version[0], old_version[1], old_version[2] + 1),
                'minor': (old_version[0], old_version[1] + 1, 0),
                'major': (old_version[0] + 1, 0, 0)}[declared]
    if version != expected:
        raise Refused('published tag is not the exact declared increment of the maximal eligible predecessor')
    old = projection(parse(tree_bytes(previous['commit'], previous['path'])))
    if old_version[0] != version[0] and parse(read(previous['path'])) != parse(tree_bytes(previous['commit'], previous['path'])):
        raise Refused('unreleased edits to the previous major cannot be absorbed by a new major')
    spec = importlib.util.spec_from_file_location('_publisher_native_gate', NATIVE)
    if spec is None or spec.loader is None:
        raise Refused('native gate module is unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if PARTY == 'ico':
        rule = flat(feed + '/rule.yaml')
        if not rule.get('entries') or not isinstance(old['payload'].get(rule['entries']), dict) or not isinstance(semantic['payload'].get(rule['entries']), dict):
            raise Refused('native entry map/rule is malformed')
        computed = module.compute(old, semantic, rule['entries'])
    else:
        try:
            computed = module.compute(old, semantic, module.load_rule(feed + '/rule.yaml'))
        except SystemExit as error:
            raise Refused('native gate refused its input: ' + str(error)) from error
    if computed not in LADDER:
        raise Refused('native gate did not compute a recognized bump')
    degraded = LADDER.index(declared) < LADDER.index(computed)
    if degraded != (quarantine is not None):
        raise Refused('computed outcome requires exactly a quarantine tag for degradation, or a clean tag for passed')
    result = 'degraded' if degraded else 'passed'
    record = {'schema': 'publisher-native-feed-gate/v1', 'publisher': PARTY,
              'target_name': feed, 'target_version': envelope['version'], 'published_as': published_as,
              'source_anchor': source_anchor, 'captured_releases': releases,
              'predecessor': {k: previous[k] for k in ('party', 'tag', 'commit', 'path', 'git_blob')},
              'target_semantic': {'path': path, 'projection': 'exclude-only-payload.release_cage/v1',
                                  'sha256': hashlib.sha256(canonical(semantic)).hexdigest()},
              'inputs': inputs, 'bump': {'declared': declared, 'computed': computed},
              'outcome': {'result': result}, 'degraded': None}
    if degraded:
        record['degraded'] = {'tier': 'quarantine', 'declared_bump': declared,
                              'computed_bump': computed, 'suffix': 'quarantine'}
    return record


def cage_for(record, native_path, native_raw):
    degraded = record['outcome']['result'] == 'degraded'
    return {'schema': 'publisher-release-cage/v1', 'target_name': record['target_name'],
            'target_version': record['target_version'], 'published_as': record['published_as'],
            'outcome': record['outcome']['result'], 'tier': 'quarantine' if degraded else 'baseline',
            'declared_bump': record['bump']['declared'], 'computed_bump': record['bump']['computed'],
            'suffix': 'quarantine' if degraded else None,
            'native_evidence': {'path': native_path, 'git_blob': blob(native_raw)},
            'gate_code': record['inputs'][CODE]}


def emit(path, value):
    relative(path)
    # Never follow an existing leaf, overwrite inputs, or manufacture directories.
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    parts = path.split('/')
    descriptor = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=descriptor)
        with os.fdopen(file, 'wb') as stream:
            stream.write(raw)
    finally:
        os.close(descriptor)
    return raw


def main(args):
    if git('rev-parse', '--show-toplevel').decode().strip() != str(Path.cwd().resolve()):
        raise Refused('run at the authenticated publisher repository root')
    if len(args) == 5 and args[0] == 'build':
        _, feed, tag, native_path, cage_path = args
        if (PARTY == 'ico' and feed != 'penalty-schema') or (PARTY == 'feeds' and feed not in ('threat-register', 'cve', 'eol', 'fx', 'market-moves', 'news')):
            raise Refused('ICO publishes penalty-schema')
        relative(feed)
        relative(native_path)
        relative(cage_path)
        if native_path == cage_path:
            raise Refused('native evidence and cage must be separate files')
        anchor = git('rev-parse', 'HEAD').decode().strip()
        record = decision(feed, tag, anchor)
        raw = emit(native_path, record)
        emit(cage_path, cage_for(record, native_path, raw))
        print('BUILT publisher native release proof; no tag/ref/payload changed')
        return
    if len(args) in (3, 4) and args[0] == 'verify':
        _, cage_path, tag = args[:3]
        selected_path = relative(args[3]) if len(args) == 4 else None
        head = git('rev-parse', 'HEAD').decode().strip()
        cage = parse(read(cage_path))
        closed(cage, ('schema', 'target_name', 'target_version', 'published_as', 'outcome', 'tier',
                      'declared_bump', 'computed_bump', 'suffix', 'native_evidence', 'gate_code'), 'cage')
        if cage['schema'] != 'publisher-release-cage/v1' or cage['published_as'] != tag:
            raise Refused('cage schema/tag mismatch')
        for key in ('gate_code', 'native_evidence'):
            ref = closed(cage[key], ('path', 'git_blob'), key)
            if bound(ref['path'], head) != ref:
                raise Refused(key + ' Git blob mismatch')
        if cage['gate_code']['path'] != CODE:
            raise Refused('cage must select this publisher native producer')
        raw = read(cage['native_evidence']['path'])
        native = parse(raw)
        if not isinstance(native, dict):
            raise Refused('native evidence must be an object')
        record = decision(cage['target_name'], tag, native.get('source_anchor'))
        if selected_path is not None and selected_path != record['target_semantic']['path']:
            raise Refused('cage target does not match the workflow-selected payload path')
        if native != record or cage != cage_for(record, cage['native_evidence']['path'], raw):
            raise Refused('native evidence/cage do not reproduce the native gate')
        payload = parse(read(record['target_semantic']['path']))['payload']
        if payload.get('release_cage') != bound(cage_path, head):
            raise Refused('target payload does not link this exact same-tree cage')
        print('VERIFIED publisher native release gate and exact target cage')
        return
    raise Refused('usage: build FEED FULL_TAG NATIVE_PATH CAGE_PATH | verify CAGE_PATH FULL_TAG [TARGET_PATH]')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (Refused, OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        print('REFUSED: publisher native release gate: ' + str(error), file=sys.stderr)
        sys.exit(1)
