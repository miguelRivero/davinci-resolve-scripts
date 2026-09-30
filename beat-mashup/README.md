# Beat mashup for DaVinci Resolve

`beat_mashup.py` randomly slices videos from a Media Pool **bin** and cuts them to a song, ready to export as a music video.

- Each cut starts on a beat and lasts 1, 2, or 4 beats, chosen at random with weights 45 / 35 / 20. 2- and 4-beat cuts only start where they fit the bar, so you get more 1-beat cuts in practice.
- You type the BPM or it is detected from the song in the Media Pool. The first beat is detected as well.
- The same video is never used twice in a row, and the script tries not to reuse the same stretch of a clip.
- Each run is a different edit. To repeat one, reuse its seed.

How to clone **this repository**, install Python, and copy the `.py` into Resolve: [root README](../README.md). That file also covers **Workspace → Scripts** and the Console.

## Your FX are kept

The script only rewrites **V1** (cuts) and **A1** (the song) on **its** timeline, named *Beat mashup* by default. Put filters on **adjustment clips on V2 or above**, and titles, overlays, or extra sound on V2+ / A2+. Regenerating leaves those (and your markers) in place.

Do not put effects on the V1 cuts themselves: they are rebuilt every run.

The timeline has a cream marker named *Beat mashup* with the BPM and seed. The script uses it to recognize its own timeline. If you delete that marker, it will not touch that timeline again. It never edits a timeline with the same name that it did not create.

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
3. Optional: **ffmpeg** on PATH, to detect BPM from MP3, M4A, or AIFF. WAV does not need it. If ffmpeg is not on PATH, set its path in `CONFIG['ffmpeg']`.
4. Optional: `pip install numpy` (Windows) or `python3 -m pip install numpy` (macOS), which speeds up analysis.
5. Quit and reopen Resolve. The script appears under **Workspace → Scripts → beat_mashup**.

## Use it in DaVinci Resolve

1. Open a project. In the Media Pool, create a **bin** with the videos to mash up and **open / select that bin** (it must be the current folder).
2. Import the song into the Media Pool. It can live in that bin or anywhere else in the pool.
3. **Workspace → Scripts → beat_mashup**. An options window appears; if your Resolve build does not show it, the script uses `CONFIG` at the top of the file.
4. Review the *Beat mashup* timeline, add FX on V2+, export from **Deliver**.
5. Do not like the edit? Run the script again: cuts change, your FX stay.

Logs and detected BPM: **Workspace → Console**.

Do not run `beat_mashup.py` from the terminal for a normal edit. Resolve must be running with a project open.

## Options

| Option | What it does |
|---|---|
| BPM | `0` = detect from the song. If you get half or double the real tempo, type it here. |
| First beat (s) | `-1` = detect. Seconds from the start of the song to the first beat. |
| Bar shift | `-1` = guess. If long cuts start on beat 2, 3, or 4 of the bar instead of 1, try 1, 2, or 3. |
| Duration | `0` = length of the song (60 s if there is no song). |
| 1/2/4-beat weights | Mix of cut lengths. `0` drops a type; 4 only = one cut per bar. |
| Seed | Empty = random. The one used is in the Console and the cream marker; type it to repeat an edit. |
| Marker every N bars | Blue markers to place FX on time (`0` = none). |
| Timeline | Timeline name. Use another name for several versions at once, each with its own FX. |
| Avoid repeating stretches | Try not to use the same part of a video twice. |

`CONFIG` also has: `audio_clip` (which song if there are several), `include_subfolders`, `tempo_range` (BPM range when detecting), and `show_dialog`.

## Limits

- Tested against a **simulation** of Resolve’s scripting API, not inside Resolve. In the simulation, cuts were gapless, always within ±1 frame of the beat, with mixed frame rates, and V2+ tracks and your own markers survived regenerate. The options window was only tried against a stand-in for Resolve’s UI.
- Needs a Resolve build that honors `recordFrame` in `AppendToTimeline` (current versions do). If not, the script stops with a warning and removes what it added.
- Tempo detection assumes a **constant tempo**. On test tracks at 87, 100.5, 120, 128, and 140 BPM it matched tempo (at most 0.01 BPM off) and the first beat (about 5 ms error). At 174 BPM (drum and bass) it reported 87, half, the usual octave error; cuts still land on time, but every 2 beats. If that happens, type the BPM. Downbeat is a guess: if long cuts look shifted, use *Bar shift*.
- Only video from the clips is used; their original audio is not in the edit.
- If clips have a different frame rate than the timeline, a cut may sit one frame early or late. The next cut corrects it, so the error does not accumulate.
