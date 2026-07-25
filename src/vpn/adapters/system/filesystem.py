"""Filesystem adapter — wraps file I/O operations."""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

from vpn.core.ports import FilesystemPort

logger = logging.getLogger("vpn")


class FilesystemAdapter:
    """Implements FilesystemPort with standard Python file operations."""

    def read_text(self, path: str) -> str:
        logger.debug("Reading: %s", path)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def read_json(self, path: str) -> dict[str, Any]:
        logger.debug("Reading JSON: %s", path)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def write_text(self, path: str, content: str) -> None:
        logger.debug("Writing: %s", path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_json(self, path: str, data: dict[str, Any]) -> None:
        logger.debug("Writing JSON: %s", path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def copy(self, src: str, dst: str) -> None:
        logger.debug("Copying: %s -> %s", src, dst)
        shutil.copy2(src, dst)

    def makedirs(self, path: str) -> None:
        logger.debug("Creating directories: %s", path)
        os.makedirs(path, exist_ok=True)
