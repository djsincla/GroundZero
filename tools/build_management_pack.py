#!/usr/bin/env python3
"""
VCF Operations 9.1 Management Pack Builder & Bundle Packaging Tool.

Validates the adapter schema, manifest, content packs, and builds a distribution
.pak archive ready for deployment into VMware Cloud Foundation Operations 9.1.
"""
import argparse
import json
import logging
import os
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, Optional, Set, Union

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mp_builder")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP_DIR = os.path.join(REPO_ROOT, "management_pack")
VCF_HCI_DIR = os.path.join(REPO_ROOT, "vcf_hci")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from vcf_hci.constants import TOOL_VERSION
except ImportError:
    TOOL_VERSION = "9.0.0"


def validate_manifest(mp_dir: str) -> Dict[str, Any]:
    """Validate manifest.txt JSON metadata."""
    txt_path = os.path.join(mp_dir, "manifest.txt")
    if not os.path.isfile(txt_path):
        raise FileNotFoundError(f"Missing manifest.txt at {txt_path}")

    with open(txt_path, encoding="utf-8") as f:
        data = json.load(f)

    required_keys = ["name", "version", "adapter_kinds", "display_name"]
    for k in required_keys:
        if k not in data:
            raise ValueError(f"manifest.txt is missing required key: {k}")

    # Aliases for backwards compatibility
    raw_name = data["name"]
    clean_id = raw_name.removeprefix("iSDK_") if hasattr(raw_name, "removeprefix") else (raw_name[5:] if raw_name.startswith("iSDK_") else raw_name)
    data.setdefault("id", clean_id)
    if "adapter_kinds" in data and len(data["adapter_kinds"]):
        data.setdefault("adapter_kind", data["adapter_kinds"][0])
    data.setdefault("adapter_version", data["version"])

    logger.info("Manifest validation passed: %s v%s (id=%s)", data.get("display_name", data["name"]), data["version"], data["id"])
    return data


def validate_describe_xml(mp_dir: str) -> None:
    """Validate that describe.xml is well-formed and declares required resource kinds."""
    xml_path = os.path.join(mp_dir, "conf", "describe.xml")
    if not os.path.isfile(xml_path):
        logger.info("conf/describe.xml not present - OK (mp-build generates it from the adapter_definition endpoint)")
        return

    tree = ET.parse(xml_path)
    root = tree.getroot()
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag != "AdapterKind":
        raise ValueError(f"Root tag must be <AdapterKind>, got <{root.tag}>")

    rk_keys = [
        el.get("key")
        for el in root.iter()
        if (el.tag.split("}")[-1] if "}" in el.tag else el.tag) == "ResourceKind"
    ]
    expected_rks = ["PhysicalServer", "Processor", "StorageController", "PhysicalDrive", "NetworkAdapter", "PowerSupplyUnit"]
    for expected in expected_rks:
        if expected not in rk_keys:
            raise ValueError(f"describe.xml is missing ResourceKind: {expected}")

    logger.info("describe.xml validation passed: %d ResourceKinds declared (%s)", len(rk_keys), ", ".join(rk_keys))


def validate_content(mp_dir: str) -> None:
    """Validate JSON content files (symptoms, alerts, dashboards, traversals)."""
    content_dir = os.path.join(mp_dir, "content")
    if not os.path.isdir(content_dir):
        raise FileNotFoundError(f"Missing content directory at {content_dir}")

    # Check alerts & symptoms
    symptoms_file = os.path.join(content_dir, "alerts", "symptoms.json")
    with open(symptoms_file, encoding="utf-8") as f:
        sdata = json.load(f)
        if "symptoms" not in sdata or not len(sdata["symptoms"]):
            raise ValueError("symptoms.json missing 'symptoms' array")

    alerts_file = os.path.join(content_dir, "alerts", "alert_definitions.json")
    with open(alerts_file, encoding="utf-8") as f:
        adata = json.load(f)
        if "alert_definitions" not in adata or not len(adata["alert_definitions"]):
            raise ValueError("alert_definitions.json missing 'alert_definitions' array")

    # Check dashboards
    dash_dir = os.path.join(content_dir, "dashboards")
    dash_files = [os.path.join(dash_dir, f) for f in os.listdir(dash_dir) if f.endswith(".json")]
    if not dash_files:
        raise ValueError("No dashboards found in content/dashboards/")

    for df in dash_files:
        with open(df, encoding="utf-8") as f:
            djson = json.load(f)
            if "name" not in djson or "widgets" not in djson:
                raise ValueError(f"Dashboard {df} missing 'name' or 'widgets'")

    logger.info("Content validation passed: %d symptoms, %d alerts, %d dashboards",
                len(sdata["symptoms"]), len(adata["alert_definitions"]), len(dash_files))


def add_zip_entry(
    zf: zipfile.ZipFile,
    arcname: str,
    src_path: Optional[str] = None,
    data: Optional[Union[str, bytes]] = None,
    dirs_added: Optional[Set[str]] = None,
) -> None:
    """Write a file or byte payload to a zip archive, ensuring all parent

    directories exist as explicit directory entries (mandatory for Java extractors
    such as VCF Operations SyncAdapters.extractFiles).
    """
    if dirs_added is None:
        dirs_added = set()
    norm_arcname = arcname.replace("\\", "/").lstrip("/")
    parts = norm_arcname.split("/")
    for i in range(1, len(parts)):
        parent_dir = "/".join(parts[:i]) + "/"
        if parent_dir not in dirs_added:
            zinfo = zipfile.ZipInfo(parent_dir)
            # POSIX directory mode: drwxr-xr-x
            zinfo.external_attr = (0o755 << 16) | 0o40000
            zf.writestr(zinfo, b"")
            dirs_added.add(parent_dir)

    if src_path is not None:
        zf.write(src_path, arcname=norm_arcname)
    elif data is not None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        zf.writestr(norm_arcname, data)


def build_pak(
    mp_dir: str,
    vcf_hci_dir: str,
    output_path: Optional[str] = None,
    create_alias: bool = False,
    sync_to_integrations: bool = True,
    registry: str = "projects.packages.broadcom.com",
    repository: str = "vmware_aria_operations_integration_sdk_mps/vcfreadinessadapter",
    digest: str = "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    use_default_registry: bool = False,
) -> str:
    """Bundle all Management Pack assets into an installable VCF Operations .pak archive."""
    manifest = validate_manifest(mp_dir)
    validate_describe_xml(mp_dir)
    validate_content(mp_dir)

    version_str = manifest.get("version", TOOL_VERSION)
    adapter_kind_key = manifest["adapter_kinds"][0] if manifest.get("adapter_kinds") else "VcfReadinessAdapter"

    if not output_path:
        output_path = os.path.join(REPO_ROOT, "dist", f"{adapter_kind_key}_{version_str}_EXPERIMENTAL.pak")

    dist_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(dist_dir, exist_ok=True)
    logger.info("Building Management Pack .pak bundle: %s", output_path)

    # 1. Build adapter.zip in memory with explicit directory entries
    import io
    adapter_zip_buffer = io.BytesIO()

    # Generate version.txt content
    version_parts = version_str.strip().split(".")
    major = version_parts[0] if len(version_parts) > 0 else "9"
    minor = version_parts[1] if len(version_parts) > 1 else "0"
    impl = version_parts[2] if len(version_parts) > 2 else "0"
    version_txt = f"Major-Version={major}\nMinor-Version={minor}\nImplementation-Version={impl}\n"

    # Generate <adapter_kind>.conf content (SDK standard: HTTPS / 443)
    conf_lines = [
        f"KINDKEY={adapter_kind_key}",
        "API_VERSION=1.0.0",
        "API_PROTOCOL=https",
        "API_PORT=443",
    ]
    if not use_default_registry and registry:
        conf_lines.append(f"REGISTRY={registry}")
    clean_repo = repository.strip("/")
    conf_lines.append(f"REPOSITORY=/{clean_repo}")
    conf_lines.append(f"DIGEST={digest}\n")
    adapter_conf_content = "\n".join(conf_lines)

    az_dirs: Set[str] = set()
    with zipfile.ZipFile(adapter_zip_buffer, "w", zipfile.ZIP_DEFLATED) as az:
        # Write adapter config
        add_zip_entry(az, f"{adapter_kind_key}.conf", data=adapter_conf_content, dirs_added=az_dirs)

        # Write manifest, eula, icon
        manifest_path = os.path.join(mp_dir, "manifest.txt")
        if os.path.isfile(manifest_path):
            add_zip_entry(az, "manifest.txt", src_path=manifest_path, dirs_added=az_dirs)

        eula_path = os.path.join(mp_dir, manifest.get("eula_file", "eula.txt"))
        if os.path.isfile(eula_path):
            add_zip_entry(az, os.path.basename(eula_path), src_path=eula_path, dirs_added=az_dirs)

        # Write root icon.png (official SDK places icon at root of adapter.zip)
        icon_path = os.path.join(mp_dir, "icon.png")
        if not os.path.isfile(icon_path):
            icon_path = os.path.join(mp_dir, "resources", "icon.png")
        if os.path.isfile(icon_path):
            add_zip_entry(az, "icon.png", src_path=icon_path, dirs_added=az_dirs)

        # Write root localization bundle to adapter.zip (inside resources/ directory)
        root_props_path = os.path.join(mp_dir, "resources", "resources.properties")
        if os.path.isfile(root_props_path):
            add_zip_entry(az, "resources/resources.properties", src_path=root_props_path, dirs_added=az_dirs)

        # Write adapter kind conf directory
        describe_path = os.path.join(mp_dir, "conf", "describe.xml")
        if os.path.isfile(describe_path):
            add_zip_entry(az, f"{adapter_kind_key}/conf/describe.xml", src_path=describe_path, dirs_added=az_dirs)

        props_path = os.path.join(mp_dir, "conf", "resources", "resources.properties")
        if os.path.isfile(props_path):
            add_zip_entry(az, f"{adapter_kind_key}/conf/resources/resources.properties", src_path=props_path, dirs_added=az_dirs)

        add_zip_entry(az, f"{adapter_kind_key}/conf/version.txt", data=version_txt, dirs_added=az_dirs)

        cfg_json = os.path.join(mp_dir, "conf", "adapter_config.json")
        if os.path.isfile(cfg_json):
            add_zip_entry(az, f"{adapter_kind_key}/conf/adapter_config.json", src_path=cfg_json, dirs_added=az_dirs)

    adapter_zip_bytes = adapter_zip_buffer.getvalue()

    # 2. Build the outer .pak archive with explicit directory entries
    pak_dirs: Set[str] = set()
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as pak:
        # Write root manifest.txt
        manifest_path = os.path.join(mp_dir, "manifest.txt")
        if os.path.isfile(manifest_path):
            add_zip_entry(pak, "manifest.txt", src_path=manifest_path, dirs_added=pak_dirs)

        # Write root eula.txt
        eula_path = os.path.join(mp_dir, manifest.get("eula_file", "eula.txt"))
        if os.path.isfile(eula_path):
            add_zip_entry(pak, os.path.basename(eula_path), src_path=eula_path, dirs_added=pak_dirs)

        # Write root icon.png
        icon_path = os.path.join(mp_dir, "icon.png")
        if not os.path.isfile(icon_path):
            icon_path = os.path.join(mp_dir, "resources", "icon.png")
        if os.path.isfile(icon_path):
            add_zip_entry(pak, "icon.png", src_path=icon_path, dirs_added=pak_dirs)

        # Write root localization bundle (required by VCF Operations CaSA)
        root_props_path = os.path.join(mp_dir, "resources", "resources.properties")
        if os.path.isfile(root_props_path):
            add_zip_entry(pak, "resources/resources.properties", src_path=root_props_path, dirs_added=pak_dirs)

        # Write content directory
        content_dir = os.path.join(mp_dir, "content")
        if os.path.isdir(content_dir):
            for root, _, files in os.walk(content_dir):
                for file in files:
                    if file.endswith(".gitkeep") or file.startswith("."):
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, mp_dir).replace("\\", "/")
                    # In dashboards/, VCF Ops requires each dashboard JSON to be inside dashboards/<name>/<name>.json
                    if "dashboards" in rel_path and file.endswith(".json"):
                        stem = os.path.splitext(file)[0]
                        parent = os.path.dirname(rel_path)
                        if not parent.endswith(stem):
                            rel_path = f"{parent}/{stem}/{file}"
                    add_zip_entry(pak, rel_path, src_path=full_path, dirs_added=pak_dirs)

        # Write adapter.zip
        add_zip_entry(pak, "adapter.zip", data=adapter_zip_bytes, dirs_added=pak_dirs)

    file_size_kb = os.path.getsize(output_path) / 1024.0
    logger.info("Successfully packaged installable PAK %s (%.1f KB)", output_path, file_size_kb)

    # 3. Synchronize canonical bundle to integrations/vcf-ops/
    if sync_to_integrations:
        vcf_ops_dir = os.path.join(REPO_ROOT, "integrations", "vcf-ops")
        if os.path.isdir(vcf_ops_dir):
            dest_pak = os.path.join(vcf_ops_dir, os.path.basename(output_path))
            shutil.copy2(output_path, dest_pak)
            logger.info("Synchronized canonical bundle to %s", dest_pak)

    if create_alias:
        alias_path = os.path.join(dist_dir, f"{adapter_kind_key}_EXPERIMENTAL.pak")
        shutil.copy2(output_path, alias_path)
        logger.info("Created unversioned alias: %s", alias_path)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="VCF Operations 9.1 Management Pack Packager")
    parser.add_argument("--validate-only", action="store_true", help="Validate manifest, XML, and content schemas without building archive")
    parser.add_argument("--output", default="", help="Output .pak archive path (defaults to dist/<AdapterKind>_<VERSION>_EXPERIMENTAL.pak)")
    parser.add_argument("--create-alias", action="store_true", help="Also create unversioned alias in dist/")
    parser.add_argument("--registry", default="projects.packages.broadcom.com", help="Container image registry")
    parser.add_argument("--repository", default="vmware_aria_operations_integration_sdk_mps/vcfreadinessadapter", help="Container repository")
    parser.add_argument("--digest", default="sha256:0000000000000000000000000000000000000000000000000000000000000000", help="Container image SHA256 digest")
    parser.add_argument("--use-default-registry", action="store_true", help="Use VCF Operations default registry")
    args = parser.parse_args()

    if args.validate_only:
        validate_manifest(MP_DIR)
        validate_describe_xml(MP_DIR)
        validate_content(MP_DIR)
        print("All validations passed.")
    else:
        out = build_pak(
            MP_DIR,
            VCF_HCI_DIR,
            args.output or None,
            create_alias=args.create_alias,
            registry=args.registry,
            repository=args.repository,
            digest=args.digest,
            use_default_registry=args.use_default_registry,
        )
        print(f"Management Pack built: {out}")


if __name__ == "__main__":
    main()
