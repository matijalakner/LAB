# pE-300 power calibration: which function fits?

`pe300_blue_0_100.csv`, `pe300_green_0_100.csv`: 0–100 % pE-300 ramps (up and down, 1 % steps)
with the PM400 power at the sample, recorded 2026-11-04.

`python fit_models.py` fits 8 functions of power against intensity to each colour and branch
(up, down, both) and writes `fit_comparison.csv` (parameters, RMSE, R², AIC/BIC) and
`fit_comparison.png` (up-branch fits and residuals).

Result: the response is sublinear. The straight line is the worst model (R² ≈ 0.98,
RMSE 24–32 µW). A saturating exponential `A·(1 − e^(−x/k)) + c` is in the top three for
both colours and all branches (RMSE ≈ 3 µW, k ≈ 101 % blue, 68 % green); a cubic or
Michaelis–Menten fit does about as well.

Note: `calibration.PE300_W_PER_PCT` (power = intensity × slope) underestimates the power
by about 45–50 % at 10 %, 25–30 % at 50 % and 3–4 % at 100 %.
