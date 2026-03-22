from __future__ import annotations

import uvicorn

from autodosie_bot.config import load_config


def main() -> None:
    config = load_config()
    uvicorn.run(
        "autodosie_bot.web:app",
        host=config.web_host,
        port=config.web_port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
