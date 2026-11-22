import pytest

from app.config import _clean


@pytest.mark.parametrize("value", [None, "", "  ", "chave_groq", "chave_comtrade", "sua_chave_groq", '""'])
def test_placeholders_count_as_missing(value):
    assert _clean(value) is None


def test_real_key_is_kept():
    assert _clean(" abc123 ") == "abc123"
