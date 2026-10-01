# Beat mashup for DaVinci Resolve

`beat_mashup.py` randomly slices videos from a Media Pool **bin** and cuts them to a song, ready to export as a music video.

- Cut length is a range you set (default 1–4 beats). All valid beat counts in the range (1, 2, 4) get equal probability. 2- and 4-beat cuts only start where they fit the bar.
- Optionally each cut point is **snapped to the nearest loud transient** (snare, clap, kick hit) within a half-beat window, so edits feel tighter to the music rather than just mathematically on-grid.
- You type the BPM or it is detected from the song in the Media Pool. The first beat is detected as well.
- The same video is never used twice in a row, and the script tries not to reuse the same stretch of a clip.
- Each run is a different edit. To repeat one, reuse its seed.

How to clone **this repository**, install Python, and copy the `.py` into Resolve: [root README](../README.md). That file also covers **Workspace → Scripts** and the Console.

## Your FX are kept

The script only rewrites **V1** (cuts) and **A1** (the song) on **its** timeline, named *Beat mashup* by default. Put filters on **adjustment clips on V2 or above**, and titles, overlays, or extra sound on V2+ / A2+. Regenerating leaves those (and your markers) in place.

Do not put effects on the V1 cuts themselves: they are rebuilt every run.

The timeline has a cream marker named *Beat mashup* with the BPM and seed. The script uses it to recognise its own timeline. If you delete that marker, it will not touch that timeline again. It never edits a timeline with the same name that it did not create.

## Install

1. Install **64-bit Python 3** from [python.org](https://www.python.org/downloads/) if you do not have it. Resolve needs it to run `.py` scripts from the menu.
2. In the **root of this repository** (`davinci-resolve-scripts/`, the folder that contains `tools/` and `beat-mashup/`), not in the Resolve scripts folder:

   **Windows (PowerShell)**

   ```powershell
   cd path\to\davinci-resolve-scripts
   python tools\install.py
   ```

   **macOS (Terminal)**

   ```sh
   cd /path/to/davinci-resolve-scripts
   python3 tools/install.py
   ```

   That copies `beat-mashup/beat_mashup.py` into the **Resolve scripts folder**, Utility menu:

   | OS | Destination |
   |---|---|
   | Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\beat_mashup.py` |
   | macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/beat_mashup.py` |

   You can copy `beat_mashup.py` there by hand instead.

3. **Optional – ffmpeg**, required to detect BPM from non-WAV files (MP3, FLAC, M4A/AAC, AIFF, OGG, OPUS, WMA …). WAV works without it.
   - Install ffmpeg from [ffmpeg.org](https://ffmpeg.org/download.html) and make sure it is on your system PATH (`ffmpeg -version` should work in a terminal).
   - Or set `ffmpeg = C:\path\to\ffmpeg.exe` in `beat_mashup.cfg` if you prefer not to touch PATH.

4. Optional: `pip install numpy` (Windows) or `python3 -m pip install numpy` (macOS), which speeds up analysis.
5. Quit and reopen Resolve. The script appears under **Workspace → Scripts → beat_mashup**.

## Configuration

All settings are in **`beat_mashup.cfg`**, which lives in the same folder as `beat_mashup.py`. Open it in any text editor, change what you need, and re-run the script — no restart required. The file is heavily commented.

If the file does not exist the script uses its built-in defaults (same as the defaults documented below).

### Options

| Option | Default | What it does |
|---|---|---|
| `bpm` | `0` | `0` = detect from the song. If you get half or double the real tempo, type it here. |
| `first_beat` | `-1` | `-1` = detect. Seconds from the start of the song to the first beat. |
| `bar_shift` | `-1` | `-1` = guess. If long cuts start on beat 2, 3, or 4 of the bar instead of 1, try 1, 2, or 3. |
| `tempo_range` | `70, 180` | BPM range searched during auto-detection. |
| `min_beats` | `1` | Minimum cut length in beats (1, 2, or 4). |
| `max_beats` | `4` | Maximum cut length in beats (1, 2, or 4). All valid counts in range get equal weight. |
| `snap_to_hits` | `true` | Nudge each beat-grid boundary to the nearest loud transient within ±half a beat. |
| `hit_threshold` | `0.35` | Fraction of the track's loudest onset. Only boundaries near a hit above this level are snapped. `0` snaps everything; `1` snaps nothing. |
| `duration` | `0` | `0` = length of the song (60 s if there is no song). |
| `seed` | *(empty)* | Empty = random. The one used is in the Console and the cream marker; paste it to repeat an edit. |
| `markers_every_bars` | `4` | Blue markers every N bars (`0` = none). |
| `timeline_name` | `Beat mashup` | Timeline name. Use another name to keep several versions at once. |
| `avoid_reuse` | `true` | Try not to use the same part of a video twice. |
| `audio_clip` | *(empty)* | Which song if there are several in the pool. Empty = first one found. |
| `include_subfolders` | `false` | Also look in subfolders of the current bin. |
| `ffmpeg` | *(empty)* | Full path to `ffmpeg` if it is not on PATH. |
| `show_dialog` | `true` | Show the options dialog before generating (only in Resolve builds that expose UIManager). |

### Cut length range

`min_beats` and `max_beats` control how long each video cut is. The valid values are **1, 2, and 4** beats (the ones that divide a 4/4 bar evenly). Any valid count between `min_beats` and `max_beats` gets equal random weight:

| `min_beats` | `max_beats` | Effect |
|---|---|---|
| 1 | 4 | Mix of 1-, 2-, and 4-beat cuts (default – varied feel) |
| 1 | 2 | Only 1- and 2-beat cuts (fast, choppy) |
| 2 | 2 | Every cut exactly 2 beats (uniform) |
| 4 | 4 | Every cut exactly one bar (slow, deliberate) |

### Transient snapping

When `snap_to_hits = true`, the script moves each computed beat boundary to the nearest loud onset (snare, clap, kick, cymbal) within a half-beat window. This makes cuts feel physically on the hit rather than just mathematically on-grid.

`hit_threshold` controls how selective the snapping is:

- **0.0** – snap every boundary regardless of the local loudness
- **0.25** – snap unless the surrounding audio is very quiet
- **0.35** *(default)* – snap only where hits are clearly present
- **0.60** – snap only on the loudest hits in the whole track
- **1.0** – effectively disables snapping (same as `snap_to_hits = false`)

Snapping requires audio analysis, so the song must be in the Media Pool. The number of snapped boundaries is reported in the Console and in the cream marker note.

### Supported audio formats

| Format | Needs ffmpeg? |
|---|---|
| WAV (any bit depth) | No |
| MP3 | Yes |
| FLAC | Yes |
| M4A / AAC | Yes |
| AIFF | Yes |
| OGG / Vorbis | Yes |
| OPUS | Yes |
| WMA | Yes |
| Any other ffmpeg-supported container | Yes |

## Limits

- Tested against a **simulation** of Resolve's scripting API, not inside Resolve. In the simulation, cuts were gapless, always within ±1 frame of the beat, with mixed frame rates, and V2+ tracks and your own markers survived regenerate. The options window was only tried against a stand-in for Resolve's UI.
- Needs a Resolve build that honours `recordFrame` in `AppendToTimeline` (current versions do). If not, the script stops with a warning and removes what it added.
- Tempo detection assumes a **constant tempo**. On test tracks at 87, 100.5, 120, 128, and 140 BPM it matched tempo (at most 0.01 BPM off) and the first beat (about 5 ms error). At 174 BPM (drum and bass) it reported 87, half, the usual octave error; cuts still land on time, but every 2 beats. If that happens, type the BPM. Downbeat is a guess: if long cuts look shifted, use `bar_shift`.
- Only video from the clips is used; their original audio is not in the edit.
- If clips have a different frame rate than the timeline, a cut may sit one frame early or late. The next cut corrects it, so the error does not accumulate.
- Transient snapping can push a cut slightly off the beat grid. If you prefer strict grid alignment, set `snap_to_hits = false`.
