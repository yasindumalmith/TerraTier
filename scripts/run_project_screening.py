import argparse
import csv
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "prompts" / "experiment_config.yaml"
DEFAULT_SAMPLES_DIR = PROJECT_ROOT / "pilot_samples"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "experiments" / "screening_v1"
RUNNER_SCRIPT = PROJECT_ROOT / "scripts" / "run_project_remediation.py"
DEFAULT_SAMPLES_FILES = (
    PROJECT_ROOT / "experiment_samples.txt",
    PROJECT_ROOT / "prompts" / "experiment_samples.txt",
)
PROTOCOL_VERSION = "1.0"
RUN_ID = "run_01"
FROZEN_MODELS = {
    "tier_1": "claude-haiku-4-5-20251001",
    "tier_2": "claude-sonnet-4-6",
    "tier_3": "claude-opus-4-8",
}
TIER_ORDER = tuple(FROZEN_MODELS)
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SAMPLE_NUMBER_RE = re.compile(r"^(.*?)(\d+)$")

MASTER_FIELDS = (
    "protocol_version",
    "sample_id",
    "tier",
    "model_id",
    "run_id",
    "prompt_sha256",
    "experiment_unit",
    "fmt_pass",
    "terraform_init_pass",
    "terraform_valid",
    "original_checkov_scan_success",
    "remediated_checkov_scan_success",
    "original_failed_finding_count",
    "remediated_failed_finding_count",
    "removed_original_finding_count",
    "remaining_original_finding_count",
    "new_finding_count",
    "remediation_coverage",
    "resources_preserved",
    "original_resource_count",
    "remediated_resource_count",
    "project_structure_preserved",
    "suppression_added",
    "semantic_validation_status",
    "semantic_validation_configured",
    "semantic_validation_pass",
    "scanner_clean",
    "generation_complete",
    "output_truncated",
    "stop_reason",
    "execution_error",
    "execution_error_type",
    "run_status",
    "final_result",
    "failure_reasons",
    "input_tokens",
    "output_tokens",
    "max_output_tokens",
    "latency_seconds",
    "generated_at",
    "record_source",
    "result_path",
)

PROJECT_SUMMARY_FIELDS = (
    "sample_id",
    "tier_1_result",
    "tier_2_result",
    "tier_3_result",
    "cheapest_successful_tier",
    "tier_1_coverage",
    "tier_2_coverage",
    "tier_3_coverage",
    "tier_1_new_findings",
    "tier_2_new_findings",
    "tier_3_new_findings",
    "tier_1_terraform_valid",
    "tier_2_terraform_valid",
    "tier_3_terraform_valid",
)


class ScreeningError(RuntimeError):
    """A clear, user-facing screening orchestration error."""


@dataclass(frozen=True)
class ScreeningRun:
    sample_id: str
    tier: str
    model_id: str
    run_id: str = RUN_ID

    def run_dir(self, output_dir: Path) -> Path:
        return output_dir / self.sample_id / self.tier / self.run_id

    @property
    def key(self):
        return self.sample_id, self.tier, self.model_id, self.run_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def natural_name_key(value: str):
    match = SAMPLE_NUMBER_RE.match(value)
    return (match.group(1), int(match.group(2))) if match else (value, -1)


def load_screening_config(path: Path):
    """Load and verify the frozen protocol controls from YAML."""
    if not path.is_file():
        raise ScreeningError(f"Screening configuration does not exist: {path}")
    try:
        with path.open(encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except (OSError, yaml.YAMLError) as exc:
        raise ScreeningError(f"Could not read screening configuration {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ScreeningError(f"Screening configuration must be a mapping: {path}")

    models = config.get("models")
    if models != FROZEN_MODELS:
        raise ScreeningError(
            "Configured model mapping does not match the frozen screening mapping: "
            f"expected {FROZEN_MODELS!r}, found {models!r}."
        )
    protocol_version = str(config.get("protocol_version", ""))
    if protocol_version != PROTOCOL_VERSION:
        raise ScreeningError(
            f"Expected protocol_version {PROTOCOL_VERSION!r}, found {protocol_version!r}."
        )
    generation = config.get("generation") or {}
    max_tokens = generation.get("max_output_tokens")
    if max_tokens != 8192:
        raise ScreeningError(
            f"Frozen screening max_output_tokens must be 8192, found {max_tokens!r}."
        )
    repetitions = (config.get("screening") or {}).get("repetitions")
    if repetitions != 1:
        raise ScreeningError(
            f"Frozen screening repetitions must be 1, found {repetitions!r}."
        )
    return {
        "protocol_version": protocol_version,
        "models": dict(models),
        "max_output_tokens": max_tokens,
        "repetitions": repetitions,
        "config_path": path,
    }


def load_samples(samples_dir: Path, samples_file: Path | None = None):
    """Load the authoritative list or discover prepared sample directories."""
    if samples_file is not None:
        if not samples_file.is_file():
            raise ScreeningError(f"Samples file does not exist: {samples_file}")
        samples = []
        for raw_line in samples_file.read_text(encoding="utf-8").splitlines():
            value = raw_line.strip()
            if not value or value.startswith("#"):
                continue
            samples.append(value)
    else:
        samples = sorted(
            (path.name for path in samples_dir.iterdir() if path.is_dir()),
            key=natural_name_key,
        ) if samples_dir.is_dir() else []

    if not samples:
        source = samples_file or samples_dir
        raise ScreeningError(f"No screening samples were found in: {source}")
    invalid = [sample for sample in samples if not SAFE_IDENTIFIER.fullmatch(sample)]
    if invalid:
        raise ScreeningError("Invalid sample identifiers: " + ", ".join(invalid))
    duplicates = sorted({sample for sample in samples if samples.count(sample) > 1})
    if duplicates:
        raise ScreeningError("Duplicate samples in screening list: " + ", ".join(duplicates))
    return samples


def choose_samples_file(explicit_path: Path | None):
    if explicit_path is not None:
        return explicit_path
    return next((path for path in DEFAULT_SAMPLES_FILES if path.is_file()), None)


def build_screening_plan(samples, models):
    """Plan three independent original-project runs per sample."""
    return [
        ScreeningRun(sample_id, tier, models[tier])
        for sample_id in samples
        for tier in TIER_ORDER
    ]


def filter_screening_plan(plan, sample_id=None, tier=None):
    """Select a manual subset without changing the full aggregation plan."""
    return [
        item
        for item in plan
        if (sample_id is None or item.sample_id == sample_id)
        and (tier is None or item.tier == tier)
    ]


def read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    return value, None


def result_identity_errors(result, item: ScreeningRun, max_tokens: int):
    """Return identity/control mismatches without silently correcting data."""
    errors = []
    expected = {
        "sample_id": item.sample_id,
        "tier": item.tier,
        "model_id": item.model_id,
        "run_id": item.run_id,
        "experiment_unit": "terraform_project",
    }
    for field, expected_value in expected.items():
        if result.get(field) != expected_value:
            errors.append(
                f"{field}={result.get(field)!r}; expected {expected_value!r}"
            )
    generation = result.get("generation")
    if not isinstance(generation, dict):
        errors.append("generation metadata is missing")
    elif generation.get("max_output_tokens") != max_tokens:
        errors.append(
            "generation.max_output_tokens="
            f"{generation.get('max_output_tokens')!r}; expected {max_tokens!r}"
        )
    if result.get("final_result") not in {"PASS", "FAIL"}:
        errors.append(f"final_result={result.get('final_result')!r}; expected PASS or FAIL")
    return errors


def completed_result(run_dir: Path, item: ScreeningRun, max_tokens: int):
    result, error = read_json(run_dir / "result.json")
    if error or not isinstance(result, dict):
        return None, error or "result.json must contain a JSON object"
    errors = result_identity_errors(result, item, max_tokens)
    return (result, None) if not errors else (None, "; ".join(errors))


def write_json_atomic(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
    temporary.replace(path)


def record_orchestration_error(
    run_dir: Path,
    item: ScreeningRun,
    max_tokens: int,
    error_type: str,
    message: str,
    runner_exit_code=None,
):
    """Persist an orchestration failure separately from authoritative result.json."""
    record = {
        "protocol_version": PROTOCOL_VERSION,
        "sample_id": item.sample_id,
        "tier": item.tier,
        "model_id": item.model_id,
        "run_id": item.run_id,
        "experiment_unit": "terraform_project",
        "generation": {
            "model_id": item.model_id,
            "max_output_tokens": max_tokens,
            "generation_complete": False,
            "output_truncated": False,
            "stop_reason": None,
            "input_tokens": None,
            "output_tokens": None,
            "latency_seconds": None,
            "generated_at": utc_now(),
        },
        "execution_error": True,
        "execution_error_type": error_type,
        "run_status": "ORCHESTRATION_ERROR",
        "final_result": None,
        "failure_reasons": [error_type],
        "failure_details": {error_type: message},
        "runner_exit_code": runner_exit_code,
    }
    write_json_atomic(run_dir / "orchestration_error.json", record)
    return record


def safely_remove_run_dir(run_dir: Path, output_dir: Path):
    """Remove only one explicitly addressed screening run directory."""
    root = output_dir.resolve()
    target = run_dir.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ScreeningError(f"Refusing to remove path outside output root: {target}") from exc
    if len(relative.parts) != 3 or relative.parts[-1] != RUN_ID:
        raise ScreeningError(f"Refusing to remove unexpected run path: {target}")
    shutil.rmtree(target)


def run_single_experiment(
    item: ScreeningRun,
    samples_dir: Path,
    output_dir: Path,
    runner_script: Path,
    max_tokens: int,
):
    """Invoke the existing project remediation runner without duplicating its logic."""
    command = [
        sys.executable,
        str(runner_script),
        "--sample-id",
        item.sample_id,
        "--tier",
        item.tier,
        "--model",
        item.model_id,
        "--run-id",
        item.run_id,
        "--max-tokens",
        str(max_tokens),
        "--samples-dir",
        str(samples_dir),
        "--output-dir",
        str(output_dir),
    ]
    return subprocess.run(command, cwd=PROJECT_ROOT).returncode


def execute_plan(
    plan,
    *,
    samples_dir: Path,
    output_dir: Path,
    runner_script: Path,
    max_tokens: int,
    resume: bool,
    force: bool,
    dry_run: bool,
    run_experiment=run_single_experiment,
    after_each=None,
):
    """Execute every planned model independently and continue after all failures."""
    events = []
    total_samples = len({item.sample_id for item in plan})
    sample_positions = {
        sample_id: index
        for index, sample_id in enumerate(
            dict.fromkeys(item.sample_id for item in plan), start=1
        )
    }
    if dry_run:
        print("Screening plan")
        print(f"Samples: {total_samples}")
        print(f"Models per sample: {len({item.tier for item in plan})}")
        print(f"Expected runs: {len(plan)}")
        for item in plan:
            missing = (
                " [MISSING SAMPLE]"
                if not (samples_dir / item.sample_id).is_dir()
                else ""
            )
            print(f"{item.sample_id} -> {item.tier} -> {item.model_id}{missing}")
        return [{"item": item, "action": "DRY_RUN"} for item in plan]

    for item in plan:
        model_position = TIER_ORDER.index(item.tier) + 1
        print("\n" + "=" * 66)
        print("TerraTier Screening v1")
        print(
            f"Sample {sample_positions[item.sample_id]}/{total_samples}: {item.sample_id}"
        )
        print(
            f"Model {model_position}/{len(TIER_ORDER)}: "
            f"{item.tier} / {item.model_id}"
        )
        print("=" * 66)

        run_dir = item.run_dir(output_dir)
        sample_dir = samples_dir / item.sample_id
        if not sample_dir.is_dir():
            message = f"Prepared sample directory does not exist: {sample_dir}"
            print(f"[ERROR] {message}")
            record_orchestration_error(
                run_dir, item, max_tokens, "MISSING_SAMPLE", message
            )
            event = {"item": item, "action": "ERROR", "error": message}
        elif run_dir.exists() and force:
            safely_remove_run_dir(run_dir, output_dir)
            event = _execute_one(
                item, samples_dir, output_dir, runner_script, max_tokens, run_experiment
            )
        elif run_dir.exists():
            result, error = completed_result(run_dir, item, max_tokens)
            if result is not None:
                prefix = "[SKIP]" if resume else "[EXISTS]"
                print(
                    f"{prefix} {item.sample_id} {item.tier} {item.run_id} "
                    "already completed"
                )
                event = {"item": item, "action": "SKIP", "result": result}
            else:
                message = (
                    f"Existing run is incomplete or inconsistent: {run_dir}: {error}. "
                    "Use --force to rerun it."
                )
                print(f"[ERROR] {message}")
                record_orchestration_error(
                    run_dir, item, max_tokens, "EXISTING_RESULT_INVALID", message
                )
                event = {"item": item, "action": "ERROR", "error": message}
        else:
            event = _execute_one(
                item, samples_dir, output_dir, runner_script, max_tokens, run_experiment
            )

        events.append(event)
        if after_each is not None:
            after_each()
    return events


def _execute_one(
    item, samples_dir, output_dir, runner_script, max_tokens, run_experiment
):
    try:
        exit_code = run_experiment(
            item, samples_dir, output_dir, runner_script, max_tokens
        )
    except Exception as exc:
        message = f"Could not launch project remediation: {exc}"
        print(f"[ERROR] {message}")
        record_orchestration_error(
            item.run_dir(output_dir),
            item,
            max_tokens,
            "RUNNER_LAUNCH_ERROR",
            message,
        )
        return {"item": item, "action": "ERROR", "error": message}

    run_dir = item.run_dir(output_dir)
    result, error = completed_result(run_dir, item, max_tokens)
    if result is None:
        message = (
            f"Runner exited with status {exit_code} without a valid result.json: {error}"
        )
        print(f"[ERROR] {message}")
        record_orchestration_error(
            run_dir,
            item,
            max_tokens,
            "RESULT_JSON_UNAVAILABLE",
            message,
            runner_exit_code=exit_code,
        )
        return {"item": item, "action": "ERROR", "error": message}

    generation = result.get("generation") or {}
    print(f"Result: {result.get('final_result')}")
    print(f"Terraform valid: {result.get('terraform_valid')}")
    print(f"Coverage: {result.get('remediation_coverage')}")
    print(f"Remaining findings: {result.get('remaining_original_finding_count')}")
    print(f"New findings: {result.get('new_finding_count')}")
    print(f"Latency: {generation.get('latency_seconds')}s")
    return {
        "item": item,
        "action": "COMPLETE",
        "result": result,
        "runner_exit_code": exit_code,
    }


def load_saved_record(item: ScreeningRun, output_dir: Path, max_tokens: int):
    run_dir = item.run_dir(output_dir)
    result_file = run_dir / "result.json"
    result, result_error = read_json(result_file)
    if isinstance(result, dict) and not result_identity_errors(
        result, item, max_tokens
    ):
        return result, "result_json", result_file
    error_file = run_dir / "orchestration_error.json"
    error_record, error_error = read_json(error_file)
    if isinstance(error_record, dict):
        return error_record, "orchestration_error", error_file
    if result_file.exists():
        invalid_message = (
            "; ".join(result_identity_errors(result, item, max_tokens))
            if isinstance(result, dict)
            else "result.json is not a JSON object"
        )
        return (
            record_orchestration_error(
                run_dir,
                item,
                max_tokens,
                "RESULT_JSON_INVALID",
                result_error or invalid_message,
            ),
            "orchestration_error",
            error_file,
        )
    if error_file.exists() and error_error:
        return None, None, error_file
    return None, None, result_file


def serialize_failure_reasons(value) -> str:
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    if value in (None, ""):
        return ""
    return str(value)


def flatten_result_for_csv(result, source: str, path: Path, protocol_version: str):
    generation = result.get("generation") or {}
    return {
        "protocol_version": protocol_version,
        "sample_id": result.get("sample_id"),
        "tier": result.get("tier"),
        "model_id": result.get("model_id"),
        "run_id": result.get("run_id"),
        "prompt_sha256": result.get("prompt_sha256"),
        "experiment_unit": result.get("experiment_unit"),
        "fmt_pass": result.get("fmt_pass"),
        "terraform_init_pass": result.get("terraform_init_pass"),
        "terraform_valid": result.get("terraform_valid"),
        "original_checkov_scan_success": result.get("original_checkov_scan_success"),
        "remediated_checkov_scan_success": result.get("remediated_checkov_scan_success"),
        "original_failed_finding_count": result.get("original_failed_finding_count"),
        "remediated_failed_finding_count": result.get("remediated_failed_finding_count"),
        "removed_original_finding_count": result.get("removed_original_finding_count"),
        "remaining_original_finding_count": result.get("remaining_original_finding_count"),
        "new_finding_count": result.get("new_finding_count"),
        "remediation_coverage": result.get("remediation_coverage"),
        "resources_preserved": result.get("resources_preserved"),
        "original_resource_count": result.get("original_resource_count"),
        "remediated_resource_count": result.get("remediated_resource_count"),
        "project_structure_preserved": result.get("project_structure_preserved"),
        "suppression_added": result.get("suppression_added"),
        "semantic_validation_status": result.get("semantic_validation_status"),
        "semantic_validation_configured": result.get("semantic_validation_configured"),
        "semantic_validation_pass": result.get("semantic_validation_pass"),
        "scanner_clean": result.get("scanner_clean"),
        "generation_complete": generation.get("generation_complete"),
        "output_truncated": generation.get("output_truncated"),
        "stop_reason": generation.get("stop_reason"),
        "execution_error": result.get("execution_error"),
        "execution_error_type": result.get("execution_error_type"),
        "run_status": result.get("run_status"),
        "final_result": result.get("final_result"),
        "failure_reasons": serialize_failure_reasons(result.get("failure_reasons")),
        "input_tokens": generation.get("input_tokens"),
        "output_tokens": generation.get("output_tokens"),
        "max_output_tokens": generation.get("max_output_tokens"),
        "latency_seconds": generation.get("latency_seconds"),
        "generated_at": generation.get("generated_at"),
        "record_source": source,
        "result_path": display_path(path),
    }


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def collect_rows(plan, output_dir: Path, protocol_version: str, max_tokens: int):
    rows_by_key = {}
    for item in plan:
        result, source, path = load_saved_record(item, output_dir, max_tokens)
        if result is not None:
            rows_by_key[item.key] = flatten_result_for_csv(
                result, source, path, protocol_version
            )
    return list(rows_by_key.values())


def csv_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else value


def write_csv_atomic(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})
    temporary.replace(path)


def determine_cheapest_successful_tier(results_by_tier):
    """Use final PASS only; partial coverage never qualifies."""
    if any(tier not in results_by_tier for tier in TIER_ORDER):
        return "incomplete"
    for tier in TIER_ORDER:
        if results_by_tier[tier].get("final_result") == "PASS":
            return tier
    return "unresolved"


def build_project_summary(samples, rows):
    indexed = {(row["sample_id"], row["tier"]): row for row in rows}
    output = []
    for sample_id in samples:
        tiers = {
            tier: indexed[(sample_id, tier)]
            for tier in TIER_ORDER
            if (sample_id, tier) in indexed
        }
        row = {
            "sample_id": sample_id,
            "cheapest_successful_tier": determine_cheapest_successful_tier(tiers),
        }
        for tier in TIER_ORDER:
            result = tiers.get(tier, {})
            row[f"{tier}_result"] = result.get("final_result")
            row[f"{tier}_coverage"] = result.get("remediation_coverage")
            row[f"{tier}_new_findings"] = result.get("new_finding_count")
            row[f"{tier}_terraform_valid"] = result.get("terraform_valid")
        output.append(row)
    return output


def numeric_values(rows, field):
    return [
        row[field]
        for row in rows
        if isinstance(row.get(field), (int, float))
        and not isinstance(row.get(field), bool)
    ]


def average(values):
    return round(sum(values) / len(values), 6) if values else None


def summarize_rows(rows):
    quality_rows = [row for row in rows if not row.get("execution_error")]
    pass_count = sum(row.get("final_result") == "PASS" for row in quality_rows)
    fail_count = sum(row.get("final_result") == "FAIL" for row in quality_rows)
    denominator = pass_count + fail_count
    return {
        "total_runs": len(rows),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "execution_error_count": sum(bool(row.get("execution_error")) for row in rows),
        "truncation_count": sum(bool(row.get("output_truncated")) for row in rows),
        "success_rate": round(pass_count / denominator, 6) if denominator else None,
        "average_remediation_coverage": average(
            numeric_values(rows, "remediation_coverage")
        ),
        "average_input_tokens": average(numeric_values(rows, "input_tokens")),
        "average_output_tokens": average(numeric_values(rows, "output_tokens")),
        "average_latency_seconds": average(numeric_values(rows, "latency_seconds")),
    }


def validate_screening_consistency(samples, rows, models, max_tokens):
    warnings = []
    keys = [(row.get("sample_id"), row.get("tier"), row.get("model_id"), row.get("run_id")) for row in rows]
    duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
    if duplicate_keys:
        warnings.append(f"Duplicate experiment rows: {duplicate_keys!r}")

    by_sample = {sample: [] for sample in samples}
    for row in rows:
        by_sample.setdefault(row.get("sample_id"), []).append(row)
        tier = row.get("tier")
        if tier not in models:
            warnings.append(f"Unknown tier in row: {tier!r}")
            continue
        if row.get("model_id") != models[tier]:
            warnings.append(
                f"{row.get('sample_id')} {tier}: model_id {row.get('model_id')!r} "
                f"does not match {models[tier]!r}"
            )
        if row.get("max_output_tokens") != max_tokens:
            warnings.append(
                f"{row.get('sample_id')} {tier}: max_output_tokens "
                f"{row.get('max_output_tokens')!r} does not match {max_tokens}"
            )
        if row.get("experiment_unit") != "terraform_project":
            warnings.append(
                f"{row.get('sample_id')} {tier}: experiment_unit is "
                f"{row.get('experiment_unit')!r}"
            )
        if row.get("run_id") != RUN_ID:
            warnings.append(
                f"{row.get('sample_id')} {tier}: run_id is {row.get('run_id')!r}"
            )

    for sample_id, sample_rows in by_sample.items():
        tiers = {row.get("tier") for row in sample_rows}
        if tiers != set(TIER_ORDER):
            warnings.append(
                f"{sample_id}: has {len(tiers)}/3 tier records ({sorted(tiers)!r})"
            )
        hashes = {
            row.get("prompt_sha256")
            for row in sample_rows
            if row.get("prompt_sha256")
        }
        if len(hashes) > 1:
            warnings.append(
                f"{sample_id}: inconsistent prompt SHA256 values: {sorted(hashes)!r}"
            )
    return warnings


def command_output(command):
    try:
        result = subprocess.run(
            command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def reproducibility_metadata(rows):
    warnings = []
    terraform_data = command_output(["terraform", "version", "-json"])
    terraform_version = None
    if terraform_data:
        try:
            terraform_version = json.loads(terraform_data).get("terraform_version")
        except json.JSONDecodeError:
            pass
    if not terraform_version:
        warnings.append("Terraform version could not be determined.")
    try:
        checkov_version = importlib.metadata.version("checkov")
    except importlib.metadata.PackageNotFoundError:
        checkov_version = None
        warnings.append("Checkov version could not be determined.")
    code_commit = command_output(["git", "rev-parse", "HEAD"])
    if not code_commit:
        warnings.append("TerraTier code commit could not be determined.")
    git_status = command_output(["git", "status", "--porcelain"])
    code_dirty = bool(git_status) if git_status is not None else None

    provider_versions = set()
    provider_re = re.compile(r"hashicorp/aws v([0-9]+(?:\.[0-9]+)+)")
    for row in rows:
        path = PROJECT_ROOT / row["result_path"]
        result, _ = read_json(path)
        if not isinstance(result, dict):
            continue
        stdout = (
            ((result.get("terraform_command_results") or {}).get("init") or {}).get("stdout")
            or ""
        )
        provider_versions.update(provider_re.findall(stdout))
    if not provider_versions:
        warnings.append("AWS provider version is not yet available from screening results.")
    warnings.append("TerraGoat source commit is not recorded in the repository configuration.")
    return {
        "code_commit_sha": code_commit,
        "code_worktree_dirty": code_dirty,
        "terragoat_commit_sha": None,
        "terraform_version": terraform_version,
        "checkov_version": checkov_version,
        "aws_provider_versions": sorted(provider_versions),
    }, warnings


def build_screening_summary(samples, rows, config, warnings):
    by_tier = {
        tier: summarize_rows([row for row in rows if row.get("tier") == tier])
        for tier in TIER_ORDER
    }
    overall = summarize_rows(rows)
    completed = sum(row.get("record_source") == "result_json" for row in rows)
    return {
        "protocol_version": config["protocol_version"],
        "generated_at": utc_now(),
        "total_samples": len(samples),
        "expected_runs": len(samples) * len(TIER_ORDER),
        "recorded_runs": len(rows),
        "completed_runs": completed,
        "pass_runs": overall["pass_count"],
        "fail_runs": overall["fail_count"],
        "truncated_runs": overall["truncation_count"],
        "execution_error_runs": overall["execution_error_count"],
        "models": config["models"],
        "max_output_tokens": config["max_output_tokens"],
        "results_by_tier": by_tier,
        "warnings": warnings,
    }


def rebuild_aggregates(samples, plan, output_dir: Path, config):
    """Deterministically rebuild every aggregate from saved run artifacts."""
    rows = collect_rows(
        plan,
        output_dir,
        config["protocol_version"],
        config["max_output_tokens"],
    )
    warnings = validate_screening_consistency(
        samples, rows, config["models"], config["max_output_tokens"]
    )
    reproducibility, reproducibility_warnings = reproducibility_metadata(rows)
    warnings.extend(reproducibility_warnings)
    write_csv_atomic(output_dir / "screening_results.csv", MASTER_FIELDS, rows)
    project_rows = build_project_summary(samples, rows)
    write_csv_atomic(
        output_dir / "project_screening_summary.csv",
        PROJECT_SUMMARY_FIELDS,
        project_rows,
    )
    summary = build_screening_summary(samples, rows, config, warnings)
    summary["reproducibility"] = reproducibility
    summary["config_path"] = display_path(config["config_path"])
    write_json_atomic(output_dir / "screening_summary.json", summary)
    return rows, project_rows, summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="Screen every prepared Terraform project against all frozen models."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--samples-file", type=Path, default=None)
    parser.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument(
        "--sample-id",
        default=None,
        help="Run only this prepared sample while retaining full CSV aggregation.",
    )
    parser.add_argument(
        "--tier",
        choices=TIER_ORDER,
        default=None,
        help="Run only this model tier while retaining full CSV aggregation.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        config = load_screening_config(args.config.resolve())
        if args.max_tokens is not None:
            if args.max_tokens <= 0:
                raise ScreeningError("--max-tokens must be greater than zero.")
            if args.max_tokens != config["max_output_tokens"]:
                raise ScreeningError(
                    "Protocol v1.0 requires --max-tokens 8192; "
                    f"received {args.max_tokens}."
                )
        samples_dir = args.samples_dir.resolve()
        samples_file = choose_samples_file(
            args.samples_file.resolve() if args.samples_file else None
        )
        samples = load_samples(samples_dir, samples_file)
        if args.sample_id is not None and args.sample_id not in samples:
            raise ScreeningError(
                f"--sample-id {args.sample_id!r} is not in the screening sample set."
            )
        full_plan = build_screening_plan(samples, config["models"])
        plan = filter_screening_plan(full_plan, args.sample_id, args.tier)
        output_dir = args.output_dir.resolve()

        if args.dry_run:
            execute_plan(
                plan,
                samples_dir=samples_dir,
                output_dir=output_dir,
                runner_script=RUNNER_SCRIPT,
                max_tokens=config["max_output_tokens"],
                resume=args.resume,
                force=args.force,
                dry_run=True,
            )
            return 0

        def refresh():
            rebuild_aggregates(samples, full_plan, output_dir, config)

        execute_plan(
            plan,
            samples_dir=samples_dir,
            output_dir=output_dir,
            runner_script=RUNNER_SCRIPT,
            max_tokens=config["max_output_tokens"],
            resume=args.resume,
            force=args.force,
            dry_run=False,
            after_each=refresh,
        )
        _, _, summary = rebuild_aggregates(samples, full_plan, output_dir, config)
        print("\n" + "=" * 66)
        print("SCREENING COMPLETE")
        print("=" * 66)
        print(f"Samples: {summary['total_samples']}")
        print(f"Expected runs: {summary['expected_runs']}")
        print(f"Completed: {summary['completed_runs']}")
        print(f"PASS: {summary['pass_runs']}")
        print(f"FAIL: {summary['fail_runs']}")
        print(f"Truncated: {summary['truncated_runs']}")
        print(f"Execution errors: {summary['execution_error_runs']}")
        print(f"Master CSV: {display_path(output_dir / 'screening_results.csv')}")
        print(
            "Project summary: "
            f"{display_path(output_dir / 'project_screening_summary.csv')}"
        )
        if summary["warnings"]:
            print(f"Warnings: {len(summary['warnings'])} (see screening_summary.json)")
        return 0
    except ScreeningError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Screening interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
