"""Tests of the pre-push hook, on a throwaway repository and a bare local remote. Nothing leaves the machine.

The hook controls every commit about to leave, not the work tree. The test identity is set in the throwaway
repository only, and the hook runs the interpreter that runs these tests.
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_check import rebuild  # noqa: E402
from test_convert import ENV, TreeTest, check, run  # noqa: E402

FORBIDDEN = 'fuite.m' + '3u'
BY_HAND = 'à relire à la main : le commit %s retouche scripts/ ou .githooks/'
NO_PRIVATE = 'avis : envoi sans contrôle privé'


def git(folder, *args, env=None, strict=True):
    """One git command in a throwaway repository, away from the configuration of the person running the tests."""
    command = ['git', '-C', str(folder)] + [str(arg) for arg in args]
    done = subprocess.run(command, env=env or ENV, capture_output=True, encoding='utf-8')
    if strict and done.returncode:
        raise AssertionError('%s: %s' % (' '.join(command), done.stderr))
    return done


def make_repository(tree):
    """A throwaway git repository on a copied tree: test identity set there only, hook active."""
    git(tree, 'init', '-q', '-b', 'main')
    for key, value in (('user.name', 'essai'), ('user.email', 'essai@example.invalid'), ('commit.gpgsign', 'false'),
                       ('core.hooksPath', '.githooks')):
        git(tree, 'config', key, value)


def commit(tree, message):
    """Commit everything in a throwaway repository; returns the commit."""
    git(tree, 'add', '-A')
    git(tree, 'commit', '-q', '-m', message)
    return git(tree, 'rev-parse', 'HEAD').stdout.strip()


@unittest.skipUnless(shutil.which('git'), 'git is not installed')
class HookTest(TreeTest):
    def setUp(self):
        super().setUp()
        make_repository(self.tree)
        self.remote = self.folder / 'distant.git'
        git(self.folder, 'init', '-q', '--bare', '-b', 'main', self.remote)
        git(self.tree, 'remote', 'add', 'origin', self.remote)
        (self.folder / 'bin').mkdir()
        (self.folder / 'bin' / 'python3').write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable, encoding='utf-8')
        (self.folder / 'bin' / 'python3').chmod(0o755)
        self.env = dict(ENV, PATH=str(self.folder / 'bin') + os.pathsep + ENV['PATH'])
        self.first = commit(self.tree, 'catalogue')

    def push(self, *refs, **env):
        return git(self.tree, 'push', '-q', 'origin', *(refs or ('main',)), env=dict(self.env, **env), strict=False)

    def sent(self):
        return git(self.remote, 'rev-parse', '--verify', '-q', 'refs/heads/main', strict=False).stdout.strip()

    def refused(self, commit_named, **env):
        done = self.push(**env)
        self.assertNotEqual(done.returncode, 0, done.stderr)
        self.assertIn('envoi refusé : commit %s' % commit_named, done.stderr)
        self.assertEqual(self.sent(), self.first)  # the remote received nothing
        return done

    def start(self):
        done = self.push()
        self.assertEqual((done.returncode, self.sent()), (0, self.first), done.stderr)
        return done

    def test_clean_push_passes_and_so_does_a_withdrawal_after_it(self):
        notices = self.start().stderr
        self.assertIn(BY_HAND % self.first, notices)  # the first commit brings the scripts: named, not refused
        self.assertIn(NO_PRIVATE, notices)
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))
        second = commit(self.tree, 'retrait')
        done = self.push()
        self.assertEqual((done.returncode, self.sent()), (0, second), done.stderr)
        self.assertNotIn('à relire à la main', done.stderr)  # this one changes data only
        path = self.tree / 'scripts' / 'stats.py'
        path.write_bytes(path.read_bytes() + b'\n# relu\n')
        third = commit(self.tree, 'script retouché')
        done = self.push()
        self.assertEqual((done.returncode, self.sent()), (0, third), done.stderr)
        self.assertIn(BY_HAND % third, done.stderr)

    def test_forbidden_file_committed_then_removed_refuses_the_push(self):
        self.start()
        (self.tree / FORBIDDEN).write_bytes(b'x')
        bad = commit(self.tree, 'fichier interdit')
        (self.tree / FORBIDDEN).unlink()
        commit(self.tree, 'fichier effacé')
        self.assertEqual(check.deviations(self.tree, hooks=True), [])  # the work tree is clean again
        self.refused(bad)

    def test_file_hidden_by_export_ignore_refuses_the_push(self):
        self.start()
        (self.tree / FORBIDDEN).write_bytes(b'x')
        (self.tree / '.gitattributes').write_text('.gitattributes export-ignore\n%s export-ignore\n' % FORBIDDEN)
        bad = commit(self.tree, 'fichier interdit caché')
        archive = subprocess.run(['git', '-C', str(self.tree), 'archive', '--format=tar', bad], env=ENV,
                                 capture_output=True).stdout
        self.assertNotIn(FORBIDDEN, tarfile.open(fileobj=io.BytesIO(archive)).getnames())  # an archive hides it
        (self.tree / FORBIDDEN).unlink()
        (self.tree / '.gitattributes').unlink()
        commit(self.tree, 'fichier effacé')
        self.refused(bad)

    def test_sequence_number_that_goes_down_then_up_refuses_the_push(self):
        self.start()
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))
        commit(self.tree, 'retrait : numéro 2')
        rebuild(self.tree, sequence=1)
        down = commit(self.tree, 'numéro 1 : il baisse')
        rebuild(self.tree, sequence=3)
        commit(self.tree, 'numéro 3 : il remonte')
        # Compared with what was already sent, the last state alone looks fine: each commit must be judged.
        self.assertEqual(self.passes(run(self.tree, 'check.py', '--base', self.first)), [])
        self.assertIn('numéro d’ordre 1 après 2', self.refused(down).stderr)

    def test_commit_that_tracks_a_build_output_refuses_the_push(self):
        self.start()
        for folder in ('publication', 'scripts/__pycache__'):
            with self.subTest(folder=folder):
                git(self.tree, 'reset', '-q', '--hard', self.first)
                (self.tree / folder).mkdir()
                (self.tree / folder / 'hors-controle.txt').write_bytes(b'x')
                git(self.tree, 'add', '-f', folder)
                bad = commit(self.tree, 'sortie de build suivie')
                self.assertIn('suivi par git', self.refused(bad).stderr)

    def test_push_by_explicit_address_is_controlled_like_the_others(self):
        (self.tree / FORBIDDEN).write_bytes(b'x')
        bad = commit(self.tree, 'fichier interdit')
        (self.tree / FORBIDDEN).unlink()
        commit(self.tree, 'fichier effacé')
        done = git(self.tree, 'push', '-q', self.remote, 'main', env=self.env, strict=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('envoi refusé : commit %s' % bad, done.stderr)
        self.assertEqual(self.sent(), '')
        git(self.tree, 'reset', '-q', '--hard', self.first)
        done = git(self.tree, 'push', '-q', self.remote, 'main', env=self.env, strict=False)
        self.assertEqual((done.returncode, self.sent()), (0, self.first), done.stderr)

    def test_new_branch_is_controlled_and_a_deleted_branch_is_not(self):
        self.start()
        self.assertEqual(self.push('main:autre').returncode, 0)
        (self.tree / FORBIDDEN).write_bytes(b'x')
        bad = commit(self.tree, 'fichier interdit')
        done = self.push('main:neuve')
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('envoi refusé : commit %s' % bad, done.stderr)
        self.assertEqual(self.push(':autre').returncode, 0)  # the work tree is not what is judged
        git(self.tree, 'checkout', '-q', '--orphan', 'racine')
        root = commit(self.tree, 'histoire neuve, le fichier interdit dès son premier commit')
        self.assertIn('envoi refusé : commit %s' % root, self.push('racine').stderr)  # no parent to compare with

    def test_forced_push_that_would_discard_commits_of_the_remote_is_refused(self):
        self.start()
        other = self.folder / 'autre'
        git(self.folder, 'clone', '-q', self.remote, other)
        (other / 'NOTICE.md').write_bytes((other / 'NOTICE.md').read_bytes() + b'\nAilleurs.\n')
        git(other, '-c', 'user.name=essai', '-c', 'user.email=essai@example.invalid', 'commit', '-q', '-am', 'ailleurs')
        git(other, 'push', '-q', 'origin', 'main')
        elsewhere = self.sent()  # it could hold a withdrawal: every commit here is judged against its parent only
        (self.tree / 'README.md').write_bytes((self.tree / 'README.md').read_bytes() + b'\nIci.\n')
        commit(self.tree, 'ici')
        for case, step in (('unknown here', ('status',)), ('known here', ('fetch', '-q', 'origin')),
                           ('ahead of what is sent', ('reset', '-q', '--hard', self.first))):
            with self.subTest(remote_commit=case):
                git(self.tree, *step)
                done = self.push('--force', 'main')
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('refusé : refs/heads/main : cet envoi écarterait des commits du distant', done.stderr)
                self.assertEqual(self.sent(), elsewhere)

    def test_commit_hidden_by_a_replacement_is_judged_as_it_leaves(self):
        self.start()
        (self.tree / 'NOTICE.md').write_bytes((self.tree / 'NOTICE.md').read_bytes() + b'\nUne ligne.\n')
        clean = commit(self.tree, 'commit sain')
        git(self.tree, 'reset', '-q', '--hard', self.first)
        (self.tree / FORBIDDEN).write_bytes(b'x')
        bad = commit(self.tree, 'fichier interdit')
        git(self.tree, 'replace', bad, clean)  # here, the faulty commit now reads as the clean one
        self.refused(bad)

    def test_merge_is_judged_against_each_of_its_parents(self):
        self.start()
        git(self.tree, 'checkout', '-q', '-b', 'cote')
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))
        commit(self.tree, 'retrait sur une branche de côté')
        git(self.tree, 'checkout', '-q', 'main')
        git(self.tree, 'merge', '-q', '--no-ff', '-s', 'ours', '-m', 'fusion qui garde main', 'cote')
        merge = git(self.tree, 'rev-parse', 'HEAD').stdout.strip()  # same tree as its first parent: the title is back
        self.assertIn('ligne présente dans la base et disparue', self.refused(merge).stderr)

    def test_bytes_of_the_commit_are_judged_whatever_the_line_ending_setting(self):
        git(self.tree, 'config', 'core.autocrlf', 'true')
        self.start()

    def test_object_that_is_not_a_commit_refuses_the_push(self):
        self.start()
        blob = git(self.tree, 'hash-object', '-w', 'README.md').stdout.strip()
        done = self.push('%s:refs/tags/objet' % blob)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('ne désigne pas un commit', done.stderr)

    def test_inactive_hook_is_a_deviation_and_blocks_what_prepares_a_push(self):
        self.assertEqual(self.passes(run(self.tree, 'check.py')), [])
        (self.tree / check.HOOK).chmod(0o644)
        lines = self.passes(run(self.tree, 'check.py'), 1)
        self.assertEqual([line.split('\t')[:2] for line in lines], [['.githooks/pre-push', '1']])
        (self.tree / check.HOOK).chmod(0o755)
        git(self.tree, 'config', '--unset', 'core.hooksPath')
        lines = self.passes(run(self.tree, 'check.py'), 1)
        self.assertEqual([line.split('\t')[:2] for line in lines], [['.git/config', '1']])
        self.assertEqual(run(self.tree, 'publish.py').returncode, 1)
        self.assertFalse((self.tree / 'publication').exists())
        self.assertEqual(run(self.tree, 'withdraw.py', 'exemple:film-page').returncode, 1)

    def test_private_command_runs_on_each_commit_then_on_the_repository(self):
        journal = self.folder / 'journal'
        done = self.push(CATALOGUE_PRIVATE_CHECK='sh -c \'echo "$1" >> "%s"\' journal' % journal)
        self.assertEqual((done.returncode, self.sent()), (0, self.first), done.stderr)
        self.assertNotIn(NO_PRIVATE, done.stderr)
        seen = journal.read_text(encoding='utf-8').split('\n')[:-1]
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[0].endswith('/tree'), seen)  # the export of the commit
        self.assertEqual(os.path.realpath(seen[1]), os.path.realpath(str(self.tree)))  # then the repository itself
        self.passes(run(self.tree, 'withdraw.py', 'exemple:film-page'))
        second = commit(self.tree, 'retrait')
        self.assertIn('contrôle privé', self.refused(second, CATALOGUE_PRIVATE_CHECK='false').stderr)


if __name__ == '__main__':
    unittest.main()
