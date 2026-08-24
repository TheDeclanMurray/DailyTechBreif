# Stub — scaffolded during architecture planning (2026-08-21), not yet implemented.
# Will hold: `aws_lambda_function` (package_type = "Image", image_uri from the ECR repo in
# ecr.tf), memory/timeout sized from real CloudWatch measurements (start generous — see
# AWS_DEPLOYMENT_PLAN.md § Open questions — then tune down), and the CloudWatch log group with
# a retention policy. Depends on the execution role defined in iam.tf.
