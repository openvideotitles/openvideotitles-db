#!/usr/bin/env python3
"""Automatic control of the limits of this repository: twelve rules, one line per deviation.

Usage: python3 -I -B scripts/check.py [--tree folder] [--base git-ref] [--publication folder]
Prints `path<TAB>rule<TAB>reason` per deviation; exit code 1 if there is any, 0 otherwise. Reads only the given
folder, opens no connection. The words it forbids are spelled in pieces, here and in the tests, so that the
repository passes its own control. The two optional comparisons live with the script that owns them:
--base in withdraw.py (what never goes back), --publication in publish.py (the published layout).
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue_lib as lib  # noqa: E402
import publish  # noqa: E402
import withdraw  # noqa: E402

FIXED = ('README.md', 'NOTICE.md', 'LICENSE', 'LICENSE-CODE', '.gitignore', '.githooks/pre-push', 'retraits.json',
         'catalogue/manifest.json', 'scripts/catalogue_lib.py', 'scripts/convert.py', 'scripts/withdraw.py',
         'scripts/publish.py', 'scripts/check.py', 'scripts/stats.py', 'tests/test_convert.py',
         'tests/test_withdraw.py', 'tests/test_publish.py', 'tests/test_check.py', 'tests/test_hook.py',
         'tests/contrat/export-essai.json', 'tests/contrat/retraits-essai.json', 'tests/contrat/SHA256SUMS')
CONTRACT, EXPECTED, SUMS = 'tests/contrat/', 'tests/contrat/attendu/', 'tests/contrat/SHA256SUMS'
HOOK, MANIFEST, WITHDRAWALS = '.githooks/pre-push', 'catalogue/manifest.json', 'retraits.json'
DATA = re.compile('catalogue/(%s)' % lib.DATA_FILE.pattern)
SUM_LINE = re.compile(r'([0-9a-f]{64})  \./(\S.*)')
ADDRESSES = re.compile(r'''(?i)https?://[^\s"'<>()\]\\]+''')
FROZEN = {SUMS: 'e6d7493c2740cc94d8c996837574c484470fe7cff61b8df1009717084d7c4d60',  # the frozen test set never changes
          CONTRACT + 'export-essai.json': '91a8e472d96d5bbcf4aa4cb9587ec8db79c4585853361eb7a0e9183fcec55134',
          CONTRACT + 'retraits-essai.json': '1356be653a4e8fcacb01c25db64c9c61396377abd4c7fcb9a37bb7c3b046c0ae'}
NC = re.compile(r'"licence_references":\[[^\]]*-NC')
LOCAL = re.compile('/' 'Users/[^/\\s"\']+|/' 'home/[^/\\s"\']+/|[A-Za-z]:' r'\\{1,2}' 'Users')
SECRETS = re.compile(r'(?i)\bwskey=\w{6,}|\b(?:api[_-]?key|apikey|secret|token|password|passwd)\s*[:=]\s*["\']'
                     r'[\w\-.]{16,}["\']|\bghp_\w{30,}|\bgithub_pat_\w{30,}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN (?:RSA '
                     r'|EC |OPENSSH |DSA )?PRIVATE KEY-----|\bBearer\s+[\w\-.]{20,}')
PRIVATE = re.compile('(?i)led' 'ger|' r'(?<![^\W_])man' r'dats?(?![^\W_])|source_' 'metadata|canonical_' 'id|url_'
                     'sha256|iptv-' 'org|' r'i\.mjh' r'\.nz|free-?tv/' 'iptv|' r'm3u\.' 'cl|fluxus' r'\.to')
NAME = re.compile('(?i)pin' 'gu|pin' 'gouin|pen' 'guin')
PROMISES = re.compile('(?i)t[ée]l[ée]s? gra' 'tuite|tv gra' 'tuite|free (?:live )?(?:tv|ip' 'tv)|chaînes gra' 'tuites|'
                      'regarder (?:le |les |un )?ma' 'tch|watch (?:the |live )?ma' 'tch|foot(?:ball)? gra' 'tuit|'
                      'free spo' 'rts?')
DONATION = re.compile(r'(?i)https?://\S*(?:sponsor|donat|funding)\S*|patreon\.com|opencollective\.com|liberapay\.com|'
                      r'ko-fi\.com|buymeacoffee\.com|paypal\.(?:me|com/donate|com/paypalme)|tipeee\.com|utip\.io|'
                      r'helloasso\.|leetchi\.com|lydia-app\.com|gofundme\.com|stripe\.com|ulule\.com|\btwint\b')
NETWORK = ('urllib.request.', 'http.client.', 'socket.', 'requests.')
COMMANDS = re.compile(r'\b(?:cu' 'rl|wg' r'et)\b')


def rule_1(tree, files, texts):
    """Closed tree: only the listed paths exist, and the frozen test set is held file by file."""
    sums = dict(FROZEN, **{EXPECTED + match.group(2): match.group(1)
                           for match in map(SUM_LINE.fullmatch, texts.get(SUMS, '').split('\n')) if match})
    for path in sorted(set(files) | set(FIXED) | set(sums)):
        if path not in files:
            yield path, 1, 'fichier attendu absent'
        elif not (path in FIXED or path in sums or DATA.fullmatch(path)):
            yield path, 1, 'fichier hors de la liste fermée'
        elif files[path] is None:
            yield path, 1, 'plus de 1 000 000 octets'
        elif path not in texts:
            yield path, 1, 'illisible en UTF-8'
        elif path in sums and lib.sha256(files[path]) != sums[path]:
            yield path, 1, 'empreinte différente de celle du jeu d’essai figé'
    if HOOK in files and not os.access(str(tree / HOOK), os.X_OK):
        yield HOOK, 1, 'crochet non exécutable'
    for path in sorted(path for path in texts if path.startswith(CONTRACT)):
        hosts = [(lib.web_address(address) or ('',))[0].lower() for address in ADDRESSES.findall(texts[path])]
        if not all(host.endswith('.example') or host == 'creativecommons.org' for host in hosts):
            yield path, 1, 'adresse hors des hôtes en .example et de creativecommons.org'
        try:
            document = json.loads(texts[path])
            items = document['items'] + []
        except lib.UNREADABLE:
            document, items = {}, []
        if path == CONTRACT + 'export-essai.json' and set(document) - lib.EXPORT_KEYS:
            yield path, 1, 'en-tête avec une clé que la conversion ne lit pas : %s' % ', '.join(
                sorted(set(document) - lib.EXPORT_KEYS))
        for item in items:  # only the keys of the format, plus an empty `assets`
            bare = {key: item[key] for key in item if key != 'assets'} if isinstance(item, dict) else item
            faults = [reason for rule, reason in lib.fautes(bare) if rule == 2]
            if faults or item.get('assets'):
                yield path, 1, 'fiche du jeu d’essai : %s' % (' ; '.join(faults) or 'assets non vide')


def data_rules(files, texts, by_file):
    """Rules 2 to 6 on the data files, without a clock: an expired source is the conversion's business.
    Fills by_file with the items of every file whose items all have an id."""
    seen = {}
    for path in sorted(filter(DATA.fullmatch, texts)):
        name = path[len('catalogue/'):]
        try:
            document = json.loads(texts[path])
            items, schema = document['items'] + [], document.get('schema')
        except lib.UNREADABLE:
            yield path, 2, 'fichier illisible comme liste de fiches'
            continue
        if set(document) != {'schema', 'section', 'items'} or type(schema) is not int or schema != 1:
            yield path, 2, 'clés du fichier différentes de schema (1), section, items'
        for item in items:
            for rule, reason in lib.fautes(item):
                yield path, rule, '%s : %s' % (item.get('id') if isinstance(item, dict) else '?', reason)
        if not all(isinstance(item, dict) and isinstance(item.get('id'), str) for item in items):
            continue
        by_file[name] = items
        if files[path] != (lib.data_file(lib.section_of(name), items) if items else None):
            yield path, 3, 'octets différents de la réécriture canonique (tri par id, une fiche par ligne)'
        for item in items:
            if item.get('section') != lib.section_of(name) or lib.file_of(item) != name:
                yield path, 3, '%s : hors du fichier de sa section ou du fragment de son empreinte' % item['id']
            if item['id'] in seen:
                yield path, 3, '%s : id déjà présent dans %s' % (item['id'], seen[item['id']])
            seen[item['id']] = path


def state_rules(files, by_file):
    """Rule 7, withdrawals: a canonical list without duplicate, no withdrawn title left in the catalogue.
    Rule 8, manifest: exactly its eight keys, equal to the manifest computed again from the data files."""
    try:
        lines = json.loads(files[WITHDRAWALS])['withdrawn']
        withdrawn, marks = [line['sha256'] for line in lines], {line['sha256'] for line in lines}
        sound = files[WITHDRAWALS] == lib.withdrawals_bytes(lines) and all(
            set(line) == {'date', 'sha256'} and re.fullmatch('[0-9a-f]{64}', line['sha256'])
            and lib.instant('%sT00:00:00Z' % line['date']) for line in lines)
    except lib.UNREADABLE:
        withdrawn, marks, sound = [], set(), WITHDRAWALS not in files
    if not sound:
        yield WITHDRAWALS, 7, 'forme non canonique : une ligne {"date":"AAAA-MM-JJ","sha256":"…"} par titre, triées'
    if len(marks) != len(withdrawn):
        yield WITHDRAWALS, 7, 'empreinte en double'
    for name, items in sorted(by_file.items()):
        for item in items:
            if lib.fingerprint(item['id']) in marks:
                yield 'catalogue/' + name, 7, '%s : titre retiré encore présent' % item['id']
    entries = {path[len('catalogue/'):]: lib.entry(path[len('catalogue/'):], files[path])
               for path in files if DATA.fullmatch(path) and files[path] is not None}
    counts = {section: sum(len(by_file.get(name, ())) for name in entries if lib.section_of(name) == section)
              for section in lib.SECTIONS}
    try:
        manifest = json.loads(files[MANIFEST])
        outside = sorted(set(entries) - set(manifest['files']))
        sequence, sound = manifest['sequence'], set(manifest) == lib.MANIFEST_KEYS and not lib.header_fault(manifest)
        sound = sound and type(sequence) is int and sequence >= 1
        same = sound and files[MANIFEST] == lib.manifest_bytes(lib.manifest_of(manifest, entries, counts, sequence))
    except lib.UNREADABLE:
        outside, sound, same = [], MANIFEST not in files, True
    for name in outside:
        yield 'catalogue/' + name, 8, 'fichier de données hors manifeste'
    if not sound:
        yield MANIFEST, 8, 'illisible, ou clés et types différents des huit clés du manifeste'
    elif not same:
        yield MANIFEST, 8, 'différent du manifeste recalculé (fichiers, tailles, sha256, comptes, révision, écriture)'


def masked(text):
    """A file of items without the values rule 9 does not aim at: title, credits and uri of each item."""
    try:
        document = json.loads(text)
        for item in document['items']:
            item['title'] = ''
            for source in item['sources']:
                source['credits'], source['uri'] = [], ''
    except lib.UNREADABLE:
        return text
    return lib.canonical(document)


def network_imports(text):
    """Network modules imported by a Python source."""
    try:
        nodes = [node for node in ast.walk(ast.parse(text)) if isinstance(node, (ast.Import, ast.ImportFrom))]
    except (SyntaxError, ValueError):
        return ['un module inconnu (source illisible)']
    names = {'%s.%s.' % (getattr(node, 'module', None) or '', alias.name) for node in nodes for alias in node.names}
    return sorted(name.strip('.') for name in names if name.lstrip('.').startswith(NETWORK))


def text_rules(files, texts):
    """Rules 9 to 12: nothing private, no name, no promise or revenue, no network."""
    nc = any(NC.search(texts[path]) for path in texts if DATA.fullmatch(path))
    for path in sorted(files):
        text, data = lib.UNSEEN.sub('', texts.get(path, '')), bool(DATA.fullmatch(path))  # the text as it is read
        if match := LOCAL.search(text):
            yield path, 9, 'chemin local : %s' % match.group(0)[:60]
        if SECRETS.search(text):
            yield path, 9, 'clé, jeton ou clé privée'
        if match := PRIVATE.search(masked(text) if data or path.startswith(CONTRACT) else text):
            yield path, 9, 'mot du circuit privé ou liste de chaînes de tiers : %s' % match.group(0)
        if NAME.search(path) or not data and NAME.search(text):
            yield path, 10, 'nom présent dans le nom du fichier ou dans son texte'
        if path in ('README.md', 'NOTICE.md') and (match := PROMISES.search(text)):
            yield path, 11, 'promesse : %s' % match.group(0)
        if path in ('README.md', 'NOTICE.md') and nc and DONATION.search(text):
            yield path, 11, 'lien de don ou de parrainage alors qu’une référence porte -NC'
        if path.startswith(('scripts/', 'tests/')) or path == HOOK:
            for module in network_imports(text) if path.endswith('.py') else []:
                yield path, 12, 'import de %s' % module
            if match := COMMANDS.search(text):
                yield path, 12, 'appel de %s' % match.group(0)


def deviations(tree, base=None, publication=None, hooks=False):
    """Every deviation of a tree as (path, rule, reason), in a stable order."""
    tree, by_file = Path(tree), {}
    files, texts, found = publish.scan(tree, ('.git', 'publication'))
    found += rule_1(tree, files, texts)
    if hooks and (tree / '.git').exists():  # git stays silent when the hook is inactive, so the control says it
        try:
            done = subprocess.run(['git', '-C', str(tree), 'config', '--get', 'core.hooksPath'], capture_output=True)
        except OSError:
            done = None
        if done is None or done.stdout.decode('utf-8', 'replace').strip() != '.githooks':
            found.append(('.git/config', 1, 'core.hooksPath différent de .githooks : le crochet est inactif'))
    found += data_rules(files, texts, by_file)
    found += state_rules(files, by_file)
    found += text_rules(files, texts)
    found += withdraw.since(files, base) if base else []
    found += publish.compare(files, publication) if publication else []
    return [(lib.CONTROL.sub('?', path), rule, lib.CONTROL.sub('?', reason)[:400]) for path, rule, reason in found]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Contrôle automatique des limites du dépôt : douze règles.')
    parser.add_argument('--tree', help='dossier contrôlé (par défaut : le dépôt)')
    parser.add_argument('--base', help='référence git lue par « git show » dans le dépôt du dossier courant')
    parser.add_argument('--publication', help='dossier de publication à comparer aux fichiers suivis')
    args = parser.parse_args(argv)
    lib.utf8_output()
    if not args.base:
        print('sans --base : les deux comparaisons à la base sont sautées', file=sys.stderr)
    found = deviations(args.tree or lib.ROOT, args.base, args.publication, hooks=args.tree is None)
    for line in found:
        print('%s\t%s\t%s' % line)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
