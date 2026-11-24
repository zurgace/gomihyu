"""Starts her: `venv/bin/python -m gomi` from the repo root (README, "Run")."""

import asyncio

from .bot import main

try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
