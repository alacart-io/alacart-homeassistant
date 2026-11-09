"""Check that every text the code asks for exists in each language."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "alacart"
LANGUAGES = ["en", "sv"]

# Home Assistant translates these OAuth abort reasons itself, for every integration.
SHARED_ABORTS = {
    "authorize_url_timeout",
    "missing_credentials",
    "no_url_available",
    "oauth_error",
    "oauth_failed",
    "oauth_implementation_unavailable",
    "oauth_timeout",
    "oauth_unauthorized",
    "user_rejected_authorize",
}


def _source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in COMPONENT.glob("*.py"))


def _translations(language: str) -> dict:
    return json.loads((COMPONENT / "translations" / f"{language}.json").read_text("utf-8"))


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_exception_key_has_a_text(language: str) -> None:
    keys = set(re.findall(r'translation_key="(\w+)"', _source()))

    assert keys
    assert keys <= set(_translations(language)["exceptions"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_abort_reason_has_a_text(language: str) -> None:
    reasons = set(re.findall(r'reason="(\w+)"', _source()))
    reasons |= {"already_configured", "reauth_successful", "missing_configuration"}

    assert reasons - SHARED_ABORTS <= set(_translations(language)["config"]["abort"])


def test_both_languages_have_the_same_keys() -> None:
    def keys(node: object, prefix: str = "") -> set[str]:
        if not isinstance(node, dict):
            return {prefix}
        return {key for name, value in node.items() for key in keys(value, f"{prefix}.{name}")}

    assert keys(_translations("en")) == keys(_translations("sv"))


def test_the_manifest_depends_on_my() -> None:
    # The client id's only redirect URI goes through my.home-assistant.io, and Home Assistant
    # uses it only when `my` is loaded. The tests load `my` themselves, so they cannot catch a
    # manifest that drops it.
    manifest = json.loads((COMPONENT / "manifest.json").read_text("utf-8"))

    assert {"application_credentials", "my"} <= set(manifest["dependencies"])
