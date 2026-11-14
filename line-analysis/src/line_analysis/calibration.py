"""Calibration constants of the setup, used by the report."""

# intensity [W/um^2] = current [A] * COEFF[objective]
COEFF = {
    "5x": 4.356367310904955e-08,
    "10x": 9.257685271674028e-08,
    "20x": 1.2076428929397266e-07,
    "40x": 8.824088200840021e-08,
}

# DC2200 light source: current [A] -> optical power [W] and intensity [mW/cm^2]
# (measured 2026-11-14; intensity = power / 0.709 cm^2, the area of a 9.5 mm
# power-meter sensor). Between the points linear; outside 0.5-2 A extrapolated
# with the nearest segment and never below 0.
DC2200_CALIBRATION = (
    # current [A], power [W], intensity [mW/cm^2]
    (0.5, 7.0e-3, 9.8),
    (1.0, 15.1e-3, 21.5),
    (2.0, 30.0e-3, 42.3),
)


def _dc2200(current_a, column):
    import numpy as np
    x = np.array([r[0] for r in DC2200_CALIBRATION])
    y = np.array([r[column] for r in DC2200_CALIBRATION])
    c = np.asarray(current_a, dtype=float)
    out = np.interp(c, x, y)
    lo, hi = c < x[0], c > x[-1]
    out = np.where(lo, y[0] + (c - x[0]) * (y[1] - y[0]) / (x[1] - x[0]), out)
    out = np.where(hi, y[-1] + (c - x[-1]) * (y[-1] - y[-2]) / (x[-1] - x[-2]), out)
    return np.maximum(out, 0.0)


def dc2200_power_w(current_a):
    """Optical power [W] of the DC2200 light source at ``current_a`` [A]."""
    return _dc2200(current_a, 1)


def dc2200_intensity_mw_cm2(current_a):
    """Intensity [mW/cm^2] of the DC2200 light source at ``current_a`` [A]."""
    return _dc2200(current_a, 2)


# power on the sample [W] = pE-300 intensity [%] * PE300_W_PER_PCT[colour]
# (slope of the up branch of the 0-100 % calibration ramps, 2026-11-04)
PE300_W_PER_PCT = {
    "blue": 6.33421762e-06,
    "green": 5.69139837e-06,
}

# angle used for the pitch = 2 * THETA * distance, per sample concentration
THETA = {
    "0.2wt": 0.011327835,
    "0.4wt": 0.011372214,
    "0.6wt": 0.0115,
    "0.8wt": 0.01147779,
    "1.0wt": 0.00198943,
    "1.5wt": 0.00280895,
}

# ---------------------------------------------------------------------------
# micrometers per pixel, per camera and objective
# ---------------------------------------------------------------------------
OBJECTIVES = ("4x", "5x", "10x", "20x", "40x")

# sensor pixel size [um]
CAMERA_PIXEL_UM = {
    "flir": 4.5,      # FLIR Blackfly S BFS-U3-27S5C-C (Sony IMX429), 1936 x 1464
    "canon": 3.72,    # Canon EOS R10, 6000 x 4000 on 22.3 mm
}
# magnification of the adapter between microscope and camera (printed on it)
CAMERA_ADAPTER = {
    "flir": 1.0,
    "canon": 1.0,
}
# measured with a stage micrometer; these win over the calculated value.
# Add a line when you calibrate: ("flir", "10x"): 0.447,
PX_UM_MEASURED = {
    ("canon", "20x"): 0.1813,
}

PX_TO_UM = 0.1813   # old default (Canon, 20x): used only when the camera is unknown


def px_to_um(camera, objective):
    """Micrometers per pixel -> (value, how it was found)."""
    camera, objective = str(camera).lower(), str(objective).lower()
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective '{objective}'; choose from {', '.join(OBJECTIVES)}")
    if (camera, objective) in PX_UM_MEASURED:
        return PX_UM_MEASURED[(camera, objective)], f"{camera}, {objective}, measured"
    if camera not in CAMERA_PIXEL_UM:
        raise ValueError(f"unknown camera '{camera}'; choose from {', '.join(CAMERA_PIXEL_UM)}")
    mag = float(objective[:-1]) * CAMERA_ADAPTER[camera]
    value = CAMERA_PIXEL_UM[camera] / mag
    return value, (f"{camera}, {objective}, calculated: {CAMERA_PIXEL_UM[camera]:g} um pixels, "
                   f"{CAMERA_ADAPTER[camera]:g}x adapter")
