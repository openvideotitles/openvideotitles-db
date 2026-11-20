"""Shared rules of the catalogue scripts: canonical JSON, fingerprints, closed key lists, per-item rules,
manifest, withdrawals, atomic writes. Standard library only, no connection. Dates and addresses are read
by their own grammar, so that every Python gives the same verdict.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ('television', 'films', 'series', 'shorts')
SHARDED = ('shorts',)  # kept in 16 fragments, named by the first hex digit of sha256(id)
REQUIRED_KEYS = ('id', 'section', 'title', 'country', 'languages', 'duration_seconds', 'sources')
ITEM_KEYS = frozenset(REQUIRED_KEYS) | {'year'}
SOURCE_KEYS = frozenset(('mode', 'uri', 'territories', 'credits', 'licence_references', 'expires_at'))
MANIFEST_KEYS = frozenset(('counts', 'files', 'generated_at', 'revision', 'schema', 'sequence', 'territories',
                           'worldwide_clearance'))
MAX_FILE_BYTES = 1_000_000
DATA_FILE = re.compile(r'(?:television|films|series|shorts-[0-9a-f])\.json')
EXPORT_KEYS = frozenset(('schema_version', 'generated_at', 'territories', 'worldwide_clearance', 'counts',
                         'publication_state', 'items'))  # what convert.py reads in an export
STREAM = re.compile(r'(?i)\.m3u8?(?:$|[?#])|/manifest\.mpd|\.mpd(?:$|[?#])|\.ism[lc]?(?:/|$|[?#])|\.f4m(?:$|[?#])')
UNREADABLE = (OSError, ValueError, KeyError, TypeError, AttributeError)  # what a damaged tracked file raises
CONTROL = re.compile('[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]')
UNSEEN = re.compile('[\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb'  # never displayed
                    '\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e007f]')
ADDRESS = re.compile(r'https?://([^/?#@\s]*)((?:/[^?#\s]*)?)(?:\?[^#\s]*)?(?:#\S*)?')  # no credentials, no space
INSTANT = re.compile(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,6}))?'
                     r'(Z|[+-][0-9]{2}:[0-9]{2})')
LICENCE = re.compile(r'(domaine public \(pd_reason\) ; licence affichée par la source : )?'
                     r'(PDM|CC0-1\.0|CC-BY(-NC)?(-SA|-ND)?-[0-9]\.[0-9](-[A-Z]{2})?) https?://\S+'
                     r'( \(marqué (NC|ND|NC/ND)\))?')


def canonical(value):
    """Canonical JSON: sorted keys, no space, non-ASCII characters written as they are."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(ident):
    """sha256 of the UTF-8 bytes of an id: the fragment of a short, and the public name of a withdrawn title."""
    return sha256(ident.encode('utf-8', 'surrogatepass'))


def section_of(name):
    """Section of a data file, from its name."""
    return name.split('.')[0].split('-')[0]


def file_of(item):
    """Name of the data file an item belongs to."""
    section = item['section']
    return '%s-%s.json' % (section, fingerprint(item['id'])[0]) if section in SHARDED else section + '.json'


def data_file(section, items):
    """Bytes of a data file: one canonical item per line, sorted by the UTF-8 bytes of the id."""
    ordered = sorted(items, key=lambda item: item['id'].encode('utf-8', 'surrogatepass'))
    lines = ',\n'.join(canonical(item) for item in ordered)
    return ('{"schema":1,"section":"%s","items":[\n%s\n]}\n' % (section, lines)).encode('utf-8', 'surrogatepass')


def entry(name, data):
    """Manifest entry of a data file."""
    return {'bytes': len(data), 'section': section_of(name), 'sha256': sha256(data)}


def manifest_of(header, entries, counts, sequence):
    """The eight keys of the manifest. `header` gives generated_at, territories and worldwide_clearance."""
    return {'counts': {section: counts.get(section, 0) for section in SECTIONS}, 'files': entries,
            'generated_at': header['generated_at'], 'revision': sha256(canonical(entries).encode('utf-8')),
            'schema': 1, 'sequence': sequence, 'territories': header['territories'],
            'worldwide_clearance': header['worldwide_clearance']}


def manifest_bytes(manifest):
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + '\n').encode('utf-8')


def header_fault(header):
    """Why the values copied from the export header cannot be trusted, or None. Serves the export and the manifest."""
    territories = header.get('territories')
    if not (isinstance(territories, list) and all(isinstance(code, str) for code in territories)
            and {'CH', 'FR'} <= set(territories)):
        return 'CH ou FR absent de territories'
    if instant(header.get('generated_at')) is None or type(header.get('worldwide_clearance')) is not bool:
        return 'generated_at ou worldwide_clearance illisible'
    return None


def withdrawals_bytes(lines):
    """Bytes of retraits.json: one line per withdrawn title, sorted by fingerprint."""
    ordered = [canonical(line) for line in sorted(lines, key=lambda line: (line['sha256'], str(line.get('date'))))]
    return ('{"schema":1,"withdrawn":[\n' + ',\n'.join(ordered) + ('\n' if ordered else '') + ']}\n').encode('utf-8')


def read_manifest(root):
    """The tracked manifest, None when there is none. Raises one of UNREADABLE when it cannot order a revision."""
    path = root / 'catalogue' / 'manifest.json'
    if not path.exists():
        return None
    manifest = json.loads(path.read_bytes())
    sequence, revision = manifest.get('sequence'), manifest.get('revision')
    if type(sequence) is not int or sequence < 1 or not isinstance(revision, str) or header_fault(manifest):
        raise ValueError('catalogue/manifest.json illisible')
    return manifest


def read_withdrawals(root):
    """Lines of retraits.json; an absent file is an empty list. Raises one of UNREADABLE when damaged."""
    path = root / 'retraits.json'
    lines = json.loads(path.read_bytes())['withdrawn'] if path.exists() else []
    if not (isinstance(lines, list) and all(isinstance(line['sha256'], str) for line in lines)):
        raise ValueError('retraits.json illisible')
    return lines


def read_data_files(root):
    """{file name: items} for the data files of catalogue/. Raises one of UNREADABLE when one is damaged."""
    found = {}
    for path in sorted((root / 'catalogue').glob('*.json')):
        if DATA_FILE.fullmatch(path.name):
            found[path.name] = json.loads(path.read_bytes())['items']
            if not all(isinstance(item['id'], str) for item in found[path.name]):
                raise ValueError('catalogue/%s illisible' % path.name)
    return found


def atomic_write(path, data):
    """Write through a temporary file and a rename: a reader never sees half a file. Same bytes: nothing is done."""
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_name('.write-' + path.name)
    with open(str(draft), 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(draft), str(path))


def utf8_output():
    """Printed lines are UTF-8 on every machine, whatever the locale."""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def instant(text):
    """Aware datetime of an ISO 8601 date written with an offset, else None."""
    match = INSTANT.fullmatch(text) if isinstance(text, str) else None
    try:
        return match and dt.datetime.fromisoformat('%s.%s%s' % (
            match.group(1), (match.group(2) or '').ljust(6, '0'), match.group(3).replace('Z', '+00:00')))
    except ValueError:
        return None


def web_address(text):
    """(host, path) of an absolute http or https address without credentials, else None."""
    match = ADDRESS.fullmatch(text) if isinstance(text, str) and not CONTROL.search(text) else None
    authority = match.group(1) if match else ''
    host = authority[:authority.find(']') + 1] if authority.startswith('[') else authority.split(':')[0]
    return (host, match.group(2)) if host else None


def licence_fault(reference, section):
    """Why a licence reference breaks rule 5, or None."""
    if section == 'television':
        return None if web_address(reference) else 'référence de chaîne : adresse http ou https attendue'
    match = LICENCE.fullmatch(reference)
    if not match:
        return 'référence de licence hors de la grammaire : %s' % reference[:80]
    expected = '/'.join(mark for mark, present in (('NC', match.group(3)), ('ND', match.group(4) == '-ND')) if present)
    return None if (match.group(7) or '') == expected else 'marque NC/ND différente du code : %s' % reference[:80]


def texts(value):
    """True for a non-empty list of texts, each with something to read."""
    return isinstance(value, list) and bool(value) and all(
        isinstance(text, str) and UNSEEN.sub('', text).strip() for text in value)


def source_faults(source, section, now):
    """Deviations of one source from rules 2, 4, 5 and 6, as (rule, reason)."""
    if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
        return [(2, 'clés différentes des six clés d’une source')]
    found, address, territories = [], web_address(source['uri']), source['territories']
    if source['mode'] not in ('direct', 'official_link'):
        found.append((4, 'mode inconnu'))
    elif section == 'television' and source['mode'] != 'official_link':
        found.append((4, 'chaîne avec une source autre que official_link'))
    if address is None:
        found.append((4, 'uri : adresse http ou https absolue attendue, avec un hôte, sans identifiant'))
    elif STREAM.search(source['uri']):
        found.append((4, 'uri : adresse de flux ou de liste'))
    found += [(5, '%s : liste de textes non vides attendue' % key) for key in ('credits', 'licence_references')
              if not texts(source[key])]
    if texts(source['licence_references']):
        faults = (licence_fault(reference, section) for reference in source['licence_references'])
        found += [(5, fault) for fault in faults if fault]
    if not (isinstance(territories, list) and all(isinstance(code, str) for code in territories)):
        found.append((2, 'territories : liste de textes attendue'))
    elif not {'CH', 'FR'} <= set(territories):
        found.append((6, 'territories sans CH et FR'))
    if source['expires_at'] is not None and instant(source['expires_at']) is None:
        found.append((6, 'expires_at : date ISO 8601 avec décalage attendue'))
    elif source['expires_at'] is not None and now is not None and instant(source['expires_at']) <= now:
        found.append((6, 'expires_at dépassé'))
    return found


def fautes(item, now=None):
    """Deviations of one item from rules 2, 4, 5 and 6: a list of (rule, reason), empty for a sound item.
    The control gives no clock. The conversion gives `now`, and a source expired by then is a deviation too."""
    if not isinstance(item, dict):
        return [(2, 'fiche qui n’est pas un objet')]
    found = [(2, 'clé hors liste : %s' % key) for key in sorted(set(item) - ITEM_KEYS)]
    found += [(2, 'clé absente : %s' % key) for key in REQUIRED_KEYS if key not in item]
    ident, title, country, section = (item.get(key) for key in ('id', 'title', 'country', 'section'))
    languages, duration, sources = (item.get(key) for key in ('languages', 'duration_seconds', 'sources'))
    if not (isinstance(ident, str) and 0 < len(ident) <= 240 and not (CONTROL.search(ident) or UNSEEN.search(ident))):
        found.append((2, 'id : texte non vide de 240 caractères au plus, sans caractère de contrôle ni invisible'))
    if not (isinstance(title, str) and UNSEEN.sub('', title).strip()):
        found.append((2, 'title vide'))
    if section not in SECTIONS:
        found.append((2, 'section inconnue'))
    if not (country is None or isinstance(country, str) and re.fullmatch('[A-Z]{2}', country)):
        found.append((2, 'country : nul ou deux majuscules'))
    if not (isinstance(languages, list)
            and all(isinstance(code, str) and re.fullmatch('[a-z]{2,3}', code) for code in languages)):
        found.append((2, 'languages : liste de codes de 2 ou 3 minuscules'))
    if not (duration is None or type(duration) is int and 1 <= duration <= 604_800):
        found.append((2, 'duration_seconds : nul ou entier de 1 à 604 800'))
    if item.get('year') is not None and not (type(item['year']) is int and 1880 <= item['year'] <= 2100):
        found.append((2, 'year : nul ou entier de 1880 à 2100'))
    if not (isinstance(sources, list) and sources):
        found.append((2, 'sources : liste non vide attendue'))
    for number, source in enumerate(sources if isinstance(sources, list) else [], 1):
        found += [(rule, 'source %d : %s' % (number, reason)) for rule, reason in source_faults(source, section, now)]
    if re.search('[\ud800-\udfff]', canonical(item)):
        found.append((2, 'texte impossible à écrire en UTF-8'))
    return found
