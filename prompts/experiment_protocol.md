# TerraTier Experiment Protocol v1.0

## Experiment Unit
One Terraform project × one model × one run.

## Dataset
Primary benchmark: TerraGoat AWS Terraform projects.
The TerraGoat commit/version used for the experiment must remain fixed.

## Models
- Tier 1: claude-haiku-4-5-20251001
- Tier 2: claude-sonnet-4-6
- Tier 3: claude-opus-4-8

## Generation Configuration
- Maximum output tokens: 8192
- Same remediation prompt for all models
- Prompt SHA256 recorded for every run
- Raw model output retained
- Input/output tokens retained
- Latency retained
- stop_reason retained

## Screening Phase
Each selected Terraform project is executed once with each of the three models.

## Validation
The following validation checks are performed:
1. terraform fmt -check
2. terraform init -backend=false
3. terraform validate
4. Checkov scan of original project
5. Checkov scan of remediated project
6. Original finding comparison
7. New finding detection
8. Resource preservation
9. Project structure preservation
10. Suppression detection
11. Semantic/generic invariant validation

## PASS Criteria
A remediation is PASS only when:
- generation completed successfully
- output was not truncated
- terraform init succeeded
- terraform validate succeeded
- all original security findings were removed
- zero new security findings were introduced
- original resources were preserved
- project structure was preserved
- no security suppression was introduced
- semantic/invariant validation passed
- no execution error occurred

## Terraform Formatting
terraform fmt is still executed and fmt_pass is recorded.

However, fmt_pass is a quality metric only and is NOT part of the final PASS/FAIL decision.

## Failure Categories
Examples:
- GENERATION_TRUNCATED
- TERRAFORM_INIT_FAILURE
- TERRAFORM_VALIDATE_FAILURE
- REMAINING_SECURITY_FINDINGS
- NEW_SECURITY_FINDINGS
- RESOURCE_PRESERVATION_FAILURE
- PROJECT_STRUCTURE_FAILURE
- SUPPRESSION_DETECTED
- SEMANTIC_VALIDATION_FAILURE
- EXECUTION_ERROR

## Cascade
Tier 1 / Haiku
    ↓ validation failure
Tier 2 / Sonnet
    ↓ validation failure
Tier 3 / Opus 4.8
    ↓ validation failure
UNRESOLVED

## Reproducibility
Model IDs, prompt, token limit, validation rules, benchmark version,
Terraform version, Checkov version, provider version and code version
must remain fixed for the screening experiment.