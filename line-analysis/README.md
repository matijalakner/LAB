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

1. `--data-dir DIR` (before the command: `analysis --data-dir DIR folder ...`), or the environment variable `LINE_ANALYSIS_DATA`, or `EQUIPMENT_DATA` (the one `equipment` uses, so one setting serves both);
2. `data/` next to the line-analysis folder (`LAB/data`);
3. `data/` in the current folder.

These are the same rules `equipment` uses, so photos are always under `data/input` and logs and results under `data/output`, and both commands find the same folder.

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
2. The middle 300 rows of every photo are cut out.
3. The lines are found from the contrast of the strip, as below. There is no tuning and nothing to confirm.

**Contrast detection.** Every pixel gets a contrast `(I - background) / background`, with `I` the mean of R, G and B and the background a moving median along x. Averaging over y gives one contrast value per x. Where `|contrast|` exceeds `--contrast-threshold` (default 0.025) there is a feature. A bright peak followed by a dark dip is a line at the zero crossing between them; anything else is one-sided and placed at its largest extremum. Dust and defects do not move: one-sided features at the same x in 3 of 6 evenly spread photos, and visible there in all 6, are not counted as lines, and their positions are in `parameters.json` under `defects_x`. If such features are more than half of all features, the lines themselves are not moving and nothing is removed.

**Peak detection.** `--peak-detection` uses the previous, tuned method on the strips: the first photo tunes the settings, the marked photo opens, and you answer `y` to keep them, `n` to see the next suggestion, or type settings such as `k=4 rel=0.2`. `--track`, `--full-image` and the detection options on the command line (`--k 4` ...) also use it. `--yes` uses the first suggestion without asking. Detection options skip the tuning. `--no-show` keeps the image viewer closed, and `--window N` sets how many neighbours each photo is compared with for the warnings.

```text
output/folder/<name>/
├── results.csv       time_stamp, photo, file, mean_spacing_px, n_lines, std_spacing_px, warning, time_source
├── parameters.json   the settings used
├── tuning/           every tuning attempt
└── <photo>_marked.png   the middle 300 px at the full width, lines painted red
```

A photo with fewer than 300 rows gets a `failed` warning.

#### Whole photos (`--full-image`)

`analysis folder NAME --full-image` analyses the whole photos with the `strip_height` setting. The files above go to `output/folder/NAME/full_image/`, with marked pictures of the full size. To use them in a report: `analysis report NAME --results output/folder/NAME/full_image/results.csv`.

This mode also writes `strips/<photo>_strip.png`: the middle 100 px rows of 6 evenly spread photos. They are cut from the original photos (full width, no marks), for the first photo and the last photo of each fifth of the series, in capture order: 100 photos give photos 1, 20, 40, 60, 80 and 100.

`warning` is filled in when a photo has fewer than 2 lines, a different line count from its neighbours, or an unusual spread of spacings. `time_stamp` is UTC.

#### Line tracking (`--track`)

With `--track`, only the first photo is detected freely. Every later photo is searched around the lines of the photo before it:

1. The tuning works as above. When you confirm a photo with `y`, its line positions are saved as the reference.
2. In the next photo, each reference line `x` gets a bracket and is looked for in `x ± x_tolerance`. If nothing is there, the search widens to half the distance to the neighbouring line on each side.
3. A bracket holds at most one line (the strongest). A bracket that reaches past the edge of the photo may be empty, because the line has moved out. Every other bracket must hold exactly one line.
4. If a bracket that must hold a line is still empty, the minimum contrast (the detection threshold) is lowered step by step (`--contrast-steps`, default `1,0.7,0.5,0.35`), and the narrow and wide searches are repeated.
5. If a line is still missing, the photo is **reported**: it gets the warning `tracking: no line near x=...`, its missing lines are drawn as dotted yellow lines in the marked photo, and the next photo is searched around the previous positions. Otherwise the positions just found become the reference for the next photo. An empty edge bracket keeps its old position, so a line that comes back into the picture is found again.

| Option | Meaning |
|---|---|
| `--track` | turn the tracking on |
| `--x-tolerance PX` | first search range ± px (default 20 % of the line spacing, at least `x_tol`) |
| `--contrast-steps F,F,...` | threshold factors tried in order when a line is missing |

The tracking also writes `tracking.csv`: `photo, file, status` (`reference`, `ok`, `reported`, `failed`), `n_lines, widened, lowered, min_contrast_factor, missing_x, left_x, reference_x`. The tracking settings are stored in `parameters.json` under `tracking`. In Python: `main_folder("s1", tracking=TrackingConfig(x_tolerance=15))`.

### `analysis report NAME`

This command lines the results of `analysis folder NAME` up with a ramp.

**Which ramp:** the one given with `--ramp`. Otherwise it is the ramp whose `_photos.csv` lists the most of the folder's photos; if no photo log matches, the newest ramp is used.

**Level of each photo:**
1. **Photo log**: the photo's row in `<ramp>_photos.csv`, with the level, step, cycle and direction recorded when it was taken.
2. **Time**: if a photo is not in the photo log (for example, a separate time-lapse during the ramp), its time from `results.csv` is compared with the ramp's time stamp. Only photos taken while the ramp ran are kept. `--camera-offset S` corrects a camera clock that is off. It only matters when the time comes from EXIF.

**Power of each photo:** it comes from the PM400 reading of the photo's step (`<ramp>_power.csv`). Without that file it comes from `--liv FILE`, interpolated at the photo's level. For a pE-300 ramp without either, `--color blue|green` gives the power on the sample from the calibration, `intensity × PE300_W_PER_PCT[--color]` (blue 6.334 µW/%, green 5.691 µW/%). For a DC2200 ramp without either, the calibrated intensity `current × COEFF[--objective]` is used. There is no 4x value in `COEFF`, so with `--objective 4x` that axis is left out.

| Option | Meaning |
|---|---|
| `--ramp` | ramp CSV (path, or a name in `output/ramp/`) |
| `--results` | a results CSV instead of the one of `NAME` |
| `--liv` | LIV CSV from `equipment liv` with the same light source |
| `--objective` | `4x`, `5x`, `10x`, `20x`, `40x`: sets micrometres per pixel, and for the DC2200 the intensity per ampere (default 20x) |
| `--camera` | `auto` (default: read from the photos' EXIF), `flir` or `canon`: sets micrometres per pixel |
| `--color` | `blue`, `green` (pE-300 only): power on the sample from the calibration when no power was measured |
| `--sample` | `0.2wt` ... `1.5wt`: the angle for the pitch (default 0.8wt) |
| `--px-um` | micrometres per pixel; overrides `--camera` / `--objective` |
| `--input-dir` | where the photos are, to read the camera from them (default `<data>/input`) |
| `--fit` | function fitted to each branch on the level and power axes (default `auto`, see below) |
| `--camera-offset` | seconds added to the photo times when they are matched by time |

**Fit** (`--fit`): one fit per ramp direction (up and down separately), for distance and pitch, on the level and the power axis. Photos with a warning are left out.

| `--fit` | Function |
|---|---|
| `linear` | `a·x + c` |
| `quadratic` | `a·x + b·x² + c` |
| `cubic` | `a·x + b·x² + d·x³ + c` |
| `saturating` | `A·(1 − exp(−x/k)) + c` |
| `power` | `a·xⁿ + c` |
| `mm` | `A·x/(K + x) + c` (Michaelis–Menten) |
| `auto` (default) | the one of linear, quadratic, saturating, power and mm with the lowest AICc, chosen for each branch and axis separately |
| `none` | no fit, only the points |

The nonlinear fits use only numpy: the shape parameter (k, n or K) is searched on a grid and the others are solved by least squares, so they always converge. In Python: `fit_curve(x, y, "saturating")` from `line_analysis.fits`.

**Micrometres per pixel** come from `calibration.py`. It uses a value you measured with a stage micrometer when the table `PX_UM_MEASURED` has one for the camera and objective. Otherwise it calculates `pixel size / (objective × adapter)`:

| Camera | Pixel | 4x | 5x | 10x | 20x | 40x |
|---|---|---|---|---|---|---|
| FLIR Blackfly S (`flir`) | 4.5 µm | 1.125 | 0.9 | 0.45 | 0.225 | 0.1125 |
| Canon EOS R10 (`canon`) | 3.72 µm | 0.93 | 0.744 | 0.372 | 0.1813 (measured) | 0.093 |

These assume a 1× camera adapter. If yours is different (e.g. 0.5×), change `CAMERA_ADAPTER`. When you calibrate with a stage micrometer, add the value to `PX_UM_MEASURED`, e.g. `("flir", "10x"): 0.447,`. The report prints the value it used and where it came from. The camera is read from the photos: `equipment` writes `Teledyne FLIR` or the Canon's own `Canon` into each photo's EXIF.

```text
output/report/<name>/
├── data.csv      time[s], step, cycle, direction, current[A] | intensity[%],
│                 power[W] and/or intensity[W/um2], mean_spacing_px, std_spacing_px,
│                 warning, n_lines, file
├── plots.png     distance and pitch against level, power (or intensity) and time;
│                 the up and down branches of the ramp are drawn separately
│                 with a fit per branch on the level and power axes (--fit)
├── fits.csv      y, x, direction, model, formula, params, slope, intercept (linear
│                 only), slope_at_mean_x, r2, rmse, aicc, n of every fit
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

Lower-level functions are also exported: `detect_lines(img, config)`, `track_lines`, `track_folder`, `TrackingConfig` → `(positions, signal, threshold)`, `load_image`, `mark_image`, `tune_candidates`, `acquire`, `plot_report`, `plot_timeline`, and the readers for the equipment files: `read_log`, `read_ramp`, `capture_times`, `find_frames_log`, `read_frames_log`.

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
    ├── track.py               line tracking from photo to photo (folder --track)
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
