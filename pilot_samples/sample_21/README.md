# TerraTier sample_21 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_126`  
**Target resource:** `aws_instance.sample_21`  
**Security domain:** Compute

## Medium-complexity characteristic

The instance uses an instance profile and secure metadata settings, but detailed monitoring is disabled.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
