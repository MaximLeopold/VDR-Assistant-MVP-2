"""Load environment variables and application settings.

This module should read values such as OPENAI_API_KEY, OPENAI_MODEL,
and VECTOR_STORE_ID from the local .env file.
"""

"""Application settings loaded from environment variables.

Secrets such as the OpenAI API key must not be committed to GitHub.
Use a local .env file when running the app locally.
"""

import os

from dotenv import load_dotenv


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")
VDR_FOLDER = os.getenv("VDR_FOLDER")


def validate_settings() -> list[str]:
    """Return a list of missing required settings."""
    missing_settings = []

    if not OPENAI_API_KEY:
        missing_settings.append("OPENAI_API_KEY")

    if not VECTOR_STORE_ID:
        missing_settings.append("VECTOR_STORE_ID")

    return missing_settings
