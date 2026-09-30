"""
Build a stdlib zipapp of the groundzero package.

The archive root contains ``groundzero/`` plus ``__main__.py``. Running
``python3 worker.pyz`` imports ``groundzero`` the same way a normal checkout does.
Do not zip the package directory itself: that drops ``groundzero`` off the import path.
"""

import os
import shutil
import tempfile
import zipapp
from typing import Optional

__all__ = ["build_collector_pyz"]

_MAIN = (
    "import sys\n"
    "from groundzero.cli import main\n"
    "if __name__ == \"__main__\":\n"
    "    sys.exit(main() or 0)\n"
)


def _ignore_junk(_directory: str, names: list) -> set:
    skip = set()
    for name in names:
        if name == "__pycache__" or name == ".DS_Store" or name.endswith(".pyc"):
            skip.add(name)
    return skip


def build_collector_pyz(output_path: str, package_root: Optional[str] = None) -> str:
    """Write a collector zipapp. ``package_root`` is the repo root that contains ``groundzero/``."""
    if package_root is None:
        package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    package_dir = os.path.join(package_root, "groundzero")
    if not os.path.isdir(package_dir):
        raise FileNotFoundError("groundzero package not found under %s" % package_root)
    output_path = os.path.abspath(output_path)
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    stage = tempfile.mkdtemp(prefix="gz_pyz_")
    try:
        shutil.copytree(package_dir, os.path.join(stage, "groundzero"), ignore=_ignore_junk)
        with open(os.path.join(stage, "__main__.py"), "w", encoding="utf-8") as fh:
            fh.write(_MAIN)
        zipapp.create_archive(
            stage,
            target=output_path,
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return output_path
