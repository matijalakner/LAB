# line-analysis

This package finds thin vertical lines in the photos and videos taken with [equipment](../equipment), the other module of this LAB repository. It measures how far apart the lines are and relates that spacing to the light-source ramp and the measured optical power.

```text
analysis image   IMAGE        lines of one photo
analysis video   VIDEO -n N   lines in a frame every N seconds
analysis spacing NAME         mean spacing (± std) against time of an analysed video
analysis folder  NAME         every photo of a folder (settings tuned on the first)
analysis jumps   NAME         every photo, lines in the middle 3 rows (template, predicted)
analysis bench                score the methods on synthetic photos with known lines
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

`IMAGE` is a path, or a file name like `mysample_0003.jpg`, which is looked up in `input/folder/mysample/`. 100 px are cut off the left and the right edge first (`--edge-crop PX`, 0 = full width), as in the folder analysis. With `--plot` it also writes the line-strength plot. The [detection options](#detection-parameters) apply.

```text
output/image/<name>/
├── <name>_marked.png     the image without the cut edges, lines painted red (extra lines cyan,
│                         missed ones dotted yellow, see "Spacing" below)
├── <name>_lines.csv      line, x_px (from the cut edge), spacing_px
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
2. The middle 300 rows of every photo are cut out, and 100 px are cut off the left and the right edge (`--edge-crop PX`; 0 keeps the full width). The edges are often dark or vignetted and give false lines there. The cut applies to every method (contrast, peak detection, tracking, `--full-image`). Line x positions (marked photos, `tracking.csv`, `defects_x`) are measured from the cut, so add the edge crop to get the x in the photo; the spacing is not affected. A line within a few px of the cut can come and go between photos.
3. The lines are found from the contrast of the strip, as below. There is no tuning and nothing to confirm.

**Contrast detection.** Every pixel gets a contrast `(I - background) / background`, with `I` the mean of R, G and B and the background a moving median along x. Averaging over y gives one contrast value per x. Where `|contrast|` exceeds `--contrast-threshold` (default 0.025) there is a feature. A bright peak followed by a dark dip is a line at the zero crossing between them; anything else is one-sided and placed at its largest extremum. Dust and defects do not move: one-sided features at the same x in 3 of 6 evenly spread photos, and visible there in all 6, are not counted as lines, and their positions are in `parameters.json` under `defects_x`. If such features are more than half of all features, the lines themselves are not moving and nothing is removed.

**Peak detection.** `--peak-detection` uses the previous, tuned method on the strips: the first photo tunes the settings, the marked photo opens, and you answer `y` to keep them, `n` to see the next suggestion, or type settings such as `k=4 rel=0.2`. `--track`, `--full-image` and the detection options on the command line (`--k 4` ...) also use it. `--yes` uses the first suggestion without asking. Detection options skip the tuning. `--no-show` keeps the image viewer closed, and `--window N` sets how many neighbours each photo is compared with for the warnings.

```text
output/folder/<name>/
├── results.csv       time_stamp, photo, file, mean_spacing_px, n_lines, std_spacing_px, warning,
│                     time_source, n_missing, n_extra
├── parameters.json   the settings used
├── tuning/           every tuning attempt
└── <photo>_marked.png   the middle 300 px without the cut edges, lines painted red,
                         extra lines cyan, missed lines dotted yellow
```

A photo with fewer than 300 rows gets a `failed` warning.

#### Whole photos (`--full-image`)

`analysis folder NAME --full-image` analyses the whole photos with the `strip_height` setting. The files above go to `output/folder/NAME/full_image/`, with marked pictures of the full size. To use them in a report: `analysis report NAME --results output/folder/NAME/full_image/results.csv`.

This mode also writes `strips/<photo>_strip.png`: the middle 100 px rows of 6 evenly spread photos. They are cut from the original photos (full width, no marks), for the first photo and the last photo of each fifth of the series, in capture order: 100 photos give photos 1, 20, 40, 60, 80 and 100.

**Spacing.** The lines of a photo are fitted with a regular grid `x = x0 + i · spacing`: every line gets the nearest grid number `i`. A line further than a quarter of the spacing from its grid position, or a second line at the same position, is **extra** (a false line); a grid position between the first and the last line without a line is **missed**. `mean_spacing_px` is then the average distance per grid step (a gap over a missed line counts as one, divided by its steps). With more than 3 lines the largest and the smallest 10 % of these distances are left out first (at least one at each end). With the plain mean, one missed or one false line among ~10 changed the spacing by ~10 % and made parallel copies of the curve in the report. `n_missing` and `n_extra` count them, and the marked photos show them. `std_spacing_px` is the std of the gaps between neighbouring grid positions.

`warning` is filled in when a photo has fewer than 2 lines, an unusual spread of spacings, or a line count 2 or more away from its neighbours. The count compared is that of the grid (found − extra + missed), so a single missed, false or edge line, which no longer changes the spacing, does not drop a photo from the report. `time_stamp` is UTC.

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

### `analysis jumps NAME`

A separate method from `analysis folder`; it writes to `output/jumps/NAME/`. Built and tested on real photos of series 08 (`tests/data/real`, lines marked by hand): every line there is found.

**What a line looks like** in these photos: a sharp brightness change through every row, a step **down** left of the brightest part of the photo, a step **up** right of it, and a thin dark or bright line near the brightest part (where the step changes sign). The distances are uneven: narrow bands of 100–185 px sit next to 300–400 px ones (at 2576 px width).

**Preparation** (on the first photo):
1. The middle 300 rows are cut out (`--prep-rows`), and 200 px of a 6000 px photo (scaled with the width) are cut off the left and the right (`--edge-crop`).
2. Brightness: the colour channels weighted by how bright they are (`--channels auto`; a saturated channel gets no weight).
3. **Line strength**: the step of log(brightness) over 18 px (`--jump-width`, scaled), both up and down, and a thin-line value, as the median over 6 bands of rows (dust in a few rows does not count), in local noise sigmas. The noise has a floor of about a third of a brightness level, so in flat dark areas, where the image sits on one level and then moves one level, that move is not a line.
4. Every peak over `contrast_diff` sigmas (default 6, `--contrast-diff`) is a line, placed at the centre of its brightness change. A small step (under 6 levels) that happens within one pixel is a **JPEG block edge**, not a line, and is weakened accordingly.
5. The gap rule (below), then the whole photo opens with the lines drawn in navy blue: `y` keeps them, `n` and then `+` (more lines), `-` (fewer) or a number, `q` stops. 15 tries at most.
6. Every kept line keeps **its own shape** (template): a step down, a step up or a thin line.

**Analysis** (every photo, the first included) with `--detector template` (default), on the middle row and the rows above and below it (`--rows 3`):
1. The lines of the photo before are shifted and stretched (±6 %) together to where they fit best, then every line is searched within ±10 % of the spacing (`--window`). The match is the correlation of its shape in brightness times that in the brightness gradient (a gentle slope between lines looks like a step in brightness but not in the gradient); a line is found over 0.3.
2. A line not found is followed at its predicted position and counted as a missed step of the spacing. Line shapes slowly follow the photos. New lines beyond the outer ones are found as in the preparation.
3. **Spacing** = the average distance between neighbouring lines (after the gap rule). With more than 3 lines, the largest and the smallest 10 % of the distances are left out of the average (at least one at each end: with 8–11 lines that is one at each end). The bands are uneven, so no regular grid is assumed. `std_spacing_px` is the spread of the distances (how uneven the bands are); `spacing_err_px` is how precisely the spacing is measured, from how far the 3-row lines lie from the same lines found on 300 rows (√2 × position error / √(distances averaged)).

`--detector threshold` is the earlier detector (largest jump near each line).

**Quality** (`quality` in `results.csv`: `ok` or the reasons). A photo is doubtful when the median match of its lines is under 0.5, fewer than 75 % of the lines in the picture are found, the spacing changed by more than 8 % from the photo before, a distance is over 1.7× the average (a missed line makes ~2×; the widest real band was 1.4×), or the lines differ from a **300-row check** (`--check-rows`, 0 = off): the same photo's middle 300 rows are searched as in the preparation; a strong line there (1.5× the limit) that is not followed, or a followed line with nothing there even at half the limit, makes the photo doubtful. The check only decides whether to ask; the spacing is always that of the 3 rows.

**Asking** (`--ask`): `doubtful` (default) shows a doubtful photo (`y` keep, `n` prepare again on it, `q` stop); `count` asks when the number of lines changes; `review` asks nothing during the run and then shows `overview.png` and every doubtful photo (`y` keep, `x` exclude, `p` prepare again, `q` stop). `--yes` asks nothing: a doubtful photo is **prepared again automatically** and measured again (`checked` in `lines.csv` says why).

**Gap rule** (every photo and the preparation): a distance below ½ of the average distance (the average of the normal distances) means a possible false line: the weaker line of the pair is excluded, but only if it is weaker than 0.4× the median line, so real narrow bands (two strong lines) stay. A distance over 2× the average (lines lost) is left out of the spacing. Excluded lines are drawn dotted red and counted in `n_extra`; lines lost in long distances and followed lines not found count in `n_missing`.

```text
output/jumps/<name>/
├── results.csv          as in analysis folder, plus spacing_err_px and quality
├── lines.csv            photo, file, n_lines, contrast_diff, checked, period_px,
│                        period_vs_spacing_pct, snr, coverage, x_px, excluded_x, long_gaps
├── overview.png         spacing (± error) against the photo, doubtful photos in red
├── parameters.json      settings and every preparation (contrast_diff, channel weights,
│                        number of line templates, initial positions)
├── preparation/         try<N>_<photo>.jpg of every preparation try
└── <photo>_marked.jpg   the whole photo, lines in navy blue, excluded lines dotted red
```

x positions are those of the whole photo. For the report: `analysis report NAME --results output/jumps/NAME/results.csv` (error bars and weighted fits from `spacing_err_px`).

**Tested on the real photos** (`tests/test_real_photos.py`, 8 photos of series 08, 74 lines):
- preparation (300 rows): 74/74 lines, no false line;
- analysis (middle 3 rows): every line in every photo, spacing within 0.25 % of the hand-marked one;
- all 8 as one series prepared only on the first (30–80 frames apart, so the lines move a lot): the photos where following fails are found doubtful by the 300-row check and prepared again; then every line is right;
- 41 different 3-row strips per photo: 99.3 % of the lines.

### `analysis bench`

Makes synthetic photo series whose line positions are known and scores the methods on them: the folder's contrast method, `analysis jumps --detector threshold` and `--detector template` (as with `--yes`). The photos imitate the real ones in `tests/data/real`: steps down left of the bright centre and up right of it, a thin line at every line, uneven bands (0.45–1.4× the spacing, some narrow), dark vignetted edges, JPEG, ~1.5 px optical blur, dust and a fixed scratch; `dark` like series 08, `bright` like the orange pE-300 photos. It prints, per series and method, the median and 95th percentile of the spacing error, the photos over 2 % off, the share of lines found and the false lines per photo. `--photos N` sets the photos per series.

| series | contrast (folder) | jumps threshold | **jumps template** |
|---|---|---|---|
| dark | median 9.3 %, bad 21/24 | median 10.1 %, bad 23/24 | **median 0.05 %, bad 5/24, 98 % of lines** |
| dark, wide | median 12.2 %, bad 21/24 | median 6.6 %, bad 23/24 | **median 0.05 %, bad 8/24, 95 %** |
| dark, low contrast | median 13.0 %, bad 22/24 | median 17.6 %, bad 24/24 | **median 1.7 %, bad 12/24, 90 %** |
| bright | median 5.4 %, bad 24/24 | median 18.4 %, bad 24/24 | **median 0.02 %, bad 6/24, 100 %** |

("bad" = over 2 % off.) Most remaining bad photos have a faint centre line inside a narrow band, which the gap rule takes for a false line; the real photos did not have that case.

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
| `--keep-outliers` | fit every photo (by default photos far from the trend are left out, see below) |
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

**Outliers.** A photo where the detection missed every second line gives twice the real spacing, and a run of such photos is not caught by the folder warnings. By default the report finds them before fitting: it starts from a Theil–Sen line, fits the chosen function, and leaves out every photo more than 3.5 robust sigmas (1.4826 × MAD of the residuals) from it, repeating until the set stops changing. This is decided once per branch on distance against the level, so the same photos are left out of every panel. They are drawn as hollow markers and counted in `n_excluded` in `fits.csv`; they stay in `data.csv`. `--keep-outliers` turns this off. If many photos are left out, look at their marked photos and rerun `analysis folder` (e.g. with `--track`).

The saturating and Michaelis–Menten fits keep k and K at least a tenth of the x range, so a few stray points cannot turn the curve into a step.

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
│                 only), slope_at_mean_x, r2, rmse, aicc, n, n_excluded of every fit
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
