# Grok CLI

CLI interface to query Grok AI from the command line. Uses stealth browser automation with your Chrome authentication to access Grok on X.com.

## Features

- **Stealth browser** - Uses nodriver for undetected Chrome automation
- **Chrome auth** - Extracts cookies from your Chrome browser (including HttpOnly)
- **Token counting** - Estimates token usage for Claude Code context budget
- **Multiple output modes** - Raw, JSON, formatted, token-focused
- **Thinking mode** - Extended timeout for complex queries

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
# Basic query
python scripts/run.py grok.py --prompt "What is the capital of France?"

# Raw output (for piping)
python scripts/run.py grok.py --prompt "2+2=" --raw

# JSON output
python scripts/run.py grok.py --prompt "Hello" --json

# Token count focus
python scripts/run.py grok.py --prompt "Explain AI" --tokens

# Complex queries (real-time data, trending, news)
python scripts/run.py grok.py --prompt "What's trending on X?" --thinking

# Debug with visible browser
python scripts/run.py grok.py --prompt "Test" --show-browser
```

## Options

| Flag | Description |
|------|-------------|
| `--prompt, -p` | The prompt to send to Grok (required) |
| `--timeout, -t` | Response timeout in seconds (default: 60) |
| `--thinking` | Use 120s timeout for Grok Thinking mode |
| `--raw` | Output only response text |
| `--json` | Output full JSON with metadata |
| `--tokens` | Show token count with truncated response |
| `--screenshot` | Save screenshot to path |
| `--show-browser` | Show browser window for debugging |

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
- **X.com Premium required** - Grok access needed
- **Rate limits** - Subject to X.com's rate limiting
- **No conversation history** - Each prompt is a fresh session

## License

MIT

## Acknowledgments

- [nodriver](https://github.com/AltamashRaza/nodriver) - Stealth browser automation
- Built for use with [Claude Code](https://claude.ai/claude-code)
