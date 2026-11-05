import pytest


@pytest.fixture(autouse=True)
def data_folder(tmp_path, monkeypatch):
    """Every test writes into its own data folder, never into LAB/data."""
    data = tmp_path / "data"
    monkeypatch.setenv("EQUIPMENT_DATA", str(data))
    monkeypatch.delenv("LINE_ANALYSIS_DATA", raising=False)
    return data
