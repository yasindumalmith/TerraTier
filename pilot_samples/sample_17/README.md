# TerraTier sample_17 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_7`  
**Target resource:** `aws_kms_key.sample_17`  
**Security domain:** Encryption

## Medium-complexity characteristic

The key is used by a CloudWatch log group, so remediation must preserve a real cross-resource reference.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
