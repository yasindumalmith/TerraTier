import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from run_remediation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    RemediationError,
    build_generation_record,
    call_anthropic,
    extract_text_response,
    import_anthropic_sdk,
    skipped_validation_fields,
    strip_outer_terraform_fence,
    update_metadata_with_generation,
    validate_identifier,
    write_metadata,
)
from validate_project_remediation import (
    check_required_tools,
    failure_result,
    normalize_finding,
    run_checkov,
    terraform_files,
    write_json,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "pilot_samples"
EXPERIMENTS_DIR = PROJECT_ROOT / "project_experiments"
VALIDATOR_SCRIPT = PROJECT_ROOT / "scripts" / "validate_project_remediation.py"

FILE_HEADER_RE = re.compile(r"^# File:[ \t]*(?P<path>[^\r\n]+?)[ \t]*$", re.MULTILINE)
SECTION_FENCE_RE = re.compile(
    r"\A[ \t\r\n]*```(?:terraform|hcl)?[ \t]*\r?\n"
    r"(?P<code>.*?)"
    r"(?:\r?\n)?```[ \t\r\n]*\Z",
    re.IGNORECASE | re.DOTALL,
)

PROMPT_TEMPLATE = """You are remediating security issues in a Terraform project.

The complete project and every security finding detected by Checkov are provided below.

Remediate the detected security issues while preserving the intended infrastructure and application functionality.

Requirements:

- Fix all reported security findings.
- Preserve required Terraform resources.
- Preserve dependencies and references between resources.
- Do not delete resources merely to make findings disappear.
- Do not remove required functionality.
- Do not add Checkov suppression comments.
- Do not disable security scanners.
- Avoid introducing new security findings.
- Keep the Terraform configuration syntactically and semantically valid.
- Preserve the existing file and module structure.
- Return the complete remediated Terraform project, including every original Terraform file.
- Do not return a patch or explanation.

Return each file using exactly this format:

# File: relative/path/to/file.tf
<complete terraform code>

Paths must be project-relative. Do not use absolute paths or parent-directory components.

## Checkov Findings

{findings}

## Complete Terraform Project

{project_files}
"""


class ProjectRemediationError(RuntimeError):
    """A clear, user-facing project remediation runner error."""


def load_project(sample_id: str):
    sample_dir = SAMPLES_DIR / sample_id
    if not sample_dir.is_dir():
        raise ProjectRemediationError(
            f"Terraform sample directory does not exist: {sample_dir}"
        )
    files = terraform_files(sample_dir)
    if not files:
        raise ProjectRemediationError(f"No Terraform files were found in: {sample_dir}")
    return sample_dir, [
        (path.relative_to(sample_dir).as_posix(), path.read_text(encoding="utf-8"))
        for path in files
    ]


def copy_project(source_dir: Path, files, destination_dir: Path):
    destination_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, _ in files:
        destination = destination_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / relative_path, destination)


def build_prompt(files, findings):
    finding_lines = []
    ordered_findings = sorted(
        (normalize_finding(item) for item in findings),
        key=lambda item: (
            item["check_id"] or "",
            item["resource"],
            item["file_path"],
            item["file_line_range"] or [],
        ),
    )
    for index, finding in enumerate(ordered_findings, start=1):
        finding_lines.extend(
            [
                f"Finding {index}",
                f"Check ID: {finding['check_id']}",
                f"Check name: {finding['check_name']}",
                f"Resource: {finding['resource']}",
                f"File path: {finding['file_path']}",
                f"Line range: {json.dumps(finding['file_line_range'])}",
                "",
            ]
        )
    project_sections = [
        f"# File: {relative_path}\n{content.rstrip()}"
        for relative_path, content in files
    ]
    return PROMPT_TEMPLATE.format(
        findings="\n".join(finding_lines).rstrip() or "No failed findings detected.",
        project_files="\n\n".join(project_sections),
    )


def safe_relative_file_path(raw_path: str):
    value = raw_path.strip()
    if not value or "\\" in value or "\x00" in value:
        raise ProjectRemediationError(f"Unsafe returned file path: {raw_path!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ProjectRemediationError(f"Unsafe returned file path: {raw_path!r}")
    if path.suffix != ".tf":
        raise ProjectRemediationError(
            f"The model returned a non-Terraform file path: {raw_path!r}"
        )
    return path.as_posix()


def _strip_section_fence(content: str):
    match = SECTION_FENCE_RE.fullmatch(content)
    return match.group("code") if match else content.strip("\r\n")


def parse_project_response(raw_response: str, expected_paths):
    """Parse complete files while rejecting flattening, duplicates, and unsafe paths."""
    response = strip_outer_terraform_fence(raw_response)
    matches = list(FILE_HEADER_RE.finditer(response))
    if not matches:
        raise ProjectRemediationError(
            "The LLM response did not contain any '# File: relative/path.tf' headers."
        )
    if response[: matches[0].start()].strip():
        raise ProjectRemediationError("Unexpected text appeared before the first file header.")

    parsed = {}
    for index, match in enumerate(matches):
        relative_path = safe_relative_file_path(match.group("path"))
        if relative_path in parsed:
            raise ProjectRemediationError(
                f"The LLM response returned the file more than once: {relative_path}"
            )
        end = matches[index + 1].start() if index + 1 < len(matches) else len(response)
        content = _strip_section_fence(response[match.end() : end])
        if not content.strip():
            raise ProjectRemediationError(
                f"The LLM response returned an empty Terraform file: {relative_path}"
            )
        parsed[relative_path] = content.rstrip() + "\n"

    missing = sorted(set(expected_paths) - set(parsed))
    if missing:
        raise ProjectRemediationError(
            "The LLM response omitted original Terraform files: " + ", ".join(missing)
        )
    return parsed


def reconstruct_project(files, destination_dir: Path):
    root = destination_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in sorted(files.items()):
        destination = (destination_dir / relative_path).resolve()
        try:
            destination.relative_to(root)
        except ValueError as exc:
            raise ProjectRemediationError(
                f"Returned path escapes the run workspace: {relative_path}"
            ) from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def prepare_run_directory(run_dir: Path):
    artifacts = [
        run_dir / name
        for name in ("prompt.txt", "raw_response.txt", "metadata.json", "result.json")
        if (run_dir / name).exists()
    ]
    if artifacts or (run_dir / "remediated").exists():
        raise ProjectRemediationError(
            f"Run artifacts already exist and will not be overwritten: {run_dir}"
        )
    run_dir.mkdir(parents=True, exist_ok=True)


def metadata_for(args, prompt: str, original_findings):
    return {
        "experiment_unit": "terraform_project",
        "sample_id": args.sample_id,
        "tier": args.tier,
        "model_tier": args.tier,
        "model_id": args.model,
        "run_id": args.run_id,
        "max_tokens": args.max_tokens,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api_request_success": False,
        "api_input_tokens": None,
        "api_output_tokens": None,
        "api_total_tokens": None,
        "request_latency_seconds": None,
        "original_checkov_scan_success": True,
        "original_findings": [normalize_finding(item) for item in original_findings],
        "generation": build_generation_record(None, args.model, args.max_tokens),
    }


def add_generation_outcome(
    result,
    metadata,
    *,
    execution_error=False,
    execution_error_type=None,
    run_status=None,
):
    """Add generation/execution evidence while preserving validator fields."""
    generation = metadata["generation"]
    if generation["output_truncated"]:
        execution_error = True
        execution_error_type = "LLM_OUTPUT_TRUNCATED"
        run_status = "GENERATION_TRUNCATED"
        result["final_result"] = "FAIL"
        reasons = result.setdefault("failure_reasons", [])
        if "LLM_OUTPUT_TRUNCATED" not in reasons:
            reasons.insert(0, "LLM_OUTPUT_TRUNCATED")

    result.update(
        {
            "generation": generation,
            "scanner_clean": bool(
                result.get("remediated_checkov_scan_success")
                and result.get("remediated_failed_finding_count") == 0
            ),
            "execution_error": execution_error,
            "execution_error_type": execution_error_type,
            "run_status": run_status
            or ("COMPLETED" if result.get("final_result") == "PASS" else "VALIDATION_FAILED"),
        }
    )
    return result


def enrich_result(result_file: Path, args, metadata):
    with result_file.open(encoding="utf-8") as file:
        result = json.load(file)
    result = add_generation_outcome(result, metadata)
    result = {
        "sample_id": args.sample_id,
        "tier": args.tier,
        "model_id": args.model,
        "run_id": args.run_id,
        "prompt_sha256": metadata["prompt_sha256"],
        **result,
    }
    write_json(result_file, result)


def add_run_context(result, args, metadata):
    return {
        "sample_id": args.sample_id,
        "tier": args.tier,
        "model_id": args.model,
        "run_id": args.run_id,
        "prompt_sha256": metadata["prompt_sha256"],
        **result,
    }


def run(args):
    validate_identifier(args.sample_id, "--sample-id")
    validate_identifier(args.tier, "--tier")
    validate_identifier(args.run_id, "--run-id")
    if args.max_tokens <= 0:
        raise ProjectRemediationError("--max-tokens must be greater than zero.")

    check_required_tools()
    sample_dir, source_files = load_project(args.sample_id)
    print(f"Scanning original project: {sample_dir}")
    original_scan = run_checkov(sample_dir)
    if not original_scan["success"]:
        raise ProjectRemediationError(
            f"Original Checkov scan failed: {original_scan['error']}"
        )

    prompt = build_prompt(source_files, original_scan["findings"])
    run_dir = EXPERIMENTS_DIR / args.sample_id / args.tier / args.run_id
    original_dir = run_dir / "original"
    remediated_dir = run_dir / "remediated"
    prompt_file = run_dir / "prompt.txt"
    raw_response_file = run_dir / "raw_response.txt"
    metadata_file = run_dir / "metadata.json"
    result_file = run_dir / "result.json"

    anthropic_module = import_anthropic_sdk()
    prepare_run_directory(run_dir)
    copy_project(sample_dir, source_files, original_dir)
    prompt_file.write_text(prompt, encoding="utf-8")
    metadata = metadata_for(args, prompt, original_scan["findings"])
    write_metadata(metadata_file, metadata)

    print(f"Requesting whole-project remediation from {args.model}...")
    message, latency, api_error = call_anthropic(
        anthropic_module, args.model, args.max_tokens, prompt
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    if api_error is not None:
        generation = build_generation_record(
            None, args.model, args.max_tokens, latency, generated_at
        )
        update_metadata_with_generation(metadata, generation)
        metadata["api_error_type"] = type(api_error).__name__
        metadata["api_error_message"] = str(api_error)
        write_metadata(metadata_file, metadata)
        reason = str(api_error)
        result = add_run_context(
            add_generation_outcome(
                failure_result("API_ERROR", reason, original_scan["findings"]),
                metadata,
                execution_error=True,
                execution_error_type="API_ERROR",
                run_status="API_ERROR",
            ),
            args,
            metadata,
        )
        result.update(skipped_validation_fields(reason))
        write_json(result_file, result)
        raise ProjectRemediationError(f"Anthropic API request failed: {api_error}")

    generation = build_generation_record(
        message, args.model, args.max_tokens, latency, generated_at
    )
    update_metadata_with_generation(metadata, generation)
    metadata.update(
        {
            "api_request_success": True,
            "response_id": getattr(message, "id", None),
        }
    )

    try:
        raw_response = extract_text_response(message)
        raw_response_file.write_text(raw_response, encoding="utf-8")
        if generation["output_truncated"]:
            reason = (
                "Anthropic stopped generation because the output token limit was reached."
            )
            metadata["response_parse_success"] = None
            metadata["response_parse_skipped_reason"] = reason
            write_metadata(metadata_file, metadata)
            result = failure_result(
                "LLM_OUTPUT_TRUNCATED", reason, original_scan["findings"]
            )
            result = add_generation_outcome(
                result,
                metadata,
                execution_error=True,
                execution_error_type="LLM_OUTPUT_TRUNCATED",
                run_status="GENERATION_TRUNCATED",
            )
            result.update(skipped_validation_fields(reason))
            result = add_run_context(result, args, metadata)
            write_json(result_file, result)
            raise ProjectRemediationError(
                f"Claude output was truncated at {args.max_tokens} output tokens. "
                f"Raw output and metadata were saved to {run_dir}."
            )
        parsed_files = parse_project_response(
            raw_response, [relative_path for relative_path, _ in source_files]
        )
        reconstruct_project(parsed_files, remediated_dir)
    except (RemediationError, ProjectRemediationError, OSError) as exc:
        if generation["output_truncated"]:
            if result_file.exists():
                raise
            reason = (
                "Anthropic stopped generation because the output token limit was "
                "reached; no usable text response was available."
            )
            if not raw_response_file.exists():
                raw_response_file.write_text("", encoding="utf-8")
            metadata["response_parse_success"] = None
            metadata["response_parse_skipped_reason"] = reason
            metadata["response_error"] = str(exc)
            write_metadata(metadata_file, metadata)
            result = failure_result(
                "LLM_OUTPUT_TRUNCATED", reason, original_scan["findings"]
            )
            result = add_generation_outcome(
                result,
                metadata,
                execution_error=True,
                execution_error_type="LLM_OUTPUT_TRUNCATED",
                run_status="GENERATION_TRUNCATED",
            )
            result.update(skipped_validation_fields(reason))
            result = add_run_context(result, args, metadata)
            write_json(result_file, result)
            raise ProjectRemediationError(reason) from exc
        metadata["response_parse_success"] = False
        metadata["response_error"] = str(exc)
        write_metadata(metadata_file, metadata)
        result = failure_result(
            "LLM_OUTPUT_PARSE_FAILURE", str(exc), original_scan["findings"]
        )
        result = add_generation_outcome(
            result,
            metadata,
            execution_error=True,
            execution_error_type="LLM_OUTPUT_PARSE_FAILURE",
            run_status="GENERATION_FAILED",
        )
        result.update(skipped_validation_fields(str(exc)))
        result = add_run_context(
            result,
            args,
            metadata,
        )
        write_json(result_file, result)
        raise ProjectRemediationError(str(exc)) from exc

    metadata["response_parse_success"] = True
    metadata["returned_files"] = sorted(parsed_files)
    write_metadata(metadata_file, metadata)

    command = [
        sys.executable,
        str(VALIDATOR_SCRIPT),
        "--original-dir",
        str(original_dir),
        "--remediated-dir",
        str(remediated_dir),
        "--output",
        str(result_file),
    ]
    validation = subprocess.run(command, cwd=PROJECT_ROOT)
    metadata["validation_exit_code"] = validation.returncode
    metadata["validation_completed"] = validation.returncode == 0 and result_file.is_file()
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_metadata(metadata_file, metadata)
    if validation.returncode != 0 or not result_file.is_file():
        reason = f"Project validator exited with status {validation.returncode}."
        result = add_run_context(
            add_generation_outcome(
                failure_result(
                    "EXECUTION_ERROR",
                    reason,
                    original_scan["findings"],
                ),
                metadata,
                execution_error=True,
                execution_error_type="VALIDATOR_EXECUTION_ERROR",
                run_status="VALIDATION_FAILED",
            ),
            args,
            metadata,
        )
        write_json(result_file, result)
        raise ProjectRemediationError(
            f"Project validator exited with status {validation.returncode}."
        )

    enrich_result(result_file, args, metadata)
    print(f"Project experiment artifacts saved to {run_dir}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run one whole-Terraform-project remediation attempt."
    )
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--tier", default="tier_1")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--run-id", default="run_01")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser.parse_args()


def main():
    try:
        run(parse_args())
        return 0
    except (ProjectRemediationError, RemediationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Project remediation interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
