"""Lambda entry point (thin shim).

The real implementation lives in lambda_app/ (common, auth, admin,
projects, board, handler). This shim keeps the configured Lambda handler
`lambda_function.handler` and any existing imports working unchanged.
"""
from lambda_app.handler import handler

__all__ = ["handler"]
