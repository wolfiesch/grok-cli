#!/usr/bin/env python3
"""
Grok CLI - Send prompts to Grok and get responses
Uses stealth browser with Chrome auth for authentication
"""

import asyncio
import argparse
import json
import sys
import time
from pathlib import Path

import nodriver as uc
from nodriver import cdp


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for Claude/GPT models.
    Uses ~4 chars per token heuristic (accurate within 10-20% for English).
    """
    if not text:
        return 0
    # More accurate: count words and apply 0.75 multiplier, or chars/4
    # Using char-based as it handles code/punctuation better
    return max(1, len(text) // 4)

from config import (
    HEADLESS, USER_DATA_DIR, BROWSER_ARGS, DEFAULT_TIMEOUT,
    GROK_URL, GROK_INPUT_SELECTORS, GROK_SEND_SELECTORS, GROK_RESPONSE_SELECTORS,
    GROK_MODELS, DEFAULT_MODEL
)
from chrome_cookies import extract_cookies as extract_chrome_cookies


async def prompt_grok(
    prompt: str,
    headless: bool = None,
    timeout: int = None,
    screenshot: str = None,
    show_browser: bool = False,
    raw: bool = False,
    model: str = None
) -> dict:
    """
    Send a prompt to Grok and get the response.

    Args:
        prompt: The prompt to send to Grok
        headless: Run headless (default from config)
        timeout: Response timeout in seconds
        screenshot: Path to save screenshot after response
        show_browser: Show browser window (overrides headless)
        raw: Return raw response without formatting
        model: Grok model to use (thinking, grok-2, grok-3)

    Returns:
        dict with response text and metadata
    """
    if headless is None:
        headless = HEADLESS
    if show_browser:
        headless = False
    if timeout is None:
        timeout = DEFAULT_TIMEOUT

    browser = None

    try:
        # Extract cookies from Chrome
        result = extract_chrome_cookies(["x.com", "twitter.com"], decrypt=True)
        if not result.get("success"):
            return {
                "success": False,
                "error": f"Cookie extraction failed: {result.get('error')}"
            }
        cookies = result.get("cookies", [])

        if not cookies:
            return {
                "success": False,
                "error": "No X.com cookies found. Make sure you're logged into X.com in Chrome."
            }

        # Start stealth browser
        browser = await uc.start(
            headless=headless,
            user_data_dir=str(USER_DATA_DIR),
            browser_args=BROWSER_ARGS
        )

        # Navigate to X.com first to set cookies
        page = await browser.get("https://x.com")
        await page.sleep(1)

        # Inject cookies via CDP
        injected = 0
        for c in cookies:
            if not c.get("value"):
                continue

            # Filter to X.com/twitter.com domains
            cookie_domain = c.get("domain", "").lstrip(".")
            if not any(d in cookie_domain for d in ["x.com", "twitter.com"]):
                continue

            try:
                same_site = None
                if c.get("same_site") in ["Strict", "Lax", "None"]:
                    same_site = cdp.network.CookieSameSite(c["same_site"])

                param = cdp.network.CookieParam(
                    name=c["name"],
                    value=c["value"],
                    domain=c.get("domain"),
                    path=c.get("path", "/"),
                    secure=c.get("secure", False),
                    http_only=c.get("http_only", False),
                    same_site=same_site,
                )
                await browser.connection.send(cdp.storage.set_cookies([param]))
                injected += 1
            except Exception:
                pass

        # Navigate to Grok (use compose URL for fresh chat)
        page = await browser.get(GROK_URL)
        await page.sleep(3)

        # Check if we're on Grok page (not login)
        current_url = page.url
        if "login" in current_url or "flow" in current_url:
            return {
                "success": False,
                "error": "Authentication failed - redirected to login. Re-login in Chrome.",
                "url": current_url
            }

        # Try to start a new chat (dismiss any rate limit dialogs)
        try:
            # Look for "new chat" or compose button
            new_chat_btn = await page.select('[aria-label="New chat"], [data-testid="newChat"]', timeout=2)
            if new_chat_btn:
                await new_chat_btn.click()
                await page.sleep(1)
        except Exception:
            pass

        # Select model if specified (and different from default)
        selected_model = model or DEFAULT_MODEL
        if selected_model and selected_model != "thinking":
            try:
                # Find and click the model selector (shows current model name)
                # Try multiple approaches to find the dropdown
                model_selector = None

                # Method 1: Find by text content "Grok" with dropdown indicator
                elements = await page.select_all('div, button, span')
                for elem in elements:
                    try:
                        text = await elem.get_js('self => self.innerText')
                        if text and "Grok" in text and "Thinking" in text:
                            # Check if it's clickable (has aria-haspopup or is near a chevron)
                            model_selector = elem
                            break
                    except Exception:
                        continue

                # Method 2: Find by aria attributes
                if not model_selector:
                    model_selector = await page.select('[aria-haspopup="listbox"], [aria-haspopup="menu"]', timeout=3)

                if model_selector:
                    await model_selector.click()
                    await page.sleep(1.5)

                    # Find and click the target model in the dropdown
                    target_model_name = GROK_MODELS.get(selected_model, selected_model)
                    # Look for menu items
                    menu_items = await page.select_all('[role="menuitem"], [role="option"], [role="listitem"]')
                    for item in menu_items:
                        try:
                            text = await item.get_js('self => self.innerText')
                            if text and target_model_name.lower() in text.lower():
                                await item.click()
                                await page.sleep(1)
                                break
                        except Exception:
                            continue
            except Exception as e:
                # Model selection failed, continue with default
                pass

        # Find and interact with the input field
        input_element = None
        for selector in GROK_INPUT_SELECTORS:
            try:
                input_element = await page.select(selector, timeout=5)
                if input_element:
                    break
            except Exception:
                continue

        if not input_element:
            # Try finding any contenteditable element
            try:
                input_element = await page.select('div[contenteditable="true"]', timeout=5)
            except Exception:
                pass

        if not input_element:
            if screenshot:
                await page.save_screenshot(screenshot)
            return {
                "success": False,
                "error": "Could not find Grok input field",
                "screenshot": screenshot
            }

        # Click the input and type the prompt
        await input_element.click()
        await page.sleep(0.5)

        # Type the prompt and send with Enter
        await input_element.send_keys(prompt + "\n")
        await page.sleep(2)

        # Wait for response - look for "Thought for" indicator first, then get response
        response_text = None
        start_time = time.time()
        last_text = None
        stable_count = 0

        while time.time() - start_time < timeout:
            try:
                # Method 1: Look for response after "Thought for Xs" element
                # The response appears below the thinking indicator
                page_text = await page.evaluate('document.body.innerText')

                # Check for rate limit
                if "reached your limit" in page_text.lower() or "limit of" in page_text:
                    if screenshot:
                        await page.save_screenshot(screenshot)
                    return {
                        "success": False,
                        "error": "Rate limit reached. Try --model grok-2 or wait for limit reset.",
                        "rate_limited": True,
                        "screenshot": screenshot
                    }

                # Check if response is ready
                # For thinking model: look for "Thought for" indicator
                # For other models: look for response after prompt
                is_thinking_model = (model or DEFAULT_MODEL) == "thinking"
                has_response = "Thought for" in page_text if is_thinking_model else (prompt in page_text and len(page_text) > len(prompt) + 100)

                if has_response:
                    # Find all text content in the main area
                    # Extract response - it's between user message and suggestions
                    lines = page_text.split('\n')

                    # Find the start of the response
                    response_start_idx = None
                    for i, line in enumerate(lines):
                        if is_thinking_model and "Thought for" in line:
                            response_start_idx = i
                            break
                        elif not is_thinking_model and prompt in line:
                            # Response starts after the prompt
                            response_start_idx = i
                            break

                    if response_start_idx is not None:
                        i = response_start_idx
                        # Response is the next non-empty line(s) after marker
                        response_lines = []
                        for j in range(i + 1, min(i + 20, len(lines))):
                            next_line = lines[j].strip()
                            # Stop at action buttons or follow-up suggestions
                            if next_line in ['', 'Explain', 'What'] or next_line.startswith('Explain ') or next_line.startswith('What '):
                                break
                            # Skip icon/button text
                            if len(next_line) <= 2 or next_line in ['Copy', 'Share', 'Like', 'Dislike']:
                                continue
                            response_lines.append(next_line)

                        if response_lines:
                            # Filter out follow-up suggestions and source citations
                            filtered = []
                            for line in response_lines:
                                words = line.split()
                                if not words:
                                    continue
                                # Skip source citations (e.g., "code.claude.com +1", "2 web pages")
                                if '+' in line and any(c.isdigit() for c in line):
                                    continue
                                if 'web page' in line.lower():
                                    continue
                                # Skip suggestions (short phrases with action verbs)
                                if len(words) <= 6 and words[0] in ['Famous', 'Other', 'More', 'Tell', 'Show', 'List', 'Give', 'Explain', 'What', 'How', 'Why', 'When', 'Where', 'Who', 'Compare', 'Explore', 'Make', 'Learn']:
                                    continue
                                filtered.append(line)

                            candidate = '\n'.join(filtered) if filtered else response_lines[0]
                            if candidate == last_text:
                                stable_count += 1
                                if stable_count >= 2:
                                    response_text = candidate
                                    break
                            else:
                                stable_count = 0
                                last_text = candidate
                        break
            except Exception:
                pass

            if response_text:
                break

            await page.sleep(1)

        # Take screenshot if requested
        if screenshot:
            await page.save_screenshot(screenshot)

        if not response_text:
            return {
                "success": False,
                "error": "Timeout waiting for Grok response",
                "screenshot": screenshot
            }

        # Estimate tokens for Claude Code context budget
        response_tokens = estimate_tokens(response_text)
        prompt_tokens = estimate_tokens(prompt)

        result = {
            "success": True,
            "response": response_text,
            "prompt": prompt,
            "cookies_used": injected,
            "tokens": {
                "response": response_tokens,
                "prompt": prompt_tokens,
                "total": response_tokens + prompt_tokens
            }
        }

        if screenshot:
            result["screenshot"] = screenshot

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        if browser:
            browser.stop()


def main():
    parser = argparse.ArgumentParser(
        description="Send prompts to Grok via CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python grok.py --prompt "What is the capital of France?"
  python grok.py --prompt "Explain quantum computing" --timeout 120
  python grok.py --prompt "Hello" --show-browser --screenshot /tmp/grok.png

Output:
  By default, prints only the response text.
  Use --json for full JSON output with metadata.
"""
    )
    parser.add_argument("--prompt", "-p", required=True,
                        help="The prompt to send to Grok")
    parser.add_argument("--timeout", "-t", type=int, default=60,
                        help="Response timeout in seconds (default: 60)")
    parser.add_argument("--thinking", action="store_true",
                        help="Use longer timeout (120s) for Grok Thinking mode queries")
    parser.add_argument("--screenshot", "-s",
                        help="Save screenshot to this path")
    parser.add_argument("--show-browser", action="store_true",
                        help="Show browser window")
    parser.add_argument("--json", action="store_true",
                        help="Output full JSON response")
    parser.add_argument("--raw", action="store_true",
                        help="Output raw response text only (no formatting)")
    parser.add_argument("--tokens", action="store_true",
                        help="Show estimated token count for Claude Code context")
    parser.add_argument("--model", "-m",
                        choices=["thinking", "grok-2", "grok-3"],
                        default="thinking",
                        help="Grok model to use (default: thinking). Use grok-2 to avoid thinking rate limits.")

    args = parser.parse_args()

    # Apply thinking mode timeout (only for thinking model)
    if args.thinking and args.model == "thinking":
        timeout = 120
    else:
        timeout = args.timeout

    result = asyncio.run(prompt_grok(
        prompt=args.prompt,
        timeout=timeout,
        screenshot=args.screenshot,
        show_browser=args.show_browser,
        raw=args.raw,
        model=args.model
    ))

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.tokens:
        # Token-focused output
        if result.get("success"):
            tokens = result.get("tokens", {})
            print(f"Response: {tokens.get('response', 0)} tokens")
            print(f"Prompt: {tokens.get('prompt', 0)} tokens")
            print(f"Total: {tokens.get('total', 0)} tokens")
            print("---")
            print(result["response"][:200] + "..." if len(result["response"]) > 200 else result["response"])
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)
    else:
        if result.get("success"):
            if args.raw:
                print(result["response"])
            else:
                tokens = result.get("tokens", {})
                print("\n" + "=" * 60)
                print(f"Prompt: {args.prompt}")
                print(f"Tokens: ~{tokens.get('total', 0)} (response: {tokens.get('response', 0)})")
                print("=" * 60)
                print()
                print(result["response"])
                print()
                print("=" * 60)
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
