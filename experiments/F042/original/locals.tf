locals {
  resource_scope = {
    bucket_path       = module.storage.bucket_arn
    object_path       = "${module.storage.bucket_arn}/*"
    encryption_target = module.storage.kms_key_arn
  }
}
