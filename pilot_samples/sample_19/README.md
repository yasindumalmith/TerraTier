# TerraTier sample_19 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_163`  
**Target resource:** `aws_ecr_repository.sample_19`  
**Security domain:** Container Registry

## Medium-complexity characteristic

Repository uses a KMS key and lifecycle policy; only scan-on-push is intentionally disabled.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
