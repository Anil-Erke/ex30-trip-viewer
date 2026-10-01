# EX30 Trip Viewer

**English** · [Türkçe](README.tr.md)

A Windows desktop app that turns the trips recorded by a **Volvo EX30** (with the
in-car app [EX30 Telemetry](https://github.com/Anil-Erke/ex30-telemetry)) into
charts, tables and route maps. Python + Tkinter + matplotlib; no installer, runs
straight from the folder.

> **Unofficial project.** Not affiliated with, endorsed by or supported by Volvo
> Cars. "Volvo" and "EX30" are trademarks of their respective owners and are used
> here only to describe compatibility. The software is provided **"as is",
> without warranty of any kind**; values shown are estimates.

![Overview](screenshots/en-overview.png)

<p>
  <img src="screenshots/en-consumption.png" width="420" alt="Consumption tab">
  <img src="screenshots/en-battery-range.png" width="420" alt="Battery and range tab">
</p>

<sub>Screenshots use the sample data shipped in this repository (`ornek/trips-ornek.txt`).</sub>

The data can come from two places:

- **Google Drive (recommended):** EX30 Telemetry uploads every trip to your own
  Drive; sign in here with the same Google account and press **From Drive**. GPS
  tracks come too (Route tab). See [From Google Drive](#from-google-drive).
- **File:** EX30 Telemetry's *Export* button writes `trips.json` on the car as
  `trips-YYYYMMDD-HHMM.txt`; move it to your PC and open it with *Add files*.

## Before you build: things you must fill in

**Nothing** for reading files and the sample data. Only **Google Drive** needs
your own Google Cloud OAuth client:

| What | Where | Required? |
|---|---|---|
| OAuth client of type *Desktop app* | `oauth.properties`, keys `desktopClientId` and `desktopClientSecret` | Yes for Drive; also for building the exe (`exe-olustur.ps1` embeds the client) |

Create it in the **same Google Cloud project** as the car app's client; a client
in another project cannot see the files the car uploaded. Step-by-step setup: the
EX30 Telemetry README,
[Google Drive sync](https://github.com/Anil-Erke/ex30-telemetry#google-drive-sync-optional).
You can start from its `oauth.properties.example`.

Put `oauth.properties` in this project's root, or point to it with the
`EX30_OAUTH_PROPERTIES` environment variable. `oauth.properties` and the
`ex30trips/_oauth.py` generated from it are in `.gitignore`: **never commit them.**

## What it shows

**Left column:** a summary of the filtered set (trips, distance, driving time,
average consumption, net energy, regen, average speed, range bias) and the trip
table. Click a column header to sort, double-click a row to open its details.

**Tabs**

| Tab | Contents |
|---|---|
| Overview | Daily distance + cumulative total, consumption by outside temperature, trip length distribution |
| Consumption | kWh/100 km per trip, consumption vs. average speed, consumption vs. outside temperature |
| Energy | Net + regen = gross stacked bars, regen share, regen vs. descent |
| Battery & range | State of charge start → end per trip, range indicator bias, range drop vs. real distance |
| Speed & elevation | Average vs. max speed, elevation gain/loss, GPS vs. wheel distance |
| Trip details | Every field of the selected trip, its performance records and GPS track status |
| Route | The selected trip's GPS track: route drawing, elevation profile, speed and power |

The selected trip is highlighted in every chart. Charts can be zoomed and panned;
*File → Save chart as PNG* saves the visible tab. *File → Export table to CSV*
writes the filtered set (UTF-8 with BOM, opens correctly in Excel).

### Route tab

The track is downloaded when the trip details or the Route tab are opened (not for
every row while browsing the list) and kept in the account's cache. Trips without
a track (before EX30 Telemetry 0.7.2, or driven without GPS) show "no track".
A track needs a connected Google account.

- **Route:** latitude/longitude; the line is coloured by speed, power or
  altitude. The power scale is two-sided: zero in the middle, regen (negative)
  green, consumption orange → red. No map tiles, only matplotlib; the aspect ratio
  is corrected for latitude.
- **Elevation profile:** raw GPS altitude plus a 15-point moving average (missing
  points are skipped, not counted as zero).
- **Speed** (speedometer + GPS) and **power**, with regen zones in green.

The three profiles share the same x axis (distance, km) and are **linked**: zoom
one and the others follow, and the range is highlighted on the route.
*File → Export track to CSV…* writes the selected trip's track.

## Run

Requires **Python 3.10+** on Windows (Tkinter is included with the python.org
installer).

```powershell
py -3 -m pip install -r requirements.txt   # matplotlib (brings numpy)
py -3 -m ex30trips                          # or double-click calistir.bat
py -3 -m ex30trips "C:\path\trips-20260915-0909.txt"
py -3 -m ex30trips "C:\Downloads"          # load every export in a folder
py -3 -m ex30trips --lang en
```

Use **Sample data** in the toolbar to try it without a car. Google sign-in, Drive
and the route map add no dependencies: they use the standard library only
(`urllib`, `http.server`, `ctypes` for DPAPI).

### Sources accumulate

*Add files*, *Add folder*, *Sample data* and *From Drive* add to what is already
loaded. The same trip appearing in several sources is counted once (matched by
`startEpoch`; the copy with the newer schema and more fields wins). An unreadable
file does not break the whole load. *Clear* drops everything, *File → Loaded
sources…* removes one source, **F5** reloads all from disk.

## From Google Drive

EX30 Telemetry uploads each trip, when it ends, to **the Drive of the Google
account connected in the car**: a **summary** and a **1 Hz GPS track** as separate
files. There is no server in between; every user signs in with their own account.
**From Drive** (Ctrl+D) downloads the new summaries from that account's Drive and
adds them to the loaded sources. The protocol is specified in the EX30 Telemetry
repository: [drive-sync/PROTOCOL.md](https://github.com/Anil-Erke/ex30-telemetry/blob/main/drive-sync/PROTOCOL.md)
(**version 3**); its counterpart here is `ex30trips/drive.py` (Drive REST) and
`ex30trips/auth.py` (Google sign-in).

### Google account

*File → Google account…* shows the connected e-mail and has **Sign in** and
**Sign out**. If no account is connected, *From Drive* opens this window first and
continues downloading after sign-in.

- Sign-in happens in the browser with the *Desktop app* OAuth client, **loopback +
  PKCE** (`http://127.0.0.1:<random port>`). The account chooser is shown every
  time, so someone else can sign in with their own account on the same PC.
- Scope: **only `drive.file`** (+ `openid email` to show which account). The app
  sees only the files created by the EX30 clients of the same Cloud project, not
  the rest of your Drive. **It never writes to Drive.**
- **Consent checkbox trap:** Google's consent screen lets you leave the Drive box
  unticked; sign-in then looks successful but every Drive call returns 403. If the
  token's `scope` has no `drive.file`, sign-in is rejected with a message to tick
  the Drive box. The same check runs on every token refresh.
- The refresh token is stored in `%LOCALAPPDATA%\EX30TripViewer\hesap.json`,
  **encrypted with DPAPI** (bound to your Windows account; copying the file to
  another user or PC is useless). The access token lives only in memory.
- **Sign out** deletes the token (and revokes it at Google), deletes that
  account's cache and cursor, and removes the Drive source loaded from it. Files in
  Drive are not touched; signing in again downloads everything again.

### Incremental sync

- Drive REST v3 `files.list` with
  `appProperties has { key='ex30' and value='trip' } and trashed=false and createdTime > '<cursor − 5 min>'`,
  paged until `nextPageToken` runs out. Files are found by `appProperties`, not by
  path or name, so moving or renaming them in Drive does not break anything.
- The **cursor** is the largest `createdTime` seen, i.e. when a file was **added
  to Drive**, not when the trip happened: an old trip the car uploads days later
  still arrives. Duplicates from the 5-minute overlap are removed by `ex30id`.
- Each missing summary is downloaded as raw bytes (four requests in parallel) and
  **verified with `md5Checksum`**; on mismatch nothing is written.
- **The cursor only moves forward when everything in the listing was
  downloaded.** The next *From Drive* retries only what is missing.
- **Gap check:** on the first sync, **at least once a day** and with
  *File → Rescan Drive*, a full listing without cursor is fetched and anything
  missing locally is downloaded.
- Errors are judged by HTTP status: 401 → refresh the token and retry once ·
  403 `insufficientPermissions` → sign in again · 429 / rate limit / 5xx → back off
  1, 2, 4 s · 404 → the file is gone. Drive's own error message is shown as is.
- Tracks are **not** downloaded during sync; only their Drive IDs are remembered.

### Migrating from the Apps Script version

Older versions of this app read Drive through an Apps Script endpoint (URL + read
key). On first start the old settings (`drive.json`), cursor and cache are deleted
**once** and a short note is shown; nothing in them is lost, because the car sends
all its trips to Drive when an account is connected. The language setting stays.

### Cache

Per account, under `%LOCALAPPDATA%\EX30TripViewer\`:

| Path | Contents |
|---|---|
| `hesap.json` | connected account's e-mail + DPAPI-encrypted refresh token |
| `hesaplar\<e-mail>\esitleme.json` | cursor (`createdTime`), last full scan, Drive IDs of trips with a track |
| `hesaplar\<e-mail>\yolculuklar\<yyyy>\<MM>\trip-<e>.json` | summaries, same year/month layout as `EX30 Trips/yolculuklar/` in Drive (Istanbul time) |
| `hesaplar\<e-mail>\yolculuklar\<yyyy>\<MM>\trip-<e>.csv.gz` | GPS tracks, byte for byte as in Drive |
| `settings.json` | UI language |

Files never change in Drive, so each is downloaded once. Writes go to a `.part`
file first. The Drive source is the account's whole `yolculuklar\` folder, so the
full history opens with **F5** even offline.

### OAuth client

The desktop client ID and secret **never go into the repository**. They are read
from `oauth.properties`. When building the exe, `araclar\oauth-gom.py` writes them
into `ex30trips\_oauth.py` (in `.gitignore`), which goes into the exe. When running
from source without `_oauth.py`, `oauth.properties` is read directly: from the
`EX30_OAUTH_PROPERTIES` environment variable, the project root, or a sibling folder
named exactly `EX30 Telemetry\` (a GitHub clone called `ex30-telemetry` is not
searched). For desktop apps Google does not treat these values as secret; on their
own they give no access to anyone's data.

The consent screen in Cloud Console must be **"In production"**: in "Testing"
status refresh tokens expire after 7 days.

## Language

English and Turkish. Choose from the **Dil / Language** menu; the switch is
instant and remembered. Numbers, dates, units and the CSV format follow the
selected language (`1,234.5` / `1.234,5`, `,` / `;` separator). Strings live in
`ex30trips/lang/en.py` and `lang/tr.py`; a test keeps the two tables in sync.

## Build a standalone exe

```powershell
.\exe-olustur.ps1              # one-file exe in dist\ (~39 MB)
.\exe-olustur.ps1 -Klasor      # folder mode: starts instantly
.\exe-olustur.ps1 -TestleriAtla  # skip tests
.\exe-olustur.ps1 -Temizle     # delete build/, dist/, *.spec
```

The script finds Python, installs missing dependencies, **runs the unit tests
(no exe if they fail)**, generates the icon, embeds the Google OAuth client
(`araclar\oauth-gom.py` → `ex30trips\_oauth.py`; **the build stops if
`oauth.properties` is not found**) and packages with PyInstaller.
`exe-olustur.bat` runs it with a double-click. The script is saved as UTF-8
**with BOM**; keep it that way, Windows PowerShell 5.1 needs it for non-ASCII text.

## Data decisions

Definitions match the in-car app (`TripStats.kt`, `RangeAuditor.kt`):

- **Average consumption is energy-weighted**, so a 2 km trip does not count as
  much as a 200 km one.
- **Range bias is distance-weighted** and only uses trips ≥ 5 km, because the
  car's range value changes in 1 km steps.
- `energyKwh` is **net** (used − regenerated); gross = net + regen.
- Bias above 1.0 means the range indicator was optimistic, below 1.0 pessimistic.
- **Missing values are not turned into zero.** They show as "—", are not drawn and
  are left out of averages.

## Tests

```powershell
py -3 -m unittest discover -s tests
```

None of the tests touch the network. `FakeDrive` is an in-memory stand-in for the
read side of Drive REST v3: it parses the real client's request URLs and `q`
queries and returns real JSON bodies. Covered: reading the sample file, missing
fields, schema compatibility, merging and de-duplication, weighted averages; Drive
paging, cursor overlap, MD5 checks, 401/403/429 handling, the daily full scan;
browser sign-in with loopback + PKCE, rejecting a sign-in without the Drive scope,
DPAPI storage, `invalid_grant`; migration from the Apps Script version; GPS track
parsing; both languages; and that every chart, including the route, actually
renders to PNG in both languages with full and empty data.

## Layout

```
ex30trips/
  model.py    Trip / PerfRecord (Python twin of trip/Trip.kt)
  loader.py   file reading, folder scan, merging / de-duplication
  drive.py    Drive protocol 3: REST layer, incremental sync, account cache, track download
  auth.py     Google sign-in: loopback + PKCE, DPAPI token, refresh, sign-out
  track.py    GPS track parsing + track CSV
  stats.py    totals; same definitions as TripStats.kt
  charts.py   matplotlib drawing, including the route (no Tkinter dependency)
  theme.py    one palette for ttk + matplotlib
  i18n.py     language selection, t(), number/date/duration/CSV formats
  lang/       tr.py + en.py string tables
  settings.py persistent preferences (language)
  app.py      Tkinter window
main.py       PyInstaller entry point
araclar/      icon generator, environment check, oauth-gom.py (embeds the OAuth client)
assets/       icon
ornek/        sample export from a car (trip summaries only, no location)
screenshots/  README images
tests/        unit tests
```

Code comments and some file names are in Turkish.

## License

Copyright (C) 2026 Anıl Erke

This program is free software: you can redistribute it and/or modify it under the
terms of the **GNU General Public License** as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version
(`GPL-3.0-or-later`).

This program is distributed in the hope that it will be useful, but **WITHOUT ANY
WARRANTY**; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the full text in [LICENSE](LICENSE).

In short: you may use, study, modify and share this code. If you distribute a
modified version (including publishing it on an app store), you must release its
source code under the same license.
