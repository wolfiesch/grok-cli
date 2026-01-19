---
name: grok-cli
description: CLI interface to Grok AI. Send prompts and get responses via command line, enabling integration with Claude Code and other tools. Uses stealth browser with Chrome auth for authenticated access.
---

# Grok CLI Skill

Query Grok AI from the command line using your existing X.com authentication. Perfect for integrating Grok responses into Claude Code workflows.

## When to Use This Skill

Trigger when user:
- Wants to query Grok/xAI
- Mentions "ask Grok", "prompt Grok", "Grok says"
- Needs real-time information that Grok has access to
- Wants to compare responses between Claude and Grok
- Needs X.com/Twitter-specific information

## Prerequisites

1. **Logged into X.com in Chrome**: The skill uses your Chrome session
2. **Grok access**: Must have access to Grok on X.com (Premium subscription)

## Critical: Always Use run.py Wrapper

**NEVER call scripts directly. ALWAYS use `python scripts/run.py [script]`:**

```bash
# CORRECT:
python scripts/run.py grok.py --prompt "Your question here"

# WRONG:
python scripts/grok.py --prompt "..."  # Fails without venv!
```

## Core Usage

### Basic Query (uses grok.com, requires --show-browser)
```bash
python scripts/run.py grok.py --prompt "What is the latest news about AI?" --show-browser
```

### Use x.com/i/grok (alternative endpoint)
```bash
python scripts/run.py grok.py --prompt "Hello" --xcom
```

### With Options
```bash
# Longer timeout for complex queries
python scripts/run.py grok.py --prompt "Explain quantum computing" --timeout 120 --show-browser

# Save screenshot
python scripts/run.py grok.py --prompt "What's trending?" --screenshot /tmp/grok.png --show-browser

# JSON output for parsing
python scripts/run.py grok.py --prompt "Capital of France?" --json --show-browser

# Raw output (just the response text, for piping)
python scripts/run.py grok.py --prompt "One word answer: 2+2=" --raw --show-browser

# Use different model (grok-2 has higher rate limits)
python scripts/run.py grok.py --prompt "Hello" --model grok-2 --show-browser

# Run multiple queries in parallel
python scripts/run.py grok.py --prompt "Query 1" --show-browser --session-id a &
python scripts/run.py grok.py --prompt "Query 2" --show-browser --session-id b &
wait
```

### Piping to Other Tools
```bash
# Get Grok's response and pipe it
python scripts/run.py grok.py --prompt "List 5 trending topics" --raw | head -5

# Use in shell scripts
GROK_RESPONSE=$(python scripts/run.py grok.py --prompt "What day is it?" --raw)
echo "Grok says: $GROK_RESPONSE"
```

## Script Reference

### `grok.py` - Main Prompt Interface
```bash
python scripts/run.py grok.py --prompt "..." [options]

Options:
  --prompt, -p    The prompt to send to Grok (required)
  --timeout, -t   Response timeout in seconds (default: 60)
  --screenshot    Save screenshot to this path
  --show-browser  Show browser window for debugging
  --json          Output full JSON response with metadata
  --raw           Output only response text (no formatting)
```

## Output Formats

### Default (formatted)
```
============================================================
Prompt: What is 2+2?
============================================================

4

============================================================
```

### JSON (`--json`)
```json
{
  "success": true,
  "response": "4",
  "prompt": "What is 2+2?",
  "cookies_used": 20
}
```

### Raw (`--raw`)
```
4
```

## Integration with Claude Code

Use this skill when Claude Code needs information that:
- Requires real-time data (news, trends, current events)
- Is specific to X.com/Twitter ecosystem
- Would benefit from a second AI perspective

Example workflow in Claude Code:
```bash
# Claude Code can invoke this to get Grok's take
python ~/.claude/skills/grok-cli/scripts/run.py grok.py \
  --prompt "What are the latest developments in AI safety?" \
  --raw
```

## Environment Management

The virtual environment is automatically managed:
- First run creates `.venv` automatically
- Dependencies install automatically
- Everything isolated in skill directory

Manual setup (only if automatic fails):
```bash
cd ~/.claude/skills/grok-cli
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Data Storage

All data stored in `~/.claude/skills/grok-cli/data/`:
- `screenshots/` - Saved screenshots
- `browser_profile/` - Browser state for stealth

## Configuration

Optional `.env` file:
```env
HEADLESS=true              # Default browser visibility
DEFAULT_TIMEOUT=60         # Response timeout (seconds)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cloudflare challenge detected" | Use `--show-browser` flag (required for grok.com) |
| "Cookie extraction failed" | Login to X.com in Chrome |
| "Authentication failed" | Re-login to X.com, cookies may have expired |
| "Grok is under heavy usage" | Try again later, or sign in to grok.com for priority |
| "Rate limit reached" | Wait for reset or use `--model grok-2` for higher limits |
| "Could not find input field" | UI may have changed, try `--xcom` flag |
| ModuleNotFoundError | Use `run.py` wrapper |
| Timeout waiting for response | Increase `--timeout`, try `--show-browser` |

## Limitations

- **macOS only** - Cookie decryption uses macOS Keychain
- **--show-browser required for grok.com** - Cloudflare blocks headless mode
- **Rate limits** - Thinking: 15/20hrs (Premium), Grok-2: higher limits, Premium+: unlimited
- **Capacity limits on grok.com** - Guest access may be throttled during high traffic
- No conversation history (each prompt is fresh)

## How It Works

1. **Cookie Extraction**: Reads X.com cookies from Chrome's database
2. **Decryption**: Decrypts encrypted cookie values using macOS Keychain
3. **Stealth Browser**: Launches nodriver (undetected Chrome)
4. **Cookie Injection**: Sets cookies via Chrome DevTools Protocol
5. **Navigation**: Opens Grok on X.com
6. **Interaction**: Types prompt, sends, waits for response
7. **Extraction**: Polls for stable response text, returns it
