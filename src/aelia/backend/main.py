from __future__ import annotations

import uvicorn

from aelia.app.config import load_settings
from aelia.backend.api import create_app


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.runtime_host,
        port=settings.runtime_port,
        log_level=settings.log_level.value.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
