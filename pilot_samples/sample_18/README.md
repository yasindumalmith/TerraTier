# TerraTier sample_18 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_338`  
**Target resource:** `aws_cloudwatch_log_group.sample_18`  
**Security domain:** Logging

## Medium-complexity characteristic

The log group is encrypted and used by a log stream, but retention remains intentionally short.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
