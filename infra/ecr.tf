# ECR repository holding the Lambda container image, built and pushed by GitHub Actions.

resource "aws_ecr_repository" "this" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE" # CI pushes a new tag (the git SHA) on every deploy

  image_scanning_configuration {
    scan_on_push = true # free vulnerability scan on every push, no reason not to
  }
}

# CI tags every push with a unique git SHA (never reused), so tagged images never age
# out on their own — rule 1 below is just a safety net for genuinely orphaned images
# (partial/interrupted pushes, manifest re-pushes). Rule 2 is what actually bounds repo
# growth: it keeps only the newest 4 tagged images (the active deploy + 3 rollback
# candidates) and expires everything older, which also naturally retires the one-off
# `:initial` bootstrap tag (see lambda.tf) once a few real deploys have landed on top of it.
resource "aws_ecr_lifecycle_policy" "expire_untagged" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 14 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 14
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the 4 most recent tagged images (active + 3 rollback candidates)"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 4
        }
        action = { type = "expire" }
      }
    ]
  })
}
