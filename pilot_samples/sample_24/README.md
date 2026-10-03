# TerraTier sample_24 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_23`  
**Target resource:** `aws_security_group.sample_24`  
**Security domain:** Network

## Medium-complexity characteristic

The security group is consumed by an ENI, and rule descriptions are intentionally omitted.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
