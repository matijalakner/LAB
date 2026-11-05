# LAB

The lab code in one repository, as two separate Python packages:

| Module | Command | What it does |
|---|---|---|
| [`equipment/`](equipment) | `equipment` | drives the instruments: Thorlabs DC2200 and PM400, CoolLED pE-300, Canon EOS R10, FLIR Blackfly S; ramps with photos and power |
| [`line-analysis/`](line-analysis) | `analysis` | finds the lines in those photos and videos and relates their spacing to the ramp and the power |

Each module has its own `pyproject.toml`, README, examples and tests. You can install either one alone; neither imports the other.

> **New here? Start with [INSTALL.md](INSTALL.md).** It's a step-by-step guide for **Fedora**, **Ubuntu**, **macOS** (`./install.sh`) and **Windows 10/11** (`install.bat`), with what to install first and what to do if something goes wrong.

```text
LAB/
├── equipment/          instrument control           (package `equipment`)
│   └── packaging/      the installers: fedora/, ubuntu/, macos/, windows/
├── line-analysis/      line detection and analysis  (package `line_analysis`)
├── lab/                the shared virtual environment, not in git
├── data/               the folders are in git, the measurements in them are not
│   ├── input/          photos and videos            (input/folder/<name>/)
│   └── output/         equipment logs and analysis results
├── INSTALL.md          how to install, step by step, on every system
├── install.sh          Fedora, Ubuntu, macOS: install everything
├── install.bat         Windows: install everything
└── setup.sh            Fedora, Ubuntu, macOS: activate the environment in a terminal
```

## Installation

**Follow [INSTALL.md](INSTALL.md).** It's a step-by-step guide for every system, with what to install first and what to do if something goes wrong.

| System | Install once | Then, every time you work |
|---|---|---|
| Fedora, Ubuntu, macOS | `./install.sh` | `source setup.sh` |
| Windows 10/11 | double-click `install.bat` | the **LAB terminal** shortcut on the desktop |

`./install.sh` recognises the system and starts the matching installer in [`equipment/packaging/`](equipment/packaging). After installing, `equipment doctor` checks every instrument on that computer. To update after `git pull`, run `./install.sh --python-only` (Windows: `install.bat -PythonOnly`).

Every instrument works on every system, except the Canon EOS R10 on Windows (its USB library exists only for Linux and macOS).

## Data

Both commands find `LAB/data` by themselves, from any folder: **equipment** writes photos to `data/input` and logs to `data/output`, and **analysis** reads them from there. Both use the same rules: `--data-dir` or `$EQUIPMENT_DATA` / `$LINE_ANALYSIS_DATA`, else `LAB/data`, else `./data` (see [equipment](equipment/README.md#where-the-data-goes) and [line-analysis](line-analysis/README.md#where-the-data-is)). `equipment devices` shows the folder in use.

```bash
equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 30 \
    --photos mysample --camera flir --shutter 1/250 --gain 0 --wb off --power
analysis folder mysample
analysis report mysample
```

The `data/input` and `data/output` folders are part of the repository, so a fresh clone already has the layout. Everything inside them is ignored by git, so measurements never end up in the repository.

## Tests

```bash
pytest equipment line-analysis
```

None of the tests need an instrument. With both packages installed, the line-analysis tests also run complete `equipment` ramps with fake hardware and analyse what equipment wrote.

## History

Both modules keep their full history: `equipment` was split out of [LineTracker](https://github.com/matijalakner/LineTracker), and `line-analysis` was built from LineTracker's detection code. `git log -- equipment` or `git log -- line-analysis` shows the history of one module.
