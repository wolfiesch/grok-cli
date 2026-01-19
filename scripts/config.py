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

# Grok UI selectors
GROK_URL = "https://x.com/i/grok"

# Input field - contenteditable div with "Ask anything" placeholder
GROK_INPUT_SELECTORS = [
    'div[data-testid="grokInput"]',
    'div[contenteditable="true"][data-placeholder="Ask anything"]',
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

# Stealth browser path (for cookie extraction)
STEALTH_BROWSER_DIR = Path.home() / ".claude" / "skills" / "stealth-browser"
