#!/usr/bin/env python3
"""Withdraw titles for good: their fingerprints join retraits.json and their lines leave the data files.

Usage: python3 -I -B scripts/withdraw.py <id>... [--date AAAA-MM-JJ]
Reads no export and opens no connection. An id absent from the catalogue is recorded all the same: it will
never enter. The manifest is computed again (the sequence number rises if the revision changes), then the
control runs. Also home of what never goes back, which check.py compares with --base: a withdrawal line
never disappears, a sequence number never decreases.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue_lib as lib  # noqa: E402

WITHDRAWALS, MANIFEST = 'retraits.json', 'catalogue/manifest.json'


def since(files, base):
    """Rules 7 and 8 against a git reference, read by `git show` in the repository of the current directory.
    `files` is the controlled tree as {relative path: bytes}. Returns (path, rule, reason) deviations."""
    found = []
    try:
        known = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', base + '^{commit}'], capture_output=True)
        if known.returncode:
            return [('--base', 'base', 'référence git illisible : %s' % base)]
        shown = [subprocess.run(['git', 'show', '%s:%s' % (base, path)], capture_output=True)
                 for path in (WITHDRAWALS, MANIFEST)]
        old_lines, old = (json.loads(done.stdout) if done.returncode == 0 else None for done in shown)
        lines, manifest = (json.loads(files[path]) for path in (WITHDRAWALS, MANIFEST))
        found += [(WITHDRAWALS, 7, 'ligne présente dans la base et disparue : %s' % line.get('sha256'))
                  for line in (old_lines['withdrawn'] if old_lines else []) if line not in lines['withdrawn']]
        changed = bool(old) and old['revision'] != manifest['revision']
        if old and (manifest['sequence'] < old['sequence'] or changed == (manifest['sequence'] == old['sequence'])):
            found.append((MANIFEST, 8, 'numéro d’ordre %s après %s dans la base, révision %s' % (
                manifest['sequence'], old['sequence'], 'changée' if changed else 'inchangée')))
    except lib.UNREADABLE:
        found.append(('--base', 'base', 'comparaison à la base impossible : git, retraits ou manifeste illisible'))
    return found


def main(argv=None):
    import check  # the control imports this module for `since`, so its own import waits until here
    parser = argparse.ArgumentParser(description='Retire définitivement des titres : retraits.json et catalogue/.')
    parser.add_argument('ids', nargs='+', metavar='id', help='identifiant du titre, tel que sa fiche l’écrit')
    parser.add_argument('--date', metavar='AAAA-MM-JJ', default=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d'),
                        help='date du retrait (par défaut : aujourd’hui, en temps universel)')
    args = parser.parse_args(argv)
    lib.utf8_output()
    root = lib.ROOT
    try:
        if lib.instant(args.date + 'T00:00:00Z') is None:
            raise ValueError('date attendue sous la forme AAAA-MM-JJ')
        lines, manifest, files = lib.read_withdrawals(root), lib.read_manifest(root), lib.read_data_files(root)
        if manifest is None:
            raise ValueError('catalogue/manifest.json absent')
        targets = {lib.fingerprint(ident): ident for ident in args.ids}
        lines += [{'date': args.date, 'sha256': mark}
                  for mark in sorted(set(targets) - {line['sha256'] for line in lines})]
        kept = {name: [item for item in items if lib.fingerprint(item['id']) not in targets]
                for name, items in files.items()}
        removed = {item['id'] for items in files.values() for item in items if lib.fingerprint(item['id']) in targets}
        data = {name: lib.data_file(lib.section_of(name), items) for name, items in kept.items() if items}
        counts = {section: sum(len(items) for name, items in kept.items() if lib.section_of(name) == section)
                  for section in lib.SECTIONS}
        updated = lib.manifest_of(manifest, {name: lib.entry(name, data[name]) for name in data}, counts,
                                  manifest['sequence'])
        updated['sequence'] += updated['revision'] != manifest['revision']
        withdrawals, document = lib.withdrawals_bytes(lines), lib.manifest_bytes(updated)
    except lib.UNREADABLE as error:  # every byte is ready before the first write, or nothing is written
        reason = 'état suivi impossible à écrire en UTF-8' if isinstance(error, UnicodeEncodeError) else error
        print('retrait refusé : %s' % reason, file=sys.stderr)
        return 1
    lib.atomic_write(root / WITHDRAWALS, withdrawals)  # first: the title can no longer come back
    for name in files:
        if name in data:
            lib.atomic_write(root / 'catalogue' / name, data[name])
        else:
            (root / 'catalogue' / name).unlink()  # a data file without any item does not exist
    lib.atomic_write(root / MANIFEST, document)  # last, like a conversion
    for mark, ident in sorted(targets.items()):
        print('%s\t%s\t%s' % ('retiré' if ident in removed else 'inscrit', lib.CONTROL.sub('?', ident), mark))
    print('retraits %d ; révision %s ; numéro d\'ordre %d' % (len(lines), updated['revision'], updated['sequence']))
    found = check.deviations(root, hooks=True)
    for line in found:
        print('%s\t%s\t%s' % line)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
