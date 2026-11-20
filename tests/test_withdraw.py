"""Tests of withdraw.py, and of what check.py --base compares with an earlier state."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_convert as shared  # noqa: E402
from test_check import item, rebuild  # noqa: E402
from test_convert import CONTRACT, TreeTest, check, data, lib, run, snapshot  # noqa: E402
from test_hook import commit, make_repository  # noqa: E402

FILM = 'exemple:film-page'
MARK = lib.fingerprint(FILM)


class WithdrawTest(TreeTest):
    def withdrawals(self):
        return (self.tree / 'retraits.json').read_bytes().decode('utf-8')

    def test_withdrawal_changes_a_data_file_the_manifest_and_the_list(self):
        before = self.manifest()
        lines = self.passes(run(self.tree, 'withdraw.py', FILM, '--date', '2026-02-03'))
        after = self.manifest()
        self.assertEqual(lines, ['retiré\t%s\t%s' % (FILM, MARK),
                                 'retraits 2 ; révision %s ; numéro d\'ordre 2' % after['revision']])
        self.assertEqual([item['id'] for item in data(self.tree, 'films.json')], ['exemple:film-direct'])
        self.assertEqual((after['sequence'], after['counts']['films']), (before['sequence'] + 1, 1))
        self.assertNotEqual(after['revision'], before['revision'])
        self.assertIn('{"date":"2026-02-03","sha256":"%s"}' % MARK, self.withdrawals())
        self.assertEqual(check.deviations(self.tree), [])

    def test_fragment_left_empty_is_deleted_and_the_date_is_today(self):
        self.passes(run(self.tree, 'withdraw.py', 'exemple:court-deux-sources'))
        self.assertFalse((self.tree / 'catalogue' / 'shorts-8.json').exists())
        self.assertNotIn('shorts-8.json', self.manifest()['files'])
        date = re.search('"date":"([0-9-]{10})","sha256":"%s"' % lib.fingerprint('exemple:court-deux-sources'),
                         self.withdrawals()).group(1)
        self.assertIsNotNone(lib.instant(date + 'T00:00:00Z'))
        self.assertNotEqual(date, '2026-01-02')

    def test_converting_the_same_export_again_does_not_bring_the_title_back(self):
        self.passes(run(self.tree, 'withdraw.py', FILM))
        withdrawn = snapshot(self.tree / 'catalogue')
        lines = self.passes(run(self.tree, 'convert.py', CONTRACT / 'export-essai.json'))
        self.assertIn('écartée\t%s\tretrait' % FILM, lines)
        self.assertEqual(snapshot(self.tree / 'catalogue'), withdrawn)  # same bytes, same sequence number

    def test_absent_id_is_recorded_all_the_same_and_will_never_enter(self):
        before = snapshot(self.tree / 'catalogue')
        lines = self.passes(run(self.tree, 'withdraw.py', 'exemple:court-fautif'))
        self.assertEqual(lines[0], 'inscrit\texemple:court-fautif\t' + lib.fingerprint('exemple:court-fautif'))
        self.assertEqual(snapshot(self.tree / 'catalogue'), before)
        export = shared.export_with(self.folder, shared.faulty())  # a sound item this time
        lines = self.passes(run(self.tree, 'convert.py', export))
        self.assertIn('écartée\texemple:court-fautif\tretrait', lines)
        self.assertEqual(snapshot(self.tree / 'catalogue'), before)

    def test_same_id_twice_keeps_one_line_and_its_first_date(self):
        self.passes(run(self.tree, 'withdraw.py', FILM, '--date', '2026-02-01'))
        once = snapshot(self.tree)
        self.passes(run(self.tree, 'withdraw.py', FILM, '--date', '2026-03-01'))
        self.assertEqual(snapshot(self.tree), once)
        self.assertEqual(self.withdrawals().count(MARK), 1)

    def test_wrong_date_is_refused_and_nothing_is_written(self):
        before = snapshot(self.tree)
        for date in ('03/02/2026', '2026-02-30'):
            with self.subTest(date=date):
                done = run(self.tree, 'withdraw.py', FILM, '--date', date)
                self.assertEqual((done.returncode, done.stdout), (1, ''))
                self.assertIn('retrait refusé : date attendue', done.stderr)
                self.assertEqual(snapshot(self.tree), before)

    def test_withdrawal_passes_while_another_item_has_expired(self):
        item('shorts-8.json', source=True, expires_at='2000-01-01T00:00:00Z')(self.tree)
        lines = self.passes(run(self.tree, 'withdraw.py', FILM))
        self.assertEqual(len(lines), 2, lines)  # the control reads no clock: nothing blocks the withdrawal

    def test_damaged_tracked_state_refuses_the_withdrawal_and_nothing_is_written(self):
        damaged = {  # reason printed: what is done to the tracked state before the withdrawal
            'catalogue/manifest.json absent': lambda path, manifest: path.unlink(),
            'catalogue/manifest.json illisible': lambda path, manifest: path.write_bytes(lib.manifest_bytes(
                {key: value for key, value in manifest.items() if key != 'revision'})),
            'état suivi impossible à écrire en UTF-8': lambda path, manifest: path.write_bytes(json.dumps(
                dict(manifest, territories=['CH', 'FR', '\ud800'])).encode('ascii')),
            'retraits.json illisible': lambda path, manifest: (self.tree / 'retraits.json').write_bytes(
                b'{"schema":1,"withdrawn":{}}\n'),
        }
        for reason, damage in damaged.items():
            with self.subTest(reason=reason):
                self.setUp()
                damage(self.tree / 'catalogue' / 'manifest.json', self.manifest())
                before = snapshot(self.tree)
                done = run(self.tree, 'withdraw.py', FILM)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (1, '', 'retrait refusé : %s\n' % reason))
                self.assertEqual(snapshot(self.tree), before)

    def test_deleting_a_withdrawal_line_fails_against_the_base(self):
        make_repository(self.tree)
        self.passes(run(self.tree, 'withdraw.py', FILM, '--date', '2026-02-03'))
        commit(self.tree, 'retrait')
        (self.tree / 'retraits.json').write_bytes((CONTRACT / 'retraits-essai.json').read_bytes())
        self.assertEqual(self.passes(run(self.tree, 'check.py')), [])  # without the base, nothing is seen
        lines = self.passes(run(self.tree, 'check.py', '--base', 'HEAD'), 1)
        self.assertEqual(lines, ['retraits.json\t7\tligne présente dans la base et disparue : ' + MARK])

    def test_sequence_number_is_compared_with_the_base(self):
        make_repository(self.tree)
        first = commit(self.tree, 'catalogue')
        self.passes(run(self.tree, 'withdraw.py', FILM))
        self.assertEqual(self.passes(run(self.tree, 'check.py', '--base', first)), [])
        second = commit(self.tree, 'retrait')
        for sequence, base, reason in ((1, second, 'numéro d’ordre 1 après 2 dans la base, révision inchangée'),
                                       (3, second, 'numéro d’ordre 3 après 2 dans la base, révision inchangée'),
                                       (1, first, 'numéro d’ordre 1 après 1 dans la base, révision changée')):
            with self.subTest(reason=reason):
                rebuild(self.tree, sequence=sequence)
                lines = self.passes(run(self.tree, 'check.py', '--base', base), 1)
                self.assertEqual(lines, ['catalogue/manifest.json\t8\t' + reason])
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-direct'))  # the revision changes once more
        rebuild(self.tree, sequence=1)
        lines = self.passes(run(self.tree, 'check.py', '--base', second), 1)
        self.assertEqual(lines, ['catalogue/manifest.json\t8\tnuméro d’ordre 1 après 2 dans la base, révision changée'])
        lines = self.passes(run(self.tree, 'check.py', '--base', 'nulle-part'), 1)
        self.assertEqual(lines, ['--base\tbase\tréférence git illisible : nulle-part'])


if __name__ == '__main__':
    unittest.main()
