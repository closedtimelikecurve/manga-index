# Index — a local manga library manager

[中文](README.md) · [**English**](README.en.md) · [日本語](README.ja.md)

<p align="center">
  <img src="docs/screenshots/web-home.jpg" width="620" alt="Web panel — home">
  <img src="docs/screenshots/app-home.jpg" width="215" alt="Android app — home">
</p>

Browse by **circle**, get automatic **tags** (event / original / artist), search globally across tags,
confirm downloads into your library through an inbox, and keep reading progress in sync — with a
companion Android reader. Runs entirely on your machine: Flask API + plain HTML/JS, no cloud service.

> **For personal, local use only.** This project does not provide, host, or distribute any copyrighted
> content, and ships no site credentials. You are responsible for complying with the laws of your
> jurisdiction and the terms of service of any site you access.
>
> Covers and titles in the screenshots above are placeholders, not real library content.

## Features

- **Library scan** — reads `<circle>/<work>.zip|cbz|rar|cbr` or `<circle>/<work name>/images…`,
  parsing the usual `(C100) [circle (artist)] title (original) [translation]` naming convention;
  unrecognised entries land in a pending folder instead of being dropped
- **Metadata layer** — `meta.db` (SQLite) is the single source of truth for tags, reading progress,
  ratings, aliases and favourite artists, rather than guesses derived from file names
- **Inbox** — downloads land in `_inbox/`; confirm one and it is de-duplicated by sha1, renamed and
  filed into the right circle
- **Reading** — web reader plus Android app (offline packages, two-way progress sync, QR pairing,
  three image-quality modes)
- **External downloaders** — plug in any CLI downloader (gallery-dl and friends) via a command
  template; results are zipped into the inbox
- **Safe-covers mode** — one switch in the drawer replaces every cover with a placeholder, so
  screenshots and screen recordings never leak what is in your library

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 (primary target; the launcher, process management and LAN pairing are Windows-specific — Linux / macOS are untested) |
| Python | 3.10+ (CI runs 3.12 / 3.13) |
| Optional | [UnRAR](https://www.rarlab.com/rar_add.htm) or WinRAR — needed only for `.rar` / `.cbr`; put `unrar.exe` on `PATH`. Without it, rar works lose their cover and page list; other formats are unaffected |

## Quick start

```bat
pip install -r requirements.txt
copy config.example.json config.json
python app.py            :: http://127.0.0.1:8765 by default
```

The program and the library live in **separate directories**: the program sits in an `_app/`
subdirectory of the library root, and the library root defaults to its parent
(changeable in the web UI under Settings).

```
D:\my-library\          <- library root
├── CircleA (Artist)\
│   ├── (C100) [CircleA (Artist)] Title (Original).zip
│   └── Work folder\images…
└── _app\               <- this program
    ├── app.py
    ├── config.json     <- local config (token / library path); git-ignored, never commit it
    ├── meta.db         <- metadata (do not delete)
    ├── _inbox\         <- works awaiting confirmation
    └── _cache\ _logs\ _state\   <- runtime artefacts, safe to delete and rebuild
```

## External downloaders

Nothing is bound to a specific site — plug in the downloader you already use. In `config.json`:

```json
"ext_downloaders": [
  { "name": "gallery-dl", "cmd": "gallery-dl -d \"{dest}\" {url}", "timeout": 1800 }
]
```

Then in the web UI: *List downloader* → *External downloader*. Paste one URL per line (passed
verbatim as `{url}`); `{dest}` is a per-run staging directory. The result is zipped into the inbox,
ready to confirm.

## Bundled site adapters

This repository ships **one adapter**: JM direct download (`crawlers/crawl_jm_direct.py`), built on the
public [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python) library (`pip install jmcomic`).
Other adapters are not distributed here; the panel narrows its UI to whatever tasks are actually
available.

## Development

- Engineering rules and quantitative budgets: [`docs/engineering-discipline.md`](docs/engineering-discipline.md)
  — file length, function length and cyclomatic complexity are **machine-enforced** by
  `scripts/quality_gate.py` plus the test suite
- Architecture map: [`docs/architecture.md`](docs/architecture.md)
- Release history: [`CHANGELOG.md`](CHANGELOG.md)

```bat
pip install -r requirements.txt -r requirements-dev.txt
python scripts/quality_gate.py     :: engineering gate
python -m pytest tests/ -q         :: regression tests
python -m ruff check .             :: static checks (advisory)
git config core.hooksPath .githooks  :: optional: run the gate before each commit
```

## Known limitations

- **Single-user** by design: no accounts; the token only gates remote access (loopback is exempt)
- The phone must be on the same LAN, or on the same overlay network (Tailscale / ZeroTier, etc.)
- The first scan of a large library is slow; thumbnails are generated on demand
- `meta.db` is the single source of truth — back it up before upgrading

## Security

Please report vulnerabilities privately per [`SECURITY.md`](SECURITY.md) rather than opening a public
issue. That file also contains the threat model (token gate / LAN exposure / QR pairing / path
traversal / external downloaders).

## License

[GPL-3.0](LICENSE) · Copyright (C) 2026 Index contributors
