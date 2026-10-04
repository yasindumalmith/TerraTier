import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from run_project_remediation import add_generation_outcome  # noqa: E402
from run_remediation import build_generation_record  # noqa: E402
from validate_project_remediation import (  # noqa: E402
    failure_result,
    project_failure_reasons,
)


def anthropic_message(stop_reason, output_tokens=100, stop_sequence=None):
    return SimpleNamespace(
        id="msg_test",
        model="claude-haiku-4-5-20251001",
        stop_reason=stop_reason,
        stop_sequence=stop_sequence,
        usage=SimpleNamespace(input_tokens=25, output_tokens=output_tokens),
    )


class GenerationStatusTests(unittest.TestCase):
    def test_end_turn_is_complete_and_not_truncated(self):
        generation = build_generation_record(
            anthropic_message("end_turn"),
            "claude-haiku-4-5-20251001",
            4096,
            latency_seconds=1.25,
            generated_at="2026-10-04T00:00:00+00:00",
        )

        self.assertFalse(generation["output_truncated"])
        self.assertTrue(generation["generation_complete"])
        self.assertEqual(generation["stop_reason"], "end_turn")
        self.assertEqual(generation["input_tokens"], 25)
        self.assertEqual(generation["output_tokens"], 100)

    def test_max_tokens_forces_execution_failure_and_cannot_pass(self):
        generation = build_generation_record(
            anthropic_message("max_tokens", output_tokens=4096),
            "claude-haiku-4-5-20251001",
            4096,
        )
        metadata = {"generation": generation}
        result = failure_result("LLM_OUTPUT_TRUNCATED", "token limit", [])
        result["final_result"] = "PASS"

        result = add_generation_outcome(result, metadata)

        self.assertTrue(generation["output_truncated"])
        self.assertFalse(generation["generation_complete"])
        self.assertEqual(result["final_result"], "FAIL")
        self.assertTrue(result["execution_error"])
        self.assertEqual(result["execution_error_type"], "LLM_OUTPUT_TRUNCATED")
        self.assertEqual(result["run_status"], "GENERATION_TRUNCATED")
        self.assertIn("LLM_OUTPUT_TRUNCATED", result["failure_reasons"])


class ProjectPassRuleTests(unittest.TestCase):
    def strict_rule(self, **overrides):
        values = {
            "fmt_pass": True,
            "init_pass": True,
            "terraform_valid": True,
            "original_scan_success": True,
            "remediated_scan_success": True,
            "remaining_finding_count": 0,
            "new_finding_count": 0,
            "resources_preserved": True,
            "suppression_added": False,
            "semantic_validation_pass": True,
        }
        values.update(overrides)
        return project_failure_reasons(**values)

    def test_formatting_failure_alone_passes(self):
        reasons = self.strict_rule(fmt_pass=False)
        final_result = "PASS" if not reasons else "FAIL"

        self.assertNotIn("TERRAFORM_FMT_FAILURE", reasons)
        self.assertEqual(final_result, "PASS")

    def test_formatting_failure_with_new_finding_fails_only_for_finding(self):
        reasons = self.strict_rule(fmt_pass=False, new_finding_count=1)
        final_result = "PASS" if not reasons else "FAIL"

        self.assertEqual(reasons, ["NEW_SECURITY_FINDINGS"])
        self.assertNotIn("TERRAFORM_FMT_FAILURE", reasons)
        self.assertEqual(final_result, "FAIL")

    def test_valid_formatting_with_invalid_terraform_fails(self):
        reasons = self.strict_rule(fmt_pass=True, terraform_valid=False)
        final_result = "PASS" if not reasons else "FAIL"

        self.assertEqual(reasons, ["TERRAFORM_VALIDATE_FAILURE"])
        self.assertEqual(final_result, "FAIL")


if __name__ == "__main__":
    unittest.main()
