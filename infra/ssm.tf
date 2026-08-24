# Stub — scaffolded during architecture planning (2026-08-21), not yet implemented.
# Will hold `aws_ssm_parameter` *definitions* (type = "SecureString") for every secret currently
# in .env.example (ANTHROPIC_API_KEY, SMTP_PASSWORD, etc.) — definitions only. Actual secret
# values are never committed here; they get set out-of-band (console or `aws ssm put-parameter`)
# after `terraform apply` creates the parameter shells.
