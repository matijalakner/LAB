"""Calibration constants of the setup, used by the report."""

# intensity [W/um^2] = current [A] * COEFF[objective]
COEFF = {
    "5x": 4.356367310904955e-08,
    "10x": 9.257685271674028e-08,
    "20x": 1.2076428929397266e-07,
    "40x": 8.824088200840021e-08,
}

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

PX_TO_UM = 0.1813   # micrometers per pixel
