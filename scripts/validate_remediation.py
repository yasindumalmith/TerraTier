import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


# ============================================================
# COMMAND EXECUTION
# ============================================================

def run_command(command, cwd):
    """Run a command and return its execution result."""

    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def check_required_tools():
    """Make sure Terraform and Checkov are installed."""

    missing = []

    for tool in ["terraform", "checkov"]:
        if shutil.which(tool) is None:
            missing.append(tool)

    if missing:
        raise RuntimeError(
            f"Missing required tools: {', '.join(missing)}"
        )


# ============================================================
# TERRAFORM VALIDATION
# ============================================================

def run_terraform_fmt(terraform_dir: Path):
    """
    Check whether Terraform formatting is valid.

    Formatting failure is recorded but is NOT currently
    treated as a mandatory remediation failure.
    """

    result = run_command(
        [
            "terraform",
            "fmt",
            "-check",
            "-recursive",
            "-no-color",
        ],
        terraform_dir,
    )

    return {
        "pass": result.returncode == 0,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def run_terraform_init(terraform_dir: Path):
    """
    Initialize Terraform without configuring a backend.
    """

    result = run_command(
        [
            "terraform",
            "init",
            "-backend=false",
            "-input=false",
            "-no-color",
        ],
        terraform_dir,
    )

    return {
        "pass": result.returncode == 0,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def run_terraform_validate(terraform_dir: Path):
    """
    Run terraform validate and parse its JSON output.
    """

    result = run_command(
        [
            "terraform",
            "validate",
            "-json",
        ],
        terraform_dir,
    )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "pass": False,
            "valid": False,
            "diagnostics": [],
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    return {
        "pass": result.returncode == 0 and data.get("valid", False),
        "valid": data.get("valid", False),
        "diagnostics": data.get("diagnostics", []),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


# ============================================================
# CHECKOV
# ============================================================

def run_checkov(terraform_dir: Path):
    """
    Run Checkov and return failed findings.
    """

    result = run_command(
        [
            "checkov",
            "-d",
            str(terraform_dir),
            "--framework",
            "terraform",
            "-o",
            "json",
            "--quiet",
            "--soft-fail",
        ],
        terraform_dir,
    )

    if not result.stdout.strip():
        return {
            "success": False,
            "findings": [],
            "error": result.stderr.strip(),
        }

    try:
        checkov_output = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "success": False,
            "findings": [],
            "error": "Could not parse Checkov JSON output.",
        }

    reports = (
        checkov_output
        if isinstance(checkov_output, list)
        else [checkov_output]
    )

    findings = []

    for report in reports:
        failed_checks = (
            report
            .get("results", {})
            .get("failed_checks", [])
        )

        for finding in failed_checks:
            findings.append({
                "check_id": finding.get("check_id"),
                "check_name": finding.get("check_name"),
                "resource": finding.get("resource"),
                "severity": finding.get("severity"),
                "file_path": finding.get("file_path"),
                "file_line_range": finding.get("file_line_range"),
            })

    return {
        "success": True,
        "findings": findings,
        "error": None,
    }


# ============================================================
# FINDING COMPARISON
# ============================================================

def finding_key(finding):
    """
    A finding is identified using both Checkov rule and resource.

    Example:
    CKV_AWS_24 + aws_security_group.sample_01
    """

    return (
        finding.get("check_id"),
        finding.get("resource"),
    )


def target_exists(findings, target_check_id, target_resource):
    return any(
        finding.get("check_id") == target_check_id
        and finding.get("resource") == target_resource
        for finding in findings
    )


def compare_findings(original_findings, remediated_findings):
    """
    Determine which findings were introduced and removed.
    """

    original_map = {
        finding_key(f): f
        for f in original_findings
    }

    remediated_map = {
        finding_key(f): f
        for f in remediated_findings
    }

    original_keys = set(original_map)
    remediated_keys = set(remediated_map)

    new_keys = remediated_keys - original_keys
    removed_keys = original_keys - remediated_keys

    new_findings = [
        remediated_map[key]
        for key in sorted(new_keys)
    ]

    removed_findings = [
        original_map[key]
        for key in sorted(removed_keys)
    ]

    return new_findings, removed_findings


# ============================================================
# RESOURCE PRESERVATION
# ============================================================

def extract_resource_identity(resource_address):
    """
    Convert a Terraform resource address into the HCL block
    type and name.

    Examples:

    aws_security_group.sample_01
        -> ("resource", "aws_security_group", "sample_01")

    data.aws_ami.example
        -> ("data", "aws_ami", "example")

    module.web.aws_instance.server
        -> ("resource", "aws_instance", "server")
    """

    if not resource_address:
        return None

    parts = resource_address.split(".")

    if len(parts) < 2:
        return None

    # Data source
    if parts[0] == "data" and len(parts) >= 3:
        resource_type = parts[1]
        resource_name = re.sub(
            r"\[.*?\]$",
            "",
            parts[2]
        )

        return (
            "data",
            resource_type,
            resource_name,
        )

    # Normal Terraform resource
    if parts[0].startswith(
        ("aws_", "azurerm_", "google_")
    ):
        resource_type = parts[0]
        resource_name = re.sub(
            r"\[.*?\]$",
            "",
            parts[1]
        )

        return (
            "resource",
            resource_type,
            resource_name,
        )

    # Resource inside module
    for index, part in enumerate(parts):
        if part.startswith(
            ("aws_", "azurerm_", "google_")
        ):
            if index + 1 < len(parts):

                resource_name = re.sub(
                    r"\[.*?\]$",
                    "",
                    parts[index + 1]
                )

                return (
                    "resource",
                    part,
                    resource_name,
                )

    return None


def check_resource_preserved(terraform_dir: Path, resource_address):
    """
    Check whether the target Terraform resource still exists.
    """

    identity = extract_resource_identity(
        resource_address
    )

    if identity is None:
        return {
            "preserved": False,
            "reason": "Could not determine resource identity."
        }

    block_type, resource_type, resource_name = identity

    pattern = re.compile(
        rf'\b{re.escape(block_type)}\s+'
        rf'"{re.escape(resource_type)}"\s+'
        rf'"{re.escape(resource_name)}"\s*\{{'
    )

    for tf_file in terraform_dir.rglob("*.tf"):

        content = tf_file.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        if pattern.search(content):
            return {
                "preserved": True,
                "reason": None,
            }

    return {
        "preserved": False,
        "reason": (
            f"{resource_type}.{resource_name} "
            "was not found in remediated Terraform."
        ),
    }


# ============================================================
# SUPPRESSION DETECTION
# ============================================================

SUPPRESSION_PATTERNS = [
    "checkov:skip",
    "skip-check",
    "trivy:ignore",
    "tfsec:ignore",
]


def collect_suppressions(terraform_dir: Path):
    """
    Collect scanner suppression lines.
    """

    suppressions = set()

    for tf_file in terraform_dir.rglob("*.tf"):

        content = tf_file.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for line in content.splitlines():

            lowered = line.lower()

            if any(
                pattern in lowered
                for pattern in SUPPRESSION_PATTERNS
            ):
                suppressions.add(
                    line.strip()
                )

    return suppressions


def check_new_suppressions(
    original_dir: Path,
    remediated_dir: Path
):

    original = collect_suppressions(
        original_dir
    )

    remediated = collect_suppressions(
        remediated_dir
    )

    added = sorted(
        remediated - original
    )

    return {
        "suppression_added": len(added) > 0,
        "added_suppressions": added,
    }


# ============================================================
# FINAL RESULT
# ============================================================

def calculate_final_result(
    terraform_init_pass,
    terraform_valid,
    checkov_success,
    target_present_original,
    target_finding_removed,
    resource_preserved,
    suppression_added,
):
    """
    Pilot PASS/FAIL rule.

    fmt is NOT currently mandatory.
    New Checkov findings are recorded separately because
    severity metadata may currently be unavailable.
    """

    mandatory_checks = [
        terraform_init_pass,
        terraform_valid,
        checkov_success,
        target_present_original,
        target_finding_removed,
        resource_preserved,
        not suppression_added,
    ]

    return (
        "PASS"
        if all(mandatory_checks)
        else "FAIL"
    )


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_remediation(
    finding_id,
    target_check_id,
    target_resource,
    original_dir: Path,
    remediated_dir: Path,
):

    print(f"\nValidating {finding_id}")
    print(f"Target check   : {target_check_id}")
    print(f"Target resource: {target_resource}")
    print()

    # --------------------------------------------------------
    # Terraform formatting
    # --------------------------------------------------------

    print("[1/6] Checking Terraform formatting...")

    fmt_result = run_terraform_fmt(
        remediated_dir
    )

    # --------------------------------------------------------
    # Terraform init
    # --------------------------------------------------------

    print("[2/6] Running terraform init...")

    init_result = run_terraform_init(
        remediated_dir
    )

    # --------------------------------------------------------
    # Terraform validate
    # --------------------------------------------------------

    print("[3/6] Running terraform validate...")

    if init_result["pass"]:
        validate_result = run_terraform_validate(
            remediated_dir
        )
    else:
        validate_result = {
            "pass": False,
            "valid": False,
            "diagnostics": [],
            "stdout": "",
            "stderr": (
                "terraform validate skipped "
                "because terraform init failed."
            ),
        }

    # --------------------------------------------------------
    # Checkov
    # --------------------------------------------------------

    print("[4/6] Scanning original Terraform...")

    original_checkov = run_checkov(
        original_dir
    )

    print("[5/6] Scanning remediated Terraform...")

    remediated_checkov = run_checkov(
        remediated_dir
    )

    original_findings = (
        original_checkov["findings"]
        if original_checkov["success"]
        else []
    )

    remediated_findings = (
        remediated_checkov["findings"]
        if remediated_checkov["success"]
        else []
    )

    target_present_original = target_exists(
        original_findings,
        target_check_id,
        target_resource,
    )

    target_still_exists = target_exists(
        remediated_findings,
        target_check_id,
        target_resource,
    )

    target_finding_removed = (
        target_present_original
        and not target_still_exists
    )

    new_findings, removed_findings = (
        compare_findings(
            original_findings,
            remediated_findings,
        )
    )

    # --------------------------------------------------------
    # Resource / suppression checks
    # --------------------------------------------------------

    print("[6/6] Checking resource preservation and suppression...")

    resource_result = check_resource_preserved(
        remediated_dir,
        target_resource,
    )

    suppression_result = check_new_suppressions(
        original_dir,
        remediated_dir,
    )

    # --------------------------------------------------------
    # Final PASS / FAIL
    # --------------------------------------------------------

    final_result = calculate_final_result(
        terraform_init_pass=init_result["pass"],
        terraform_valid=validate_result["valid"],
        checkov_success=remediated_checkov["success"],
        target_present_original=target_present_original,
        target_finding_removed=target_finding_removed,
        resource_preserved=resource_result["preserved"],
        suppression_added=suppression_result[
            "suppression_added"
        ],
    )

    output = {
        "finding_id": finding_id,
        "target_check_id": target_check_id,
        "target_resource": target_resource,

        "fmt_pass": fmt_result["pass"],

        "terraform_init_pass": init_result["pass"],

        "terraform_valid": validate_result["valid"],

        "original_checkov_scan_success":
            original_checkov["success"],

        "remediated_checkov_scan_success":
            remediated_checkov["success"],

        "target_present_in_original":
            target_present_original,

        "target_finding_removed":
            target_finding_removed,

        "resource_preserved":
            resource_result["preserved"],

        "suppression_added":
            suppression_result[
                "suppression_added"
            ],

        "added_suppressions":
            suppression_result[
                "added_suppressions"
            ],

        "new_findings":
            new_findings,

        "removed_findings":
            removed_findings,

        "original_failed_finding_count":
            len(original_findings),

        "remediated_failed_finding_count":
            len(remediated_findings),

        "final_result":
            final_result,
    }

    return output


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Validate an LLM-generated Terraform remediation."
        )
    )

    parser.add_argument(
        "--finding-id",
        required=True,
    )

    parser.add_argument(
        "--target-check-id",
        required=True,
    )

    parser.add_argument(
        "--target-resource",
        required=True,
    )

    parser.add_argument(
        "--original-dir",
        required=True,
    )

    parser.add_argument(
        "--remediated-dir",
        required=True,
    )

    parser.add_argument(
        "--output",
        default=None,
    )

    args = parser.parse_args()

    check_required_tools()

    original_dir = Path(
        args.original_dir
    ).resolve()

    remediated_dir = Path(
        args.remediated_dir
    ).resolve()

    if not original_dir.exists():
        raise RuntimeError(
            f"Original directory does not exist: "
            f"{original_dir}"
        )

    if not remediated_dir.exists():
        raise RuntimeError(
            f"Remediated directory does not exist: "
            f"{remediated_dir}"
        )

    result = validate_remediation(
        finding_id=args.finding_id,
        target_check_id=args.target_check_id,
        target_resource=args.target_resource,
        original_dir=original_dir,
        remediated_dir=remediated_dir,
    )

    if args.output:
        output_file = Path(
            args.output
        ).resolve()
    else:
        output_file = (
            remediated_dir
            / "result.json"
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            indent=2,
        )

    print()
    print("--------------------------------")
    print("Validation complete")
    print("--------------------------------")

    print(
        f"Terraform valid       : "
        f"{result['terraform_valid']}"
    )

    print(
        f"Target finding removed: "
        f"{result['target_finding_removed']}"
    )

    print(
        f"Resource preserved     : "
        f"{result['resource_preserved']}"
    )

    print(
        f"Suppression added      : "
        f"{result['suppression_added']}"
    )

    print(
        f"New findings           : "
        f"{len(result['new_findings'])}"
    )

    print()
    print(
        f"FINAL RESULT: "
        f"{result['final_result']}"
    )

    print(
        f"Saved result: "
        f"{output_file}"
    )


if __name__ == "__main__":
    main()