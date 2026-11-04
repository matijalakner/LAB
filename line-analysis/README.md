# line-analysis

This package finds thin vertical lines in the photos and videos taken with [equipment](../equipment), the other module of this LAB repository. It measures how far apart the lines are and relates that spacing to the light-source ramp and the measured optical power.

```text
analysis image   IMAGE        lines of one photo
analysis video   VIDEO -n N   lines in a frame every N seconds
analysis spacing NAME         mean spacing (± std) against time of an analysed video
analysis folder  NAME         every photo of a folder (settings tuned on the first)
analysis report  NAME         folder results against the DC2200 / pE-300 ramp
```

The line detection comes from [LineTracker](https://github.com/matijalakner/LineTracker)'s `strip_line_finder` and works the same way. The difference is that this package reads the files `equipment` writes:

| equipment writes | analysis uses it for |
|---|---|
| `input/folder/<name>/<name>_XXXX.jpg/.png/.tif` | the photos. 16-bit FLIR PNG/TIFF files are scaled to 8 bit. |
| `output/ramp/<ramp>_photos.csv` | **the level of every photo**, plus its step and its up/down direction. No clock is compared. |
| `output/ramp/<ramp>_power.csv` | the PM400 power of every photo's step |
| `output/ramp/<ramp>.csv` (`current_A` **or** `intensity_pct`) | the DC2200 and the pE-300 both work |
| `output/camera/{camera,flir}_<UTC>.csv` | photo times from the computer clock, not the camera clock |
| `output/camera/flir_<UTC>_frames.csv` | the real time of each video frame, so dropped frames do not shift the times |
| `output/liv/liv_<UTC>.csv` (optional) | power against level, for ramps run without `--power` |

The outputs use LineTracker's layout and CSV formats (`output/image`, `output/video`, `output/folder`, `output/report`).

## Installation

Requires Python 3.10 or newer. The expected lab layout is:

```text
LAB/
├── equipment/
├── line-analysis/        this module
└── data/
    ├── input/            photos and videos written by equipment (input/folder/<name>/)
    └── output/           equipment logs (ramp/, camera/, ...) and the results of analysis
```

```bash
git clone https://github.com/matijalakner/LAB.git
cd LAB/line-analysis
source ../lab/bin/activate    # the shared LAB environment (see ../setup.sh)
pip install -e .            # numpy, pillow, opencv-python, matplotlib, pandas
analysis --help
```

It can share an environment with `equipment`; neither package needs the other.

### Where the data is

`analysis` reads and writes in `LAB/data`, wherever you run it from. The data folder is the first of:

1. `--data-dir PATH` (before the command: `analysis --data-dir D:/run2 folder s1`), or the environment variable `LINE_ANALYSIS_DATA`;
2. `data/` next to the `line-analysis` folder, which is `LAB/data`. This needs the editable install (`pip install -e .`), because the package finds its own folder;
3. `data/` in the current folder;
4. the current folder itself (plain `input/` and `output/`).

Inside it, photos and videos come from `<data>/input`. Equipment logs are read from `<data>/output`, and the results are written to `<data>/output` too. `--input-dir` / `--output-dir` on a command override each one separately.

## Typical run

```bash
# measure: pE-300 blue ramp, FLIR photo and PM400 reading in every step
equipment pe300 ramp --channels B --min 0 --max 100 --step 5 --step-time 60 \
    --photos mysample --camera flir --shutter 1/250 --gain 0 --wb off --power

# analyse
analysis folder mysample        # tune on the first photo, confirm with y, analyse all
analysis report mysample        # finds the ramp whose photo log lists these photos
```

## Commands

Paths below are inside the [data folder](#where-the-data-is) (`LAB/data`): `input/...` means `LAB/data/input/...`. Every command takes `--output-dir`, and the commands that read photos or videos also take `--input-dir`. Add `--debug` before the command to get a full traceback instead of a one-line error.

### `analysis image IMAGE`

`IMAGE` is a path, or a file name like `mysample_0003.jpg`, which is looked up in `input/folder/mysample/`. With `--plot` it also writes the line-strength plot. The [detection options](#detection-parameters) apply.

```text
output/image/<name>/
├── <name>_marked.png     the image, same size, lines painted red
├── <name>_lines.csv      line, x_px, spacing_px
└── <name>_signal.png     line-strength plot (only with --plot)
```

### `analysis video VIDEO -n N`

This command analyses one frame every `N` seconds (default 1). `VIDEO` is a path, or a name like `mysample_0002.mp4`.

For a video from `equipment flir video`, the command finds the frame log through the capture log in `output/camera/`. The frames are then chosen by their **real** times, and `lines.csv` gets those times, with the recording start as its time stamp. Without a frame log (Canon videos, other files), or with `--nominal-fps`, the frame rate stored in the file is used and the time stamp is the start of the analysis. `--frames-log FILE` names the frame log yourself.

```text
output/video/
├── frames/<name>/frame_00000.png ...      raw frames
└── <name>/
    ├── frame_00000_marked.png ...
    └── lines.csv        time_stamp line, then time, frame, lines (JSON array of x in px)
```

### `analysis spacing NAME` (alias `analyse`)

This command reads `output/video/<name>/lines.csv`. It writes `spacing.csv` (`time, frame, n_lines, mean_spacing_px, std_spacing_px`) and `spacing.png` (mean spacing, error bar = sample std of the spacings in each frame). Frames with fewer than 2 lines are skipped.

### `analysis folder NAME`

`NAME` is the measurement name (`input/folder/NAME`) or any folder of photos. Videos in the folder are ignored.

1. The photos are sorted by capture time. The time comes from the equipment capture or photo log when the photo is listed there (`log`), else from EXIF (`exif`), else from the file (`file`).
2. The first photo tunes the detection settings. The marked photo opens; answer `y` to keep the settings, `n` to see the next suggestion, or type settings such as `k=4 strip_height=400`.
3. Every photo is analysed with the confirmed settings.

`--yes` uses the first suggestion without asking. Detection options on the command line (`--k 4` ...) skip the tuning. `--no-show` keeps the image viewer closed, and `--window N` sets how many neighbours each photo is compared with for the warnings.

```text
output/folder/<name>/
├── results.csv       time_stamp, photo, file, mean_spacing_px, n_lines, std_spacing_px, warning, time_source
├── parameters.json   the settings used
├── tuning/           every tuning attempt
└── <photo>_marked.png
```

`warning` is filled in when a photo has fewer than 2 lines, a different line count from its neighbours, or an unusual spread of spacings. `time_stamp` is UTC.

### `analysis report NAME`

This command lines the results of `analysis folder NAME` up with a ramp.

**Which ramp:** the one given with `--ramp`. Otherwise it is the ramp whose `_photos.csv` lists the most of the folder's photos; if no photo log matches, the newest ramp is used.

**Level of each photo:**
1. **Photo log**: the photo's row in `<ramp>_photos.csv`, with the level, step, cycle and direction recorded when it was taken.
2. **Time**: if a photo is not in the photo log (for example, a separate time-lapse during the ramp), its time from `results.csv` is compared with the ramp's time stamp. Only photos taken while the ramp ran are kept. `--camera-offset S` corrects a camera clock that is off. It only matters when the time comes from EXIF.

**Power of each photo:** it comes from the PM400 reading of the photo's step (`<ramp>_power.csv`). Without that file it comes from `--liv FILE`, interpolated at the photo's level. For a pE-300 ramp without either, `--color blue|green` gives the power on the sample from the calibration, `intensity × PE300_W_PER_PCT[--color]` (blue 6.334 µW/%, green 5.691 µW/%). For a DC2200 ramp without either, the calibrated intensity `current × COEFF[--objective]` is used.

| Option | Meaning |
|---|---|
| `--ramp` | ramp CSV (path, or a name in `output/ramp/`) |
| `--results` | a results CSV instead of the one of `NAME` |
| `--liv` | LIV CSV from `equipment liv` with the same light source |
| `--objective` | `5x`, `10x`, `20x`, `40x` (DC2200 only, default 20x) |
| `--color` | `blue`, `green` (pE-300 only): power on the sample from the calibration when no power was measured |
| `--sample` | `0.2wt` ... `1.5wt`: the angle for the pitch (default 0.8wt) |
| `--px-um` | micrometres per pixel (default 0.1813) |
| `--camera-offset` | seconds added to the photo times when they are matched by time |

```text
output/report/<name>/
├── data.csv      time[s], step, cycle, direction, current[A] | intensity[%],
│                 power[W] and/or intensity[W/um2], mean_spacing_px, std_spacing_px,
│                 warning, n_lines, file
├── plots.png     distance and pitch against level, power (or intensity) and time;
│                 the up and down branches of the ramp are drawn separately
│                 with a linear fit per branch on the level and power axes
├── fits.csv      y, x, direction, slope, intercept, r2, n of every fit
└── timeline.png  level, power and pitch on the ramp's own time axis
```

Photos with a warning are kept in `data.csv` and left out of the plots. Because the photo log shares its clock with the ramp, the timeline uses real seconds from the ramp start; nothing is shifted or stretched. The calibration constants are in `src/line_analysis/calibration.py`.

## How the detection works

1. **Bands.** The analysed strip (`strip_height` rows around the middle) is cut into `n_blocks` horizontal bands. Each band becomes one colour profile along x: the median over its rows.
2. **Line strength.** For each colour channel, a moving-median background is subtracted. The largest deviation over R, G and B is the line strength of that column. Wide colour stripes stay in the background.
3. **Candidates.** The band-averaged signal is smoothed. Local maxima above `max(k·sigma, rel·strong level, min_threshold)` that are at least `min_dist` px apart become candidates.
4. **Confirmation.** A candidate is accepted only if it is visible in at least `min_fraction` of the bands. This rejects defects that cover only part of the height.

Size-dependent parameters scale with the image width (they were tuned on 6000 px), so the same defaults work for the Canon (6000 px) and the FLIR (1936 px).

## Detection parameters

These options work on `image`, `video` and `folder` (as `--min-fraction 0.5` and so on), or in Python as `DetectionConfig(...)`.

| Parameter | Default | Meaning |
|---|---|---|
| `n_blocks` | 8 | horizontal bands that must agree |
| `k` | 3.0 | noise floor in sigmas |
| `rel` | 0.25 | threshold floor as a fraction of the strong responses |
| `min_fraction` | 0.6 | fraction of bands a line must be visible in |
| `band_rel` | 0.5 | per-band visibility, as a fraction of the threshold |
| `bg_window` | from width | background filter width (px) |
| `min_dist` | from width | minimum distance between lines (px) |
| `x_tol` | from width | allowed x shift between bands (px) |
| `smooth` | 5 | smoothing width (px) |
| `half_width` | 1 | painted half-width of a line (px) |
| `strip_height` | 200 | rows around the middle that are analysed; 0 = all |
| `min_threshold` | 2.0 | absolute threshold floor (0–255 levels); lower it for dark images |

## Python API

```python
from line_analysis import (DetectionConfig, analyse_image, process_video, analyse_spacing,
                           main_folder, main_report)

res = analyse_image("input/folder/s1/s1_0000.jpg", "output/image/s1_0000", DetectionConfig(k=4))
rows = process_video("s1_0002.mp4", interval=5)              # FLIR frame log found automatically
main_folder("s1", interactive=False, show=False)
out = main_report("s1")                                      # out["table"] is a pandas DataFrame
```

Lower-level functions are also exported: `detect_lines(img, config)` → `(positions, signal, threshold)`, `load_image`, `mark_image`, `tune_candidates`, `acquire`, `plot_report`, `plot_timeline`, and the readers for the equipment files: `read_log`, `read_ramp`, `capture_times`, `find_frames_log`, `read_frames_log`.

## Project structure

```text
line-analysis/
├── pyproject.toml
├── examples/
├── tests/                     includes an end-to-end run through the equipment CLI
└── src/line_analysis/
    ├── cli.py                 the `analysis` command
    ├── paths.py               where the data folder is (LAB/data)
    ├── logs.py                readers for every equipment file, path lookup
    ├── detect.py              DetectionConfig and the line detector
    ├── tune.py                automatic settings from one photo
    ├── image.py               load (8/16 bit), detect, mark, save
    ├── video.py               frame selection (real FLIR frame times), video pipeline
    ├── spacing.py             spacing statistics and the spacing plot
    ├── folder.py              folder analysis, photo times, warnings
    ├── report.py              photo ↔ ramp ↔ power, report plots
    ├── calibration.py         objective, pE-300, sample and pixel-size constants
    └── style.py               plot look
```

## Tests

```bash
pip install -e ".[test]"
pytest
```

The tests use synthetic photos with known line positions. They cover detection accuracy, 16-bit images, folder and report runs on files in the exact equipment formats (pE-300 with photo and power logs, DC2200 matched by time, LIV power, and FLIR video with dropped frames), and the CLI. If `equipment` is installed in the same environment, two more tests run a real `equipment pe300 ramp` and `equipment dc2200 ramp` with fake hardware that photographs lines whose spacing follows the light level. They then check that `analysis report` recovers the spacing, the level, the power and the up/down branches.
