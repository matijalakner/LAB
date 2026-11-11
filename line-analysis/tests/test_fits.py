import numpy as np
import pytest

from line_analysis.fits import AUTO_MODELS, FIT_CHOICES, MODELS, fit_curve

X = np.linspace(0, 100, 21)


@pytest.mark.parametrize("model, params", [
    ("linear", (0.5, 3.0)),
    ("quadratic", (0.5, -0.002, 3.0)),
    ("cubic", (0.5, -0.002, 1e-5, 3.0)),
    ("saturating", (40.0, 30.0, 3.0)),
    ("power", (2.0, 0.6, 3.0)),
    ("mm", (60.0, 50.0, 3.0)),
])
def test_recovers_parameters(model, params):
    exact = fit_curve(X, X, model)            # any fit, only to get .predict for the model
    exact.params = params
    y = exact.predict(X)
    f = fit_curve(X, y, model)
    assert f.model == model
    assert np.allclose(f.params, params, rtol=1e-3, atol=1e-6)
    assert f.r2 > 0.999999


def test_auto_picks_curved_model_for_saturating_data():
    rng = np.random.default_rng(0)
    y = 40 * (1 - np.exp(-X / 30)) + 3 + rng.normal(0, 0.05, X.size)
    f = fit_curve(X, y, "auto")
    assert f.model in AUTO_MODELS and f.model != "linear"
    assert f.r2 > fit_curve(X, y, "linear").r2


def test_auto_keeps_linear_for_linear_data():
    rng = np.random.default_rng(1)
    y = 0.5 * X + 3 + rng.normal(0, 0.5, X.size)
    assert fit_curve(X, y, "auto").model == "linear"


def test_too_few_points_and_nan():
    assert fit_curve([1, 1, 1], [1, 2, 3], "linear") is None
    assert fit_curve([1, 2], [1, 2], "quadratic") is None
    assert fit_curve([0, 1], [1, 3], "auto").model == "linear"   # two points: a line, as before
    f = fit_curve([0, 1, np.nan, 3], [1, 3, 5, 7], "linear")
    assert f.n == 3 and np.isclose(f.params[0], 2)
    with pytest.raises(ValueError):
        fit_curve(X, X, "spline")


def test_choices():
    assert set(MODELS) | {"auto", "none"} == set(FIT_CHOICES)


def test_auto_with_three_points_is_a_line():
    assert fit_curve([0, 50, 100], [1, 2, 4], "auto").model == "linear"


def _noisy_saturating(seed, n=100):
    rng = np.random.default_rng(seed)
    x = np.repeat(np.linspace(0, 100, n // 5), 5)
    return x, 188 + 62 * (1 - np.exp(-x / 35)) + rng.normal(0, 1.5, x.size)


def test_outliers_from_missed_lines_are_found():
    from line_analysis.fits import outlier_mask
    x, y = _noisy_saturating(2)
    bad = np.zeros(x.size, bool)
    bad[10:14] = True            # every third line missed: 1.5x
    bad[25:35:2] = True          # every second line missed: 2x
    y = np.where(bad, y * np.where(np.arange(x.size) < 20, 1.5, 2.0), y)
    out = outlier_mask(x, y, "auto")
    assert np.array_equal(out, bad)
    f = fit_curve(x[~out], y[~out], "saturating")
    assert abs(f.params[1] - 35) < 5 and f.r2 > 0.98


def test_clean_data_keeps_its_points():
    from line_analysis.fits import outlier_mask
    for seed in range(5):
        x, y = _noisy_saturating(seed)
        assert outlier_mask(x, y, "auto").sum() <= 1
    assert not outlier_mask(X, 0.5 * X + 3, "linear").any()      # exact data
    assert not outlier_mask([0, 1, 2], [0, 10, 0], "auto").any()  # too few to judge


def test_no_step_shaped_saturating_fit():
    f = fit_curve(X, np.where(X > 0, 10.0, 0.0), "saturating")
    assert f.params[1] >= np.ptp(X) / 10 * 0.999
