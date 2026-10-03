# TerraTier sample_13 — Medium Complexity

**Intended primary Checkov check:** `CKV_AWS_24`  
**Target resource:** `aws_security_group.sample_13`  
**Security domain:** Network

## Medium-complexity characteristic

Security group is referenced by an ENI; vulnerable CIDR is supplied through a variable.

## Important

This sample is intentionally vulnerable for research. Verify the intended check ID with the exact Checkov version used in the TerraTier experiment before launching LLM runs. Additional Checkov findings may appear; record them rather than silently editing the sample after experiments begin.
