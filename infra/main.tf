# Terraform + provider setup for the Tech Briefing Pipeline.
# See ../docs/ARCHITECTURE.md and ../docs/AWS_DEPLOYMENT_PLAN.md for the design this implements.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # State: local for now (single-maintainer project, no shared/remote state needed yet).
  # Revisit if a second person or a second machine (e.g. a CI runner triggering `apply`,
  # not just `update-function-code`) ever needs to run this — see docs/DECISIONS.md.
  #
  # backend "s3" {
  #   bucket         = "tech-briefing-tfstate"
  #   key            = "tech-briefing/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "tech-briefing-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  # Applied to every resource that supports tagging, automatically — this is the
  # AWS equivalent of grouping everything under one Azure-style resource group.
  # (No aws_resourcegroups_group resource — that would only add a cosmetic console
  # view on top of these tags, decided not worth it for this project's size.)
  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}

# Handy for building account-scoped ARNs elsewhere without hardcoding the account ID.
data "aws_caller_identity" "current" {}
