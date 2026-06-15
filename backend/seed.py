"""Convenience wrapper so you can run `python seed.py` from the backend directory."""
import asyncio
from app.seed import main

if __name__ == "__main__":
    asyncio.run(main())
