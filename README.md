# Grok CLI

CLI interface to query Grok AI from the command line. Uses stealth browser automation with your Chrome authentication to access Grok.

## Features

- **Dual endpoints** - Supports both grok.com (default) and x.com/i/grok
- **Stealth browser** - Uses nodriver for undetected Chrome automation
- **Chrome auth** - Extracts cookies from your Chrome browser (including HttpOnly)
- **Token counting** - Estimates token usage for Claude Code context budget
- **Multiple output modes** - Raw, JSON, formatted, token-focused
- **Model selection** - Support for Grok 4.1 Thinking, Grok 2, Grok 3

## Requirements

- **macOS** (uses Keychain for Chrome cookie decryption)
- **Python 3.11+**
- **Chrome browser** with active X.com login
- **X.com Premium** (Grok access required)

## Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/grok-cli.git
cd grok-cli

# The venv is created automatically on first run
python scripts/run.py grok.py --prompt "Hello"
```

Or install to Claude Code skills directory:
```bash
git clone https://github.com/yourusername/grok-cli.git ~/.claude/skills/grok-cli
```

## Usage

```bash
# Basic query (uses grok.com, requires --show-browser for Cloudflare bypass)
python scripts/run.py grok.py --prompt "What is the capital of France?" --show-browser

# Use x.com/i/grok instead (works headless but has stricter rate limits)
python scripts/run.py grok.py --prompt "Hello" --xcom

# Raw output (for piping)
python scripts/run.py grok.py --prompt "2+2=" --raw --show-browser

# JSON output
python scripts/run.py grok.py --prompt "Hello" --json --show-browser

# Token count focus
python scripts/run.py grok.py --prompt "Explain AI" --tokens --show-browser

# Complex queries with thinking model
python scripts/run.py grok.py --prompt "What's trending on X?" --thinking --show-browser
```

## Options

| Flag | Description |
|------|-------------|
| `--prompt, -p` | The prompt to send to Grok (required) |
| `--model, -m` | Model to use: `thinking` (default), `grok-2`, `grok-3` |
| `--timeout, -t` | Response timeout in seconds (default: 60) |
| `--thinking` | Use 120s timeout for Grok Thinking mode |
| `--xcom` | Use x.com/i/grok instead of grok.com |
| `--raw` | Output only response text |
| `--json` | Output full JSON with metadata |
| `--tokens` | Show token count with truncated response |
| `--screenshot` | Save screenshot to path |
| `--show-browser` | Show browser window (required for grok.com due to Cloudflare) |

## Model Selection

```bash
# Default: Grok 4.1 Thinking (15 queries per 20 hours on Premium)
python scripts/run.py grok.py --prompt "Complex question" --thinking

# Grok 2: Faster, no thinking overhead, different rate limits
python scripts/run.py grok.py --prompt "Quick question" --model grok-2
```

**Rate Limits (Premium):**
- Grok 4.1 Thinking: 15 queries per 20 hours
- Grok 2: Higher limits
- Premium+: Unlimited

## How It Works

1. **Cookie Extraction** - Reads X.com cookies from Chrome's SQLite database
2. **Decryption** - Decrypts cookie values using Chrome Safe Storage key from macOS Keychain
3. **Stealth Browser** - Launches nodriver (undetected Chrome)
4. **Cookie Injection** - Sets cookies via Chrome DevTools Protocol
5. **Navigation** - Opens Grok on X.com with your auth
6. **Interaction** - Types prompt, sends, polls for stable response
7. **Extraction** - Returns clean response text with token estimate

## Claude Code Integration

Use as a Claude Code skill to get real-time information:

```bash
# In Claude Code
python ~/.claude/skills/grok-cli/scripts/run.py grok.py \
  --prompt "What's the latest AI news?" \
  --thinking --raw
```

## Limitations

- **macOS only** - Cookie decryption uses macOS Keychain
- **X.com Premium required** - Grok access needed for x.com/i/grok
- **Cloudflare on grok.com** - Headless mode triggers Cloudflare challenge; use `--show-browser`
- **Rate limits (x.com)** - Thinking mode: 15 queries per 20 hours (Premium), unlimited with Premium+
- **Capacity limits (grok.com)** - Guest access may hit "heavy usage" limits; sign in for priority
- **Model switching blocked when rate limited** - The rate limit dialog blocks UI on x.com
- **No conversation history** - Each prompt is a fresh session

## License

MIT

## Acknowledgments

- [nodriver](https://github.com/AltamashRaza/nodriver) - Stealth browser automation
- Built for use with [Claude Code](https://claude.ai/claude-code)
