import hashlib
from pathlib import Path

import pytest

from scripts.bootstrap import prepare_redis


def test_bootstrap_preserves_unique_credentials_and_only_hashes_enter_server_acl(
    tmp_path: Path,
) -> None:
    directories = [tmp_path / name for name in ("clients", "server", "admin")]
    prepare_redis(*directories)
    files = {
        path.relative_to(tmp_path): path.read_bytes()
        for directory in directories
        for path in directory.iterdir()
    }
    prepare_redis(*directories)
    assert files == {
        path.relative_to(tmp_path): path.read_bytes()
        for directory in directories
        for path in directory.iterdir()
    }
    passwords = [content for path, content in files.items() if path.name.endswith("-password")]
    assert len(passwords) == len(set(passwords)) == 4
    acl = (directories[1] / "users.acl").read_text(encoding="ascii")
    assert acl.startswith("user default reset off\n")
    for password in passwords:
        assert password.decode("ascii") not in acl
        assert hashlib.sha256(password).hexdigest() in acl
    assert sorted(path.name for path in directories[0].iterdir()) == [
        "cache-password",
        "quota-password",
    ]


def test_invalid_persisted_credential_is_not_silently_rotated(tmp_path: Path) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()
    (clients / "quota-password").write_text("invalid", encoding="ascii")
    with pytest.raises(ValueError, match="refusing to replace"):
        prepare_redis(clients, tmp_path / "server", tmp_path / "admin")
    assert (clients / "quota-password").read_text(encoding="ascii") == "invalid"
