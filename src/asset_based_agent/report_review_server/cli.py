"""Development server launcher."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "asset_based_agent.report_review_server.main:app",
        host="127.0.0.1",
        port=8800,
        reload=False,
    )
