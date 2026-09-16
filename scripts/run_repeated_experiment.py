import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNNER_SCRIPT = PROJECT_ROOT / "scripts" / "run_remediation.py"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"

DEFAULT_RUNS = 5
DEFAULT_MAX_TOKENS = 4096
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
RUN_ARTIFACTS = (
    "main.tf",
    "prompt.txt",
    "raw_response.txt",
    "metadata.json",
    "result.json",
)


class RepeatedExperimentError(RuntimeError):
    """A clear, user-facing repeated experiment error."""


def validate_identifier(value: str, argument_name: str):
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise RepeatedExperimentError(
            f"{argument_name} must contain only letters, numbers, underscores, "
            "and hyphens, and must start with a letter or number."
        )


def read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file), None
    except FileNotFoundError:
        return None, f"Missing file: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Could not read {path}: {exc}"


def has_existing_artifacts(run_dir: Path):
    return any((run_dir / filename).exists() for filename in RUN_ARTIFACTS)


def build_runner_command(args, run_id: str):
    return [
        sys.executable,
        str(RUNNER_SCRIPT),
        "--finding-id",
        args.finding_id,
        "--sample-id",
        args.sample_id,
        "--check-id",
        args.check_id,
        "--resource",
        args.resource,
        "--tier",
        args.tier,
        "--run-id",
        run_id,
        "--model",
        args.model,
        "--max-tokens",
        str(args.max_tokens),
    ]


def classify_run(
    run_id: str,
    run_dir: Path,
    expected_controls,
    runner_exit_code,
    execution_attempted: bool,
    launch_error=None,
):
    metadata_file = run_dir / "metadata.json"
    result_file = run_dir / "result.json"
    metadata, metadata_error = read_json(metadata_file)
    result, result_error = read_json(result_file)

    detail = {
        "run_id": run_id,
        "status": "EXECUTION_ERROR",
        "execution_attempted": execution_attempted,
        "runner_exit_code": runner_exit_code,
        "api_request_success": (
            metadata.get("api_request_success")
            if isinstance(metadata, dict)
            else None
        ),
        "validation_result": (
            result.get("final_result")
            if isinstance(result, dict)
            else None
        ),
        "api_input_tokens": (
            metadata.get("api_input_tokens")
            if isinstance(metadata, dict)
            else None
        ),
        "api_output_tokens": (
            metadata.get("api_output_tokens")
            if isinstance(metadata, dict)
            else None
        ),
        "request_latency_seconds": (
            metadata.get("request_latency_seconds")
            if isinstance(metadata, dict)
            else None
        ),
        "metadata_file": str(metadata_file.relative_to(PROJECT_ROOT)),
        "result_file": str(result_file.relative_to(PROJECT_ROOT)),
    }

    if launch_error is not None:
        detail["error_type"] = "runner_launch_error"
        detail["error_message"] = str(launch_error)
        return detail

    if isinstance(metadata, dict):
        mismatches = [
            f"{field}={metadata.get(field)!r} (expected {expected!r})"
            for field, expected in expected_controls.items()
            if metadata.get(field) != expected
        ]

        if mismatches:
            detail["error_type"] = "experimental_control_mismatch"
            detail["error_message"] = "; ".join(mismatches)
            return detail

    if not isinstance(metadata, dict):
        detail["error_type"] = "metadata_error"
        detail["error_message"] = metadata_error
        return detail

    if not metadata.get("api_request_success"):
        detail["error_type"] = "api_error"
        detail["error_message"] = metadata.get(
            "api_error_message",
            "The API request did not complete successfully.",
        )
        return detail

    if isinstance(result, dict) and result.get("final_result") in {"PASS", "FAIL"}:
        detail["status"] = result["final_result"]
        return detail

    if runner_exit_code not in (None, 0):
        detail["error_type"] = "runtime_error"
        detail["error_message"] = (
            f"run_remediation.py exited with status {runner_exit_code}."
        )
        return detail

    if not isinstance(result, dict):
        detail["error_type"] = "validation_error"
        detail["error_message"] = result_error
        return detail

    detail["error_type"] = "validation_error"
    detail["error_message"] = (
        f"Unexpected final_result in {result_file}: "
        f"{result.get('final_result')!r}"
    )
    return detail


def numeric_values(run_results, field_name: str):
    return [
        result[field_name]
        for result in run_results
        if isinstance(result.get(field_name), (int, float))
        and not isinstance(result.get(field_name), bool)
    ]


def average_or_none(values):
    return round(sum(values) / len(values), 6) if values else None


def build_summary(args, run_results):
    pass_count = sum(result["status"] == "PASS" for result in run_results)
    fail_count = sum(result["status"] == "FAIL" for result in run_results)
    execution_error_count = sum(
        result["status"] == "EXECUTION_ERROR" for result in run_results
    )

    input_tokens = numeric_values(run_results, "api_input_tokens")
    output_tokens = numeric_values(run_results, "api_output_tokens")
    latencies = numeric_values(run_results, "request_latency_seconds")

    prompt_hashes = set()
    for result in run_results:
        metadata_path = PROJECT_ROOT / result["metadata_file"]
        metadata, _ = read_json(metadata_path)
        if isinstance(metadata, dict) and metadata.get("prompt_sha256"):
            prompt_hashes.add(metadata["prompt_sha256"])

    return {
        "finding_id": args.finding_id,
        "sample_id": args.sample_id,
        "check_id": args.check_id,
        "resource": args.resource,
        "tier": args.tier,
        "model_id": args.model,
        "max_tokens": args.max_tokens,
        "total_runs": args.runs,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "execution_error_count": execution_error_count,
        "success_rate": round(pass_count / args.runs, 6),
        "total_input_tokens": sum(input_tokens),
        "total_output_tokens": sum(output_tokens),
        "average_input_tokens": average_or_none(input_tokens),
        "average_output_tokens": average_or_none(output_tokens),
        "average_latency_seconds": average_or_none(latencies),
        "token_observation_count": len(input_tokens),
        "latency_observation_count": len(latencies),
        "prompt_consistent": len(prompt_hashes) <= 1,
        "prompt_sha256": next(iter(prompt_hashes)) if len(prompt_hashes) == 1 else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": run_results,
    }


def write_summary(summary_file: Path, summary):
    temporary_file = summary_file.with_suffix(".json.tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
        file.write("\n")

    temporary_file.replace(summary_file)


def run(args):
    validate_identifier(args.finding_id, "--finding-id")
    validate_identifier(args.sample_id, "--sample-id")
    validate_identifier(args.tier, "--tier")

    if args.runs <= 0:
        raise RepeatedExperimentError("--runs must be greater than zero.")

    if args.max_tokens <= 0:
        raise RepeatedExperimentError("--max-tokens must be greater than zero.")

    tier_dir = EXPERIMENTS_DIR / args.finding_id / args.tier
    tier_dir.mkdir(parents=True, exist_ok=True)
    run_width = max(2, len(str(args.runs)))
    run_results = []

    for run_number in range(1, args.runs + 1):
        run_id = f"run_{run_number:0{run_width}d}"
        run_dir = tier_dir / run_id
        expected_controls = {
            "finding_id": args.finding_id,
            "sample_id": args.sample_id,
            "check_id": args.check_id,
            "resource": args.resource,
            "model_id": args.model,
            "model_tier": args.tier,
            "run_id": run_id,
            "max_tokens": args.max_tokens,
        }

        print()
        print("=" * 64)
        print(f"Starting {args.tier} / {run_id} ({run_number}/{args.runs})")
        print("=" * 64)

        if has_existing_artifacts(run_dir):
            print(f"Existing artifacts found; preserving and summarizing {run_dir}")
            detail = classify_run(
                run_id,
                run_dir,
                expected_controls,
                runner_exit_code=None,
                execution_attempted=False,
            )
            run_results.append(detail)
            continue

        command = build_runner_command(args, run_id)

        try:
            completed = subprocess.run(command, cwd=PROJECT_ROOT)
            detail = classify_run(
                run_id,
                run_dir,
                expected_controls,
                runner_exit_code=completed.returncode,
                execution_attempted=True,
            )
        except OSError as exc:
            detail = classify_run(
                run_id,
                run_dir,
                expected_controls,
                runner_exit_code=None,
                execution_attempted=True,
                launch_error=exc,
            )

        run_results.append(detail)
        print(f"Recorded {run_id}: {detail['status']}")

    summary = build_summary(args, run_results)
    summary_file = tier_dir / "summary.json"
    write_summary(summary_file, summary)

    print()
    print("-" * 64)
    print("Repeated experiment complete")
    print("-" * 64)
    print(f"PASS             : {summary['pass_count']}")
    print(f"FAIL             : {summary['fail_count']}")
    print(f"Execution errors : {summary['execution_error_count']}")
    print(f"Success rate     : {summary['success_rate']:.2%}")
    print(f"Prompt consistent: {summary['prompt_consistent']}")
    print(f"Summary          : {summary_file}")

    return 1 if (
        summary["execution_error_count"]
        or not summary["prompt_consistent"]
    ) else 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run one remediation tier repeatedly without overwriting runs."
    )
    parser.add_argument("--finding-id", required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--check-id", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--tier", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser.parse_args()


def main():
    try:
        return run(parse_args())
    except RepeatedExperimentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Repeated experiment interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
