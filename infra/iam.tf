# Stub — scaffolded during architecture planning (2026-08-21), not yet implemented.
# Will hold two distinct roles — keep them separate, don't merge:
#   1. Lambda execution role: CloudWatch Logs write, S3 read/write scoped to the token bucket
#      only, SSM GetParameter scoped to this project's parameter path only.
#   2. GitHub OIDC deploy role: trust policy = token.actions.githubusercontent.com, condition
#      scoped to this exact repo (TheDeclanMurray/DailyTechBreif) and branch (main) so no other
#      repo/branch can assume it. Permissions: ECR push + lambda:UpdateFunctionCode only —
#      nothing broader. No static AWS access keys anywhere (see docs/DECISIONS.md).
