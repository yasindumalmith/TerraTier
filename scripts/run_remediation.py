import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FINDINGS_CSV = PROJECT_ROOT / "data" / "processed" / "enriched_findings.csv"
SAMPLES_DIR = PROJECT_ROOT / "pilot_samples"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
VALIDATOR_SCRIPT = PROJECT_ROOT / "scripts" / "validate_remediation.py"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 4096
GENERATED_ARTIFACTS = (
    "main.tf",
    "prompt.txt",
    "raw_response.txt",
    "metadata.json",
    "result.json",
)

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
OUTER_TERRAFORM_FENCE = re.compile(
    r"\A[ \t\r\n]*```(?:terraform|hcl)[ \t]*\r?\n"
    r"(?P<code>.*?)"
    r"(?:\r?\n)?```[ \t\r\n]*\Z",
    re.IGNORECASE | re.DOTALL,
)

PROMPT_TEMPLATE = """You are remediating a specific security finding in Terraform Infrastructure-as-Code.

## Target Finding

Finding ID: {finding_id}
Checkov Check ID: {check_id}
Checkov Check Name: {check_name}
Affected Resource: {resource}
Resource Type: {resource_type}

## Terraform Configuration

{terraform_code}

## Task

Modify the Terraform configuration to remediate ONLY the target security finding identified above.

Follow these requirements:

1. Make the minimum necessary security change.
2. Preserve the intended infrastructure functionality as much as possible.
3. Do not delete the affected resource simply to remove the finding.
4. Do not add Checkov skip comments, suppression directives, or other mechanisms that bypass security scanning.
5. Do not intentionally modify unrelated resources or unrelated security findings.
6. Preserve existing variable references, resource relationships, and configuration structure unless changing them is necessary for the remediation.
7. Produce syntactically valid Terraform/HCL.
8. Do not invent unnecessary resources, values, or dependencies.
9. If additional Terraform configuration is genuinely required to remediate the finding, add only what is necessary.
10. Do not explain the solution.

## Output Format

Return only the complete corrected Terraform configuration.

Do not include:

- Markdown code fences
- Explanations
- Comments describing your reasoning
- Checkov suppression comments
- Any text before or after the Terraform code
"""


class RemediationError(RuntimeError):
    """A clear, user-facing remediation runner error."""


def validate_identifier(value: str, argument_name: str):
    """Reject identifiers that could escape the experiment directories."""
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise RemediationError(
            f"{argument_name} must contain only letters, numbers, underscores, "
            "and hyphens, and must start with a letter or number."
        )


def load_finding(sample_id: str, check_id: str, resource: str):
    """Load exactly one matching finding from the enriched dataset."""
    if not FINDINGS_CSV.is_file():
        raise RemediationError(f"Finding dataset does not exist: {FINDINGS_CSV}")

    with FINDINGS_CSV.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        required_fields = {
            "sample_id",
            "check_id",
            "check_name",
            "resource",
            "resource_type",
        }
        available_fields = set(reader.fieldnames or [])
        missing_fields = required_fields - available_fields

        if missing_fields:
            raise RemediationError(
                "The enriched findings dataset is missing required columns: "
                + ", ".join(sorted(missing_fields))
            )

        matches = [
            row
            for row in reader
            if row.get("sample_id") == sample_id
            and row.get("check_id") == check_id
            and row.get("resource") == resource
        ]

    if not matches:
        raise RemediationError(
            "No finding matched "
            f"sample_id={sample_id!r}, check_id={check_id!r}, "
            f"resource={resource!r}."
        )

    if len(matches) > 1:
        raise RemediationError(
            f"Expected one matching finding, but found {len(matches)} for "
            f"sample_id={sample_id!r}, check_id={check_id!r}, "
            f"resource={resource!r}."
        )

    return matches[0]


def load_terraform_source(sample_id: str):
    """Read all Terraform files for one pilot sample."""
    sample_dir = SAMPLES_DIR / sample_id

    if not sample_dir.is_dir():
        raise RemediationError(f"Terraform sample directory does not exist: {sample_dir}")

    terraform_files = sorted(
        sample_dir.rglob("*.tf"),
        key=lambda path: path.relative_to(sample_dir).as_posix(),
    )

    if not terraform_files:
        raise RemediationError(f"No Terraform files were found in: {sample_dir}")

    file_contents = [
        (path, path.read_text(encoding="utf-8"))
        for path in terraform_files
    ]

    if len(file_contents) == 1:
        terraform_code = file_contents[0][1]
    else:
        sections = []
        for path, content in file_contents:
            relative_path = path.relative_to(sample_dir).as_posix()
            sections.append(f"# File: {relative_path}\n{content}")
        terraform_code = "\n\n".join(sections)

    return sample_dir, file_contents, terraform_code


def copy_original_files(sample_dir: Path, source_files, original_dir: Path):
    """Refresh the experiment's source copy without touching pilot_samples."""
    original_dir.mkdir(parents=True, exist_ok=True)

    for old_file in original_dir.rglob("*.tf"):
        old_file.unlink()

    for source_file, _ in source_files:
        relative_path = source_file.relative_to(sample_dir)
        destination = original_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)


def build_prompt(finding_id: str, finding, terraform_code: str):
    """Complete the common remediation prompt for one finding."""
    return PROMPT_TEMPLATE.format(
        finding_id=finding_id,
        check_id=finding["check_id"],
        check_name=finding["check_name"],
        resource=finding["resource"],
        resource_type=finding["resource_type"],
        terraform_code=terraform_code,
    )


def strip_outer_terraform_fence(raw_response: str):
    """Remove one whole-response Terraform/HCL fence and nothing else."""
    match = OUTER_TERRAFORM_FENCE.fullmatch(raw_response)

    if not match:
        return raw_response

    code = match.group("code")

    if "```" in code:
        return raw_response

    return code


def extract_text_response(message):
    """Concatenate text content blocks in their returned order."""
    text_blocks = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]

    if not text_blocks:
        raise RemediationError("The Anthropic response contained no text blocks.")

    return "".join(text_blocks)


def build_generation_record(
    message,
    model_id: str,
    max_tokens: int,
    latency_seconds=None,
    generated_at=None,
):
    """Build the canonical generation record from Anthropic response metadata."""
    usage = getattr(message, "usage", None) if message is not None else None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    stop_reason = getattr(message, "stop_reason", None) if message is not None else None
    output_truncated = stop_reason == "max_tokens"
    return {
        "model_id": model_id,
        "response_model_id": (
            getattr(message, "model", None) if message is not None else None
        ),
        "max_output_tokens": max_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stop_reason": stop_reason,
        "stop_sequence": (
            getattr(message, "stop_sequence", None) if message is not None else None
        ),
        "output_truncated": output_truncated,
        "generation_complete": message is not None and not output_truncated,
        "latency_seconds": (
            round(latency_seconds, 6)
            if isinstance(latency_seconds, (int, float))
            else None
        ),
        "generated_at": generated_at,
    }


def update_metadata_with_generation(metadata, generation):
    """Store canonical fields while retaining the pre-existing flat schema."""
    input_tokens = generation["input_tokens"]
    output_tokens = generation["output_tokens"]
    metadata.update(
        {
            "generation": generation,
            "api_input_tokens": input_tokens,
            "api_output_tokens": output_tokens,
            "api_total_tokens": (
                input_tokens + output_tokens
                if isinstance(input_tokens, int) and isinstance(output_tokens, int)
                else None
            ),
            "request_latency_seconds": generation["latency_seconds"],
            "response_model_id": generation["response_model_id"],
            "response_stop_reason": generation["stop_reason"],
            "response_stop_sequence": generation["stop_sequence"],
            "output_truncated": generation["output_truncated"],
            "generation_complete": generation["generation_complete"],
        }
    )


def skipped_validation_fields(reason: str):
    """Describe validation stages deliberately skipped before Terraform extraction."""
    return {
        "validation_skipped": True,
        "validation_skip_reason": reason,
        "validation_stages": {
            stage: {"status": "SKIPPED", "reason": reason}
            for stage in (
                "terraform_fmt",
                "terraform_init",
                "terraform_validate",
                "checkov",
                "resource_preservation",
                "suppression_detection",
                "semantic_validation",
            )
        },
    }


def generation_failure_result(reason: str, error_type: str, generation):
    """Create a compact result when generation cannot reach validation."""
    return {
        "generation": generation,
        "scanner_clean": False,
        "terraform_valid": False,
        "resources_preserved": False,
        "suppression_added": False,
        "execution_error": True,
        "execution_error_type": error_type,
        "run_status": (
            "GENERATION_TRUNCATED"
            if error_type == "LLM_OUTPUT_TRUNCATED"
            else "API_ERROR"
            if error_type == "API_ERROR"
            else "GENERATION_FAILED"
        ),
        "final_result": "FAIL",
        "failure_reasons": [error_type],
        "failure_details": {error_type: reason},
        **skipped_validation_fields(reason),
    }


def enrich_result_with_generation(result, generation):
    """Attach generation evidence without weakening the validator's PASS rule."""
    final_result = result.get("final_result")
    result.update(
        {
            "generation": generation,
            "scanner_clean": bool(
                result.get("remediated_checkov_scan_success")
                and result.get("remediated_failed_finding_count") == 0
            ),
            "execution_error": False,
            "execution_error_type": None,
            "run_status": (
                "COMPLETED" if final_result == "PASS" else "VALIDATION_FAILED"
            ),
            "validation_skipped": False,
        }
    )
    return result


def write_metadata(metadata_file: Path, metadata):
    with metadata_file.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2)
        file.write("\n")


def make_base_metadata(args, finding, prompt: str):
    return {
        "finding_id": args.finding_id,
        "sample_id": args.sample_id,
        "check_id": finding["check_id"],
        "check_name": finding["check_name"],
        "resource": finding["resource"],
        "resource_type": finding["resource_type"],
        "model_id": args.model,
        "model_tier": args.tier,
        "run_id": args.run_id,
        "max_tokens": args.max_tokens,
        "api_input_tokens": None,
        "api_output_tokens": None,
        "api_total_tokens": None,
        "request_latency_seconds": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api_request_success": False,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "generation": build_generation_record(
            None, args.model, args.max_tokens
        ),
    }


def call_anthropic(anthropic_module, model_id: str, max_tokens: int, prompt: str):
    """Make one synchronous Anthropic Messages API request."""
    started = time.perf_counter()

    try:
        client = anthropic_module.Anthropic()
        message = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )
    except Exception as exc:
        latency = time.perf_counter() - started
        return None, latency, exc

    latency = time.perf_counter() - started
    return message, latency, None


def run_validator(args, original_dir: Path, tier_dir: Path):
    """Invoke the existing validator without duplicating its logic."""
    command = [
        sys.executable,
        str(VALIDATOR_SCRIPT),
        "--finding-id",
        args.finding_id,
        "--target-check-id",
        args.check_id,
        "--target-resource",
        args.resource,
        "--original-dir",
        str(original_dir),
        "--remediated-dir",
        str(tier_dir),
    ]

    return subprocess.run(command, cwd=PROJECT_ROOT).returncode


def import_anthropic_sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise RemediationError(
            "The Anthropic Python SDK is not installed. Install it with: "
            ".venv/bin/python -m pip install anthropic"
        ) from exc

    return anthropic


def prepare_output_directory(output_dir: Path, allow_overwrite: bool):
    """Prepare an output directory while retaining Terraform's cache."""
    existing_artifacts = [
        output_dir / filename
        for filename in GENERATED_ARTIFACTS
        if (output_dir / filename).exists()
    ]

    if existing_artifacts and not allow_overwrite:
        existing_names = ", ".join(path.name for path in existing_artifacts)
        raise RemediationError(
            f"Run directory already contains artifacts and will not be overwritten: "
            f"{output_dir} ({existing_names})"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    if allow_overwrite:
        for output_file in existing_artifacts:
            output_file.unlink()


def run(args):
    validate_identifier(args.finding_id, "--finding-id")
    validate_identifier(args.sample_id, "--sample-id")
    validate_identifier(args.tier, "--tier")

    if args.run_id is not None:
        validate_identifier(args.run_id, "--run-id")

    if args.max_tokens <= 0:
        raise RemediationError("--max-tokens must be greater than zero.")

    anthropic_module = import_anthropic_sdk()
    finding = load_finding(args.sample_id, args.check_id, args.resource)
    sample_dir, source_files, terraform_code = load_terraform_source(args.sample_id)

    experiment_dir = EXPERIMENTS_DIR / args.finding_id
    original_dir = experiment_dir / "original"
    tier_dir = experiment_dir / args.tier
    output_dir = tier_dir / args.run_id if args.run_id else tier_dir
    prompt_file = output_dir / "prompt.txt"
    raw_response_file = output_dir / "raw_response.txt"
    generated_file = output_dir / "main.tf"
    metadata_file = output_dir / "metadata.json"
    result_file = output_dir / "result.json"

    prompt = build_prompt(args.finding_id, finding, terraform_code)

    prepare_output_directory(
        output_dir,
        allow_overwrite=args.run_id is None,
    )
    copy_original_files(sample_dir, source_files, original_dir)
    prompt_file.write_text(prompt, encoding="utf-8")

    metadata = make_base_metadata(args, finding, prompt)
    write_metadata(metadata_file, metadata)

    print(f"Requesting remediation from {args.model}...")
    message, latency, api_error = call_anthropic(
        anthropic_module,
        args.model,
        args.max_tokens,
        prompt,
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
        result = {
            "finding_id": args.finding_id,
            "sample_id": args.sample_id,
            "check_id": args.check_id,
            "resource": args.resource,
            **generation_failure_result(str(api_error), "API_ERROR", generation),
        }
        write_metadata(result_file, result)
        raise RemediationError(
            f"Anthropic API request failed: {api_error}. "
            f"Failure metadata was saved to {metadata_file}."
        )

    generation = build_generation_record(
        message, args.model, args.max_tokens, latency, generated_at
    )
    update_metadata_with_generation(metadata, generation)
    metadata.update(
        api_request_success=True,
        response_id=getattr(message, "id", None),
    )

    try:
        raw_response = extract_text_response(message)
    except RemediationError as exc:
        metadata["response_error"] = str(exc)
        write_metadata(metadata_file, metadata)
        if generation["output_truncated"]:
            reason = (
                "Anthropic stopped generation because the output token limit was "
                "reached; the response contained no text blocks."
            )
            raw_response_file.write_text("", encoding="utf-8")
            result = {
                "finding_id": args.finding_id,
                "sample_id": args.sample_id,
                "check_id": args.check_id,
                "resource": args.resource,
                **generation_failure_result(
                    reason, "LLM_OUTPUT_TRUNCATED", generation
                ),
            }
            write_metadata(result_file, result)
            raise RemediationError(reason) from exc
        result = {
            "finding_id": args.finding_id,
            "sample_id": args.sample_id,
            "check_id": args.check_id,
            "resource": args.resource,
            **generation_failure_result(
                str(exc), "LLM_OUTPUT_PARSE_FAILURE", generation
            ),
        }
        write_metadata(result_file, result)
        raise

    raw_response_file.write_text(raw_response, encoding="utf-8")
    if generation["output_truncated"]:
        reason = "Anthropic stopped generation because the output token limit was reached."
        metadata["response_parse_success"] = None
        metadata["response_parse_skipped_reason"] = reason
        write_metadata(metadata_file, metadata)
        result = {
            "finding_id": args.finding_id,
            "sample_id": args.sample_id,
            "check_id": args.check_id,
            "resource": args.resource,
            **generation_failure_result(
                reason, "LLM_OUTPUT_TRUNCATED", generation
            ),
        }
        write_metadata(result_file, result)
        raise RemediationError(
            f"Claude output was truncated at {args.max_tokens} output tokens. "
            f"Raw output and metadata were saved to {output_dir}."
        )

    generated_code = strip_outer_terraform_fence(raw_response)
    generated_file.write_text(generated_code, encoding="utf-8")
    write_metadata(metadata_file, metadata)

    print(f"Generated Terraform saved to {generated_file}")
    print("Running the existing remediation validator...")

    validation_exit_code = run_validator(args, original_dir, output_dir)
    validation_completed = validation_exit_code == 0 and result_file.is_file()

    metadata["validation_exit_code"] = validation_exit_code
    metadata["validation_completed"] = validation_completed
    write_metadata(metadata_file, metadata)

    if validation_exit_code != 0:
        reason = f"The validator exited with status {validation_exit_code}."
        result = {
            "finding_id": args.finding_id,
            "sample_id": args.sample_id,
            "check_id": args.check_id,
            "resource": args.resource,
            "generation": generation,
            "scanner_clean": False,
            "terraform_valid": False,
            "resources_preserved": False,
            "suppression_added": False,
            "execution_error": True,
            "execution_error_type": "VALIDATOR_EXECUTION_ERROR",
            "run_status": "VALIDATION_FAILED",
            "validation_skipped": False,
            "final_result": "FAIL",
            "failure_reasons": ["VALIDATOR_EXECUTION_ERROR"],
            "failure_details": {"VALIDATOR_EXECUTION_ERROR": reason},
        }
        write_metadata(result_file, result)
        raise RemediationError(
            f"The validator exited with status {validation_exit_code}. "
            f"Generated artifacts remain in {output_dir}."
        )

    if not result_file.is_file():
        raise RemediationError(
            f"The validator completed without creating the expected result: {result_file}"
        )

    with result_file.open(encoding="utf-8") as file:
        result = json.load(file)
    result = enrich_result_with_generation(result, generation)
    write_metadata(result_file, result)

    print(f"Experiment artifacts saved to {output_dir}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run one Terraform finding through one Anthropic model."
    )
    parser.add_argument("--finding-id", required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--check-id", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--tier", default="tier_1")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser.parse_args()


def main():
    try:
        run(parse_args())
    except RemediationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Remediation run interrupted.", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
