# TerraTier sample_23 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_119`  
**Target resource:** `aws_dynamodb_table.sample_23`  
**Security domain:** Database

## Medium-complexity characteristic

A customer-managed key exists but the table encryption block does not reference it.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
