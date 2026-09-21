import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from api_sentinel.seed import write_private_json


def test_first_secret_creation_is_private(tmp_path: Path) -> None:
    target = tmp_path / "demo.json"
    write_private_json(target, {"probe": "credencial fictícia de teste"})
    assert json.loads(target.read_text()) == {"probe": "credencial fictícia de teste"}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.skipif(
    not hasattr(os, "getuid") or getattr(os, "getuid", lambda: -1)() != 0,
    reason="Verificação de leitores por UID exige Linux/root no container isolado de testes.",
)
@pytest.mark.parametrize("owner,mode", [(0, 0o644), (10001, 0o600), (10001, 0o640)])
def test_seed_rewrite_preserves_owner_permissions_and_reader_access(owner: int, mode: int) -> None:
    with tempfile.TemporaryDirectory(prefix="sentinel-file-reader-") as directory:
        parent = Path(directory)
        parent.chmod(0o755)
        target = parent / "demo.json"
        target.write_text(json.dumps({"probe": "controlled-before"}))
        target.chmod(mode)
        os.chown(target, owner, owner)
        before = target.stat()
        command = [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).read_text()",
            str(target),
        ]
        assert subprocess.run(command, user=10001, capture_output=True).returncode == 0
        write_private_json(target, {"probe": "controlled-after"})
        after = target.stat()
        assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
        assert stat.S_IMODE(after.st_mode) == mode
        assert subprocess.run(command, user=10001, capture_output=True).returncode == 0
        assert json.loads(target.read_text()) == {"probe": "controlled-after"}
        assert list(parent.iterdir()) == [target]


def test_failed_write_preserves_existing_file_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo.json"
    target.write_text('{"probe":"controlled-existing"}')

    def reject_payload(*args: object, **kwargs: object) -> None:
        raise ValueError("Falha de serialização controlada.")

    monkeypatch.setattr(json, "dump", reject_payload)
    with pytest.raises(ValueError, match="serialização"):
        write_private_json(target, {"probe": "controlled-new"})
    assert target.read_text() == '{"probe":"controlled-existing"}'
    assert list(tmp_path.iterdir()) == [target]
