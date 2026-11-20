#!/usr/bin/env python3
"""Print the counts of the catalogue by section, mode, host and licence form. Read only.

Usage: python3 -I -B scripts/stats.py
"""
import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue_lib as lib  # noqa: E402

HOSTS_SHOWN = 20


def licence_form(reference, section):
    """The form of a licence reference: its code, or what stands for it."""
    if section == 'television':
        return 'page du diffuseur'
    match = lib.LICENCE.fullmatch(reference)
    if not match:
        return 'hors de la grammaire'
    return ('domaine public (pd_reason) + ' if match.group(1) else '') + match.group(2)


def main(argv=None):
    argparse.ArgumentParser(description='Comptes du catalogue par section, mode, hôte et forme de licence.'
                            ).parse_args(argv)
    lib.utf8_output()
    titles, sources, modes, hosts, forms = (collections.Counter() for _ in range(5))
    try:
        manifest = lib.read_manifest(lib.ROOT)
        for items in lib.read_data_files(lib.ROOT).values():
            for item in items:
                titles[item['section']] += 1
                for source in item['sources']:
                    sources[item['section']] += 1
                    modes[item['section'], source['mode']] += 1
                    hosts[(lib.web_address(source['uri']) or ('?',))[0].lower()] += 1
                    forms.update(licence_form(reference, item['section']) for reference in source['licence_references'])
        print('numéro d\'ordre %d ; révision %s ; export du %s' % (
            manifest['sequence'], manifest['revision'], manifest['generated_at']))
    except lib.UNREADABLE as error:
        print('comptes impossibles, catalogue illisible : %s' % error, file=sys.stderr)
        return 1
    print('section\tfiches\tsources\tdirect\tofficial_link')
    for section in lib.SECTIONS + ('total',):
        whole = section == 'total'
        row = [sum(titles.values()), sum(sources.values())] if whole else [titles[section], sources[section]]
        row += [sum(count for (name, mode), count in modes.items() if mode == wanted and section in (name, 'total'))
                for wanted in ('direct', 'official_link')]
        print('\t'.join([section] + [str(count) for count in row]))
    print('hôtes : %d, dont les %d premiers' % (len(hosts), min(len(hosts), HOSTS_SHOWN)))
    for host, count in sorted(hosts.items(), key=lambda pair: (-pair[1], pair[0]))[:HOSTS_SHOWN]:
        print('%d\t%s' % (count, host))
    print('formes de licence : %d' % len(forms))
    for form, count in sorted(forms.items(), key=lambda pair: (-pair[1], pair[0])):
        print('%d\t%s' % (count, form))
    return 0


if __name__ == '__main__':
    sys.exit(main())
