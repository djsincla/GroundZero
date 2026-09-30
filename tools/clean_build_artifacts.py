#!/usr/bin/env python3
"""
tools/clean_build_artifacts.py — Automated Post-Build Cleanup & Retention

Maintains a rolling retention of the last N versions (default: 3) for compiled
binaries and release archives in dist/ and bin/. Removes obsolete versions,
cleans transient PyInstaller build directories and .spec files, purges loose
unpacked libraries in bin/, and updates unversioned launcher aliases.

Zero external dependencies (Python 3.9+ stdlib only).
"""

import argparse
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

VERSION_PATTERN = re.compile(
    r"^(?P<prefix>VCF-Readiness-Web|vcf-assess|vcf-hci-readiness-adapter|VcfReadinessAdapter|vcf-readiness-adapter)[-_]v?(?P<version>\d+(?:\.\d+)+)(?:-(?P<platform>mac|win|linux))?(?P<suffix>.*)$",
    re.IGNORECASE,
)

ALLOWED_BIN_ROOT_NAMES = {
    "VCF-Readiness-Web-mac",
    "VCF-Readiness-Web-linux",
    "VCF-Readiness-Web.exe",
    "vcf-assess",
    "vcf-assess.exe",
    "VCF-Readiness-Web-mac.app",
    "vcf-assess.app",
    "VcfReadinessAdapter.pak",
    "VcfReadinessAdapter_EXPERIMENTAL.pak",
    "vcf-hci-readiness-adapter.pak",
    "vcf-readiness-adapter.pak",
    "HOW_TO_OPEN_ON_MAC.txt",
    "Launch-VCF-Readiness-Web.command",
    "README.md",
    ".gitkeep",
    ".gitignore",
}


def parse_version_tuple(v_str: str) -> Tuple[int, ...]:
    """Convert version string like '6.15.9' to tuple (6, 15, 9) for numeric sorting."""
    digits = re.findall(r"\d+", v_str)
    return tuple(int(d) for d in digits) if digits else (0,)


def remove_path(path: str) -> bool:
    """Safely remove a file or directory path."""
    try:
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
            return True
        elif os.path.isdir(path):
            shutil.rmtree(path)
            return True
    except Exception as exc:
        sys.stderr.write(f"[WARN] Failed to remove {path}: {exc}\n")
    return False


def clean_scratch_artifacts(workspace_dir: str) -> None:
    """Remove PyInstaller temporary build/ directory and root *.spec files."""
    build_dir = os.path.join(workspace_dir, "build")
    if os.path.isdir(build_dir):
        remove_path(build_dir)
        print("  Cleaned build/ directory")

    # Clean *.spec files in root
    try:
        for fname in os.listdir(workspace_dir):
            if fname.endswith(".spec") and ("VCF-Readiness-Web" in fname or "vcf-assess" in fname):
                spec_path = os.path.join(workspace_dir, fname)
                remove_path(spec_path)
                print(f"  Cleaned {fname}")
    except OSError:
        pass


def clean_loose_bin_files(bin_dir: str) -> None:
    """Remove loose unpacked libraries, frameworks, misplaced archives, and scratch files from bin/."""
    if not os.path.isdir(bin_dir):
        return

    for item in os.listdir(bin_dir):
        item_path = os.path.join(bin_dir, item)

        # Allow recognized aliases and doc files
        if item in ALLOWED_BIN_ROOT_NAMES:
            continue

        # Allow valid versioned executable binaries (excluding .pak files in bin/)
        match = VERSION_PATTERN.match(item)
        if match:
            prefix = match.group("prefix")
            if prefix not in ("vcf-hci-readiness-adapter", "VcfReadinessAdapter", "vcf-readiness-adapter"):
                continue

        # Purge non-whitelisted items (stray subdirectories, misplaced .pak files, loose libs, etc.)
        if remove_path(item_path):
            print(f"  Purged non-whitelisted item in bin/: {item}")


def prune_versions_in_dir(
    target_dir: str,
    keep_count: int,
    platform_filter: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Enforce rolling retention of the last `keep_count` versions per (prefix, platform).
    Returns mapping of group -> list of removed item names.
    """
    if not os.path.isdir(target_dir):
        return {}

    # Group items by (prefix, platform) -> dict of version -> list of paths
    # e.g. ("VCF-Readiness-Web", "mac") -> {"6.15.9": ["...-mac", "...-mac.zip"]}
    groups: Dict[Tuple[str, str], Dict[str, List[str]]] = {}

    for item in os.listdir(target_dir):
        match = VERSION_PATTERN.match(item)
        if not match:
            continue

        prefix = match.group("prefix")
        version = match.group("version")
        plat = (match.group("platform") or "pak").lower()

        if platform_filter and platform_filter != "all" and plat != platform_filter.lower():
            continue

        key = (prefix, plat)
        if key not in groups:
            groups[key] = {}
        groups[key].setdefault(version, []).append(item)

    pruned_summary: Dict[str, List[str]] = {}

    for (prefix, plat), version_map in groups.items():
        # Sort versions descending (newest first)
        sorted_versions = sorted(version_map.keys(), key=parse_version_tuple, reverse=True)
        retained = sorted_versions[:keep_count]
        obsolete = sorted_versions[keep_count:]

        group_label = f"{prefix} ({plat})"
        pruned_summary[group_label] = []

        for old_ver in obsolete:
            for item in version_map[old_ver]:
                item_path = os.path.join(target_dir, item)
                if remove_path(item_path):
                    pruned_summary[group_label].append(item)
                    print(f"  Removed obsolete build from {os.path.basename(target_dir)}: {item}")

        kept_items = [item for v in retained for item in version_map[v]]
        print(f"  Retained {len(retained)} recent version(s) for {group_label}: {', '.join(retained)}")

    return pruned_summary


def update_unversioned_aliases(bin_dir: str, dist_dir: str, platform_filter: Optional[str] = None) -> None:
    """Sync the latest versioned builds to the standard unversioned alias names in bin/."""
    if not os.path.isdir(bin_dir):
        os.makedirs(bin_dir, exist_ok=True)

    # Collect latest versions in bin or dist
    search_dirs = [d for d in (bin_dir, dist_dir) if os.path.isdir(d)]

    # (prefix, platform) -> (latest_version_tuple, latest_version_str, full_path)
    latest_targets: Dict[Tuple[str, str], Tuple[Tuple[int, ...], str, str]] = {}

    for s_dir in search_dirs:
        for item in os.listdir(s_dir):
            match = VERSION_PATTERN.match(item)
            if not match:
                continue

            prefix = match.group("prefix")
            ver_str = match.group("version")
            plat = (match.group("platform") or "pak").lower()
            suffix = match.group("suffix")

            if platform_filter and platform_filter != "all" and plat != platform_filter.lower():
                continue

            # We want the primary executable or .pak (not .zip)
            if suffix.lower() == ".zip":
                continue

            ver_tuple = parse_version_tuple(ver_str)
            key = (prefix, plat)
            item_path = os.path.join(s_dir, item)

            if key not in latest_targets or ver_tuple > latest_targets[key][0]:
                latest_targets[key] = (ver_tuple, ver_str, item_path)

    # Update aliases in bin/
    for (prefix, plat), (_, ver_str, source_path) in latest_targets.items():
        alias_name = ""
        if prefix == "VCF-Readiness-Web":
            if plat == "mac":
                alias_name = "VCF-Readiness-Web-mac"
            elif plat == "win":
                alias_name = "VCF-Readiness-Web.exe"
            elif plat == "linux":
                alias_name = "VCF-Readiness-Web-linux"
        elif prefix == "vcf-assess":
            if plat == "mac":
                alias_name = "vcf-assess"
            elif plat == "win":
                alias_name = "vcf-assess.exe"
            elif plat == "linux":
                alias_name = "vcf-assess"
        elif prefix in ("VcfReadinessAdapter", "vcf-hci-readiness-adapter", "vcf-readiness-adapter"):
            alias_name = f"{prefix}.pak"

        if alias_name:
            dest_path = os.path.join(bin_dir, alias_name)
            try:
                if os.path.isdir(source_path):
                    if os.path.exists(dest_path):
                        remove_path(dest_path)
                    shutil.copytree(source_path, dest_path)
                else:
                    shutil.copy2(source_path, dest_path)
                    if plat != "win":
                        os.chmod(dest_path, 0o755)
                print(f"  Updated alias bin/{alias_name} -> v{ver_str}")
            except Exception as exc:
                sys.stderr.write(f"[WARN] Failed to update alias {alias_name}: {exc}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean build artifacts with rolling version retention.")
    parser.add_argument("--keep", type=int, default=3, help="Number of recent versions to retain per platform (default: 3)")
    parser.add_argument("--platform", choices=["mac", "win", "linux", "all"], default="all", help="Platform filter")
    parser.add_argument("--workspace-dir", default="", help="Workspace root directory")
    parser.add_argument("--dist-dir", default="", help="dist/ directory path")
    parser.add_argument("--bin-dir", default="", help="bin/ directory path")
    parser.add_argument("--no-scratch-clean", action="store_true", help="Skip cleaning build/ and *.spec")

    args = parser.parse_args()

    workspace_dir = args.workspace_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dist_dir = args.dist_dir or os.path.join(workspace_dir, "dist")
    bin_dir = args.bin_dir or os.path.join(workspace_dir, "bin")

    print(f"==> Running build artifact cleanup (retention: last {args.keep} versions)...")

    if not args.no_scratch_clean:
        clean_scratch_artifacts(workspace_dir)

    clean_loose_bin_files(bin_dir)

    print("==> Pruning dist/ directory...")
    prune_versions_in_dir(dist_dir, keep_count=args.keep, platform_filter=args.platform)

    print("==> Pruning bin/ directory...")
    prune_versions_in_dir(bin_dir, keep_count=args.keep, platform_filter=args.platform)

    print("==> Updating unversioned aliases in bin/...")
    update_unversioned_aliases(bin_dir, dist_dir, platform_filter=args.platform)

    print("==> Artifact cleanup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
