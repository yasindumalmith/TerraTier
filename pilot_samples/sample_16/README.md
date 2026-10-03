# TerraTier sample_16 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_28`  
**Target resource:** `aws_dynamodb_table.sample_16`  
**Security domain:** Database

## Medium-complexity characteristic

The table is referenced by a least-privilege IAM policy, but point-in-time recovery is disabled.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
