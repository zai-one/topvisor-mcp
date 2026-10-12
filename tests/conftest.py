import pytest

from zai_topvisor import update_check


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """Keep every test offline: no GitHub request and no DNS lookup from the update check.

    tests/test_update_check.py re-enables the check with an injected or patched fetcher.
    """
    monkeypatch.setenv(update_check.ENV_DISABLE, "1")
