# Stub — scaffolded during architecture planning (2026-08-21), not yet implemented.
# Will hold an EventBridge Scheduler rule invoking the Lambda directly (no intermediary), cron
# = weekly Monday — timezone is an open decision (EventBridge cron expressions are UTC; the old
# Ubuntu cron implicitly used server-local time, see ARCHITECTURE.md § Open items) — resolve
# and document the chosen timezone here once decided, don't leave it implicit.
