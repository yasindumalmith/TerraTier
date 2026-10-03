# TerraTier sample_26 — Medium Complexity

**Intended primary Checkov check:** `CKV2_AWS_40`  
**Target resource:** `aws_iam_policy.sample_26`  
**Security domain:** IAM

## Medium-complexity characteristic

Policy actions are defined through locals and attached to a role, creating moderate indirection without modules.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
