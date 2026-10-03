# TerraTier sample_22 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_136`  
**Target resource:** `aws_ecr_repository.sample_22`  
**Security domain:** Container Registry

## Medium-complexity characteristic

The repository has scanning and immutable tags, but deliberately uses AES256 instead of KMS encryption.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
