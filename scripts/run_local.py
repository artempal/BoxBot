#!/usr/bin/env python
"""Script to run the BoxBot locally in development mode."""

import os
import sys
import logging
import asyncio

# Add parent directory to path to import boxbot
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from boxbot.bot.bot import run_polling

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    logging.info("Starting BoxBot in development mode...")
    run_polling() 