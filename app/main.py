"""Minimal FastAPI receiver for Microsoft Graph change notifications.
"""

import hmac
import json
import logging
import os
import sys
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

# --- Logging ---------------------------------------------------------------
# Log to stdout (not a file) so Azure can capture the output as app logs.
# Format: timestamp | level | logger name | message
logging.basicConfig(
    stream=sys.stdout,
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("graph-webhook")

# Interactive docs are switched off so the public endpoint exposes only the
# two routes below (/docs, /redoc and /openapi.json would otherwise be public).
app = FastAPI(
    title="Graph Webhook (R&D)",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/")
async def index() -> dict[str, str]:
    """Health check. Application Gateway's health probe should call this."""
    logger.info("Hello World")
    return {"message": "Hello World"}


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    """Receive Microsoft Graph change notifications."""
    EXPECTED_CLIENT_STATE = os.getenv("CLIENT_STATE")

    # A) Validation handshake.
    # When a subscription is created, Graph POSTs to this URL with a
    # ?validationToken=... query parameter and expects the exact token back
    # as text/plain with HTTP 200 (within 10 seconds).
    validation_token = request.query_params.get("validationToken")
    if validation_token is not None:
        logger.info("Received validation request")
        return PlainTextResponse(content=validation_token, status_code=200)

    # B) Real change notification.
    # The body looks like {"value": [ {...}, {...} ]}. Graph can batch several
    # notifications into one request, so we never assume a single item.
    try:
        payload: Any = await request.json()
    except json.JSONDecodeError:
        logger.warning("Received a non-JSON body on /webhook")
        return JSONResponse(status_code=400, content={"detail": "Body must be valid JSON"})

    notifications = payload.get("value", []) if isinstance(payload, dict) else []

    valid = []
    for item in notifications:
        received = item.get("clientState", "")
        if EXPECTED_CLIENT_STATE and hmac.compare_digest(received, EXPECTED_CLIENT_STATE):
            valid.append(item)
        else:
            logger.warning("Dropping notification with bad clientState (subscription %s)",
                        item.get("subscriptionId"))

    logger.info("Received %d notification(s), %d valid", len(notifications), len(valid))
    logger.info("Valid payload: %s", json.dumps(valid))

    # Graph expects a quick 202 Accepted. Processing is intentionally skipped.
    return Response(status_code=202)
