"""Marketplace-facing metadata in action.yml."""
from pathlib import Path

import yaml

ACTION = yaml.safe_load((Path(__file__).resolve().parents[1] / "action.yml").read_text(encoding="utf-8"))

# From GitHub's metadata-syntax docs (branding.color).
ALLOWED_COLORS = {"white", "black", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark"}


def test_display_name_does_not_match_the_failfirst_account():
    # A GitHub account named "failfirst" exists; Marketplace names can't match a user or org.
    assert ACTION["name"] == "failfirst: verified PR tests"
    assert ACTION["name"].lower() != "failfirst"


def test_description_is_one_short_line():
    description = ACTION["description"]
    assert "\n" not in description
    assert 0 < len(description) <= 125


def test_branding_uses_allowed_values():
    assert ACTION["branding"]["color"] in ALLOWED_COLORS
    assert ACTION["branding"]["icon"] == "check-circle"  # checked against the docs' icon list
