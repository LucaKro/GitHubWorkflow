from pathlib import Path


def test_the_package_reads_its_settings():
    Path("/no-such-directory/settings.json").read_text()
