from pathlib import Path

from app.token_store import is_protected, protect, unprotect, write_token


def test_token_store_round_trip():
    original = b'{"refresh_token":"test-secret","token":"access"}'
    stored = protect(original)
    assert unprotect(stored) == original
    # On Windows this must be DPAPI-wrapped; development hosts retain plaintext.
    if __import__("os").name == "nt":
        assert is_protected(stored)
    else:
        assert not is_protected(stored)


def test_token_write_is_atomic_and_creates_parent(tmp_path: Path):
    target = tmp_path / "nested" / "tokens" / "channel.json"
    original = b'{"refresh_token":"secret"}'
    write_token(target, original)
    assert target.is_file()
    assert unprotect(target.read_bytes()) == original
    assert list(target.parent.glob("*.tmp")) == []
