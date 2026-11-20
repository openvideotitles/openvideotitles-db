"""Tests of check.py: the frozen test set passes, and each rule fails on a mutated copy of it.

Forbidden words are spelled in pieces, as in check.py, so that this file passes the control too.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_convert import REPO, TreeTest, check, data, lib, run  # noqa: E402

DROP = object()
NAME = 'Pin' + 'gu'
UNSEEN = ('\u00ad\u061c\u180e\u200b\u200f\u202a\u202e\u2060\u206f\ufeff\ufff9\ufffb\U00013430\U0001343f\U0001bca0'
          '\U0001bca3\U0001d173\U0001d17a\U000e0000\U000e007f')  # ends of the ranges of invisible characters
STREAMS = ['https://media.example/' + path for path in (  # one address per form of the stream pattern
    'live/index.m' + '3u8', 'live.i' + 'sm/manifest', 'lire?liste=A.M' + '3U8', 'direct.i' + 'sml', 'film.m' + 'pd',
    'film/manifest.m' + 'pd/segment-1', 'film.f' + '4m', 'liste.m' + '3u?jeton=1', 'liste.m' + '3u8#debut')]
DONATIONS = ['https://%s/essai' % host for host in (
    'dons.example/donate', 'www.helloasso.com', 'www.leetchi.com', 'lydia-app.com', 'www.gofundme.com',
    'buy.stripe.com', 'www.paypal.com/paypalme', 'fr.ulule.com')] + ['TWINT 079 000 00 00']
NC_NO_MARK = 'CC-BY-NC-SA-4.0 https://creativecommons.org/licenses/by-nc-sa/4.0/'


def rebuild(tree, **keys):
    """The manifest computed again from the data files; header and sequence number kept, `keys` forced."""
    old, found = json.loads((tree / check.MANIFEST).read_bytes()), lib.read_data_files(tree)
    entries = {name: lib.entry(name, (tree / 'catalogue' / name).read_bytes()) for name in found}
    counts = {section: sum(len(items) for name, items in found.items() if lib.section_of(name) == section)
              for section in lib.SECTIONS}
    manifest = dict(lib.manifest_of(old, entries, counts, old['sequence']), **keys)
    (tree / check.MANIFEST).write_bytes(lib.manifest_bytes(manifest))


def store(tree, name, items):
    """One data file written again in canonical form, and the manifest with it: the mutation breaks one rule."""
    path = tree / 'catalogue' / name
    path.write_bytes(lib.data_file(lib.section_of(name), items)) if items else path.unlink()
    rebuild(tree)


def item(name, source=False, **keys):
    """Mutation: set keys (DROP removes one) on the first item of a data file, or on its first source."""
    def change(tree):
        items = data(tree, name)
        target = items[0]['sources'][0] if source else items[0]
        for key, value in keys.items():
            target.pop(key) if value is DROP else target.update({key: value})
        store(tree, name, items)
    return change


def moved(origin, target, copy=False, **keys):
    """Mutation: the first item of a data file joins another file with `keys` changed, and leaves its own or not."""
    def change(tree):
        items = data(tree, origin)
        store(tree, target, data(tree, target) + [dict(items[0], **keys)])
        store(tree, origin, items if copy else items[1:])
    return change


def raw(path, change=None, content=None, manifest=False):
    """Mutation: a file rewritten through change(text), or created with `content`; the manifest follows on demand."""
    def mutate(tree):
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        new = content if content is not None else change(target.read_bytes().decode('utf-8'))
        target.write_bytes(new if isinstance(new, bytes) else new.encode('utf-8'))
        if manifest:
            rebuild(tree)
    return mutate


def reverse(text):
    """A data file of two items, the second written before the first."""
    head, first, second, tail = text.split('\n', 3)
    return '\n'.join([head, second + ',', first.rstrip(','), tail])


def lines(*sha, **keys):
    """Text of retraits.json for the given fingerprints."""
    return lib.withdrawals_bytes([dict({'date': '2026-01-02', 'sha256': mark}, **keys) for mark in sha])


FILM, TV, NC_SHORT = 'films.json', 'television.json', 'shorts-a.json'
OLD_MARK = '787dc9435800da951061fed6b7017afdbf1ecc6a9b224e81fff2936a032cb4e9'
MUTATIONS = [  # (rules expected, what is broken, mutation); each one goes through the command
    ({1}, 'file outside the closed list', raw('notes.txt', content='x')),
    ({1}, 'workflow folder', raw('.github/workflows/build.yml', content='on: push\n')),
    ({1}, 'expected file missing', lambda tree: (tree / 'NOTICE.md').unlink()),
    ({1}, 'file above the size limit', raw('README.md', lambda text: text + 'a ' * 500_001)),
    ({1}, 'file that is not UTF-8', raw('LICENSE-CODE', content=b'\xff\xfe')),
    ({1}, 'hook not executable', lambda tree: (tree / check.HOOK).chmod(0o644)),
    ({1}, 'symbolic link in the place of a listed file', lambda tree: [
        (tree / 'NOTICE.md').unlink(), os.symlink('README.md', str(tree / 'NOTICE.md'))]),
    ({1}, 'empty folder', lambda tree: (tree / 'vide').mkdir()),
    ({1}, 'extra file in the test set', raw('tests/contrat/attendu/catalogue/extra.json', content='{}')),
    ({1}, 'test set file with other bytes', raw('tests/contrat/attendu/catalogue/films.json',
                                                lambda text: text + '\n')),
    ({1}, 'file added to the test set and to its list', lambda tree: [
        raw(check.EXPECTED + 'notes.txt', content='x')(tree),
        raw(check.SUMS, lambda text: text + '%s  ./notes.txt\n' % lib.sha256(b'x'))(tree)]),
    ({1}, 'test export that is no export any more', raw('tests/contrat/export-essai.json', content='<tv/>\n')),
    ({1}, 'test withdrawals rewritten', raw('tests/contrat/retraits-essai.json', content='{}\n')),
    ({1}, 'test export header with a key the conversion does not read', raw(
        'tests/contrat/export-essai.json', lambda text: text.replace('{\n', '{\n "profile": "ESSAI",\n', 1))),
    ({2}, 'forbidden key on a source', item(FILM, source=True, stream_url='')),
    ({2}, 'source key missing', item(FILM, source=True, expires_at=DROP)),
    ({2, 3}, 'unknown section', item(FILM, section='nulle')),
    ({2, 3}, 'text that cannot be written in UTF-8', raw('catalogue/films.json', lambda text: text.replace(
        'Le Film d’essai"}', 'Le Film \\ud800"}'), manifest=True)),
    ({2, 3}, 'fourth key in a data file', raw('catalogue/films.json', lambda text: text.replace(
        '{"schema":1,', '{"extra":0,"schema":1,'), manifest=True)),
    ({3}, 'items out of order', raw('catalogue/films.json', reverse, manifest=True)),
    ({3}, 'data file not canonical', raw('catalogue/films.json', lambda text: json.dumps(json.loads(text), indent=1),
                                         manifest=True)),
    ({3}, 'short outside the fragment of its fingerprint', moved('shorts-0.json', 'shorts-3.json')),
    ({3}, 'item in the file of another section', item(FILM, section='series')),
    ({3}, 'same id in two files', moved(FILM, 'series.json', copy=True, section='series')),
    ({3}, 'data file without item', raw('catalogue/series.json', lambda text: text.split('\n')[0] + '\n\n]}\n',
                                        manifest=True)),
    ({4}, 'unknown mode', item(FILM, source=True, mode='embed')),
    ({4}, 'address that is not http', item(FILM, source=True, uri='ftp://media.example/film.mp4')),
    ({4}, 'address with credentials', item(FILM, source=True, uri='https://nom:passe@media.example/film.mp4')),
    ({4}, 'channel with a direct source', item(TV, source=True, mode='direct')),
    ({5}, 'no credit', item(FILM, source=True, credits=[])),
    ({5}, 'credit that cannot be seen', item(FILM, source=True, credits=['\u200b'])),
    ({5}, 'licence outside the grammar', item(FILM, source=True, licence_references=['Tous droits réservés'])),
    ({5}, 'NC code without its mark', item(NC_SHORT, source=True, licence_references=[NC_NO_MARK])),
    ({5}, 'mark without the code', item(FILM, source=True, licence_references=[
        'PDM https://creativecommons.org/publicdomain/mark/1.0/ (marqué NC)'])),
    ({5}, 'channel reference that is not an address', item(TV, source=True, licence_references=['voir le site'])),
    ({6}, 'territories without FR', item(FILM, source=True, territories=['CH'])),
    ({6}, 'date without offset', item(FILM, source=True, expires_at='2099-12-31T00:00:00')),
    ({7}, 'withdrawn title still present', raw('retraits.json', content=lines(lib.fingerprint('exemple:film-page')))),
    ({7}, 'list not canonical', raw('retraits.json', lambda text: json.dumps(json.loads(text), indent=1))),
    ({7}, 'same fingerprint twice', raw('retraits.json', content=lines(OLD_MARK, OLD_MARK))),
    ({7}, 'third key on a line', raw('retraits.json', content=lines(OLD_MARK, motif='plainte'))),
    ({7}, 'impossible date', raw('retraits.json', content=lines(OLD_MARK, date='2026-13-01'))),
    ({7}, 'fingerprint that is no sha256', raw('retraits.json', content=lines('g' * 64))),
    ({8}, 'ninth key', lambda tree: rebuild(tree, profile='ESSAI')),
    ({8}, 'data file changed without the manifest', raw('catalogue/films.json', lambda text: text.replace(
        'Le Film d’essai"}', 'Le Film d’essai, bis"}'))),
    ({8}, 'data file outside the manifest', lambda tree: rebuild(tree, files={})),
    ({8}, 'wrong revision', lambda tree: rebuild(tree, revision='0' * 64)),
    ({8}, 'sequence number below one', lambda tree: rebuild(tree, sequence=0)),
    ({8}, 'territories without FR', lambda tree: rebuild(tree, territories=['CH'])),
    ({9}, 'token', raw('scripts/stats.py', lambda text: text + '\ntok' + 'en = "%s"\n' % ('a1' * 10))),
    ({9}, 'word of the private circuit', raw('NOTICE.md', lambda text: text + '\nled' + 'ger\n')),
    ({9}, 'private word in an id', item(FILM, id='led' + 'ger:1')),
    ({1, 10}, 'name in a file name', raw('%s.md' % NAME, content='x')),
    ({11}, 'promise', raw('README.md', lambda text: text + '\nLa télé' + ' gratuite.\n')),
    ({12}, 'socket import', raw('scripts/stats.py', lambda text: text + '\nimport socket\n')),
    ({12}, 'requests import', raw('scripts/stats.py', lambda text: text + '\nimport requests\n')),
    ({12}, 'request import', raw('tests/test_publish.py', lambda text: text + '\nfrom urllib import request\n')),
    ({12}, 'client import', raw('scripts/convert.py', lambda text: text + '\nimport http.client as web\n')),
    ({12}, 'command launched', raw('scripts/publish.py', lambda text: text + '\nCOMMAND = ["cu' + 'rl"]\n')),
    ({12}, 'other command launched', raw('.githooks/pre-push', lambda text: text + '\nwg' + 'et -q adresse\n')),
]
MUTATIONS += [({2}, 'item with %r' % keys, item(FILM, **keys)) for keys in (
    dict(poster='https://media.example/affiche.jpg'), dict(assets=[]), dict(country=DROP), dict(id='x' * 241),
    dict(id=''), dict(id='a\x07'), dict(id='a\u200b'), dict(title=' '), dict(title='\u200b'), dict(country='fr'),
    dict(languages=['FRA']), dict(duration_seconds=0), dict(duration_seconds=604_801), dict(year=1700),
    dict(year=2101), dict(sources=[]))]
MUTATIONS += [({4}, 'stream or list address: ' + uri[22:], item(FILM, source=True, uri=uri)) for uri in STREAMS]
MUTATIONS += [({9}, 'private: ' + new, raw('README.md', lambda text, new=new: '%s\n%s\n' % (text, new))) for new in (
    '/' + 'Users' + '/quelquun/notes', '/' + 'home' + '/quelquun/notes', 'C:' + '\\Users' + '\\quelquun',
    'iptv-' + 'org', 'man' + 'dat_id', 'le_man' + 'dat')]
MUTATIONS += [({10}, 'name in a text: %a' % new, raw('README.md', lambda text, new=new: '%s\n%s\n' % (text, new)))
              for new in [NAME, 'pin' + 'gouin', 'PEN' + 'GUIN'] + ['Pin%sgu' % unseen for unseen in UNSEEN]]
MUTATIONS += [({11}, 'donation link beside an NC title: ' + new, raw('NOTICE.md', lambda text, new=new: text + new))
              for new in DONATIONS]


class CheckTest(TreeTest):
    def rules(self, done):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        return {line.split('\t')[1] for line in done.stdout.split('\n')[:-1]}

    def test_frozen_set_passes_and_the_missing_base_is_said(self):
        done = run(self.tree, 'check.py', '--tree', self.tree)
        self.assertEqual((done.returncode, done.stdout), (0, ''), done.stderr)
        self.assertEqual(done.stderr, 'sans --base : les deux comparaisons à la base sont sautées\n')

    def test_repository_passes_its_own_control(self):
        self.assertEqual(check.deviations(REPO), [])

    def test_every_mutation_fails_the_command_with_the_number_of_its_rule_and_no_other(self):
        self.assertEqual({rule for expected, _, _ in MUTATIONS for rule in expected}, set(range(1, 13)))
        for expected, broken, mutate in MUTATIONS:
            with self.subTest(broken=broken):
                self.setUp()
                mutate(self.tree)
                found = self.rules(run(self.tree, 'check.py', '--tree', self.tree))
                self.assertEqual(found, {str(rule) for rule in expected})

    def test_frozen_set_is_held_by_its_fingerprints_and_its_content_is_read_all_the_same(self):
        export = check.CONTRACT + 'export-essai.json'
        for old, new, reason in (('https://media.example/', 'https://media.example.org/', 'adresse hors des hôtes'),
                                 ('https://media.example/', 'HTTPS://media.example.org/', 'adresse hors des hôtes'),
                                 ('"assets": []', '"assets": ["logo"]', 'fiche du jeu d’essai : assets non vide'),
                                 ('"assets": []', '"logo": "x"', 'fiche du jeu d’essai : clé hors liste : logo'),
                                 ('{\n', '{\n "profile": "ESSAI",\n', 'en-tête avec une clé')):
            with self.subTest(new=new):
                self.setUp()
                raw(export, lambda text: text.replace(old, new, 1))(self.tree)
                found = check.deviations(self.tree)
                self.assertEqual([line[:2] for line in found], [(export, 1)] * 2, found)
                self.assertIn('empreinte différente', found[0][2])
                self.assertIn(reason, found[1][2])

    def test_data_file_outside_the_manifest_is_named(self):
        rebuild(self.tree, files={})
        self.assertIn(('catalogue/films.json', 8, 'fichier de données hors manifeste'), check.deviations(self.tree))

    def test_control_reads_no_clock_and_accepts_a_null_year_and_a_date_written_with_z(self):
        item(FILM, year=None)(self.tree)
        item(FILM, source=True, expires_at='2000-01-01T00:00:00Z')(self.tree)  # expired: the conversion's business
        self.assertEqual(check.deviations(self.tree), [])
        item(FILM, year=1921)(self.tree)
        self.assertEqual(check.deviations(self.tree), [])

    def test_title_credits_and_uri_are_not_read_for_names_and_private_words(self):
        word = 'led' + 'ger'
        item(FILM, title='%s, %s' % (NAME, word))(self.tree)
        item(FILM, source=True, credits=[word + ' ' + NAME], uri='https://%s.example/%s.mp4' % (word, NAME))(self.tree)
        raw('README.md', lambda text: text + '\nUn man' + 'dataire, man' + 'daté.\n')(self.tree)  # other words
        self.assertEqual(check.deviations(self.tree), [])

    def test_donation_link_is_allowed_once_no_reference_carries_nc(self):
        raw('NOTICE.md', lambda text: text + '\nhttps://dons.example/donate\n')(self.tree)
        store(self.tree, NC_SHORT, [])
        self.assertEqual(check.deviations(self.tree), [])


if __name__ == '__main__':
    unittest.main()
