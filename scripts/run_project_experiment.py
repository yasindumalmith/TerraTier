import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from run_remediation import DEFAULT_MAX_TOKENS, validate_identifier


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNNER_SCRIPT = PROJECT_ROOT / "scripts" / "run_project_remediation.py"
EXPERIMENTS_DIR = PROJECT_ROOT / "project_experiments"
DEFAULT_RUNS = 5


class ProjectExperimentError(RuntimeError):
    """A clear, user-facing repeated project experiment error."""


def read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file), None
    except FileNotFoundError:
        return None, f"Missing file: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Could not read {path}: {exc}"


def has_existing_artifacts(run_dir: Path):
    return any(
        (run_dir / name).exists()
        for name in (
            "prompt.txt",
            "raw_response.txt",
            "metadata.json",
            "result.json",
            "original",
            "remediated",
        )
    )


def display_path(path: Path):
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_runner_command(args, run_id: str):
    return [
        sys.executable,
        str(RUNNER_SCRIPT),
        "--sample-id",
        args.sample_id,
        "--tier",
        args.tier,
        "--model",
        args.model,
        "--run-id",
        run_id,
        "--max-tokens",
        str(args.max_tokens),
    ]


def classify_run(run_id, run_dir, expected_controls, exit_code, attempted, error=None):
    metadata_file = run_dir / "metadata.json"
    result_file = run_dir / "result.json"
    metadata, metadata_error = read_json(metadata_file)
    result, result_error = read_json(result_file)
    generation = result.get("generation", {}) if isinstance(result, dict) else {}
    stop_reason = (
        generation.get("stop_reason")
        if isinstance(generation, dict) and generation.get("stop_reason") is not None
        else metadata.get("response_stop_reason")
        if isinstance(metadata, dict)
        else None
    )
    output_truncated = bool(
        (generation.get("output_truncated") if isinstance(generation, dict) else False)
        or stop_reason == "max_tokens"
    )
    execution_error = bool(
        (result.get("execution_error") if isinstance(result, dict) else False)
        or output_truncated
    )
    run_status = result.get("run_status") if isinstance(result, dict) else None
    if output_truncated:
        run_status = "GENERATION_TRUNCATED"

    detail = {
        "run_id": run_id,
        "status": "EXECUTION_ERROR",
        "run_status": run_status,
        "execution_error": execution_error,
        "execution_error_type": (
            result.get("execution_error_type") if isinstance(result, dict) else None
        ) or ("LLM_OUTPUT_TRUNCATED" if output_truncated else None),
        "stop_reason": stop_reason,
        "output_truncated": output_truncated,
        "execution_attempted": attempted,
        "runner_exit_code": exit_code,
        "api_request_success": metadata.get("api_request_success")
        if isinstance(metadata, dict)
        else None,
        "validation_result": result.get("final_result")
        if isinstance(result, dict)
        else None,
        "api_input_tokens": metadata.get("api_input_tokens")
        if isinstance(metadata, dict)
        else None,
        "api_output_tokens": metadata.get("api_output_tokens")
        if isinstance(metadata, dict)
        else None,
        "request_latency_seconds": metadata.get("request_latency_seconds")
        if isinstance(metadata, dict)
        else None,
        "remediation_coverage": result.get("remediation_coverage")
        if isinstance(result, dict)
        else None,
        "original_failed_finding_count": result.get("original_failed_finding_count")
        if isinstance(result, dict)
        else None,
        "remaining_original_finding_count": result.get(
            "remaining_original_finding_count"
        )
        if isinstance(result, dict)
        else None,
        "new_finding_count": result.get("new_finding_count")
        if isinstance(result, dict)
        else None,
        "failure_reasons": result.get("failure_reasons", [])
        if isinstance(result, dict)
        else [],
        "metadata_file": display_path(metadata_file),
        "result_file": display_path(result_file),
    }
    if error is not None:
        detail.update(error_type="runner_launch_error", error_message=str(error))
        return detail
    if not isinstance(metadata, dict):
        detail.update(error_type="metadata_error", error_message=metadata_error)
        return detail
    mismatches = [
        f"{field}={metadata.get(field)!r} (expected {expected!r})"
        for field, expected in expected_controls.items()
        if metadata.get(field) != expected
    ]
    if mismatches:
        detail.update(
            error_type="experimental_control_mismatch",
            error_message="; ".join(mismatches),
        )
        return detail
    if not metadata.get("api_request_success"):
        detail["run_status"] = "API_ERROR"
        detail["execution_error"] = True
        detail["execution_error_type"] = "API_ERROR"
        detail.update(
            error_type="api_error",
            error_message=metadata.get(
                "api_error_message", "The API request did not complete successfully."
            ),
        )
        return detail
    if detail["execution_error"] or (
        isinstance(result, dict)
        and "EXECUTION_ERROR" in result.get("failure_reasons", [])
    ):
        detail.update(
            error_type=detail["execution_error_type"] or "runtime_error",
            error_message=(
                result.get("failure_details", {}).get(
                    detail["execution_error_type"], "Project execution failed."
                )
                if isinstance(result, dict)
                else "Project execution failed."
            ),
        )
        return detail
    if isinstance(result, dict) and result.get("final_result") in {"PASS", "FAIL"}:
        detail["status"] = result["final_result"]
        return detail
    if exit_code not in (None, 0):
        detail.update(
            error_type="runtime_error",
            error_message=f"run_project_remediation.py exited with status {exit_code}.",
        )
        return detail
    detail.update(error_type="result_error", error_message=result_error)
    return detail


def numeric_values(results, field):
    return [
        item[field]
        for item in results
        if isinstance(item.get(field), (int, float))
        and not isinstance(item.get(field), bool)
    ]


def average_or_none(values):
    return round(sum(values) / len(values), 6) if values else None


def build_summary(args, run_results):
    pass_count = sum(item["status"] == "PASS" for item in run_results)
    fail_count = sum(item["status"] == "FAIL" for item in run_results)
    execution_error_count = sum(
        item.get("execution_error") or item["status"] == "EXECUTION_ERROR"
        for item in run_results
    )
    generation_truncated_count = sum(
        item.get("run_status") == "GENERATION_TRUNCATED" for item in run_results
    )
    api_error_count = sum(
        item.get("run_status") == "API_ERROR" for item in run_results
    )
    validation_failed_count = sum(
        item.get("run_status") == "VALIDATION_FAILED" for item in run_results
    )
    input_tokens = numeric_values(run_results, "api_input_tokens")
    output_tokens = numeric_values(run_results, "api_output_tokens")
    latencies = numeric_values(run_results, "request_latency_seconds")
    coverages = numeric_values(run_results, "remediation_coverage")
    original_counts = numeric_values(run_results, "original_failed_finding_count")
    remaining_counts = numeric_values(
        run_results, "remaining_original_finding_count"
    )
    new_counts = numeric_values(run_results, "new_finding_count")
    prompt_hashes = set()
    for item in run_results:
        metadata, _ = read_json(PROJECT_ROOT / item["metadata_file"])
        if isinstance(metadata, dict) and metadata.get("prompt_sha256"):
            prompt_hashes.add(metadata["prompt_sha256"])
    return {
        "sample_id": args.sample_id,
        "experiment_unit": "terraform_project",
        "tier": args.tier,
        "model_id": args.model,
        "max_tokens": args.max_tokens,
        "total_runs": args.runs,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "execution_error_count": execution_error_count,
        "generation_truncated_count": generation_truncated_count,
        "api_error_count": api_error_count,
        "validation_failed_count": validation_failed_count,
        "success_rate": round(pass_count / args.runs, 6),
        "average_remediation_coverage": average_or_none(coverages),
        "average_original_failed_findings": average_or_none(original_counts),
        "average_remaining_original_findings": average_or_none(remaining_counts),
        "average_new_findings": average_or_none(new_counts),
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


def write_summary(path: Path, summary):
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
        file.write("\n")
    temporary.replace(path)


def run(args):
    validate_identifier(args.sample_id, "--sample-id")
    validate_identifier(args.tier, "--tier")
    if args.runs <= 0:
        raise ProjectExperimentError("--runs must be greater than zero.")
    if args.max_tokens <= 0:
        raise ProjectExperimentError("--max-tokens must be greater than zero.")

    tier_dir = EXPERIMENTS_DIR / args.sample_id / args.tier
    tier_dir.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(args.runs)))
    run_results = []
    for number in range(1, args.runs + 1):
        run_id = f"run_{number:0{width}d}"
        run_dir = tier_dir / run_id
        expected = {
            "sample_id": args.sample_id,
            "tier": args.tier,
            "model_id": args.model,
            "run_id": run_id,
            "max_tokens": args.max_tokens,
        }
        print(f"\nStarting {args.tier} / {run_id} ({number}/{args.runs})")
        if has_existing_artifacts(run_dir):
            print(f"Existing artifacts found; preserving and summarizing {run_dir}")
            detail = classify_run(run_id, run_dir, expected, None, False)
        else:
            try:
                completed = subprocess.run(
                    build_runner_command(args, run_id), cwd=PROJECT_ROOT
                )
                detail = classify_run(
                    run_id, run_dir, expected, completed.returncode, True
                )
            except OSError as exc:
                detail = classify_run(run_id, run_dir, expected, None, True, exc)
        run_results.append(detail)
        print(f"Recorded {run_id}: {detail['status']}")

    summary = build_summary(args, run_results)
    summary_file = tier_dir / "summary.json"
    write_summary(summary_file, summary)
    print(f"\nPASS: {summary['pass_count']}")
    print(f"FAIL: {summary['fail_count']}")
    print(f"Execution errors: {summary['execution_error_count']}")
    print(f"Truncated generations: {summary['generation_truncated_count']}")
    print(f"Success rate: {summary['success_rate']:.2%}")
    print(f"Prompt consistent: {summary['prompt_consistent']}")
    print(f"Summary: {summary_file}")
    return 1 if summary["execution_error_count"] or not summary["prompt_consistent"] else 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run repeated whole-project remediations from one untouched sample."
    )
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--tier", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser.parse_args()


def main():
    try:
        return run(parse_args())
    except (ProjectExperimentError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Project experiment interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
