"""Tests of convert.py, and the helpers shared by the other test files.

Every test works in a temporary copy of this repository whose catalogue is the frozen test set of
tests/contrat/. Items are fictitious, their addresses on hosts in .example. Nothing opens a connection.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO, CONTRACT = HERE.parent, HERE / 'contrat'
sys.path.insert(0, str(REPO / 'scripts'))
import catalogue_lib as lib  # noqa: E402
import check  # noqa: E402
import convert  # noqa: E402

REVISION = '4924b73fb7837a40b04aa9788e37683b07e049f8ce365486100278bc018f1a7d'
ENV = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')


def make_tree(folder, catalogue=True):
    """A copy of this repository in `folder`; with `catalogue`, the frozen test set is its tracked state."""
    tree = Path(folder)
    for path in check.FIXED:
        if not path.startswith(('catalogue/', 'tests/contrat/')) and path != 'retraits.json':
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(REPO / path), str(tree / path))
    shutil.copytree(str(CONTRACT), str(tree / 'tests' / 'contrat'))
    shutil.copy(str(CONTRACT / 'retraits-essai.json'), str(tree / 'retraits.json'))
    if catalogue:
        shutil.copytree(str(CONTRACT / 'attendu' / 'catalogue'), str(tree / 'catalogue'))
    return tree


def run(tree, script, *args, cwd=None, env=None):
    """One script of a copied tree, under the interpreter that runs the tests, isolated as documented."""
    command = [sys.executable, '-I', '-B', str(Path(tree) / 'scripts' / script)] + [str(arg) for arg in args]
    return subprocess.run(command, cwd=str(cwd or tree), env=env or ENV, capture_output=True, encoding='utf-8')


def data(tree, name):
    """Items of one data file of a copied tree."""
    return json.loads((tree / 'catalogue' / name).read_bytes())['items']


def snapshot(folder):
    """{relative path: bytes} of every file under a folder."""
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(Path(folder).rglob('*'))
            if path.is_file()}


def expected(part):
    """The files SHA256SUMS lists under `part` ('catalogue' or 'publication'), as {relative path: bytes}."""
    return snapshot(CONTRACT / 'attendu' / part)


def export_with(folder, change=None, counts=True):
    """A copy of the test export after `change(export)`; its header counts follow the items unless told not to."""
    export = json.loads((CONTRACT / 'export-essai.json').read_bytes())
    if change:
        change(export)
    if counts:
        export['counts'] = {section: sum(item.get('section') == section for item in export['items'])
                            for section in lib.SECTIONS}
    path = Path(folder) / 'export.json'  # a lone surrogate, which UTF-8 cannot carry, is written as its JSON escape
    path.write_bytes(json.dumps(export, ensure_ascii=False, indent=1).encode('utf-8', 'backslashreplace'))
    return path


def drop(ident):
    """A change that removes one item from an export."""
    def change(export):
        export['items'] = [item for item in export['items'] if item['id'] != ident]
    return change


def faulty(**keys):
    """A change that adds to an export a copy of a sound short carrying extra or replaced keys."""
    def change(export):
        sound = next(item for item in export['items'] if item['id'] == 'exemple:court-http-direct')
        export['items'].append(dict(json.loads(json.dumps(sound)), id='exemple:court-fautif', **keys))
    return change


class TreeTest(unittest.TestCase):
    """A test with a temporary copy of the repository, removed afterwards."""
    catalogue = True

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='catalogue-test-'))
        self.addCleanup(shutil.rmtree, str(self.folder), True)
        self.tree = make_tree(self.folder / 'tree', self.catalogue)

    def manifest(self):
        return json.loads((self.tree / 'catalogue' / 'manifest.json').read_bytes())

    def passes(self, done, code=0):
        self.assertEqual(done.returncode, code, done.stdout + done.stderr)
        return done.stdout.split('\n')[:-1]


class ConvertTest(TreeTest):
    catalogue = False

    def test_frozen_set_is_reproduced_byte_for_byte(self):
        lines = self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        self.assertEqual(snapshot(self.tree / 'catalogue'), expected('catalogue'))
        self.assertEqual(lines[0], 'écartée\texemple:court-retire\tretrait')
        self.assertEqual(len([line for line in lines if line.startswith('+\t')]), 8)
        self.assertEqual(lines[-1], 'lues 9 ; écrites 8 ; écartées 1 (retrait 1, faute 0) ; révision %s ; '
                                    'numéro d\'ordre 1' % REVISION)

    def test_item_with_a_forbidden_key_is_set_aside_and_the_others_written(self):
        export = export_with(self.folder, faulty(poster='https://media.example/affiche.jpg'))
        lines = self.passes(run(self.tree, 'convert.py', export))
        self.assertIn('écartée\texemple:court-fautif\tfaute : clé hors liste : poster', lines)
        self.assertIn('lues 10 ; écrites 8 ; écartées 2 (retrait 1, faute 1)', lines[-1])
        self.assertEqual(snapshot(self.tree / 'catalogue'), expected('catalogue'))

    def test_assets_or_an_expired_source_set_an_item_aside(self):
        def expire(export):
            faulty(assets=['logo'])(export)
            export['items'][0]['sources'][0]['expires_at'] = '2000-01-01T00:00:00+00:00'
        lines = self.passes(run(self.tree, 'convert.py', export_with(self.folder, expire)))
        self.assertIn('écartée\texemple:court-fautif\tfaute : assets non vide', lines)
        self.assertIn('écartée\tExempleTV.ch\tfaute : source 1 : expires_at dépassé', lines)
        self.assertFalse((self.tree / 'catalogue' / 'television.json').exists())
        self.assertEqual(self.manifest()['counts'], {'films': 2, 'series': 1, 'shorts': 4, 'television': 0})

    def test_clock_of_the_conversion_is_injected_and_an_expired_item_is_set_aside(self):
        export = json.loads((CONTRACT / 'export-essai.json').read_bytes())
        early, late = (dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) for year in (2099, 2100))
        self.assertEqual(convert.plan(export, self.tree, early)[2], [('exemple:court-retire', 'retrait')])
        self.assertIn(('exemple:court-deux-sources', 'faute : source 2 : expires_at dépassé'),
                      convert.plan(export, self.tree, late)[2])

    def test_year_a_mixed_item_and_a_date_written_with_z_are_converted(self):
        def change(export):
            film, page = export['items'][1], export['items'][2]
            export['generated_at'], film['year'], page['year'] = '2026-01-01T00:00:00Z', 1921, None
            film['sources'][0]['expires_at'] = '2099-12-31T00:00:00Z'
            film['sources'].append(dict(page['sources'][0], uri='https://studio.example/film-essai'))  # a file, a page
            naive = json.loads(json.dumps(dict(page, id='exemple:echeance-sans-decalage')))
            naive['sources'][0]['expires_at'] = '2099-12-31T00:00:00'
            export['items'] += [dict(page, id='exemple:annee-en-texte', year='1921'), naive]
        lines = self.passes(run(self.tree, 'convert.py', export_with(self.folder, change)))
        self.assertIn('écartée\texemple:annee-en-texte\tfaute : year : nul ou entier de 1880 à 2100', lines)
        self.assertIn('écartée\texemple:echeance-sans-decalage\tfaute : source 1 : expires_at : date ISO 8601 avec '
                      'décalage attendue', lines)
        self.assertIn('écrites 8 ; écartées 3 (retrait 1, faute 2)', lines[-1])
        films = data(self.tree, 'films.json')
        self.assertEqual([film.get('year', 'absente') for film in films], [1921, None])
        self.assertEqual([source['mode'] for source in films[0]['sources']], ['direct', 'official_link'])
        self.assertEqual(self.manifest()['generated_at'], '2026-01-01T00:00:00Z')
        self.assertEqual(self.passes(run(self.tree, 'check.py', '--tree', self.tree)), [])

    def test_second_conversion_changes_no_byte_and_no_file(self):
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (self.tree / 'catalogue').iterdir()}
        lines = self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (self.tree / 'catalogue').iterdir()}
        self.assertEqual(before, after)
        self.assertEqual([line[:8] for line in lines], ['écartée\t', 'lues 9 ;'])
        self.assertEqual(self.manifest()['sequence'], 1)

    def test_sequence_rises_only_when_the_revision_changes(self):
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        shorter = export_with(self.folder, drop('exemple:film-page'))  # same date: a withdrawal done in place
        lines = self.passes(run(self.tree, 'convert.py', shorter))
        self.assertIn('-\texemple:film-page', lines)
        self.assertEqual(self.manifest()['sequence'], 2)
        self.passes(run(self.tree, 'convert.py', shorter))
        self.assertEqual(self.manifest()['sequence'], 2)
        lines = self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        self.assertIn('+\texemple:film-page', lines)
        self.assertEqual((self.manifest()['sequence'], self.manifest()['revision']), (3, REVISION))

    def test_fragment_left_empty_is_deleted(self):
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        self.passes(run(self.tree, 'convert.py', export_with(self.folder, drop('exemple:court-sans-extension'))))
        self.assertFalse((self.tree / 'catalogue' / 'shorts-0.json').exists())
        self.assertNotIn('shorts-0.json', self.manifest()['files'])
        self.assertEqual(self.passes(run(self.tree, 'check.py', '--tree', self.tree)), [])

    def test_empty_export_gives_the_empty_catalogue(self):
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        self.passes(run(self.tree, 'convert.py', export_with(self.folder, lambda export: export.update(items=[]))))
        self.assertEqual(sorted(path.name for path in (self.tree / 'catalogue').iterdir()), ['manifest.json'])
        manifest = self.manifest()
        self.assertEqual((manifest['files'], manifest['sequence'], sum(manifest['counts'].values())), ({}, 2, 0))
        self.assertEqual(self.passes(run(self.tree, 'check.py', '--tree', self.tree)), [])
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))  # back from the emergency stop
        wanted = expected('catalogue')
        wanted['manifest.json'] = wanted['manifest.json'].replace(b'"sequence": 1', b'"sequence": 3')
        self.assertEqual(snapshot(self.tree / 'catalogue'), wanted)

    def test_untrusted_export_is_refused_and_nothing_is_written(self):
        lone = export_with(self.folder, lambda export: export.update(territories=['CH', 'FR', '\ud800']))  # unwritable
        self.assertEqual((run(self.tree, 'convert.py', lone).returncode, snapshot(self.tree / 'catalogue')), (1, {}))
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        before = snapshot(self.tree)
        refused = {
            'JSON illisible': lambda export: None,
            'schema_version': lambda export: export.update(schema_version=2),
            'publication_state': lambda export: export.update(publication_state='DRAFT'),
            'CH ou FR absent': lambda export: export.update(territories=['CH']),
            'counts': lambda export: export['counts'].update(shorts=9),
            'deux fiches de même id': lambda export: export['items'].append(export['items'][1]),
            'generated_at antérieur': lambda export: export.update(generated_at='2026-01-01T01:00:00+02:00'),  # instant
            'catalogue/films.json dépasserait': lambda export: export['items'][1].update(title='x' * 1_000_000),
            'catalogue/manifest.json dépasserait': lambda export: [  # with a title less: half a conversion would show
                drop('exemple:film-page')(export), export.update(territories=['CH', 'FR'] * 100_000)],
            'territories impossible à écrire en UTF-8': lambda export: [  # a file changes, a fragment goes
                drop('exemple:film-page')(export), drop('exemple:court-sans-extension')(export),
                export.update(territories=['CH', 'FR', '\ud800'])],
        }
        for reason, change in refused.items():
            with self.subTest(reason=reason):
                export = export_with(self.folder, change, counts=reason not in ('counts', 'deux fiches de même id'))
                if reason == 'JSON illisible':
                    export.write_bytes(export.read_bytes()[:-3])
                done = run(self.tree, 'convert.py', export)
                self.assertEqual((done.returncode, done.stdout), (1, ''))
                self.assertIn('conversion refusée : ' + reason, done.stderr)
                self.assertEqual(snapshot(self.tree), before)

    def test_damaged_withdrawal_list_or_manifest_stops_the_conversion(self):
        self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        cut, short = (lambda sound: sound[:-9]), (lambda sound: sound.replace(b' "revision"', b' "revisio"'))
        for name, damage in (('retraits.json', cut), (check.MANIFEST, cut), (check.MANIFEST, short)):
            with self.subTest(damaged=name, cut=damage is cut):
                sound = (self.tree / name).read_bytes()
                (self.tree / name).write_bytes(damage(sound))
                before = snapshot(self.tree)
                done = run(self.tree, 'convert.py', export_with(self.folder, drop('exemple:film-page')))
                self.assertEqual((done.returncode, done.stdout), (1, ''))
                self.assertIn('conversion refusée : état suivi illisible', done.stderr)
                self.assertEqual(snapshot(self.tree), before)
                (self.tree / name).write_bytes(sound)


if __name__ == '__main__':
    unittest.main()
