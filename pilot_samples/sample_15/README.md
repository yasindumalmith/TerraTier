# TerraTier sample_15 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_189`  
**Target resource:** `aws_ebs_volume.sample_15`  
**Security domain:** Encryption

## Medium-complexity characteristic

A customer-managed KMS key exists in the configuration but the EBS volume does not reference it.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
