import tarfile
from pathlib import Path

import build_backend


def test_sdist_contains_makefile(tmp_path: Path) -> None:
    filename = build_backend.build_sdist(str(tmp_path))

    with tarfile.open(tmp_path / filename, "r:gz") as archive:
        names = archive.getnames()

    assert any(name.endswith("/Makefile") for name in names)
