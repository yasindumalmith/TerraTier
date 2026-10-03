# TerraTier sample_42

Complex/stress-test Terraform sample for TerraTier.

## Intended target

- Check: `CKV_AWS_355`
- Resource: `aws_iam_policy.worker`
- Security domain: IAM
- Complexity: complex / cross-resource

## Intended semantic remediation

The `ObjectAccess` statement should use:

`local.resource_scope.object_path`

The `BucketAccess` statement should remain:

`local.resource_scope.bucket_path`

The `EncryptionAccess` statement should use:

`local.resource_scope.encryption_target`

The model should preserve the original IAM actions and supporting resources.

## Validate before API experiments

```bash
terraform fmt
terraform init
terraform validate
checkov -d .
```

Confirm that your installed Checkov version detects the intended target before running LLM experiments.
