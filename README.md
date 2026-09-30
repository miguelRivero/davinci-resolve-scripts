# DaVinci Resolve scripts

This **Git repository** (`davinci-resolve-scripts`) holds Python scripts that automate DaVinci Resolve. It is **not** Resolve’s scripts folder: you edit code here; an installer **copies** each `.py` into Resolve.

Each script lives in **its own folder in this repository**, with its own README. Resolve never reads those folders; it only sees the copied `.py`.

| Folder in this repository | What it does |
|---|---|
| [beat-mashup](beat-mashup/) | Randomly slices videos from a Media Pool bin and cuts them to a song (BPM you type or detected from audio). It only rewrites V1 and A1, so FX on V2+ survive when you regenerate. |

## Three places that are easy to mix up

| Name | What it is | Example |
|---|---|---|
| **This repository** | The Git clone that contains this README | `…/davinci-resolve-scripts/` |
| **Script folder** | A subfolder of this repository (source) | `davinci-resolve-scripts/beat-mashup/` |
| **Resolve scripts folder** | Where Resolve loads **Workspace → Scripts**. The installer copies the `.py` here | see the path table under Install |

```
davinci-resolve-scripts/          ← this repository (Git)
├── README.md
├── tools/install.py              ← copies .py files into Resolve
├── _template/                    ← starter (not installed)
└── beat-mashup/                  ← script folder
    ├── README.md
    └── beat_mashup.py            ← this file is what Resolve runs
```

## Requirements

### To run any `.py` from Resolve’s Scripts menu

DaVinci Resolve does **not** run the copy of Python you might use in a terminal by itself. For **Workspace → Scripts** it looks for a **64-bit Python 3** install and executes the `.py` that was copied into the Resolve scripts folder.

1. Install DaVinci Resolve.
2. Install **64-bit Python 3** from [python.org](https://www.python.org/downloads/). On Windows, check **Add python.exe to PATH**.
3. Confirm the terminal sees Python:

**Windows (PowerShell or Command Prompt)**

```bat
python --version
```

If `python` is missing, try `py --version`.

**macOS (Terminal)**

```sh
python3 --version
```

Without this, the installer can still copy files, but Resolve will not run them.

### To clone this repository and install from it

You need **Git** to clone, and the same Python on your PATH so you can run `tools/install.py` from **this repository** (that script only copies files; it is not what Resolve executes later).

### Extra tools some scripts need

A script may need **ffmpeg**, **numpy**, and so on **when it runs inside Resolve**. That is listed in that **script folder’s** README, not here.

## Clone this repository

Replace the URL if you use a different remote. The last argument is the local folder name of the clone.

**Windows (PowerShell)**

```powershell
cd $HOME\Documents
git clone https://github.com/miguelRivero/davinci-resolve-scripts.git
cd davinci-resolve-scripts
```

**macOS (Terminal)**

```sh
cd ~/Documents
git clone https://github.com/miguelRivero/davinci-resolve-scripts.git
cd davinci-resolve-scripts
```

You must be **inside `davinci-resolve-scripts`** (the folder that contains `tools/` and `beat-mashup/`) for the next step. Do **not** use the Resolve scripts folder as your working directory.

## Install into DaVinci Resolve

From the root of **this repository**, the installer copies each `.py` (for example `beat-mashup/beat_mashup.py`) into a submenu of the **Resolve scripts folder** (`Utility`, `Edit`, and so on, from the file header).

**Windows (PowerShell)** — from the root of this repository:

```powershell
cd path\to\davinci-resolve-scripts
python tools\install.py
```

**macOS (Terminal)** — from the root of this repository:

```sh
cd /path/to/davinci-resolve-scripts
python3 tools/install.py
```

Installer flags (on macOS use `python3` if `python` is missing):

```sh
python tools/install.py --list        # print what would be copied; write nothing
python tools/install.py --uninstall   # delete those .py files from the Resolve scripts folder
```

Default destination (**Resolve** scripts folder, not this repository):

| OS | Resolve scripts folder |
|---|---|
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts` |
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts` |

On Windows, `%APPDATA%` is usually `C:\Users\<you>\AppData\Roaming`. On macOS, `~` is `/Users/<you>`.

After `git pull` in **this repository** or a change in a **script folder**, run `tools/install.py` again.

## Use a script in DaVinci Resolve

Installing only copies files. You run the script **inside Resolve**, on an open project.

1. **Quit and reopen DaVinci Resolve** so it reloads **Workspace → Scripts** (do this after every install or update).
2. Open (or create) a project. Scripts act on the **current** project, Media Pool bin, and timeline — not on this Git repository.
3. Prepare media the way that script’s README describes (beat-mashup: select a Media Pool **bin** of videos and import a song).
4. Run it: **Workspace → Scripts →** the `.py` name (`beat_mashup`, not the folder name `beat-mashup`). Utility scripts appear on every page; Edit / Color / Deliver / Comp scripts only on that page.
5. If a options window appears, set values and confirm. If your Resolve build has no UI for scripts, it uses `CONFIG` at the top of the `.py`.
6. Read log lines in **Workspace → Console** (detected BPM, errors, seed, and so on).
7. Check the timeline the script created or updated, then continue editing or export from **Deliver**.

You do **not** run `beat_mashup.py` from the terminal for normal use. The terminal is for Git and `tools/install.py` only.

Details, options, and limits for each tool: that **script folder’s** README, e.g. [beat-mashup/README.md](beat-mashup/README.md).

## Add a script (in this repository)

Work only inside **this repository**. `_template/` is not installed (folders starting with `_` are skipped).

**Windows (PowerShell)** — from the root of this repository:

```powershell
Copy-Item -Recurse _template render-queue-tools
Rename-Item render-queue-tools\script_template.py render_queue_tools.py
python tools\install.py
```

**macOS (Terminal)** — from the root of this repository:

```sh
cp -R _template render-queue-tools
mv render-queue-tools/script_template.py render-queue-tools/render_queue_tools.py
python3 tools/install.py
```

1. The **script folder** name is kebab-case (`render-queue-tools/`).
2. The `.py` is snake_case (`render_queue_tools.py`). That name is the Resolve menu entry and **must be unique** across folders in this repository.
3. Pick the menu with `# resolve-menu:` in the header: `Utility` (every page), `Edit`, `Color`, `Deliver`, or `Comp` (Fusion).
4. Implement `run()` and fill in the README **in that script folder**.
5. Install as above, restart Resolve, then run it from **Workspace → Scripts**.

The template already gets the `resolve` object (Scripts menu, Console, or outside Resolve), an optional options window, and clear errors. As-is it prints info about the open project, which is enough to check that Resolve can run your scripts.

### Conventions

- **One file per script.** Resolve copies and runs the `.py` alone; it cannot import modules from **this repository**.
- **Settings in `CONFIG`** at the top of the file. Use an options window only if Resolve provides one (otherwise `CONFIG` is used as-is).
- **Do not destroy manual work.** A script should only change what it created and tag it so it can recognize it later (beat-mashup does this with a marker).
- **Console messages** via `log()`, user-facing failures via `Abort('…')`.
- Python 3.6 or later.

## API documentation

Resolve ships its scripting reference: **Help → Documentation → Developer**, file `README.txt`.

On Windows it is usually under `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` (`%PROGRAMDATA%` is usually `C:\ProgramData`). That path belongs to **installed Resolve**, not this repository.
