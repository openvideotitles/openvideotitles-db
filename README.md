# Catalogue

This repository is a list of titles: television channels, films, episodes and short films. Each entry gives the title and one or more sources, and also the country, the languages and the duration when they are known. A source is either a video file made available by its host, or the official page where the title can be watched. It carries the credit and the licence reference found at that address.

**Everything listed here is free to watch and to share legally: every film, episode and short film is in the public domain or released by its own rights holder under an open licence (Creative Commons), and every channel links only to its broadcaster's own official live page. Each entry carries its licence and credit; reuse must follow them.**

The videos stay with their host; the repository only keeps their address. For a channel, the entry points to its broadcaster's live page.

## Files

The entries are in `catalogue/`, one per line, sorted by identifier. `television.json`, `films.json` and `series.json` each hold one section. Short films are split across sixteen files, from `shorts-0.json` to `shorts-f.json`, by the first digit of the sha256 of their identifier.

`catalogue/manifest.json` gives each file's size and sha256, then the number of entries per section, a revision computed over the whole set, and a sequence number that increases with every change.

`retraits.json` lists the titles withdrawn for good. It only holds the sha256 of the identifier and the date of the withdrawal.

## Checking

Python 3.9 or later is required. The scripts only use the standard library and open no network connection.

```
python3 -I -B scripts/check.py
python3 -I -B -m unittest discover -s tests
```

`check.py` reads the whole repository again and prints one line per problem, for example an unexpected file, a stream address, a missing credit or licence, or a withdrawn title still present. It exits with code 1 as soon as it finds one.

After each clone, enable the hook that runs this check before a push.

```
git config core.hooksPath .githooks
```

The hook checks every outgoing commit, one by one. It also refuses a push that would discard commits the remote already has, even with `--force`. Git does not enable it by itself, and without this command a push goes out unchecked. If the environment variable `CATALOGUE_PRIVATE_CHECK` holds a command, the hook also runs it on each commit, then on the repository folder.

The check compares bytes, so git must not convert line endings on checkout. If `git config core.autocrlf` returns `true`, as is common on Windows, clone with `git clone -c core.autocrlf=false <address>`.

## Updating

```
python3 -I -B scripts/convert.py <export.json>
python3 -I -B scripts/withdraw.py <identifier>
python3 -I -B scripts/publish.py
python3 -I -B scripts/stats.py
```

`convert.py` rewrites `catalogue/` from an export file. A faulty or withdrawn entry is left out and listed; the others are written. `withdraw.py` withdraws a title for good. `publish.py` writes the `publication/` folder, which git does not track. Once the repository has a commit, it only publishes what is committed. `stats.py` prints the counts.

## Asking for a withdrawal

If you are the author or rights holder of a title listed here, or if you represent a broadcaster, you can ask for it to be taken out of the catalogue. Write to shideneyu@gmail.com with the title and the address concerned. `NOTICE.md` says how the request is handled. A withdrawn title is recorded in `retraits.json` and the conversion no longer takes it back.

## Licences

The data in this repository, that is the choice of entries and their arrangement into files, is under CC0 1.0 (`LICENSE`). The scripts are under 0BSD (`LICENSE-CODE`). Each title keeps the licence and credit written in its entry, and the repository's two licences do not apply to the works. `NOTICE.md` gives the details.

## Integration

`publish.py` writes `publication/catalog/manifest.json` and `publication/catalog/<revision>/<file>.json`, byte-for-byte copies of the files in `catalogue/`.

Served as is over HTTPS, this folder is the remote publication. The base address is the one ending in `/catalog`. An application reads `<base>/manifest.json`, then `<base>/<revision>/<file>`, and checks each file's size and sha256. It only adopts a manifest whose sequence number (`sequence`) is greater than the one it holds. This is what stops an older copy from bringing back a withdrawn title.

Given to an application's build, the same folder is the embedded seed. The property `-Pcatalogue.seedDir=<path>/publication` gives the folder, and `-Pcatalogue.url=<base>` the address of the remote publication.

The schema is number 1. An entry has the keys `id`, `section`, `title`, `country`, `languages`, `duration_seconds` and `sources`. The schema also allows `year`, which current entries do not carry. A source has the keys `mode` (`direct` for a video file, `official_link` for a page to open), `uri`, `territories` (the countries for which the source was checked), `credits`, `licence_references` and `expires_at`.
