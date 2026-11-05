# LAB

The lab code in one repository, as two separate Python packages:

| Module | Command | What it does |
|---|---|---|
| [`equipment/`](equipment) | `equipment` | drives the instruments: Thorlabs DC2200 and PM400, CoolLED pE-300, Canon EOS R10, FLIR Blackfly S; ramps with photos and power |
| [`line-analysis/`](line-analysis) | `analysis` | finds the lines in those photos and videos and relates their spacing to the ramp and the power |

Each module has its own `pyproject.toml`, README, examples and tests. You can install either one alone; neither imports the other.

```text
LAB/
├── equipment/          instrument control           (package `equipment`)
├── line-analysis/      line detection and analysis  (package `line_analysis`)
├── lab/                the shared virtual environment, not in git
├── data/               the folders are in git, the measurements in them are not
│   ├── input/          photos and videos            (input/folder/<name>/)
│   └── output/         equipment logs and analysis results
└── setup.sh            one environment with both packages
```

## Installation

```bash
git clone https://github.com/matijalakner/LAB.git
cd LAB
source setup.sh                   # creates the "lab" environment with both packages and activates it
```

`setup.sh` installs both modules in editable mode, with equipment's `thorlabs`, `coolled` and `flir` extras. To add the Canon extra, which needs the system library libgphoto2, run `EXTRAS=all source setup.sh`. The DC2200 driver (`measurement_control`) and the FLIR libraries (Spinnaker or Aravis) do not come from PyPI; see [equipment's README](equipment/README.md#installation).

To install the modules by hand:

```bash
python3 -m venv --system-site-packages lab && source lab/bin/activate
pip install -e "./equipment[thorlabs,coolled,flir]" -e "./line-analysis[test]"
```

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
