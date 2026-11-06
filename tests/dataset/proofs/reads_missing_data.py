from pathlib import Path


def test_reads_its_data():
    (Path(__file__).parent / "dataset" / "doubling.json").read_text()
