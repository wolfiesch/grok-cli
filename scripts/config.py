#!/usr/bin/env python3
"""
Configuration for Grok CLI skill
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
SKILL_DIR = Path(__file__).parent.parent
load_dotenv(SKILL_DIR / ".env")

# Data directories
DATA_DIR = SKILL_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
USER_DATA_DIR = DATA_DIR / "browser_profile"

# Create directories
DATA_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)
USER_DATA_DIR.mkdir(exist_ok=True)

# Browser settings
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "60"))

# Browser args for stealth
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]

# Grok URLs
GROK_URL_XCOM = "https://x.com/i/grok"
GROK_URL_STANDALONE = "https://grok.com"
GROK_URL = GROK_URL_STANDALONE  # Default to standalone (different rate limits)

# Input field selectors for both grok.com and x.com/i/grok
GROK_INPUT_SELECTORS = [
    # grok.com standalone site
    'textarea[aria-label="Ask Grok anything"]',
    'textarea[aria-label*="Ask Grok"]',
    # x.com/i/grok
    'div[data-testid="grokInput"]',
    'div[contenteditable="true"][data-placeholder="Ask anything"]',
    'div[contenteditable="true"][data-placeholder*="What do you want"]',
    'div[role="textbox"][data-placeholder]',
    'textarea[placeholder*="Ask"]',
]

# Send button
GROK_SEND_SELECTORS = [
    'button[data-testid="grokSendButton"]',
    'button[aria-label="Send"]',
    'div[data-testid="grokInput"] ~ button',
]

# Response container
GROK_RESPONSE_SELECTORS = [
    'div[data-testid="grokResponse"]',
    'div[data-testid="messageContent"]',
    'div.message-content',
]

# Available Grok models
GROK_MODELS = {
    "thinking": "Grok 4.1 Thinking",  # Default, has 15/20hr rate limit
    "grok-2": "Grok 2",               # Faster, no thinking overhead
    "grok-3": "Grok 3",               # If available
}
DEFAULT_MODEL = "thinking"

