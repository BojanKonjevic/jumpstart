"""Shared fixtures for handler tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.core.handlers.locators import LOCATOR_AT_FILE_END
from zenit.schema.models import LocatorSpec, ManifestBlock


def make_block(
    lines: str, file: Path, addon: str = "redis", point: str = "env_vars"
) -> ManifestBlock:
    return ManifestBlock(
        addon=addon,
        point=point,
        file=str(file),
        lines=lines,
        fingerprint="sha256:abc",
        fingerprint_normalised="sha256:def",
        locator=LocatorSpec(name=LOCATOR_AT_FILE_END, args={}),
    )


@pytest.fixture
def block() -> type[ManifestBlock]:
    # Convenience alias so tests can use `block` fixture name
    return ManifestBlock
