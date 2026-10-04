import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

from validate_remediation import (
    check_new_suppressions,
    check_required_tools,
    run_checkov,
    run_terraform_fmt,
    run_terraform_init,
    run_terraform_validate,
)


IGNORED_DIRECTORY_NAMES = {
    ".terraform",
    "experiments",
    "project_experiments",
    "remediated",
    "__pycache__",
}

RESOURCE_BLOCK_RE = re.compile(
    r'\b(resource|data)\s+"([^"]+)"\s+"([^"]+)"\s*\{'
)
MODULE_BLOCK_RE = re.compile(r'\bmodule\s+"([^"]+)"\s*\{')
MODULE_SOURCE_RE = re.compile(r'^\s*source\s*=\s*"([^"]+)"', re.MULTILINE)
INDEX_SUFFIX_RE = re.compile(r"(?:\[[^\]]*\])+$")


class ProjectValidationError(RuntimeError):
    """A clear, user-facing project validation error."""


def terraform_files(project_dir: Path):
    """Return relevant Terraform files in deterministic project-relative order."""
    files = []
    for path in project_dir.rglob("*.tf"):
        relative = path.relative_to(project_dir)
        if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts[:-1]):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(project_dir).as_posix())


def normalize_relative_path(value):
    """Normalize Checkov paths while retaining their module directory."""
    if not value:
        return ""
    normalized = str(value).replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    return PurePosixPath(*parts).as_posix() if parts else ""


def normalize_resource_address(value):
    """Normalize instance suffixes without discarding module address segments."""
    if not value:
        return ""
    return ".".join(INDEX_SUFFIX_RE.sub("", part) for part in str(value).split("."))


def normalize_finding(finding):
    line_range = finding.get("file_line_range")
    if not isinstance(line_range, list) or len(line_range) < 2:
        line_range = None
    return {
        "check_id": finding.get("check_id"),
        "check_name": finding.get("check_name"),
        "resource": normalize_resource_address(finding.get("resource")),
        "severity": finding.get("severity"),
        "file_path": normalize_relative_path(finding.get("file_path")),
        "file_line_range": line_range,
    }


def finding_key(finding):
    normalized = normalize_finding(finding)
    return (
        normalized["check_id"] or "",
        normalized["resource"],
        normalized["file_path"],
    )


def compare_project_findings(original_findings, remediated_findings):
    """Compare findings with module-aware resource and file identities."""
    original_map = {finding_key(item): normalize_finding(item) for item in original_findings}
    remediated_map = {
        finding_key(item): normalize_finding(item) for item in remediated_findings
    }
    original_keys = set(original_map)
    remediated_keys = set(remediated_map)
    removed = [original_map[key] for key in sorted(original_keys - remediated_keys)]
    remaining = [original_map[key] for key in sorted(original_keys & remediated_keys)]
    new = [remediated_map[key] for key in sorted(remediated_keys - original_keys)]
    return removed, remaining, new


def _matching_brace(text: str, opening_index: int):
    """Find a block's closing brace while ignoring braces in strings/comments."""
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening_index

    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "#":
            line_comment = True
        elif char == "/" and following == "/":
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            block_comment = True
            index += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def iter_blocks(content: str, pattern):
    for match in pattern.finditer(content):
        opening_index = content.find("{", match.start(), match.end())
        closing_index = _matching_brace(content, opening_index)
        if closing_index is not None:
            yield match, content[opening_index + 1 : closing_index]


def discover_module_directories(project_dir: Path):
    """Map local module directories to their Terraform module address prefix."""
    mapping = {project_dir.resolve(): ""}
    pending = [project_dir.resolve()]
    while pending:
        current_dir = pending.pop(0)
        current_prefix = mapping[current_dir]
        for tf_file in sorted(current_dir.glob("*.tf")):
            content = tf_file.read_text(encoding="utf-8", errors="ignore")
            for match, body in iter_blocks(content, MODULE_BLOCK_RE):
                source_match = MODULE_SOURCE_RE.search(body)
                if not source_match:
                    continue
                source = source_match.group(1)
                if not source.startswith("."):
                    continue
                module_dir = (current_dir / source).resolve()
                try:
                    module_dir.relative_to(project_dir.resolve())
                except ValueError:
                    continue
                if not module_dir.is_dir():
                    continue
                name = match.group(1)
                prefix = f"{current_prefix}.module.{name}" if current_prefix else f"module.{name}"
                if module_dir not in mapping:
                    mapping[module_dir] = prefix
                    pending.append(module_dir)
    return mapping


def discover_resources(project_dir: Path):
    """Discover managed/data resource identities without flattening local modules."""
    module_dirs = discover_module_directories(project_dir)
    resources = {}
    for tf_file in terraform_files(project_dir):
        content = tf_file.read_text(encoding="utf-8", errors="ignore")
        parent = tf_file.parent.resolve()
        module_prefix = module_dirs.get(parent)
        if module_prefix is None:
            relative_parent = tf_file.parent.relative_to(project_dir).as_posix()
            module_prefix = f"directory:{relative_parent}"
        for match in RESOURCE_BLOCK_RE.finditer(content):
            block_type, resource_type, resource_name = match.groups()
            base = (
                f"data.{resource_type}.{resource_name}"
                if block_type == "data"
                else f"{resource_type}.{resource_name}"
            )
            address = f"{module_prefix}.{base}" if module_prefix else base
            resources[address] = {
                "address": address,
                "block_type": block_type,
                "resource_type": resource_type,
                "resource_name": resource_name,
                "file_path": tf_file.relative_to(project_dir).as_posix(),
            }
    return resources


def compare_resources(original_dir: Path, remediated_dir: Path):
    original = discover_resources(original_dir)
    remediated = discover_resources(remediated_dir)
    missing = [original[key] for key in sorted(set(original) - set(remediated))]
    return {
        "resources_preserved": not missing,
        "missing_resources": missing,
        "original_resource_count": len(original),
        "remediated_resource_count": len(remediated),
    }


def compare_project_files(original_dir: Path, remediated_dir: Path):
    original = {
        path.relative_to(original_dir).as_posix() for path in terraform_files(original_dir)
    }
    remediated = {
        path.relative_to(remediated_dir).as_posix()
        for path in terraform_files(remediated_dir)
    }
    missing = sorted(original - remediated)
    return {
        "project_structure_preserved": not missing,
        "missing_terraform_files": missing,
        "added_terraform_files": sorted(remediated - original),
    }


def failure_result(reason: str, message: str, original_findings=None):
    """Create a schema-compatible result when validation cannot be reached."""
    original_scan_success = original_findings is not None
    original_findings = [normalize_finding(item) for item in (original_findings or [])]
    return {
        "experiment_unit": "terraform_project",
        "fmt_pass": False,
        "terraform_init_pass": False,
        "terraform_valid": False,
        "original_checkov_scan_success": original_scan_success,
        "remediated_checkov_scan_success": False,
        "original_findings": original_findings,
        "remediated_findings": [],
        "original_failed_finding_count": len(original_findings),
        "remediated_failed_finding_count": 0,
        "removed_original_findings": [],
        "remaining_original_findings": original_findings,
        "new_findings": [],
        "removed_original_finding_count": 0,
        "remaining_original_finding_count": len(original_findings),
        "new_finding_count": 0,
        "remediation_coverage": 0.0 if original_findings else 1.0,
        "resources_preserved": False,
        "missing_resources": [],
        "project_structure_preserved": False,
        "missing_terraform_files": [],
        "added_terraform_files": [],
        "suppression_added": False,
        "added_suppressions": [],
        "semantic_validation_status": "not_run",
        "semantic_validation_configured": False,
        "semantic_validation_pass": False,
        "scanner_clean": False,
        "execution_error": True,
        "execution_error_type": reason,
        "run_status": "VALIDATION_FAILED",
        "final_result": "FAIL",
        "failure_reasons": [reason],
        "failure_details": {reason: message},
    }


def project_failure_reasons(
    *,
    fmt_pass,
    init_pass,
    terraform_valid,
    original_scan_success,
    remediated_scan_success,
    remaining_finding_count,
    new_finding_count,
    resources_preserved,
    suppression_added,
    semantic_validation_pass,
):
    """Apply the project-level PASS rule; fmt_pass is a metric, not a gate."""
    checks = [
        (init_pass, "TERRAFORM_INIT_FAILURE"),
        (terraform_valid, "TERRAFORM_VALIDATE_FAILURE"),
        (original_scan_success, "ORIGINAL_SCAN_FAILURE"),
        (remediated_scan_success, "REMEDIATED_SCAN_FAILURE"),
        (remaining_finding_count == 0, "REMAINING_SECURITY_FINDINGS"),
        (new_finding_count == 0, "NEW_SECURITY_FINDINGS"),
        (resources_preserved, "RESOURCE_REMOVED"),
        (not suppression_added, "SUPPRESSION_ADDED"),
        (semantic_validation_pass, "SEMANTIC_VALIDATION_FAILURE"),
    ]
    return [reason for passed, reason in checks if not passed]


def validate_project_remediation(original_dir: Path, remediated_dir: Path):
    print("[1/7] Checking Terraform formatting...")
    fmt_result = run_terraform_fmt(remediated_dir)
    print("[2/7] Running terraform init -backend=false...")
    init_result = run_terraform_init(remediated_dir)
    print("[3/7] Running terraform validate...")
    if init_result["pass"]:
        validate_result = run_terraform_validate(remediated_dir)
    else:
        validate_result = {
            "pass": False,
            "valid": False,
            "diagnostics": [],
            "stdout": "",
            "stderr": "terraform validate skipped because terraform init failed.",
        }

    print("[4/7] Scanning original Terraform with Checkov...")
    original_scan = run_checkov(original_dir)
    print("[5/7] Scanning remediated Terraform with Checkov...")
    remediated_scan = run_checkov(remediated_dir)
    original_findings = original_scan["findings"] if original_scan["success"] else []
    remediated_findings = (
        remediated_scan["findings"] if remediated_scan["success"] else []
    )
    if original_scan["success"] and remediated_scan["success"]:
        removed, remaining, new = compare_project_findings(
            original_findings, remediated_findings
        )
    elif original_scan["success"]:
        removed = []
        remaining = [normalize_finding(item) for item in original_findings]
        new = []
    else:
        removed, remaining, new = [], [], []

    print("[6/7] Checking resources, files, and suppressions...")
    resource_result = compare_resources(original_dir, remediated_dir)
    structure_result = compare_project_files(original_dir, remediated_dir)
    suppression_result = check_new_suppressions(original_dir, remediated_dir)

    print("[7/7] Applying project-level PASS rule...")
    original_count = len({finding_key(item) for item in original_findings})
    if original_count:
        coverage = round(len(removed) / original_count, 6)
    else:
        coverage = 1.0 if original_scan["success"] and remediated_scan["success"] else 0.0
    semantic_pass = (
        resource_result["resources_preserved"]
        and structure_result["project_structure_preserved"]
    )

    failure_reasons = project_failure_reasons(
        fmt_pass=fmt_result["pass"],
        init_pass=init_result["pass"],
        terraform_valid=validate_result["valid"],
        original_scan_success=original_scan["success"],
        remediated_scan_success=remediated_scan["success"],
        remaining_finding_count=len(remaining),
        new_finding_count=len(new),
        resources_preserved=resource_result["resources_preserved"],
        suppression_added=suppression_result["suppression_added"],
        semantic_validation_pass=semantic_pass,
    )
    final_result = "PASS" if not failure_reasons else "FAIL"
    scanner_clean = remediated_scan["success"] and not remediated_findings

    return {
        "experiment_unit": "terraform_project",
        "fmt_pass": fmt_result["pass"],
        "terraform_init_pass": init_result["pass"],
        "terraform_valid": validate_result["valid"],
        "original_checkov_scan_success": original_scan["success"],
        "remediated_checkov_scan_success": remediated_scan["success"],
        "original_findings": [normalize_finding(item) for item in original_findings],
        "remediated_findings": [normalize_finding(item) for item in remediated_findings],
        "original_failed_finding_count": original_count,
        "remediated_failed_finding_count": len(
            {finding_key(item) for item in remediated_findings}
        ),
        "removed_original_findings": removed,
        "remaining_original_findings": remaining,
        "new_findings": new,
        "removed_original_finding_count": len(removed),
        "remaining_original_finding_count": len(remaining),
        "new_finding_count": len(new),
        "remediation_coverage": coverage,
        **resource_result,
        **structure_result,
        "suppression_added": suppression_result["suppression_added"],
        "added_suppressions": suppression_result["added_suppressions"],
        "semantic_validation_status": "generic_invariants_only",
        "semantic_validation_configured": False,
        "semantic_validation_pass": semantic_pass,
        "scanner_clean": scanner_clean,
        "execution_error": False,
        "execution_error_type": None,
        "run_status": "COMPLETED" if final_result == "PASS" else "VALIDATION_FAILED",
        "validation_skipped": False,
        "terraform_command_results": {
            "fmt": fmt_result,
            "init": init_result,
            "validate": validate_result,
        },
        "terraform_diagnostics": validate_result["diagnostics"],
        "scan_errors": {
            "original": original_scan["error"],
            "remediated": remediated_scan["error"],
        },
        "final_result": final_result,
        "failure_reasons": failure_reasons,
    }


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
    temporary.replace(path)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate a complete LLM-remediated Terraform project."
    )
    parser.add_argument("--original-dir", required=True)
    parser.add_argument("--remediated-dir", required=True)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        check_required_tools()
        original_dir = Path(args.original_dir).resolve()
        remediated_dir = Path(args.remediated_dir).resolve()
        if not original_dir.is_dir():
            raise ProjectValidationError(f"Original directory does not exist: {original_dir}")
        if not remediated_dir.is_dir():
            raise ProjectValidationError(
                f"Remediated directory does not exist: {remediated_dir}"
            )
        output_file = (
            Path(args.output).resolve()
            if args.output
            else remediated_dir.parent / "result.json"
        )
        result = validate_project_remediation(original_dir, remediated_dir)
        write_json(output_file, result)
        print(f"FINAL RESULT: {result['final_result']}")
        print(f"Saved result: {output_file}")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Project validation interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
