#!/usr/bin/env python3
"""
Grok CLI - Send prompts to Grok and get responses
Uses stealth browser with Chrome auth for authentication
"""

import asyncio
import argparse
import json
import re
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
    GROK_URL, GROK_URL_XCOM, GROK_URL_STANDALONE,
    GROK_INPUT_SELECTORS, GROK_SEND_SELECTORS, GROK_RESPONSE_SELECTORS,
    GROK_MODELS, DEFAULT_MODEL
)
from chrome_cookies import extract_cookies as extract_chrome_cookies


async def handle_grok_auth(page, browser, cookies):
    """
    Handle grok.com OAuth flow via X.com sign-in.

    Returns:
        tuple: (page, success, error_message)
    """
    # Check current URL
    current_url = page.url

    # First, inject X.com cookies (needed for OAuth)
    for c in cookies:
        if not c.get("value"):
            continue
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
        except Exception:
            pass

    # Check if we're on grok.com and need to sign in
    if "grok.com" in current_url and "sign-in" not in current_url:
        # Check if there's a sign-in button in header (indicates not logged in)
        needs_signin = await page.evaluate('''() => {
            // Check header for sign-in button
            const allElements = document.querySelectorAll('button, a');
            for (const el of allElements) {
                const text = (el.innerText || el.textContent || '').trim();
                // Header buttons will have text "Sign in"
                if (text === 'Sign in') {
                    return true;
                }
            }
            return false;
        }''')

        if needs_signin:
            # Use nodriver's select to find and click the sign-in button
            try:
                # Find the Sign in link/button in header
                sign_in_elements = await page.query_selector_all('button, a')
                for el in (sign_in_elements or []):
                    text = await page.evaluate('(el) => el.innerText', el)
                    if text and text.strip() == 'Sign in':
                        await el.click()
                        await page.sleep(3)
                        current_url = page.url
                        break
            except Exception:
                pass

    # If we're on accounts.x.ai sign-in page, complete the OAuth flow
    if "accounts.x.ai" in current_url or "sign-in" in current_url:
        # Look for "Sign in with X" or similar button
        await page.sleep(2)

        # Try multiple selectors for the X sign-in button
        sign_in_clicked = False
        sign_in_selectors = [
            'button:has-text("Sign in with X")',
            'button:has-text("Continue with X")',
            'a:has-text("Sign in with X")',
            '[data-testid="OAuth_Consent_Button"]',
        ]

        # Use JavaScript to find and click the sign-in button
        sign_in_clicked = await page.evaluate('''() => {
            const buttons = document.querySelectorAll('button, a');
            for (const btn of buttons) {
                const text = btn.innerText || btn.textContent || '';
                if (text.includes('Sign in with X') || text.includes('Continue with X') ||
                    text.includes('Sign in with 𝕏') || text.includes('Continue with 𝕏')) {
                    btn.click();
                    return true;
                }
            }
            // Also check for X logo button
            const xButtons = document.querySelectorAll('[aria-label*="X"], [aria-label*="Twitter"]');
            for (const btn of xButtons) {
                if (btn.tagName === 'BUTTON' || btn.tagName === 'A') {
                    btn.click();
                    return true;
                }
            }
            return false;
        }''')

        if sign_in_clicked:
            await page.sleep(3)

            # Check if we need to authorize the app (OAuth consent screen)
            current_url = page.url
            if "oauth" in current_url.lower() or "authorize" in current_url.lower():
                # Look for authorize/allow button
                await page.evaluate('''() => {
                    const buttons = document.querySelectorAll('button, input[type="submit"]');
                    for (const btn of buttons) {
                        const text = (btn.innerText || btn.value || '').toLowerCase();
                        if (text.includes('authorize') || text.includes('allow') || text.includes('continue')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                await page.sleep(3)

            # Wait for redirect back to grok.com
            for _ in range(10):
                current_url = page.url
                if "grok.com" in current_url and "sign-in" not in current_url:
                    return page, True, None
                await page.sleep(1)

        # If we're still on sign-in page, auth failed
        return page, False, f"OAuth flow incomplete. URL: {page.url}"

    # Already on grok.com or authenticated
    return page, True, None


async def prompt_grok(
    prompt: str,
    headless: bool = None,
    timeout: int = None,
    screenshot: str = None,
    show_browser: bool = False,
    raw: bool = False,
    model: str = None,
    use_xcom: bool = False,
    session_id: str = None
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
        # Extract cookies from Chrome - include grok.com and x.ai domains for standalone
        domains_to_extract = ["x.com", "twitter.com"]
        if not use_xcom:
            # Add grok.com and x.ai domains for standalone grok.com
            domains_to_extract.extend(["grok.com", "x.ai", "accounts.x.ai"])

        result = extract_chrome_cookies(domains_to_extract, decrypt=True)
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

        # Determine browser profile directory (unique per session for concurrency)
        if session_id:
            browser_profile = USER_DATA_DIR.parent / f"browser_profile_{session_id}"
            browser_profile.mkdir(exist_ok=True)
        else:
            browser_profile = USER_DATA_DIR

        # Start stealth browser
        browser = await uc.start(
            headless=headless,
            user_data_dir=str(browser_profile),
            browser_args=BROWSER_ARGS
        )

        # Determine if using standalone grok.com or x.com/i/grok
        grok_url = GROK_URL_XCOM if use_xcom else GROK_URL
        using_standalone = "grok.com" in grok_url

        if using_standalone:
            # For grok.com: First inject all relevant cookies
            injected = 0

            # Navigate to x.com first to set X.com cookies
            page = await browser.get("https://x.com")
            await page.sleep(1)

            for c in cookies:
                if not c.get("value"):
                    continue
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

            # Navigate to grok.com to set grok.com/x.ai cookies
            page = await browser.get("https://grok.com")
            await page.sleep(1)

            for c in cookies:
                if not c.get("value"):
                    continue
                cookie_domain = c.get("domain", "").lstrip(".")
                if not any(d in cookie_domain for d in ["grok.com", "x.ai"]):
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

            # Reload grok.com with cookies set
            page = await browser.get(grok_url)
            await page.sleep(3)

            # Handle OAuth flow if needed
            page, auth_success, auth_error = await handle_grok_auth(page, browser, cookies)
            if not auth_success:
                return {
                    "success": False,
                    "error": auth_error or "Authentication failed",
                    "url": page.url
                }
        else:
            # For x.com/i/grok: Set cookies first, then navigate
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

            # Navigate to Grok
            page = await browser.get(grok_url)
            await page.sleep(3)

        # Check if we're on Grok page (not login or challenge)
        current_url = page.url
        page_text = await page.evaluate('document.body.innerText') or ""

        # Check for Cloudflare challenge (common in headless mode)
        if "verify you are human" in page_text.lower() or "cloudflare" in page_text.lower():
            if screenshot:
                await page.save_screenshot(screenshot)
            return {
                "success": False,
                "error": "Cloudflare challenge detected. Use --show-browser flag to bypass.",
                "cloudflare_blocked": True,
                "hint": "Headless mode triggers Cloudflare protection on grok.com. Run with --show-browser instead.",
                "screenshot": screenshot
            }

        if "login" in current_url or "flow" in current_url or "sign-in" in current_url:
            return {
                "success": False,
                "error": "Authentication failed - redirected to login. Re-login in Chrome.",
                "url": current_url
            }

        # Dismiss any modal popups (grok.com shows upgrade/sign-in modals)
        try:
            # Try clicking the X button on the modal (visible in top-right of modal)
            dismissed = await page.evaluate('''() => {
                // Method 1: Find the X/close button by looking for SVG inside small button
                const allButtons = document.querySelectorAll('button');
                for (const btn of allButtons) {
                    // X button is typically small, circular, contains just an SVG
                    const svg = btn.querySelector('svg');
                    const text = (btn.innerText || '').trim();
                    // X button has no text, just icon
                    if (svg && !text && btn.offsetWidth < 60) {
                        btn.click();
                        return 'x-button';
                    }
                }

                // Method 2: Press Escape to close modal
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true
                }));
                return 'escape';
            }''')
            await page.sleep(1.5)

            # Double-check if modal is gone, try clicking outside it if still there
            still_has_modal = await page.evaluate('''() => {
                const modal = document.querySelector('[role="dialog"]');
                if (modal) {
                    // Try to click the overlay/backdrop behind modal
                    const rect = modal.getBoundingClientRect();
                    // Click far left of viewport (outside modal)
                    const clickEvent = new MouseEvent('click', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: 10, clientY: rect.top + 10
                    });
                    document.elementFromPoint(10, rect.top + 10)?.dispatchEvent(clickEvent);
                    return true;
                }
                return false;
            }''')
            if still_has_modal:
                await page.sleep(1)
        except Exception:
            pass

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
                # The model selector is in the header area, shows "Grok X.X Thinking" with dropdown
                # Use JavaScript to find and click it more precisely
                clicked = await page.evaluate('''() => {
                    // Find the model selector in the header (contains "Grok" and has a chevron/arrow)
                    const header = document.querySelector('header') || document.body;
                    const elements = header.querySelectorAll('div, button, span');
                    for (const el of elements) {
                        const text = el.innerText || '';
                        // Look for "Grok" + version number pattern in header area
                        if (text.match(/Grok\\s+[0-9]/) && text.includes('Thinking')) {
                            // Make sure it's the clickable dropdown, not a child element
                            if (el.closest('[aria-haspopup]') || el.querySelector('svg') || text.length < 30) {
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }''')

                if clicked:
                    await page.sleep(1.5)

                    # Find and click the target model in the dropdown
                    target_model_name = GROK_MODELS.get(selected_model, selected_model)

                    # Use JavaScript to find and click the menu option
                    await page.evaluate(f'''(targetModel) => {{
                        const items = document.querySelectorAll('[role="menuitem"], [role="option"], [role="menuitemradio"]');
                        for (const item of items) {{
                            if (item.innerText.toLowerCase().includes(targetModel.toLowerCase())) {{
                                item.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}''', target_model_name)
                    await page.sleep(1)

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
            # grok.com specific: find input near the placeholder text
            try:
                # Use JavaScript to find the input more reliably
                found = await page.evaluate('''() => {
                    // Find by placeholder text
                    const inputs = document.querySelectorAll('input, textarea, [contenteditable="true"]');
                    for (const input of inputs) {
                        const placeholder = input.getAttribute('placeholder') || input.getAttribute('data-placeholder') || '';
                        if (placeholder.toLowerCase().includes('what do you want') ||
                            placeholder.toLowerCase().includes('ask')) {
                            input.focus();
                            return true;
                        }
                    }
                    // Find by nearby text
                    const textNodes = document.evaluate(
                        "//text()[contains(., 'What do you want')]",
                        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    ).singleNodeValue;
                    if (textNodes) {
                        const container = textNodes.parentElement?.closest('[contenteditable], input, textarea');
                        if (container) {
                            container.focus();
                            return true;
                        }
                    }
                    return false;
                }''')
                if found:
                    # Get the focused element
                    input_element = await page.select(':focus', timeout=2)
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

        # Type the prompt
        await input_element.send_keys(prompt)
        await page.sleep(1)

        # Try to submit - first try clicking the submit button, then fallback to Enter
        submitted = False
        try:
            # Find and click submit button (grok.com uses aria-label="Submit")
            submit_btn = await page.select('button[aria-label="Submit"], button[type="submit"]', timeout=3)
            if submit_btn:
                await submit_btn.click()
                submitted = True
        except Exception:
            pass

        if not submitted:
            # Fallback to pressing Enter
            await input_element.send_keys("\n")

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

                # Check for rate limit or capacity errors
                if "reached your limit" in page_text.lower() or "limit of" in page_text:
                    if screenshot:
                        await page.save_screenshot(screenshot)
                    return {
                        "success": False,
                        "error": "Rate limit reached (15 Thinking queries/20hrs). Wait for reset or upgrade to Premium+.",
                        "rate_limited": True,
                        "hint": "Model switching unavailable while rate limited - the dialog blocks UI interaction.",
                        "screenshot": screenshot
                    }

                # Check for grok.com capacity/heavy usage error
                if "heavy usage" in page_text.lower() or "try again soon" in page_text.lower():
                    # Try to sign in to get priority access
                    if using_standalone:
                        # Click the Sign in button in the capacity error message
                        try:
                            sign_in_clicked = await page.evaluate('''() => {
                                const btns = document.querySelectorAll('button, a');
                                for (const btn of btns) {
                                    const text = (btn.innerText || '').trim();
                                    if (text === 'Sign in') {
                                        btn.click();
                                        return true;
                                    }
                                }
                                return false;
                            }''')
                            if sign_in_clicked:
                                await page.sleep(5)
                                # Check if we're now on sign-in page
                                current_signin_url = page.url
                                if "accounts.x.ai" in current_signin_url or "x.com" in current_signin_url:
                                    # Complete OAuth - look for authorize button
                                    await page.evaluate('''() => {
                                        const btns = document.querySelectorAll('button, input[type="submit"]');
                                        for (const btn of btns) {
                                            const text = (btn.innerText || btn.value || '').toLowerCase();
                                            if (text.includes('authorize') || text.includes('allow') ||
                                                text.includes('sign in') || text.includes('continue')) {
                                                btn.click();
                                                return true;
                                            }
                                        }
                                        return false;
                                    }''')
                                    await page.sleep(5)
                                    # If back on grok.com, retry the query
                                    if "grok.com" in page.url and "sign-in" not in page.url:
                                        continue  # Retry the response polling
                        except Exception:
                            pass

                    if screenshot:
                        await page.save_screenshot(screenshot)
                    return {
                        "success": False,
                        "error": "Grok is under heavy usage. Sign in for higher priority or try again later.",
                        "capacity_limited": True,
                        "hint": "Sign in to grok.com for priority access, or use --xcom flag to use x.com/i/grok instead.",
                        "screenshot": screenshot
                    }

                # Check if response is ready
                # For x.com/i/grok thinking model: look for "Thought for" indicator
                # For grok.com or other models: look for response content after prompt
                is_thinking_model = (model or DEFAULT_MODEL) == "thinking"
                is_standalone = using_standalone

                # Different detection for standalone grok.com vs x.com/i/grok
                if is_standalone:
                    # grok.com shows response timing (e.g., "911ms Fast") below response
                    has_response = prompt in page_text and ('ms' in page_text.lower() or 'fast' in page_text.lower() or 'slow' in page_text.lower())
                else:
                    has_response = "Thought for" in page_text if is_thinking_model else (prompt in page_text and len(page_text) > len(prompt) + 100)

                if has_response:
                    lines = page_text.split('\n')

                    # Find the prompt in the text
                    prompt_idx = None
                    for i, line in enumerate(lines):
                        if prompt in line:
                            prompt_idx = i
                            break

                    if prompt_idx is not None:
                        # Response is between the prompt and the action buttons/suggestions
                        response_lines = []

                        # For grok.com: response appears after prompt, before timing info
                        # For x.com: response appears after "Thought for" marker
                        start_idx = prompt_idx + 1

                        # On x.com, skip past "Thought for" line if present
                        if not is_standalone:
                            for j in range(prompt_idx + 1, min(prompt_idx + 5, len(lines))):
                                if "Thought for" in lines[j]:
                                    start_idx = j + 1
                                    break

                        for j in range(start_idx, min(start_idx + 30, len(lines))):
                            line = lines[j].strip()

                            # Skip empty lines at start
                            if not line and not response_lines:
                                continue

                            # Stop at timing info (grok.com shows "XXXms", "X.Xs", or "Fast/Slow")
                            if line.endswith('ms') or line.endswith('s') or line.lower() in ['fast', 'slow', 'medium']:
                                # Check if it looks like timing
                                stripped = line.rstrip('ms').rstrip('s').strip()
                                if stripped.replace('.', '').isdigit():
                                    break
                                if line.lower() in ['fast', 'slow', 'medium']:
                                    break
                            # Also check for combined timing like "989ms Fast" or "1.3s"
                            if re.match(r'^[\d.]+m?s(\s+(fast|slow|medium))?$', line.lower()):
                                break

                            # Stop at action buttons
                            if line in ['Copy', 'Share', 'Like', 'Dislike', 'Think Harder', '...']:
                                break

                            # Stop at follow-up suggestions (arrows)
                            if line.startswith('↳') or line.startswith('→'):
                                break

                            # Skip very short lines (icons, single chars)
                            if len(line) <= 2:
                                continue

                            # Skip suggestion lines
                            words = line.split()
                            if words and len(words) <= 6 and words[0] in ['Famous', 'Other', 'More', 'Tell', 'Show', 'List', 'Give', 'Explain', 'What', 'How', 'Why', 'When', 'Where', 'Who', 'Compare', 'Explore', 'Make', 'Learn']:
                                break

                            response_lines.append(line)

                        if response_lines:
                            candidate = '\n'.join(response_lines).strip()
                            if candidate == last_text:
                                stable_count += 1
                                if stable_count >= 2:
                                    response_text = candidate
                                    break
                            else:
                                stable_count = 0
                                last_text = candidate
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
    parser.add_argument("--xcom", action="store_true",
                        help="Use x.com/i/grok instead of standalone grok.com")
    parser.add_argument("--session-id",
                        help="Unique session ID for concurrent queries (uses separate browser profile)")

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
        model=args.model,
        use_xcom=args.xcom,
        session_id=args.session_id
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
