# TerraTier sample_14 — Medium Complexity

**Intended primary Checkov check:** `CKV2_AWS_40`  
**Target resource:** `aws_iam_policy.sample_14`  
**Security domain:** IAM

## Medium-complexity characteristic

Broad IAM permissions are attached to a role, adding resource references and policy context.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
