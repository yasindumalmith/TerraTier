import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from run_project_screening import (  # noqa: E402
    FROZEN_MODELS,
    MASTER_FIELDS,
    PROTOCOL_VERSION,
    ScreeningRun,
    build_project_summary,
    build_screening_plan,
    collect_rows,
    determine_cheapest_successful_tier,
    execute_plan,
    filter_screening_plan,
    rebuild_aggregates,
    serialize_failure_reasons,
    validate_screening_consistency,
    write_csv_atomic,
    write_json_atomic,
)


def fake_result(item, final_result="PASS", prompt_sha="same-prompt", max_tokens=8192):
    return {
        "sample_id": item.sample_id,
        "tier": item.tier,
        "model_id": item.model_id,
        "run_id": item.run_id,
        "prompt_sha256": prompt_sha,
        "experiment_unit": "terraform_project",
        "fmt_pass": True,
        "terraform_init_pass": True,
        "terraform_valid": True,
        "original_checkov_scan_success": True,
        "remediated_checkov_scan_success": True,
        "original_failed_finding_count": 2,
        "remediated_failed_finding_count": 0,
        "removed_original_finding_count": 2,
        "remaining_original_finding_count": 0,
        "new_finding_count": 0,
        "remediation_coverage": 1.0,
        "resources_preserved": True,
        "original_resource_count": 1,
        "remediated_resource_count": 1,
        "project_structure_preserved": True,
        "suppression_added": False,
        "semantic_validation_status": "generic_invariants_only",
        "semantic_validation_configured": False,
        "semantic_validation_pass": True,
        "scanner_clean": True,
        "execution_error": False,
        "execution_error_type": None,
        "run_status": "COMPLETED" if final_result == "PASS" else "VALIDATION_FAILED",
        "final_result": final_result,
        "failure_reasons": [] if final_result == "PASS" else ["TEST_FAILURE"],
        "generation": {
            "model_id": item.model_id,
            "max_output_tokens": max_tokens,
            "input_tokens": 100,
            "output_tokens": 200,
            "stop_reason": "end_turn",
            "output_truncated": False,
            "generation_complete": True,
            "latency_seconds": 1.5,
            "generated_at": "2026-10-04T00:00:00+00:00",
        },
    }


class ScreeningTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.samples_dir = self.root / "samples"
        self.output_dir = self.root / "screening"
        sample_dir = self.samples_dir / "sample_01"
        sample_dir.mkdir(parents=True)
        (sample_dir / "main.tf").write_text("resource \"null_resource\" \"x\" {}\n")
        self.plan = build_screening_plan(["sample_01"], FROZEN_MODELS)

    def tearDown(self):
        self.temporary.cleanup()

    def runner_that_writes(self, calls, results=None):
        results = results or {}

        def runner(item, samples_dir, output_dir, runner_script, max_tokens):
            calls.append(item.tier)
            result = fake_result(item, results.get(item.tier, "PASS"), max_tokens=max_tokens)
            write_json_atomic(item.run_dir(output_dir) / "result.json", result)
            return 0

        return runner

    def execute(self, runner, **overrides):
        options = {
            "samples_dir": self.samples_dir,
            "output_dir": self.output_dir,
            "runner_script": Path("unused-runner.py"),
            "max_tokens": 8192,
            "resume": False,
            "force": False,
            "dry_run": False,
            "run_experiment": runner,
        }
        options.update(overrides)
        return execute_plan(self.plan, **options)


class ScreeningExecutionTests(ScreeningTestCase):
    def test_three_independent_model_runs_are_planned(self):
        self.assertEqual(len(self.plan), 3)
        self.assertEqual([item.tier for item in self.plan], list(FROZEN_MODELS))
        self.assertEqual({item.sample_id for item in self.plan}, {"sample_01"})

    def test_plan_can_select_exactly_one_sample_and_model(self):
        selected = filter_screening_plan(self.plan, "sample_01", "tier_2")

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].sample_id, "sample_01")
        self.assertEqual(selected[0].tier, "tier_2")

    def test_haiku_pass_does_not_prevent_later_models(self):
        calls = []
        events = self.execute(self.runner_that_writes(calls))

        self.assertEqual(calls, ["tier_1", "tier_2", "tier_3"])
        self.assertEqual([event["action"] for event in events], ["COMPLETE"] * 3)

    def test_validation_failure_does_not_stop_later_models(self):
        calls = []
        events = self.execute(
            self.runner_that_writes(calls, {"tier_1": "FAIL"})
        )

        self.assertEqual(calls, ["tier_1", "tier_2", "tier_3"])
        self.assertEqual(events[0]["result"]["final_result"], "FAIL")
        self.assertEqual(events[1]["action"], "COMPLETE")
        self.assertEqual(events[2]["action"], "COMPLETE")

    def test_model_invocation_error_does_not_stop_later_models(self):
        calls = []

        def runner(item, samples_dir, output_dir, runner_script, max_tokens):
            calls.append(item.tier)
            if item.tier == "tier_1":
                raise OSError("network unavailable")
            write_json_atomic(
                item.run_dir(output_dir) / "result.json", fake_result(item)
            )
            return 0

        events = self.execute(runner)

        self.assertEqual(calls, ["tier_1", "tier_2", "tier_3"])
        self.assertEqual(events[0]["action"], "ERROR")
        self.assertEqual(events[1]["action"], "COMPLETE")
        self.assertEqual(events[2]["action"], "COMPLETE")

    def test_resume_skips_completed_pass_or_fail_result(self):
        first = self.plan[0]
        write_json_atomic(
            first.run_dir(self.output_dir) / "result.json",
            fake_result(first, final_result="FAIL"),
        )
        calls = []
        events = execute_plan(
            [first],
            samples_dir=self.samples_dir,
            output_dir=self.output_dir,
            runner_script=Path("unused-runner.py"),
            max_tokens=8192,
            resume=True,
            force=False,
            dry_run=False,
            run_experiment=self.runner_that_writes(calls),
        )

        self.assertEqual(calls, [])
        self.assertEqual(events[0]["action"], "SKIP")

    def test_force_explicitly_replaces_existing_run(self):
        first = self.plan[0]
        run_dir = first.run_dir(self.output_dir)
        write_json_atomic(run_dir / "result.json", fake_result(first))
        marker = run_dir / "old-marker.txt"
        marker.write_text("old")
        calls = []
        events = execute_plan(
            [first],
            samples_dir=self.samples_dir,
            output_dir=self.output_dir,
            runner_script=Path("unused-runner.py"),
            max_tokens=8192,
            resume=False,
            force=True,
            dry_run=False,
            run_experiment=self.runner_that_writes(calls),
        )

        self.assertEqual(calls, ["tier_1"])
        self.assertFalse(marker.exists())
        self.assertEqual(events[0]["action"], "COMPLETE")

    def test_dry_run_makes_zero_runner_calls(self):
        calls = []
        events = self.execute(
            self.runner_that_writes(calls),
            dry_run=True,
            force=True,
        )

        self.assertEqual(calls, [])
        self.assertEqual([event["action"] for event in events], ["DRY_RUN"] * 3)
        self.assertFalse(self.output_dir.exists())

    def test_malformed_result_is_reported_without_rerun(self):
        first = self.plan[0]
        result_file = first.run_dir(self.output_dir) / "result.json"
        result_file.parent.mkdir(parents=True)
        result_file.write_text("{not json")
        calls = []
        events = execute_plan(
            [first],
            samples_dir=self.samples_dir,
            output_dir=self.output_dir,
            runner_script=Path("unused-runner.py"),
            max_tokens=8192,
            resume=True,
            force=False,
            dry_run=False,
            run_experiment=self.runner_that_writes(calls),
        )

        self.assertEqual(calls, [])
        self.assertEqual(events[0]["action"], "ERROR")
        self.assertTrue((result_file.parent / "orchestration_error.json").is_file())

    def test_missing_result_after_runner_exit_is_recorded(self):
        first = self.plan[0]

        def runner(item, samples_dir, output_dir, runner_script, max_tokens):
            return 1

        events = execute_plan(
            [first],
            samples_dir=self.samples_dir,
            output_dir=self.output_dir,
            runner_script=Path("unused-runner.py"),
            max_tokens=8192,
            resume=False,
            force=False,
            dry_run=False,
            run_experiment=runner,
        )

        self.assertEqual(events[0]["action"], "ERROR")
        self.assertTrue(
            (first.run_dir(self.output_dir) / "orchestration_error.json").is_file()
        )


class ScreeningAggregationTests(ScreeningTestCase):
    def write_all_results(self, prompt_hashes=None):
        prompt_hashes = prompt_hashes or {}
        for item in self.plan:
            write_json_atomic(
                item.run_dir(self.output_dir) / "result.json",
                fake_result(item, prompt_sha=prompt_hashes.get(item.tier, "same")),
            )

    def test_master_csv_has_one_unique_row_per_model(self):
        self.write_all_results()
        rows = collect_rows(
            self.plan + [self.plan[0]], self.output_dir, PROTOCOL_VERSION, 8192
        )
        csv_file = self.output_dir / "screening_results.csv"
        write_csv_atomic(csv_file, MASTER_FIELDS, rows)
        with csv_file.open(encoding="utf-8", newline="") as file:
            saved = list(csv.DictReader(file))

        self.assertEqual(len(rows), 3)
        self.assertEqual(len(saved), 3)
        self.assertEqual(len({(row["sample_id"], row["tier"]) for row in saved}), 3)

    def test_cheapest_successful_tier_uses_final_pass_only(self):
        cases = (
            (("PASS", "PASS", "PASS"), "tier_1"),
            (("FAIL", "PASS", "PASS"), "tier_2"),
            (("FAIL", "FAIL", "PASS"), "tier_3"),
            (("FAIL", "FAIL", "FAIL"), "unresolved"),
        )
        for results, expected in cases:
            with self.subTest(results=results):
                by_tier = {
                    tier: {"final_result": result}
                    for tier, result in zip(FROZEN_MODELS, results)
                }
                self.assertEqual(determine_cheapest_successful_tier(by_tier), expected)

    def test_project_summary_contains_cheapest_tier(self):
        rows = []
        for item, final_result in zip(self.plan, ("FAIL", "PASS", "PASS")):
            result = fake_result(item, final_result=final_result)
            rows.append({
                "sample_id": item.sample_id,
                "tier": item.tier,
                "final_result": final_result,
                "remediation_coverage": result["remediation_coverage"],
                "new_finding_count": result["new_finding_count"],
                "terraform_valid": result["terraform_valid"],
            })

        summary = build_project_summary(["sample_01"], rows)

        self.assertEqual(summary[0]["cheapest_successful_tier"], "tier_2")

    def test_failure_reasons_are_semicolon_serialized(self):
        self.assertEqual(
            serialize_failure_reasons(
                ["TERRAFORM_VALIDATE_FAILURE", "NEW_SECURITY_FINDINGS"]
            ),
            "TERRAFORM_VALIDATE_FAILURE;NEW_SECURITY_FINDINGS",
        )

    def test_prompt_hash_inconsistency_is_reported(self):
        self.write_all_results({"tier_3": "different"})
        rows = collect_rows(self.plan, self.output_dir, PROTOCOL_VERSION, 8192)

        warnings = validate_screening_consistency(
            ["sample_01"], rows, FROZEN_MODELS, 8192
        )

        self.assertTrue(any("inconsistent prompt SHA256" in item for item in warnings))

    def test_rebuild_aggregates_writes_all_screening_indexes(self):
        self.write_all_results()
        config = {
            "protocol_version": PROTOCOL_VERSION,
            "models": FROZEN_MODELS,
            "max_output_tokens": 8192,
            "config_path": PROJECT_ROOT / "prompts" / "experiment_config.yaml",
        }

        rows, project_rows, summary = rebuild_aggregates(
            ["sample_01"], self.plan, self.output_dir, config
        )

        self.assertEqual(len(rows), 3)
        self.assertEqual(len(project_rows), 1)
        self.assertEqual(summary["completed_runs"], 3)
        self.assertEqual(summary["pass_runs"], 3)
        self.assertTrue((self.output_dir / "screening_results.csv").is_file())
        self.assertTrue(
            (self.output_dir / "project_screening_summary.csv").is_file()
        )
        self.assertTrue((self.output_dir / "screening_summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
