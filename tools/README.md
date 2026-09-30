# Developer & BMC Capture Tools (`tools/`)

> Developer utilities, Clarity asset builders, and Redfish BMC capture tools for offline fixture recording.

---

## Utility Index

### 1. `tools/bundle_assets.py`
- **Purpose:** Fetches the Clarity Design System CSS stylesheet, compresses it using gzip, base64 encodes it, and regenerates `vcf_hci/web/assets.py`.
- **Usage:**
  ```bash
  python tools/bundle_assets.py
  ```
- **Constraint:** Requires an active internet connection. `vcf_hci/web/assets.py` is committed to source control so the application runs offline without running this script.

---

### 2. `tools/crawl_oem_host.py`
- **Purpose:** Pure Python standard library tool (zero external pip dependencies) for recursively crawling live Redfish BMC services, discovering unmapped OEM endpoints, generating DMTF mockup folders/ZIPs, and exporting endpoint coverage manifests.
- **Usage:**
  ```bash
  python tools/crawl_oem_host.py -r 192.0.2.10 -u root -p calvin -D samples/dell_r750 --zip
  ```

---

### 3. `tools/redfishMockupCreate.py`
- **Purpose:** Legacy DMTF tool for crawling a Redfish service (requires `pip install redfish`). For offline/air-gapped environments without pip, prefer `tools/crawl_oem_host.py`.
- **Usage:**
  ```bash
  python tools/redfishMockupCreate.py -r <BMC_IP> -u <USER> -p <PASS> -D <output_dir>
  ```

---

### 4. `tools/anonymize_captured_mockups.py`
- **Purpose:** Pure standard library pipeline for converting raw Redfish mockups and manifest captures from live BMC lab scans into 100% PII-free, sanitized sample directories under `samples/`. Supports 1-step automated ingestion (`--scan-dir`) or explicit multi-file arguments. Replaces private IPs with RFC 5737 documentation addresses, hostnames with `rainpole.net`, hardware serials/MACs with fictitious identifiers, synthesizes DMTF mockup archives from embedded telemetry, and extracts canonical replay fixtures.
- **Usage:**
  ```bash
  # 1-Step Ingestion Mode (Auto-discovers, synthesizes mockup, and sanitizes):
  python3 tools/anonymize_captured_mockups.py --scan-dir /path/to/scan_output_dir

  # Explicit Multi-File Mode:
  python3 tools/anonymize_captured_mockups.py \
      --input-zip /tmp/scans/redfish_mockup_<IP>.zip \
      --actions-json /tmp/scans/actions_manifest_<IP>.json \
      --endpoints-json /tmp/scans/endpoints_manifest_<IP>.json \
      --summary-json /tmp/scans/host_summary_<IP>.json \
      --output-dir samples/<vendor>-<model> \
      --fictitious-ip 192.0.2.x \
      --fictitious-hostname esxi-01.rainpole.net \
      --fictitious-serial <MODEL>-SN001
  ```

---

### 5. `tools/check_data_hygiene.py`
- **Purpose:** Deterministic scanner enforcing the Customer-Facing Data Hygiene policy by checking customer-facing files for internal corporate hostnames, private lab IPs, and Artifactory repository paths.
- **Usage:**
  ```bash
  python tools/check_data_hygiene.py            # scan default customer-facing paths
  python tools/check_data_hygiene.py --all      # scan entire repository (advisory mode)
  python tools/check_data_hygiene.py PATH ...   # scan specific target files or directories
  ```

---

## Source & License Metadata

See [`tools/SOURCE.md`](SOURCE.md) for upstream source attribution and BSD 3-Clause license details for `redfishMockupCreate.py`.
