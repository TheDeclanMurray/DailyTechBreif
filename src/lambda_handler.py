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
        dict: {"statusCode": 200, "body": str} on success. The return value isn't
            consumed by EventBridge (this is an async invocation).

    Raises:
        RuntimeError: If the pipeline exits non-zero. Raising is load-bearing, not
            stylistic -- Lambda counts an invocation as an error ONLY when the handler
            raises. This previously returned {"statusCode": 500} instead, on the
            mistaken assumption that a non-2xx body registered as a failure; it does
            not. Every failed run was recorded as a success, so the Errors metric sat
            at 0 and the CloudWatch alarm in infra/alarms.tf never fired through seven
            consecutive days of dead briefings (2026-09-07 to 2026-09-15). The alarm is
            the backstop for failures that crash before main.py's own alerting can run,
            so it has to be driven by something the handler can't silently swallow.
    """
    exitCode = runPipeline()

    if exitCode == 0:
        return {"statusCode": 200, "body": "Pipeline completed successfully."}

    log.error("Lambda invocation failed with pipeline exit code %s.", exitCode)
    raise RuntimeError(f"Pipeline failed with exit code {exitCode}.")
