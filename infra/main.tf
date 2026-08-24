# Stub — scaffolded during architecture planning (2026-08-21), not yet implemented.
# Will hold: the `terraform { }` block (required_version, required_providers pinned to a
# specific `hashicorp/aws` version) and the `provider "aws" { }` block (region sourced from a
# variable, never hardcoded). Remote state backend (e.g. S3 + DynamoDB lock table) also
# belongs here once decided — currently undecided, defaults to local state until then.
#
# See ../docs/ARCHITECTURE.md and ../docs/AWS_DEPLOYMENT_PLAN.md for the design this implements.
