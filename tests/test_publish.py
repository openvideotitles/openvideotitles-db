"""Tests of publish.py, of what check.py --publication compares with the tracked files, and of stats.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_convert import REVISION, TreeTest, expected, export_with, run, snapshot  # noqa: E402
from test_hook import commit, git, make_repository  # noqa: E402


class PublishTest(TreeTest):
    def test_publication_reproduces_the_frozen_set_byte_for_byte(self):
        lines = self.passes(run(self.tree, 'publish.py'))
        wanted = expected('publication')
        self.assertEqual(snapshot(self.tree / 'publication'), wanted)
        self.assertEqual(lines, ['publiés 8 fichiers ; %d octets ; révision %s ; numéro d\'ordre 1' % (
            sum(len(data) for data in wanted.values()), REVISION)])

    def test_any_other_revision_is_removed_from_the_folder(self):
        stale = self.tree / 'publication' / 'catalog'
        (stale / ('0' * 64)).mkdir(parents=True)
        (stale / ('0' * 64) / 'films.json').write_bytes(b'{}')
        (stale / 'reste.txt').write_bytes(b'x')
        self.passes(run(self.tree, 'publish.py'))
        self.assertEqual(snapshot(self.tree / 'publication'), expected('publication'))

    def test_publication_follows_a_withdrawal(self):
        self.passes(run(self.tree, 'publish.py'))
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))
        self.passes(run(self.tree, 'publish.py'))
        catalog, manifest = self.tree / 'publication' / 'catalog', self.manifest()
        self.assertEqual({path.name for path in catalog.iterdir()}, {'manifest.json', manifest['revision']})
        tracked = snapshot(self.tree / 'catalogue')
        self.assertEqual((catalog / 'manifest.json').read_bytes(), tracked.pop('manifest.json'))
        self.assertEqual(snapshot(catalog / manifest['revision']), tracked)
        self.assertNotIn(b'exemple:film-page', b''.join(snapshot(catalog).values()))

    def test_tracked_manifest_that_does_not_match_the_files_is_not_published(self):
        path = self.tree / 'catalogue' / 'films.json'
        text = path.read_bytes().decode('utf-8')
        path.write_bytes(text.replace('Le Film d’essai"}', 'Autre titre"}').encode('utf-8'))
        done = run(self.tree, 'publish.py')
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn('catalogue/manifest.json\t8\t', done.stdout)
        self.assertIn('publication refusée : 1 écart(s)', done.stderr)
        self.assertFalse((self.tree / 'publication').exists())

    def test_only_a_committed_state_is_published_once_the_repository_has_a_commit(self):
        make_repository(self.tree)
        self.passes(run(self.tree, 'publish.py'))  # nothing committed yet: a local trial, allowed
        commit(self.tree, 'catalogue')
        self.passes(run(self.tree, 'publish.py'))
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))
        done = run(self.tree, 'publish.py')
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn('catalogue/manifest.json\tpublication\tdifférent du dernier commit', done.stdout)
        self.assertEqual(snapshot(self.tree / 'publication'), expected('publication'))  # still the committed one
        commit(self.tree, 'retrait')
        self.passes(run(self.tree, 'publish.py'))
        self.assertIn(self.manifest()['revision'], ' '.join(snapshot(self.tree / 'publication')))

    def test_nothing_is_published_while_git_does_not_say_the_state_is_committed(self):
        cases = {'git ne répond pas': lambda: (self.tree / '.git' / 'index').write_bytes(b'index illisible'),
                 'différent du dernier commit': lambda: git(self.tree, 'checkout', '-q', '--orphan', 'autre')}
        for reason, spoil in cases.items():  # an unreadable index, then a branch without any commit of its own
            with self.subTest(reason=reason):
                self.setUp()
                make_repository(self.tree)
                commit(self.tree, 'catalogue')
                self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))  # a change that is never committed
                spoil()
                done = run(self.tree, 'publish.py')
                self.assertEqual(done.returncode, 1, done.stdout)
                self.assertIn('\tpublication\t' + reason, done.stdout)
                self.assertFalse((self.tree / 'publication').exists())

    def test_publication_option_sees_a_changed_a_missing_and_an_extra_file(self):
        self.passes(run(self.tree, 'publish.py'))
        folder = self.tree / 'publication' / 'catalog'
        compared = ('check.py', '--tree', self.tree, '--publication', 'publication')
        self.assertEqual(self.passes(run(self.tree, *compared)), [])
        (folder / REVISION / 'films.json').write_bytes(b'{}')
        (folder / REVISION / 'series.json').unlink()
        (folder / 'autre.json').write_bytes(b'{}')
        lines = self.passes(run(self.tree, *compared), 1)
        revision = 'publication/catalog/%s/' % REVISION
        self.assertEqual(lines, [revision + 'films.json\tpublication\tfichier différent du fichier suivi',
                                 revision + 'series.json\tpublication\tfichier absent',
                                 'publication/catalog/autre.json\tpublication\tfichier en trop'])

    def test_empty_catalogue_is_published_as_a_manifest_alone(self):
        self.passes(run(self.tree, 'publish.py'))
        self.passes(run(self.tree, 'convert.py', export_with(self.folder, lambda export: export.update(items=[]))))
        lines = self.passes(run(self.tree, 'publish.py'))
        self.assertEqual(sorted(snapshot(self.tree / 'publication')), ['catalog/manifest.json'])
        self.assertIn('publiés 1 fichiers', lines[0])
        self.assertEqual(self.manifest()['sequence'], 2)


class StatsTest(TreeTest):
    def test_counts_by_section_mode_host_and_licence_form_without_writing(self):
        before = snapshot(self.tree)
        lines = self.passes(run(self.tree, 'stats.py'))
        self.assertEqual(lines[0], 'numéro d\'ordre 1 ; révision %s ; export du 2026-01-01T00:00:00+00:00' % REVISION)
        self.assertEqual(lines[1:7], ['section\tfiches\tsources\tdirect\tofficial_link', 'television\t1\t1\t0\t1',
                                      'films\t2\t2\t1\t1', 'series\t1\t1\t1\t0', 'shorts\t4\t5\t4\t1',
                                      'total\t8\t9\t6\t3'])
        self.assertEqual(lines[7:9], ['hôtes : 7, dont les 7 premiers', '3\tmedia.example'])
        self.assertEqual(lines[15:], ['formes de licence : 7', '3\tPDM', '1\tCC-BY-3.0', '1\tCC-BY-4.0',
                                      '1\tCC-BY-NC-SA-4.0', '1\tCC-BY-ND-3.0-DE',
                                      '1\tdomaine public (pd_reason) + CC0-1.0', '1\tpage du diffuseur'])
        self.assertEqual(snapshot(self.tree), before)


if __name__ == '__main__':
    unittest.main()
