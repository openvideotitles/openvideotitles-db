#!/usr/bin/env python3
"""Convert the export into catalogue/. The only input is the export file, given as an argument.

Usage: python3 -I -B scripts/convert.py <export.json>
An export that cannot be trusted is refused and nothing is written (exit code 1). A withdrawn or faulty item
is set aside and listed, and the others are written: a faulty item never blocks the withdrawal of another.
Each conversion replaces everything: a title absent from the export is in no file any more.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue_lib as lib  # noqa: E402

MANIFEST = 'manifest.json'


class Refused(Exception):
    """The export is not converted; the message says why."""


def load(path):
    """The export, checked as a whole. Raises Refused before anything is written."""
    try:
        export = json.loads(Path(path).read_bytes())
    except (OSError, ValueError, RecursionError) as error:
        raise Refused('JSON illisible (%s)' % error)
    if not isinstance(export, dict) or not isinstance(export.get('items'), list):
        raise Refused('JSON illisible (objet à clé items attendu)')
    if type(export.get('schema_version')) is not int or export['schema_version'] != 1:
        raise Refused('schema_version différent de 1')
    if export.get('publication_state') != 'READY':
        raise Refused('publication_state différent de READY')
    if lib.header_fault(export):
        raise Refused(lib.header_fault(export))
    counted, seen = dict.fromkeys(lib.SECTIONS, 0), set()
    for item in export['items']:
        if not isinstance(item, dict):
            raise Refused('fiche qui n’est pas un objet')
        section = item.get('section') if isinstance(item.get('section'), str) else '?'
        counted[section] = counted.get(section, 0) + 1
        if isinstance(item.get('id'), str) and item['id'] in seen:
            raise Refused('deux fiches de même id : %s' % shown(item['id']))
        seen.add(item['id'] if isinstance(item.get('id'), str) else None)
    if export.get('counts') != counted:
        raise Refused('counts de l’en-tête différents des fiches comptées')
    return export


def plan(export, root, now=None):
    """Everything computed in memory: (files as {name: bytes}, manifest, items set aside, ids written).
    `files` holds every byte to write, the manifest last: what cannot be written is refused here, before any write.
    `now` is the clock of the conversion: an item with a source expired by then is set aside."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        previous = lib.read_manifest(root)
        withdrawn = {line['sha256'] for line in lib.read_withdrawals(root)}
    except lib.UNREADABLE as error:
        raise Refused('état suivi illisible (%s)' % error)
    if previous and lib.instant(export['generated_at']) < lib.instant(previous['generated_at']):
        raise Refused('generated_at antérieur à celui du manifeste suivi (%s)' % previous['generated_at'])
    kept, aside = {}, []
    for item in export['items']:
        item = dict(item)
        assets, ident = item.pop('assets', None), item.get('id')
        if isinstance(ident, str) and lib.fingerprint(ident) in withdrawn:
            aside.append((ident, 'retrait'))
            continue
        reasons = (['assets non vide'] if assets else []) + [reason for _, reason in lib.fautes(item, now)]
        if reasons:
            aside.append((ident, 'faute : ' + ' ; '.join(reasons)))
            continue
        kept.setdefault(lib.file_of(item), []).append(item)
    files = {name: lib.data_file(lib.section_of(name), items) for name, items in sorted(kept.items())}
    counts = {section: sum(len(items) for name, items in kept.items() if lib.section_of(name) == section)
              for section in lib.SECTIONS}
    manifest = lib.manifest_of(export, {name: lib.entry(name, data) for name, data in files.items()}, counts, 1)
    if previous:
        manifest['sequence'] = previous['sequence'] + (manifest['revision'] != previous['revision'])
    try:
        files[MANIFEST] = lib.manifest_bytes(manifest)
    except UnicodeEncodeError:  # the header gives the only free texts of a manifest
        raise Refused('territories impossible à écrire en UTF-8')
    for name, data in files.items():
        if len(data) > lib.MAX_FILE_BYTES:
            raise Refused('catalogue/%s dépasserait 1 000 000 octets' % name)
    return files, manifest, aside, {item['id'] for items in kept.values() for item in items}


def tracked_ids(root):
    """Ids of the state before the conversion. An unreadable catalogue counts as empty: it is replaced anyway."""
    try:
        return {item['id'] for items in lib.read_data_files(root).values() for item in items}
    except lib.UNREADABLE:
        return set()


def write(root, files):
    """Write the bytes of `plan` and compute nothing: changed files first, then the fragments that became empty
    are removed, the manifest last."""
    folder = root / 'catalogue'
    for name in files:
        if name != MANIFEST:
            lib.atomic_write(folder / name, files[name])
    for path in sorted(folder.glob('*.json')):
        if lib.DATA_FILE.fullmatch(path.name) and path.name not in files:
            path.unlink()
    lib.atomic_write(folder / MANIFEST, files[MANIFEST])


def shown(ident):
    """An id as one printable field of a tab-separated line."""
    plain = isinstance(ident, str) and ident and not lib.CONTROL.search(ident)
    return ident if plain else json.dumps(ident, ensure_ascii=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Convertit le fichier d’export en catalogue/.')
    parser.add_argument('export', help='fichier d’export, seule entrée de la conversion')
    args = parser.parse_args(argv)
    lib.utf8_output()
    try:
        export = load(args.export)
        files, manifest, aside, after = plan(export, lib.ROOT)
    except Refused as refusal:
        print('conversion refusée : %s' % refusal, file=sys.stderr)
        return 1
    before = tracked_ids(lib.ROOT)
    write(lib.ROOT, files)
    for ident, reason in aside:
        print('écartée\t%s\t%s' % (shown(ident), lib.CONTROL.sub('?', reason)))
    for ident in sorted(before ^ after, key=lambda ident: ident.encode('utf-8', 'surrogatepass')):
        print('%s\t%s' % ('+' if ident in after else '-', shown(ident)))
    retired = sum(reason == 'retrait' for _, reason in aside)
    print('lues %d ; écrites %d ; écartées %d (retrait %d, faute %d) ; révision %s ; numéro d\'ordre %d' % (
        len(export['items']), len(after), len(aside), retired, len(aside) - retired, manifest['revision'],
        manifest['sequence']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
