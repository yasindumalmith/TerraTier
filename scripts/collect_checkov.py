import csv
import json
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

SAMPLES_DIR = PROJECT_ROOT / "pilot_samples"
RAW_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "checkov"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# CHECKOV
# ============================================================

def run_checkov(sample_dir: Path):

    command = [
        sys.executable,
        "-m",
        "checkov.main",
        "-d",
        str(sample_dir),
        "--framework",
        "terraform",
        "-o",
        "json",
        "--quiet",
        "--soft-fail",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        raise RuntimeError(
            f"No JSON output returned for {sample_dir.name}\n"
            f"stderr:\n{result.stderr}"
        )

    try:
        return json.loads(result.stdout)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse Checkov JSON for {sample_dir.name}"
        ) from exc


def get_failed_checks(checkov_output):

    reports = (
        checkov_output
        if isinstance(checkov_output, list)
        else [checkov_output]
    )

    failed_checks = []

    for report in reports:
        results = report.get("results", {})
        failed_checks.extend(
            results.get("failed_checks", [])
        )

    return failed_checks


# ============================================================
# TERRAFORM FEATURE EXTRACTION
# ============================================================

def get_resource_type(resource):

    if not resource:
        return None

    parts = resource.split(".")

    # Simple resource:
    # aws_s3_bucket.example
    if len(parts) >= 2 and parts[0] != "module":
        return parts[0]

    # Module resource:
    # module.example.aws_s3_bucket.bucket
    if "module" in parts:
        for part in parts:
            if part.startswith(
                ("aws_", "azurerm_", "google_")
            ):
                return part

    return parts[0]


def get_tf_files(sample_dir: Path):
    """Return all Terraform files inside the sample."""
    return list(sample_dir.rglob("*.tf"))


def get_file_content_for_finding(
    sample_dir: Path,
    file_path: str
):

    if not file_path:
        return ""

    # Checkov often returns /main.tf
    relative_path = file_path.lstrip("/\\")

    terraform_file = sample_dir / relative_path

    if not terraform_file.exists():
        return ""

    return terraform_file.read_text(
        encoding="utf-8",
        errors="ignore"
    )


def extract_affected_code(
    sample_dir: Path,
    finding
):
    """
    Extract only the Terraform block identified
    by Checkov's file_line_range.
    """

    file_path = finding.get("file_path")

    content = get_file_content_for_finding(
        sample_dir,
        file_path
    )

    if not content:
        return ""

    line_range = finding.get("file_line_range")

    if (
        not isinstance(line_range, list)
        or len(line_range) < 2
    ):
        return content

    start_line = line_range[0]
    end_line = line_range[1]

    lines = content.splitlines()

    # Checkov line ranges are normally 1-based
    start_index = max(start_line - 1, 0)

    return "\n".join(
        lines[start_index:end_line]
    )


def count_lines_of_code(code: str):

    count = 0

    for line in code.splitlines():

        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            continue

        if stripped.startswith("//"):
            continue

        count += 1

    return count


def count_attributes(code: str):
    """
    Count HCL-style assignments:
    encrypted = true
    name      = "example"
    """

    pattern = re.compile(
        r'^\s*[A-Za-z_][A-Za-z0-9_-]*\s*=',
        re.MULTILINE
    )

    return len(pattern.findall(code))


def count_nested_blocks(code: str):
    """
    Approximate nested Terraform blocks.

    Example:
        ingress {
        metadata_options {
        lifecycle {
    """

    pattern = re.compile(
        r'^\s*[A-Za-z_][A-Za-z0-9_-]*'
        r'(?:\s+"[^"]+")*'
        r'\s*\{\s*$',
        re.MULTILINE
    )

    block_count = len(pattern.findall(code))

    # Remove outer resource/data/module block
    return max(block_count - 1, 0)


def count_variables(code: str):

    variables = set(
        re.findall(
            r'\bvar\.([A-Za-z0-9_-]+)',
            code
        )
    )

    return len(variables)


def discover_resource_addresses(sample_dir: Path):
    """
    Discover resource addresses defined inside sample.

    Example:
    aws_s3_bucket.example
    aws_security_group.web
    """

    addresses = set()

    resource_pattern = re.compile(
        r'resource\s+"([^"]+)"\s+"([^"]+)"'
    )

    data_pattern = re.compile(
        r'data\s+"([^"]+)"\s+"([^"]+)"'
    )

    for tf_file in get_tf_files(sample_dir):

        content = tf_file.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        # Resources
        for resource_type, name in (
            resource_pattern.findall(content)
        ):
            addresses.add(
                f"{resource_type}.{name}"
            )

        # Data sources
        for resource_type, name in (
            data_pattern.findall(content)
        ):
            addresses.add(
                f"data.{resource_type}.{name}"
            )

    return addresses


def resource_reference_features(
    code: str,
    sample_dir: Path
):

    addresses = discover_resource_addresses(
        sample_dir
    )

    total_references = 0
    related_resources = set()

    for address in addresses:

        occurrences = len(
            re.findall(
                rf'\b{re.escape(address)}\b',
                code
            )
        )

        if occurrences > 0:

            total_references += occurrences

            related_resources.add(address)

    return (
        total_references,
        len(related_resources)
    )


def uses_module(code: str, finding):

    resource = finding.get("resource", "")
    file_path = finding.get("file_path", "")

    if "module." in code:
        return 1

    if resource.startswith("module."):
        return 1

    if "/modules/" in file_path.replace("\\", "/"):
        return 1

    return 0


def uses_for_each(code: str):

    return int(
        bool(
            re.search(
                r'^\s*for_each\s*=',
                code,
                re.MULTILINE
            )
        )
    )


def uses_count(code: str):

    return int(
        bool(
            re.search(
                r'^\s*count\s*=',
                code,
                re.MULTILINE
            )
        )
    )


def extract_features(
    sample_dir: Path,
    finding
):

    code = extract_affected_code(
        sample_dir,
        finding
    )

    (
        resource_reference_count,
        related_resource_count
    ) = resource_reference_features(
        code,
        sample_dir
    )

    return {

        "lines_of_code":
            count_lines_of_code(code),

        "num_attributes":
            count_attributes(code),

        "num_nested_blocks":
            count_nested_blocks(code),

        "num_variables_used":
            count_variables(code),

        "num_resource_references":
            resource_reference_count,

        "num_related_resources":
            related_resource_count,

        "uses_module":
            uses_module(
                code,
                finding
            ),

        "uses_for_each":
            uses_for_each(code),

        "uses_count":
            uses_count(code),

        "num_files_in_sample":
            len(
                get_tf_files(sample_dir)
            ),
    }


# ============================================================
# NORMALIZE CHECKOV FINDING
# ============================================================

def normalize_finding(
    sample_id,
    finding
):

    check_result = finding.get(
        "check_result",
        {}
    )

    if isinstance(check_result, dict):
        result_value = check_result.get(
            "result"
        )
    else:
        result_value = check_result

    line_range = finding.get(
        "file_line_range"
    )

    start_line = None
    end_line = None

    if (
        isinstance(line_range, list)
        and len(line_range) >= 2
    ):
        start_line = line_range[0]
        end_line = line_range[1]

    resource = finding.get("resource")

    return {

        "sample_id":
            sample_id,

        "check_id":
            finding.get("check_id"),

        "check_name":
            finding.get("check_name"),

        "severity":
            finding.get("severity"),

        "resource":
            resource,

        "resource_type":
            get_resource_type(resource),

        "file_path":
            finding.get("file_path"),

        "start_line":
            start_line,

        "end_line":
            end_line,

        "guideline":
            finding.get("guideline"),

        "check_result":
            result_value,
    }


# ============================================================
# CSV
# ============================================================

BASE_FIELDS = [
    "sample_id",
    "check_id",
    "check_name",
    "severity",
    "resource",
    "resource_type",
    "file_path",
    "start_line",
    "end_line",
    "guideline",
    "check_result",
]


FEATURE_FIELDS = [
    "lines_of_code",
    "num_attributes",
    "num_nested_blocks",
    "num_variables_used",
    "num_resource_references",
    "num_related_resources",
    "uses_module",
    "uses_for_each",
    "uses_count",
    "num_files_in_sample",
]


def write_csv(
    output_file,
    rows,
    fieldnames
):

    with output_file.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# MAIN
# ============================================================

def main():

    raw_findings = []
    enriched_findings = []

    sample_dirs = sorted(
        directory
        for directory in SAMPLES_DIR.iterdir()
        if directory.is_dir()
    )

    print(
        f"Found {len(sample_dirs)} Terraform samples.\n"
    )

    for sample_dir in sample_dirs:

        sample_id = sample_dir.name

        print(
            f"Scanning {sample_id}..."
        )

        try:
            checkov_output = run_checkov(
                sample_dir
            )

        except Exception as exc:

            print(
                f"ERROR: {exc}"
            )

            continue

        # ----------------------------------------------------
        # Save raw Checkov JSON
        # ----------------------------------------------------

        raw_file = (
            RAW_OUTPUT_DIR
            / f"{sample_id}.json"
        )

        with raw_file.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                checkov_output,
                file,
                indent=2,
            )

        # ----------------------------------------------------
        # Process findings
        # ----------------------------------------------------

        failed_checks = get_failed_checks(
            checkov_output
        )

        print(
            f"  Failed checks: "
            f"{len(failed_checks)}"
        )

        for finding in failed_checks:

            base_row = normalize_finding(
                sample_id,
                finding
            )

            raw_findings.append(
                base_row
            )

            features = extract_features(
                sample_dir,
                finding
            )

            enriched_row = {
                **base_row,
                **features
            }

            enriched_findings.append(
                enriched_row
            )

    # --------------------------------------------------------
    # Original Checkov dataset
    # --------------------------------------------------------

    findings_csv = (
        PROCESSED_DIR
        / "findings.csv"
    )

    write_csv(
        findings_csv,
        raw_findings,
        BASE_FIELDS
    )

    # --------------------------------------------------------
    # ML feature-enriched dataset
    # --------------------------------------------------------

    enriched_csv = (
        PROCESSED_DIR
        / "enriched_findings.csv"
    )

    write_csv(
        enriched_csv,
        enriched_findings,
        BASE_FIELDS + FEATURE_FIELDS
    )

    print()
    print("--------------------------------")
    print("Collection finished")
    print("--------------------------------")

    print(
        f"Samples scanned : "
        f"{len(sample_dirs)}"
    )

    print(
        f"Findings        : "
        f"{len(raw_findings)}"
    )

    print(
        f"Raw dataset     : "
        f"{findings_csv}"
    )

    print(
        f"Enriched dataset: "
        f"{enriched_csv}"
    )


if __name__ == "__main__":
    main()
