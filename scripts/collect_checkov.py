import csv
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

SAMPLES_DIR = PROJECT_ROOT / "pilot_samples"
RAW_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "checkov"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def run_checkov(sample_dir: Path):
    """
    Run Checkov against one Terraform sample directory.
    """

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
            f"Could not parse Checkov JSON for {sample_dir.name}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        ) from exc


def get_failed_checks(checkov_output):
    """
    Checkov may return either one report object or
    multiple framework report objects.
    """

    reports = (
        checkov_output
        if isinstance(checkov_output, list)
        else [checkov_output]
    )

    failed_checks = []

    for report in reports:
        results = report.get("results", {})
        failed_checks.extend(results.get("failed_checks", []))

    return failed_checks


def get_resource_type(resource):
    """
    Example:
    aws_security_group.example
        -> aws_security_group
    """

    if not resource:
        return None

    return resource.split(".")[0]


def normalize_finding(sample_id, finding):
    """
    Convert a Checkov finding into one dataset row.
    """

    check_result = finding.get("check_result", {})

    if isinstance(check_result, dict):
        result_value = check_result.get("result")
    else:
        result_value = check_result

    line_range = finding.get("file_line_range")

    start_line = None
    end_line = None

    if isinstance(line_range, list) and len(line_range) >= 2:
        start_line = line_range[0]
        end_line = line_range[1]

    resource = finding.get("resource")

    return {
        "sample_id": sample_id,
        "check_id": finding.get("check_id"),
        "check_name": finding.get("check_name"),
        "severity": finding.get("severity"),
        "resource": resource,
        "resource_type": get_resource_type(resource),
        "file_path": finding.get("file_path"),
        "start_line": start_line,
        "end_line": end_line,
        "guideline": finding.get("guideline"),
        "check_result": result_value,
    }


def main():

    all_findings = []

    sample_dirs = sorted(
        directory
        for directory in SAMPLES_DIR.iterdir()
        if directory.is_dir()
    )

    print(f"Found {len(sample_dirs)} Terraform samples.\n")

    for sample_dir in sample_dirs:

        sample_id = sample_dir.name

        print(f"Scanning {sample_id}...")

        try:
            checkov_output = run_checkov(sample_dir)

        except Exception as exc:
            print(f"ERROR: {exc}")
            continue

        # --------------------------------------------------
        # Save original Checkov output
        # --------------------------------------------------

        raw_file = RAW_OUTPUT_DIR / f"{sample_id}.json"

        with raw_file.open("w", encoding="utf-8") as file:
            json.dump(
                checkov_output,
                file,
                indent=2,
            )

        # --------------------------------------------------
        # Extract failed findings
        # --------------------------------------------------

        failed_checks = get_failed_checks(checkov_output)

        print(f"  Failed checks: {len(failed_checks)}")

        for finding in failed_checks:

            row = normalize_finding(
                sample_id,
                finding,
            )

            all_findings.append(row)

    # ------------------------------------------------------
    # Save normalized CSV
    # ------------------------------------------------------

    output_csv = PROCESSED_DIR / "findings.csv"

    fieldnames = [
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

    with output_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(all_findings)

    print()
    print("--------------------------------")
    print("Collection finished")
    print("--------------------------------")
    print(f"Samples scanned : {len(sample_dirs)}")
    print(f"Findings        : {len(all_findings)}")
    print(f"Dataset         : {output_csv}")


if __name__ == "__main__":
    main()
