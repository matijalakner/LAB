"""The data folder: LAB/data next to the repository, $LINE_ANALYSIS_DATA, --data-dir."""
import pytest

from line_analysis import cli, paths
from conftest import save_photo


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """LAB/{equipment, line-analysis, data/{input, output}}, run from somewhere else."""
    lab = tmp_path / "LAB"
    for d in ("equipment", "line-analysis", "data/input", "data/output"):
        (lab / d).mkdir(parents=True)
    monkeypatch.setattr(paths, "_REPO", lab / "line-analysis")
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.delenv(paths.SHARED_ENV_VAR, raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return lab


def test_data_next_to_the_repository(lab):
    assert paths.data_dir() == lab / "data"
    assert paths.input_root() == lab / "data" / "input"
    assert paths.output_root() == lab / "data" / "output"
    assert paths.output_root("x") == paths.Path("x")              # explicit wins


def test_environment_variable_wins(lab, tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "other"))
    assert paths.data_dir() == tmp_path / "other"


def test_fallback_is_data_in_the_current_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_REPO", tmp_path / "nowhere" / "line-analysis")
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.delenv(paths.SHARED_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.data_dir() == paths.Path("data")
    assert paths.input_root() == paths.Path("data/input")
    assert paths.output_root() == paths.Path("data/output")


def test_equipment_variable_is_shared(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.setenv(paths.SHARED_ENV_VAR, str(tmp_path / "eq"))
    assert paths.data_dir() == tmp_path / "eq"


def test_same_folders_as_equipment(lab, monkeypatch):
    eq_paths = pytest.importorskip("equipment.paths")
    monkeypatch.setattr(eq_paths, "_PACKAGE_DIR", lab / "equipment")
    monkeypatch.delenv(eq_paths.ENV_VAR, raising=False)
    assert eq_paths.input_root() == paths.input_root() == lab / "data" / "input"
    assert eq_paths.output_root() == paths.output_root() == lab / "data" / "output"


def test_folder_command_reads_and_writes_in_lab_data(lab):
    for k in range(3):
        save_photo(lab / "data" / "input" / "folder" / "s1" / f"s1_{k:04d}.jpg", 50, seed=k)
    cli.main(["folder", "s1", "--yes", "--no-show"])
    assert (lab / "data" / "output" / "folder" / "s1" / "results.csv").exists()
    cli.main(["image", "s1_0001.jpg"])
    assert (lab / "data" / "output" / "image" / "s1_0001" / "s1_0001_lines.csv").exists()


def test_data_dir_option(lab, tmp_path, monkeypatch):
    other = tmp_path / "run2"
    save_photo(other / "input" / "folder" / "s2" / "s2_0000.jpg", 50)
    cli.main(["--data-dir", str(other), "image", "s2_0000.jpg"])
    assert (other / "output" / "image" / "s2_0000" / "s2_0000_marked.png").exists()
