"""Structure checks for strings.json / translations (mirrors hassfest rules we hit)."""

import json
from pathlib import Path

import pytest

BASE = Path(__file__).parents[1] / "custom_components/philips_titan"
FILES = ["strings.json", "translations/en.json", "translations/de.json"]


@pytest.mark.parametrize("name", FILES)
def test_exceptions_and_issues_are_mappings(name):
    d = json.loads((BASE / name).read_text())
    for key, value in d.get("exceptions", {}).items():
        assert isinstance(value, dict) and isinstance(value.get("message"), str), key
    for key, value in d.get("issues", {}).items():
        assert {"title", "description"} <= value.keys(), key


def test_translations_have_same_keys():
    def keys(o, prefix=""):
        if isinstance(o, dict):
            return {k2 for k, v in o.items() for k2 in keys(v, f"{prefix}{k}.")}
        return {prefix.rstrip(".")}

    ref = keys(json.loads((BASE / "strings.json").read_text()))
    for name in FILES[1:]:
        assert keys(json.loads((BASE / name).read_text())) == ref, name
