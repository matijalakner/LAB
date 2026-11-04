"""One look for every plot: thin marks, recessive grid and axes, fixed colours.

Colours are slots of a colour-blind-checked categorical palette, always used in
this order: BLUE for the measured line data, ORANGE for the second series
(the light level, or the down branch of a ramp).
"""
from pathlib import Path

BLUE = "#2a78d6"
ORANGE = "#eb6834"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#8c8b86"
GRID = "#e4e3df"

# ramp direction -> (colour, marker); the marker repeats the colour so the
# direction is never told by colour alone
DIRECTION_STYLE = {"up": (BLUE, "o"), "down": (ORANGE, "^")}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "axes.titlecolor": TEXT,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "xtick.color": TEXT_2, "ytick.color": TEXT_2,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "legend.frameon": False, "font.size": 10, "lines.linewidth": 2,
        "savefig.facecolor": "white",
    })
    return plt


def figure(*args, **kwargs):
    return _plt().subplots(*args, **kwargs)


def finish(fig, out_path, dpi=150):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    _plt().close(fig)
    return out_path
