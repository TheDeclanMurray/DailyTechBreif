"""
AWS Lambda entry point for the Tech Briefing Pipeline.

Wraps src.main.runPipeline() behind the handler(event, context) signature the Lambda
Runtime Interface Client expects (see the Dockerfile's CMD). EventBridge Scheduler
invokes this on a cron schedule with an empty event -- neither event nor context
carries any pipeline input, everything comes from src/config.py (Lambda env vars +
SSM Parameter Store).
"""

import logging

from src.main import runPipeline

log = logging.getLogger("tech_briefing")


def handler(event, context):
    """
    Lambda entry point. Runs the full pipeline and reports success/failure.

    Args:
        event (dict): Lambda event payload. Unused -- EventBridge sends no pipeline
            input; everything the pipeline needs comes from config.
        context (LambdaContext): Lambda runtime context object. Unused.

    Returns:
        dict: {"statusCode": int, "body": str} -- 200 on success, 500 on failure.
            The return value isn't consumed by EventBridge (this is an async
            invocation), but a non-2xx statusCode is what makes a failed run show up
            as an "Errors" metric in CloudWatch, which the alarm in
            docs/TODO.md's backstop-alert item will watch.
    """
    exitCode = runPipeline()

    if exitCode == 0:
        return {"statusCode": 200, "body": "Pipeline completed successfully."}

    log.error("Lambda invocation failed with pipeline exit code %s.", exitCode)
    return {"statusCode": 500, "body": f"Pipeline failed with exit code {exitCode}."}
