#!/usr/bin/env python3
"""Publish catalogue/ as publication/catalog/: the manifest, and the data files under their revision.

Usage: python3 -I -B scripts/publish.py
Runs the control, writes byte for byte copies of the tracked files, removes any other revision from the folder,
then reads again what it wrote. The same folder is the remote publication and the seed given to a build.
In a repository that already has a commit, only a committed state is published: two different revisions
under one sequence number could otherwise leave, and a device that adopted the first refuses the second.
Also home of the folder reader and of the publication layout that check.py compares with --publication.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue_lib as lib  # noqa: E402


def scan(folder, aside=()):
    """A folder as ({relative path: bytes, None above the size limit}, {path: text of a UTF-8 file}, deviations).
    `aside` names the top-level build outputs left unread, and then __pycache__ is left unread everywhere."""
    files, texts, found = {}, {}, []
    for current, folders, names in os.walk(str(folder)):
        relative = os.path.relpath(current, str(folder)).replace(os.sep, '/')
        prefix = '' if relative == '.' else relative + '/'
        skipped = (set() if prefix else set(aside)) | ({'__pycache__'} if aside else set())
        folders[:], names = sorted(set(folders) - skipped), sorted(set(names) - skipped)
        if prefix and not folders and not names:
            found.append((prefix[:-1], 1, 'dossier vide'))
        for name in folders + names:
            path = os.path.join(current, name)
            if os.path.islink(path) or name in names and not os.path.isfile(path):
                found.append((prefix + name, 1, 'lien symbolique ou fichier spécial'))
            elif name in names:
                with open(path, 'rb') as stream:
                    data = stream.read(lib.MAX_FILE_BYTES + 1)
                files[prefix + name] = data if len(data) <= lib.MAX_FILE_BYTES else None
                try:
                    texts[prefix + name] = files[prefix + name].decode('utf-8')
                except (AttributeError, UnicodeDecodeError):
                    pass  # above the limit or not UTF-8: rule 1 of the control says so
    return files, texts, found


def layout(files):
    """(manifest, publication as {path under the publication folder: bytes}) from the tracked files."""
    manifest = json.loads(files['catalogue/manifest.json'])
    wanted = {'catalog/%s/%s' % (manifest['revision'], name): files['catalogue/' + name] for name in manifest['files']}
    wanted['catalog/manifest.json'] = files['catalogue/manifest.json']
    return manifest, wanted


def compare(files, folder):
    """Deviations of a publication folder from the tracked files: nothing but the layout, byte for byte."""
    try:
        wanted = layout(files)[1]
    except lib.UNREADABLE:
        return [('catalogue/manifest.json', 'publication', 'manifeste suivi illisible, ou fichier du manifeste absent')]
    present, _, found = scan(Path(folder))
    found = [('%s/%s' % (folder, path), 'publication', reason) for path, _, reason in found]
    for path in sorted(set(wanted) | set(present)):
        if path not in present or path not in wanted or present[path] != wanted[path]:
            extra = 'en trop' if path not in wanted else 'différent du fichier suivi'
            reason = 'absent' if path not in present else extra
            found.append(('%s/%s' % (folder, path), 'publication', 'fichier ' + reason))
    return found


def uncommitted(root):
    """Deviations when catalogue/ or retraits.json differ from the last commit; none while the repository holds
    no commit at all, on any branch. A git that does not answer is a deviation: nothing says the state is committed."""
    def git(*query):
        try:
            done = subprocess.run(['git', '-C', str(root)] + list(query), capture_output=True)
        except OSError:
            return None
        return None if done.returncode else done.stdout.decode('utf-8', 'replace')
    if not (root / '.git').exists():
        return []
    commits = git('rev-list', '-n', '1', '--all')
    changed = git('status', '--porcelain', '--', 'catalogue', 'retraits.json') if commits else ''
    if commits is None or changed is None:
        return [('.git', 'publication', 'git ne répond pas : rien ne dit que cet état est commité')]
    return [(line[3:], 'publication', 'différent du dernier commit : on ne publie que ce qui est commité')
            for line in changed.split('\n') if line]


def prune(folder, kept):
    """Remove from a folder every entry that is not named in `kept`."""
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.name not in kept and path.is_dir() and not path.is_symlink():
            shutil.rmtree(str(path))
        elif path.name not in kept:
            path.unlink()


def main(argv=None):
    import check  # the control imports this module for scan and compare, so its own import waits until here
    argparse.ArgumentParser(description='Écrit publication/catalog/ depuis catalogue/, après le contrôle.'
                            ).parse_args(argv)
    lib.utf8_output()
    target = lib.ROOT / 'publication'
    found = check.deviations(lib.ROOT, hooks=True) or uncommitted(lib.ROOT)
    if not found:
        files = scan(lib.ROOT, ('.git', 'publication'))[0]
        manifest, wanted = layout(files)
        for path in sorted(wanted, key=lambda path: (path == 'catalog/manifest.json', path)):  # the manifest last
            lib.atomic_write(target / path, wanted[path])
        prune(target / 'catalog', {'manifest.json'} | ({manifest['revision']} if manifest['files'] else set()))
        prune(target / 'catalog' / manifest['revision'], set(manifest['files']))
        found = compare(files, os.path.relpath(str(target)))
    for line in found:
        print('%s\t%s\t%s' % line)
    if found:
        print('publication refusée : %d écart(s)' % len(found), file=sys.stderr)
        return 1
    print('publiés %d fichiers ; %d octets ; révision %s ; numéro d\'ordre %d' % (
        len(wanted), sum(len(data) for data in wanted.values()), manifest['revision'], manifest['sequence']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
