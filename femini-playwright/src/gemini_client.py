import asyncio
import time
import json
import re
import os
import base64
import traceback
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
import cv2
import numpy as np
from json_repair import repair_json
from playwright.async_api import BrowserContext, Page, Locator, TimeoutError as PlaywrightTimeoutError

from .config import Credential, Settings
import structlog

logger = structlog.get_logger(__name__)


class GeminiClient:
    """Async Playwright-based Gemini AI Studio automation client"""

    def __init__(self, context: BrowserContext, credential: Credential, settings: Settings):
        self.context = context
        self.credential = credential
        self.settings = settings

        # State management
        self.page: Optional[Page] = None
        self.last_prompt: Optional[str] = None
        self.is_last_response_image = False
        self.generation_in_progress = False
        self.generated_images: List[str] = []
        self.is_image = False
        self.reference_starred_drive_image_name: Optional[str] = None
        self.reference_image_path: Optional[str] = None
        self.force_json = False
        self.force_text = False
        self.enable_paste_with_js = True
        self.retry = True

        # Stats
        self.request_count = 0
        self.error_count = 0

    async def _clean_response_text(self, text: str) -> str:
        """Clean and normalize response text from Gemini"""
        if not text:
            return text

        # 1. Decode literal Unicode escapes (e.g., \u1234, \u1F600, \U0001F600)
        # Using regex to find and decode escapes individually preserves existing UTF-8 emojis.
        if "\\u" in text or "\\U" in text:
            try:
                def decode_match(match):
                    esc = match.group(0)
                    try:
                        # Handle non-standard 5-digit escapes (e.g. \u1F600)
                        if esc.startswith("\\u") and len(esc) == 7:
                            return chr(int(esc[2:], 16))
                        # Handle standard escapes (\uXXXX or \UXXXXXXXX)
                        return esc.encode('utf-8').decode('unicode-escape')
                    except Exception:
                        return esc
                
                # Regex for: \uXXXX, \uXXXXX (non-standard but common), or \UXXXXXXXX
                text = re.sub(r'\\u[0-9a-fA-F]{4,5}|\\U[0-9a-fA-F]{8}', decode_match, text)
            except Exception as e:
                logger.debug("unicode_decode_failed", error=str(e))

        # 2. Remove Mojibake and problematic characters provided by user
        # These are common artifacts of character encoding mismatches
        # User provided list: âññàññ, ñàáâãäåæçèéêëìíîïðòóôõöøùúûüýþÿ, âãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ
        # We'll also add some other common ones.
        mojibake_chars = "âññàñññàáâãäåæçèéêëìíîïðòóôõöøùúûüýþÿâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ¦"
        
        # Create a translation table to remove these characters efficiently
        table = str.maketrans('', '', mojibake_chars)
        text = text.translate(table)

        return text.strip()

    async def dump_page_content(self, prefix: str = "error"):
        """Dump page content (HTML and screenshot) for debugging"""
        if not self.page:
            return
            
        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            
            # Save screenshot
            screenshot_path = self.settings.log_path / f"{prefix}_{timestamp}.png"
            await self.page.screenshot(path=str(screenshot_path))
            logger.info("debug_screenshot_saved", path=str(screenshot_path))
            
            # Save HTML
            html_path = self.settings.log_path / f"{prefix}_{timestamp}.html"
            content = await self.page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("debug_html_saved", path=str(html_path))
            
        except Exception as e:
            logger.error("failed_to_dump_page_content", error=str(e))

    async def initialize(self):
        """Initialize the client by reusing or creating a page"""
        # Guard: if the context was somehow closed, fail with a clear error
        try:
            _ = self.context.pages  # accessing .pages raises if context is closed
        except Exception as e:
            raise RuntimeError(f"BrowserContext is closed and cannot be reused: {e}") from e

        # Reuse existing page from persistent context if available
        pages = self.context.pages
        if pages:
            self.page = pages[0]
            logger.debug("reusing_existing_page", credential_key=self.credential.key)
        else:
            self.page = await self.context.new_page()
            logger.debug("created_new_page", credential_key=self.credential.key)

    async def cleanup(self):
        """Clean up resources"""
        if self.page:
            try:
                await self.page.close()
            except Exception as e:
                logger.warning("error_closing_page", error=str(e))
            self.page = None

        logger.debug("client_cleanup_completed", credential_key=self.credential.key)

    async def navigate_to_gemini(self):
        """Navigate to Google AI Studio homepage"""
        if not self.page:
            await self.initialize()

        logger.info("navigating_to_gemini", url=self.settings.base_url)
        await self.page.goto(self.settings.base_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        logger.info("navigation_completed")

    async def click_sign_in(self) -> bool:
        """
        Click the Sign In button. Tries multiple selectors to handle DOM changes.
        """
        selectors = [
            # Current DOM: <gem-button data-test-id='sign-in-button'>
            "[data-test-id='sign-in-button']",
            # Inner button text fallback
            "button:has-text('Sign in')",
            # Legacy anchor-based selector
            "//a[contains(@aria-label, 'Sign in') or .//span[text()='Sign in']]",
        ]

        for selector in selectors:
            try:
                element = self.page.locator(selector).first
                await element.wait_for(state="visible", timeout=3000)
                await element.click()
                logger.info("clicked_sign_in", selector=selector)
                await asyncio.sleep(1)
                return True
            except Exception:
                continue

        logger.warning("sign_in_button_not_found")
        return False

    async def enter_email(self):
        """Enter email address in the Google login form"""
        try:
            email_input = self.page.locator("#identifierId").first
            await email_input.wait_for(state="visible", timeout=10000)
            await email_input.fill("")
            await email_input.fill(self.credential.email)
            logger.debug("email_entered")
        except Exception as e:
            logger.error("error_entering_email", error=str(e), trace=traceback.format_exc())
            raise

    async def click_next_button(self):
        """Click the Next button"""
        try:
            next_button = self.page.locator("button:has-text('Next')").first
            await next_button.wait_for(state="visible", timeout=5000)
            await next_button.click()
            logger.debug("clicked_next_button")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error("error_clicking_next", error=str(e), trace=traceback.format_exc())
            raise

    async def enter_password(self):
        """Enter password in the Google login form"""
        try:
            password_input = self.page.locator("input[name='Passwd']").first
            # Increased timeout for Docker environment
            await password_input.wait_for(state="visible", timeout=30000)
            await asyncio.sleep(3)
            await password_input.fill("")
            await password_input.fill(self.credential.password)
            logger.debug("password_entered")
        except Exception as e:
            await self.dump_page_content("login_password_error")
            logger.error("error_entering_password", error=str(e), trace=traceback.format_exc())
            raise

    async def wait_for_dashboard(self):
        """Wait for AI Studio dashboard to load"""
        try:
            await self.page.wait_for_url(
                lambda url: "gemini.google.com/app" in url,
                timeout=self.settings.request_timeout * 1000
            )
            await asyncio.sleep(2)
            logger.info("dashboard_loaded")
        except Exception as e:
            logger.error("error_waiting_for_dashboard", error=str(e), trace=traceback.format_exc())
            raise

    async def _is_logged_in_on_current_page(self) -> bool:
        """
        Check if already logged in on current page.
        Returns True only if a sign-in button is NOT visible AND a known
        logged-in indicator IS present, to avoid false positives.
        """
        try:
            await asyncio.sleep(2)

            # Sign-in button selectors — any of these visible means NOT logged in
            sign_in_selectors = [
                "[data-test-id='sign-in-button']",
                "button:has-text('Sign in')",
                "//a[contains(@aria-label, 'Sign in') or .//span[text()='Sign in']]",
            ]

            for selector in sign_in_selectors:
                try:
                    element = self.page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        logger.debug("sign_in_button_found_marking_not_logged_in", selector=selector)
                        return False
                except Exception:
                    continue

            # Double-check: look for a known logged-in element (the chat editor)
            try:
                editor = self.page.locator("rich-textarea div.ql-editor").first
                if await editor.is_visible(timeout=3000):
                    logger.debug("editor_found_confirming_logged_in")
                    return True
            except Exception:
                pass

            # No sign-in button and no editor — ambiguous; treat as not logged in to be safe
            logger.debug("login_status_ambiguous_assuming_not_logged_in")
            return False

        except Exception as e:
            logger.warning("error_checking_login_status", error=str(e))
            return False

    async def close_popups(self):
        """Close any popups if present"""
        popup_selectors = [
            "[data-test-id='close-button']",
            "[data-test-id='upload-image-agree-button']"
        ]

        for selector in popup_selectors:
            try:
                popup_button = self.page.locator(selector).first
                if await popup_button.is_visible(timeout=1000):
                    await popup_button.click()
                    logger.debug("popup_closed", selector=selector)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    # Error phrases that indicate a transient server/network rejection by Gemini
    _TRANSIENT_ERROR_PHRASES = [
        "check your internet connection",
        "something went wrong",
        "try again",
        "server error",
        "network error",
        "unable to process",
        "request failed",
    ]

    async def _detect_page_error(self) -> Optional[str]:
        """
        Detect transient error toasts / snackbars shown by Gemini when the server
        rejects a generation request (e.g. "Check your internet connection and try again").
        Returns the matched error phrase (lowercased) or None.
        """
        # Snackbar / toast selectors used by Angular Material (which Gemini uses)
        error_selectors = [
            "mat-snack-bar-container",
            ".toast-message",
            "[class*='snack']",
            "[class*='toast']",
            "[class*='error-message']",
            "[role='alert']",
        ]
        for selector in error_selectors:
            try:
                el = self.page.locator(selector).first
                if await el.is_visible(timeout=500):
                    text = (await el.text_content() or "").lower()
                    for phrase in self._TRANSIENT_ERROR_PHRASES:
                        if phrase in text:
                            logger.warning("page_error_detected", selector=selector, phrase=phrase, text=text[:120])
                            return phrase
            except Exception:
                pass
        return None

    async def _recover_from_page_error(self):
        """
        Reload and re-navigate to a fresh Gemini chat to clear any
        transient server error state on the page.
        """
        logger.info("recovering_from_page_error")
        try:
            await self.page.goto(self.settings.base_url, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            await self.close_popups()
            await self.select_model()
        except Exception as e:
            logger.warning("recovery_navigation_failed", error=str(e))

    async def setup(self):
        """Complete setup and login process"""
        logger.info("setup_started", credential_key=self.credential.key)

        # Reuse existing page from persistent context
        await self.initialize()

        # Navigate to Gemini
        await self.navigate_to_gemini()
        await asyncio.sleep(5)

        # Check if already logged in
        if await self._is_logged_in_on_current_page():
            await self.close_popups()
            await self.select_model()
            logger.info("setup_completed_already_logged_in", credential_key=self.credential.key)
            return

        # Not logged in, perform manual login
        logger.info("starting_manual_login", credential_key=self.credential.key)

        clicked = await self.click_sign_in()
        await asyncio.sleep(2)

        account_selector = f"div[data-identifier='{self.credential.email}']"
        account_element = self.page.locator(account_selector).first
        
        is_account_chooser = "signin/accountchooser" in self.page.url
        
        if is_account_chooser or await account_element.is_visible(timeout=2000):
            logger.info("account_chooser_detected", credential_key=self.credential.key)
            if await account_element.is_visible(timeout=3000):
                await account_element.click()
                logger.debug("clicked_existing_account")
            else:
                logger.debug("account_not_visible_in_chooser_falling_back")
                try:
                    use_another = self.page.locator("text='Use another account'").first
                    if await use_another.is_visible(timeout=2000):
                        await use_another.click()
                except Exception:
                    pass
                await self.enter_email()
                await self.click_next_button()
        else:
            if not clicked:
                # Maybe already on login page
                try:
                    email_input = self.page.locator("#identifierId").first
                    password_input = self.page.locator("input[name='Passwd']").first
                    if not await email_input.is_visible(timeout=3000) and not await password_input.is_visible(timeout=1000):
                        logger.error("cannot_find_login_page")
                        return
                except Exception:
                    logger.error("cannot_proceed_with_login")
                    return

            email_input = self.page.locator("#identifierId").first
            if await email_input.is_visible(timeout=2000):
                await self.enter_email()
                await self.click_next_button()

        # Check for password or direct login
        password_input = self.page.locator("input[name='Passwd']").first
        dashboard_reached = False
        
        for _ in range(15): # wait up to 15s for password field or dashboard
            if await password_input.is_visible():
                break
            if "gemini.google.com/app" in self.page.url or "gemini.google.com/prompt" in self.page.url:
                dashboard_reached = True
                break
            await asyncio.sleep(1)
            
        if not dashboard_reached:
            await self.enter_password()
            await self.click_next_button()

            # Handle potential recovery options screen with multiple prompts
            for _ in range(15):  # poll up to 15 iterations (waiting for next screens)
                # If we made it to dashboard, stop waiting entirely
                if "gemini.google.com/app" in self.page.url or "gemini.google.com/prompt" in self.page.url:
                    break

                if "web/recoveryoptions" in self.page.url or "gds.google.com" in self.page.url:
                    logger.info("recovery_options_page_detected", url=self.page.url)
                    try:
                        # Look for visible cancel or skip button with a short timeout to poll quickly
                        cancel_selector = "button[aria-label='Cancel']:visible, button:has-text('Cancel'):visible, button[aria-label='Skip']:visible, button:has-text('Skip'):visible"
                        cancel_locator = self.page.locator(cancel_selector).first
                        
                        if await cancel_locator.is_visible(timeout=2000):
                            await cancel_locator.click()
                            logger.debug("clicked_cancel_on_recovery_options")
                            await asyncio.sleep(1) # Extra brief wait after click
                    except Exception as e:
                        logger.warning("error_cancelling_recovery_options", error=str(e))
                
                await asyncio.sleep(1)

        await self.wait_for_dashboard()
        await self.close_popups()
        await self.select_model()

        logger.info("setup_completed_with_manual_login", credential_key=self.credential.key)

    async def select_model(self, model_name: Optional[str] = None):
        """Switch Gemini model if specified in settings or parameter"""
        target_model = model_name or self.settings.gemini_model
        if not target_model:
            return

        target_model = target_model.strip()
        logger.info("checking_model", target_model=target_model)

        try:
            button_selector = "[data-test-id='bard-mode-menu-button'], [data-test-id='gem-mode-menu-button'], [data-test-id='gemini-mode-menu-button']"
            button = self.page.locator(button_selector).first

            if not await button.is_visible(timeout=5000):
                logger.warning("mode_menu_button_not_visible")
                return

            # Check if currently selected model is already the target
            current_model_label = (await button.text_content() or "").strip()
            
            if current_model_label.lower() == target_model.lower():
                logger.info("model_already_selected", model=target_model)
                return
                
            if target_model.lower().endswith(current_model_label.lower()):
                logger.info("model_already_selected_by_suffix", current=current_model_label, target=target_model)
                return

            logger.info("switching_model", from_model=current_model_label, to_model=target_model)
            
            # Click to open menu
            await button.click()
            await asyncio.sleep(1)

            # Find menu items
            menu_items = await self.page.locator("gem-menu-item, mat-menu-item, [role='menuitem']").all()

            target_item = None
            
            # Try to find exact match or ends with first
            for item in menu_items:
                label_el = item.locator(".label").first
                if await label_el.is_visible(timeout=500):
                    item_text = (await label_el.text_content() or "").strip()
                else:
                    item_text = (await item.text_content() or "").strip()
                    
                if item_text.lower() == target_model.lower():
                    target_item = item
                    break
                elif item_text.lower().endswith(target_model.lower()):
                    target_item = item
                    break
            
            # Fallback to contains
            if not target_item:
                for item in menu_items:
                    label_el = item.locator(".label").first
                    if await label_el.is_visible(timeout=500):
                        item_text = (await label_el.text_content() or "").strip()
                    else:
                        item_text = (await item.text_content() or "").strip()
                        
                    if target_model.lower() in item_text.lower() or item_text.lower() in target_model.lower():
                        target_item = item
                        break
            
            if target_item and await target_item.is_visible():
                is_disabled = await target_item.get_attribute("aria-disabled") == "true"
                if is_disabled:
                    sublabel_el = target_item.locator(".sublabel").first
                    if await sublabel_el.is_visible(timeout=500):
                        reset_msg = (await sublabel_el.text_content() or "").strip()
                        logger.warning("model_disabled_due_to_limit", model=target_model, message=reset_msg)
                    else:
                        logger.warning("model_disabled", model=target_model)
                    await self.page.keyboard.press("Escape")
                    return

                await target_item.click()
                logger.info("model_switched_successfully", model=target_model)
                await asyncio.sleep(2)
            else:
                logger.warning("target_model_not_found_in_list", model=target_model)
                await self.page.keyboard.press("Escape")
                
        except Exception as e:
            logger.error("error_switching_model", error=str(e))

    async def wait_for_completion(self, timeout: int = 120):
        """Wait if a generation is already in progress"""
        start_time = time.time()
        while self.generation_in_progress:
            if time.time() - start_time > timeout:
                logger.warning("timeout_waiting_for_previous_generation")
                break
            await asyncio.sleep(2)

    async def get_editor(self) -> Locator:
        """
        Get the text editor element.
        Ported from bananabot2.py: uses strict 'rich-textarea div.ql-editor'
        If not found on the first attempt, reload the page and retry once.
        """
        selector = "rich-textarea div.ql-editor"
        timeouts = [10000, 15000]

        for attempt, timeout in enumerate(timeouts):
            if attempt > 0:
                logger.warning("editor_not_found_reloading_page", selector=selector, attempt=attempt)
                await self.page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3)
            try:
                element = self.page.locator(selector).first
                await element.wait_for(state="visible", timeout=timeout)
                logger.debug("editor_found", selector=selector, attempt=attempt)
                return element
            except Exception:
                pass

        logger.error("no_editor_found", selector=selector)
        raise RuntimeError("Could not find text editor element")

    async def paste_with_js(self, editor: Locator, text: str):
        """Paste text using JavaScript"""
        await editor.evaluate("""
            (element, text) => {
                element.textContent = text;
                element.innerText = text;

                const inputEvent = new InputEvent('input', {
                    bubbles: true,
                    cancelable: true,
                    inputType: 'insertText',
                    data: text
                });
                element.dispatchEvent(inputEvent);

                const compositionEnd = new CompositionEvent('compositionend', {
                    bubbles: true,
                    data: text
                });
                element.dispatchEvent(compositionEnd);

                element.focus();
            }
        """, text)

    async def send_prompt(self, prompt_text: str, force_json: bool = False, force_text: bool = False) -> int:
        """Send a prompt to Gemini.
        
        Returns the message-content count captured right before the click (old_count),
        so callers can use it as an atomic baseline for get_response.
        """
        logger.info("send_prompt_started", prompt=prompt_text[:50] + "...")

        await self.wait_for_completion()
        await self.close_popups()

        self.generation_in_progress = True
        self.last_prompt = prompt_text

        try:
            editor = await self.get_editor()
            await editor.click()

            # Clear existing text
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Delete")
            await asyncio.sleep(0.5)

            # Prepare prompt
            safe_prompt = prompt_text.replace('\n', ' ').replace('\t', ' ')

            if force_json or self.force_json:
                safe_prompt += "\n\nCRITICAL: Generate only the requested valid JSON string (no delimiter issues or double quotes in key values; it should work with json.loads. Don't include '\\u' starting emojis like \\U0001F600, but allow only decoded emojis in the response)."

            if force_text or self.force_text:
                safe_prompt += "\n\nCRITICAL: Generate only plain text response without any special formatting or markdown."

            # Input text using bananabot JS paste logic ideally, but keeping current JS paste as it matches intent
            if self.enable_paste_with_js:
                await self.paste_with_js(editor, safe_prompt)
            else:
                await editor.fill(safe_prompt)

            await asyncio.sleep(0.5)

            # Snapshot the current message count BEFORE clicking Send.
            # This must happen as close as possible to the actual click to avoid
            # a late-arriving previous response inflating the baseline.
            pre_send_count = await self.page.locator("message-content").count()

            # Send prompt - strict selector based on latest DOM with retry/verification
            send_selector = "[data-test-id='send-button-container'] button[aria-label*='Send']"
            sent = False

            for attempt in range(3):
                try:
                    send_button = self.page.locator(send_selector).first
                    if await send_button.is_visible(timeout=2000):
                        await send_button.click()
                        logger.debug("send_button_clicked", attempt=attempt)
                        sent = True

                        # Wait for send button to disappear or change state (submission confirmed).
                        try:
                            # When sent, the button either hides, loses the 'Send' aria-label, or the container hides
                            await send_button.wait_for(state="hidden", timeout=3000)
                            logger.info("prompt_sent_verified")
                        except PlaywrightTimeoutError:
                            # Button didn't hide — server likely rejected the request (503/rate-limit).
                            # Check for a page error toast before assuming the click registered.
                            logger.warning("send_button_still_visible_after_click", attempt=attempt)
                            page_error = await self._detect_page_error()
                            if page_error:
                                logger.warning("send_rejected_by_server", error=page_error)
                                await self._recover_from_page_error()
                                # Raise so the caller's retry logic (get_response) handles resend
                                self.generation_in_progress = False
                                raise RuntimeError(f"Send rejected by server: {page_error}")
                        # Either way, one click is enough — stop the loop.
                        break
                    else:
                        if sent:
                            # Button disappeared after our previous click — we're done.
                            break
                        # Button was never visible; fall back to Enter.
                        logger.info("send_button_not_visible_pressing_enter")
                        await editor.press("Enter")
                        sent = True
                        await asyncio.sleep(1)
                        if not await send_button.is_visible(timeout=1000):
                            break
                except Exception as e:
                    logger.warning("error_during_send_attempt", attempt=attempt, error=str(e))
                    if not sent:
                        # Only press Enter if we haven't successfully sent yet
                        await editor.press("Enter")
                        sent = True
                    await asyncio.sleep(0.5)
                    break

            logger.info("prompt_sent", pre_send_count=pre_send_count)
            await asyncio.sleep(0.5)
            await self.close_popups()

            return pre_send_count

        except Exception as e:
            logger.error("error_sending_prompt", error=str(e), trace=traceback.format_exc())
            self.generation_in_progress = False
            raise

    async def get_current_chat_id(self) -> Tuple[Optional[str], Optional[str]]:
        """Get the current chat session ID and account id from URL"""
        current_url = self.page.url
        match = re.search(r'(?:/u/([^/]+))?/?app/([^/?]+)', current_url)
        if match:
            account_id = match.group(1)
            chat_id = match.group(2)
            logger.debug("chat_id_extracted", account_id=account_id, chat_id=chat_id)
            return account_id, chat_id
        return None, None

    async def load_chat(self, account_id: Optional[str], chat_id: str):
        """Load a specific chat session by account and chat ID"""
        chat_url = f"https://gemini.google.com/app/{chat_id}"
        if account_id:
            chat_url = f"https://gemini.google.com/u/{account_id}/app/{chat_id}"

        current_account_id, current_chat_id = await self.get_current_chat_id()

        if current_chat_id != chat_id:
            logger.info("loading_chat", url=chat_url)
            await self.page.goto(chat_url)
        else:
            logger.debug("chat_already_loaded")

        await self.get_editor()
        await self.close_popups()

    async def load_new_chat(self):
        """Start a new chat session"""
        current_account_id, current_chat_id = await self.get_current_chat_id()

        if current_chat_id:
            logger.info("starting_new_chat")
            await self.page.goto(self.settings.base_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            await self.get_editor()
            await self.close_popups()
        else:
            logger.debug("already_on_new_chat")

    async def get_response(self, old_count: Optional[int] = None, stable_check_interval: float = 1.0, stable_cycles: int = 5,
                          force_json: bool = False, force_text: bool = False, retry_count: int = 0) -> Optional[str]:
        """
        Wait until the response is complete and return the text.
        Strictly uses 'message-content' selector from bananabot2.py
        Timeout set to 60s for non-image responses.
        """
        # Use timeout from settings
        timeout_seconds = self.settings.timeout
        logger.info("waiting_for_response", retry_count=retry_count, timeout=timeout_seconds)

        try:
            # If old_count not provided, get it now (fallback for direct calls)
            if old_count is None:
                old_count = await self.page.locator("message-content").count()
            
            logger.info("old_count", old_count=old_count)

            # Wait for count to increase or send button to reappear
            await asyncio.sleep(1) # Ensure DOM has fully updated after sending
            
            send_selector = "[data-test-id='send-button-container'] button[aria-label*='Send']"
            start_time = time.time()
            success = False
            
            while time.time() - start_time < timeout_seconds:
                try:
                    await self.page.wait_for_function(
                        f"""() => {{
                            if (document.querySelectorAll('message-content').length > {old_count}) return true;
                            const sendBtn = document.querySelector("[data-test-id='send-button-container'] button[aria-label*='Send']");
                            if (sendBtn && sendBtn.offsetParent !== null) return true;
                            return false;
                        }}""",
                        timeout=2000
                    )
                except PlaywrightTimeoutError:
                    pass
                
                current_count = await self.page.locator("message-content").count()
                if current_count > old_count:
                    success = True
                    break
                    
                send_btn = self.page.locator(send_selector).first
                if await send_btn.is_visible(timeout=500):
                    logger.warning("generation_failed_early_send_button_visible_retrying_click")
                    # Check if Gemini is showing a transient error (e.g. "Check your internet connection")
                    page_error = await self._detect_page_error()
                    if page_error:
                        logger.warning("transient_error_detected_recovering", error=page_error)
                        await self._recover_from_page_error()
                        # Resend after recovery — break the inner loop to let the outer retry handle it
                        raise PlaywrightTimeoutError(f"Transient page error: {page_error}")
                    try:
                        await send_btn.click(timeout=1000)
                        await send_btn.wait_for(state="hidden", timeout=3000)
                    except Exception:
                        pass
                        
            if not success:
                raise PlaywrightTimeoutError("Timeout waiting for new message")

        except (asyncio.TimeoutError, PlaywrightTimeoutError):
            logger.warning("timeout_waiting_for_new_message", retry_count=retry_count)
            self.generation_in_progress = False
            self.is_last_response_image = False

            # Retry mechanism
            if self.retry and self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt", 
                           attempt=retry_count + 1, 
                           max_retries=self.settings.max_retries)
                
                # Refresh/New Chat to clear state
                await self.load_new_chat()
                
                # Resend the prompt — returns pre-send count atomically
                retry_old_count = await self.send_prompt(self.last_prompt, force_json, force_text)
                
                # Recursive retry
                return await self.get_response(
                    old_count=retry_old_count,
                    stable_check_interval=stable_check_interval, 
                    stable_cycles=stable_cycles, 
                    force_json=force_json, 
                    force_text=force_text, 
                    retry_count=retry_count + 1
                )
            
            logger.error("max_retries_exceeded", attempts=retry_count + 1, max_retries=self.settings.max_retries)
            return None

        # Poll until text stabilizes
        stable_count = 0
        last_text = ""
        start_time = time.time()

        while time.time() - start_time < self.settings.max_timeout:
            current_text = ""
            
            # bananabot: message_elements = driver.find_elements(..., "message-content")
            message_elements = self.page.locator("message-content")
            count = await message_elements.count()
            
            if count > 0:
                last_message = message_elements.nth(count - 1)
                # Use evaluate to get innerText to preserve newlines from <p> and <br> tags
                current_text = (await last_message.evaluate("el => el.innerText") or "").strip()
            
            if current_text:
                if current_text == last_text:
                    stable_count += 1
                    if stable_count >= stable_cycles:
                        self.generation_in_progress = False
                        self.is_last_response_image = False

                        # Clean the text
                        cleaned_text = await self._clean_response_text(current_text)

                        if force_json or self.force_json:
                            try:
                                repaired = repair_json(cleaned_text)
                                # If repair succeeded, we return the repaired string
                                # We don't return the parsed object yet because process_request handles it
                                return repaired
                            except Exception as e:
                                logger.warning("json_repair_failed", error=str(e))
                            
                            if not (cleaned_text.startswith("{") and cleaned_text.endswith("}")):
                                if self.last_prompt:
                                    logger.info("retrying_prompt_for_invalid_json")
                                    await self.load_new_chat()
                                    retry_old_count = await self.send_prompt(self.last_prompt, force_json, force_text)
                                    return await self.get_response(
                                        old_count=retry_old_count, 
                                        stable_check_interval=stable_check_interval, 
                                        stable_cycles=stable_cycles, 
                                        force_json=force_json, 
                                        force_text=force_text,
                                        retry_count=retry_count + 1
                                    )

                        logger.debug("response_received", length=len(cleaned_text))
                        return cleaned_text
                else:
                    stable_count = 0

                last_text = current_text
                await asyncio.sleep(stable_check_interval)
            else:
                await asyncio.sleep(stable_check_interval)

        self.generation_in_progress = False
        self.is_last_response_image = False
        
        # Clean the final text before returning
        cleaned_text = await self._clean_response_text(last_text if last_text else "")
        
        if (force_json or self.force_json) and cleaned_text:
            try:
                repaired = repair_json(cleaned_text)
                return repaired
            except Exception as e:
                logger.warning("json_repair_failed_at_timeout", error=str(e))
            
        logger.warning("response_timeout", retry_count=retry_count)

        # Retry mechanism for stability timeout
        if self.retry and self.last_prompt and retry_count < self.settings.max_retries:
            logger.info("retrying_last_prompt_after_timeout", 
                       attempt=retry_count + 1, 
                       max_retries=self.settings.max_retries)
            await self.load_new_chat()
            retry_old_count = await self.send_prompt(self.last_prompt, force_json, force_text)
            return await self.get_response(
                old_count=retry_old_count, 
                stable_check_interval=stable_check_interval, 
                stable_cycles=stable_cycles, 
                force_json=force_json, 
                force_text=force_text, 
                retry_count=retry_count + 1
            )

        return cleaned_text if cleaned_text else None

    ERROR_RESPONSES = [
        "error",
        "having a hard time fulfilling your request",
        "Can I help you with something else instead",
        "something went wrong",
        "more images for you today",
        "I can still find images from the web",
        "can't generate",
    ]

    async def get_image_response(self, old_count: Optional[int] = None, retry_count: int = 0) -> Tuple[Optional[str], Optional[str]]:
        """Wait for image generation to complete and return the URL and optional error message with retry logic"""
        logger.info("waiting_for_image", retry_count=retry_count)
        
        try:
            send_selector = "[data-test-id='send-button-container'] button[aria-label*='Send']"
            
            # Poll for new image src AND error text in the LAST message-content
            for _ in range(self.settings.image_generation_timeout):
                if old_count is not None:
                    current_count = await self.page.locator("message-content").count()
                    if current_count <= old_count:
                        send_btn = self.page.locator(send_selector).first
                        if await send_btn.is_visible(timeout=500):
                            logger.warning("generation_failed_early_send_button_visible_retrying_click")
                            # Check if Gemini is showing a transient error toast
                            page_error = await self._detect_page_error()
                            if page_error:
                                logger.warning("transient_error_detected_recovering", error=page_error)
                                await self._recover_from_page_error()
                                await asyncio.sleep(3)
                                # Re-arm image mode and resend
                                await self.set_as_image(True, self.reference_starred_drive_image_name, self.reference_image_path)
                                retry_old_count = await self.send_prompt(self.last_prompt)
                                return await self.get_image_response(old_count=retry_old_count, retry_count=retry_count + 1)
                            try:
                                await send_btn.click(timeout=1000)
                                await send_btn.wait_for(state="hidden", timeout=3000)
                            except Exception:
                                pass
                            await asyncio.sleep(1)
                            continue
                        
                        await asyncio.sleep(0.5)
                        continue

                # Restrict to the last message to ensure we get the latest generation
                last_msg = self.page.locator("message-content").last
                
                # Make sure the message element exists before querying
                if await last_msg.count() > 0:
                    images = await last_msg.locator("generated-image img").all()
                    
                    new_srcs = []
                    for img in images:
                        try:
                            src = await img.get_attribute("src")
                            if src and src not in self.generated_images:
                                new_srcs.append(src)
                        except Exception:
                            continue

                    if new_srcs:
                        # Add all new srcs to the list
                        for src in new_srcs:
                            self.generated_images.append(src)
                            
                        # Return the LAST new image in this set (often the most "latest")
                        latest_src = new_srcs[-1]
                        logger.info("new_image_found", src=latest_src[:50] + "...")

                        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(3)

                        src_highres = re.sub(r'1024-rj', '16383', latest_src)
                        return src_highres, None

                # Check for AI refusal text to fail fast
                if await last_msg.count() > 0:
                    try:
                        text_content = await last_msg.text_content()
                        if text_content:
                            for error_text in self.ERROR_RESPONSES:
                                if error_text in text_content:
                                    logger.warning("ai_refusal_detected", error_text=error_text)
                                    
                                    # Respect retry limit for early failure
                                    if self.retry and self.last_prompt and retry_count < self.settings.max_retries:
                                        logger.info("retrying_last_prompt_after_ai_refusal",
                                                   attempt=retry_count + 1,
                                                   max_retries=self.settings.max_retries)
                                        self.generation_in_progress = False
                                        await asyncio.sleep(5)
                                        await self.set_as_image(True, self.reference_starred_drive_image_name, self.reference_image_path)
                                        retry_old_count = await self.send_prompt(self.last_prompt)
                                        return await self.get_image_response(old_count=retry_old_count, retry_count=retry_count + 1)
                                    
                                    self.generation_in_progress = False
                                    return None, f"AI Error: {error_text}"
                    except Exception:
                        pass

                await asyncio.sleep(1)

            logger.warning("no_new_image_generated", retry_count=retry_count)
            
            # Retry mechanism for missing image src
            if self.retry and self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt_for_missing_image",
                           attempt=retry_count + 1,
                           max_retries=self.settings.max_retries)
                await asyncio.sleep(5)
                await self.set_as_image(True, self.reference_starred_drive_image_name, self.reference_image_path)
                retry_old_count = await self.send_prompt(self.last_prompt)
                return await self.get_image_response(old_count=retry_old_count, retry_count=retry_count + 1)

            return None, "No new image generated"

        except PlaywrightTimeoutError:
            logger.warning("timeout_waiting_for_image", retry_count=retry_count)
            self.generation_in_progress = False
            self.is_last_response_image = False

            # Retry mechanism with configurable max retries (stay in same chat for images)
            if self.retry and self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt_for_image_in_same_chat",
                           attempt=retry_count + 1,
                           max_retries=self.settings.max_retries)
                # Don't load new chat for image retry - stay in same chat
                await asyncio.sleep(5)
                await self.set_as_image(True, self.reference_starred_drive_image_name, self.reference_image_path)
                retry_old_count = await self.send_prompt(self.last_prompt)
                return await self.get_image_response(old_count=retry_old_count, retry_count=retry_count + 1)

            logger.error("max_retries_exceeded_for_image", attempts=retry_count + 1, max_retries=self.settings.max_retries)
            return None, "Timeout waiting for image generation"

        except Exception as e:
            logger.error("error_getting_image_response", error=str(e), trace=traceback.format_exc())
            self.generation_in_progress = False
            self.is_last_response_image = False

            # Retry on error with counter (stay in same chat for images)
            if self.retry and self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt_after_error_in_same_chat",
                           attempt=retry_count + 1,
                           max_retries=self.settings.max_retries)
                # Don't load new chat for image retry - stay in same chat
                await asyncio.sleep(5)
                await self.set_as_image(True, self.reference_starred_drive_image_name, self.reference_image_path)
                retry_old_count = await self.send_prompt(self.last_prompt)
                return await self.get_image_response(old_count=retry_old_count, retry_count=retry_count + 1)

            logger.error("max_retries_exceeded_after_error", attempts=retry_count + 1)
            return None, f"Error getting image response: {str(e)}"

        finally:
            self.generation_in_progress = False
            self.is_last_response_image = True

    async def set_as_image(self, enable: bool = True, reference_starred_drive_image_name: Optional[str] = None, reference_image_path: Optional[str] = None):
        """Set the input mode to image or text"""
        await self.wait_for_completion()
        self.is_image = enable

        if enable and reference_image_path:
            self.reference_image_path = reference_image_path
            logger.info("uploading_image_from_path", path=reference_image_path)
            
            try:
                uploader_btn = self.page.locator("button[aria-label='Upload and tools'], uploader").first
                await uploader_btn.click()
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning("failed_to_click_uploader_btn", error=str(e))
                
            file_input = self.page.locator('input.hidden-file-input[type="file"], input[type="file"]').first
            await file_input.set_input_files(reference_image_path)
            await asyncio.sleep(2)
        elif enable and reference_starred_drive_image_name:
            self.reference_starred_drive_image_name = reference_starred_drive_image_name

            # Add retry with page reload if uploader-drive-button times out
            for attempt in range(3):
                try:
                    uploader_btn = self.page.locator("button[aria-label='Upload and tools'], uploader").first
                    await uploader_btn.click()

                    drive_uploader = self.page.locator("button[data-test-id='uploader-drive-button'], drive-uploader").first
                    await drive_uploader.wait_for(state="visible", timeout=10000)
                    await drive_uploader.click()
                    await asyncio.sleep(2)
                    break  # Success
                except PlaywrightTimeoutError:
                    if attempt == 0:
                        logger.warning("drive_uploader_timeout_reloading_page")
                        await self.page.reload(wait_until="domcontentloaded")
                        await asyncio.sleep(4)
                    else:
                        logger.error("drive_uploader_timeout_after_reload")
                        raise

            # Handle potential popups (Connect Workspace, Image Upload Disclaimer) before or while iframe loads
            logger.debug("checking_for_popups_before_picker")
            for _ in range(10):  # Up to 5 seconds
                try:
                    # Check Connect
                    connect_btn = self.page.locator("gem-button[data-test-id='confirm-button'] button, button:has-text('Connect')").first
                    if await connect_btn.is_visible():
                        logger.info("connect_button_found_clicking")
                        await connect_btn.click()
                        await asyncio.sleep(1)
                        
                    # Check Agree
                    agree_btn = self.page.locator("gem-button[data-test-id='upload-image-agree-button'] button, button:has-text('Agree')").first
                    if await agree_btn.is_visible():
                        logger.info("agree_button_found_clicking")
                        await agree_btn.click()
                        await asyncio.sleep(1)
                        
                    # If the iframe is visible, we are ready to proceed
                    if await self.page.locator("div.google-picker iframe").first.is_visible():
                        break
                except Exception as e:
                    logger.debug("error_checking_popups", error=str(e))
                
                await asyncio.sleep(0.5)

            # Switch to the Google Picker iframe
            iframe_selector = "div.google-picker iframe"
            iframe_element = await self.page.wait_for_selector(iframe_selector)
            iframe = self.page.frame_locator(iframe_selector)

            # Click "Starred" tab inside iframe
            starred_tab = iframe.locator("//button[.//span[text()='Starred']]").first
            await starred_tab.wait_for(state="visible")
            await starred_tab.click()
            await asyncio.sleep(1)

            # Select file with matching name
            file_element = iframe.locator(f"//div[@aria-label='{self.reference_starred_drive_image_name}']").first
            await file_element.wait_for(state="visible")
            await file_element.dblclick()
            logger.info("selected_drive_image", name=reference_starred_drive_image_name)

            await asyncio.sleep(2)
            # await self.page.wait_for_load_state("networkidle") # Removed as it's unreliable in AI Studio

        # Logic ported from bananabot2.py: only toggle if not already in image mode
        if not self.is_last_response_image:
            logger.debug("switching_to_image_mode")
            
            # The toolbox is now inside the "Upload and tools" menu
            # Only click the menu if we didn't already click it for drive upload above
            # (If we did drive upload, the menu might still be open or closed, but actually after drive upload the Google picker opens. 
            # Wait, if we did drive upload, we probably don't need to do "Create image" because the prompt handles it? No, set_as_image sets the tool.)
            # Actually we should click the Upload and tools button to open the menu.
            uploader_btn = self.page.locator("button[aria-label='Upload and tools'], uploader").first
            try:
                await uploader_btn.click()
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning("failed_to_click_uploader_btn", error=str(e))
            
            # Robust XPath from bananabot2.py
            create_images_selector = "//toolbox-drawer-item//div[contains(text(), 'Create image')]/ancestor::button"
            create_images_btn = self.page.locator(create_images_selector).first

            # Retry loop for clicking
            drawer_opened = False
            for attempt in range(3):
                try:
                    if await create_images_btn.is_visible(timeout=5000):
                        drawer_opened = True
                        break
                    else:
                        logger.warning("create_images_btn_not_visible_retrying", attempt=attempt)
                        # Maybe the menu closed, try opening it again
                        await uploader_btn.click()
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.warning("error_finding_create_image_btn", attempt=attempt, error=str(e))
                    await asyncio.sleep(1)

            if not drawer_opened:
                logger.error("failed_to_open_toolbox_drawer_after_retries")
            
            try:
                await create_images_btn.wait_for(state="visible", timeout=5000)
                await create_images_btn.click()
                logger.debug("clicked_create_images")
                # Wait for tool selection to register
                await asyncio.sleep(1)
            except Exception as e:
                # Diagnostic screenshot and HTML dump
                try:
                    await self.dump_page_content(prefix="failed_to_click_create_images")
                except Exception as dump_err:
                    logger.warning("failed_to_dump_on_failed_to_click_create_images", error=str(dump_err))
                
                logger.error("failed_to_click_create_images", error=str(e))
                # Fallback: click via aria-label matching the zero-state card button
                await self.page.locator("button[aria-label*='Create image']").first.click()


    async def deselect_as_image(self):
        """Deselect image input mode"""
        try:
            deselect_btn = self.page.locator("button[aria-label='Deselect Create image']").first
            if await deselect_btn.is_visible():
                await deselect_btn.click()
                self.is_image = False
                logger.debug("deselected_image_mode")
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning("error_deselecting_image", error=str(e))

    async def rerun_prompt(self):
        """Rerun the prompt"""
        logger.info("rerunning_prompt")
        rerun_btn = self.page.locator("button[name='rerun-button']").first
        await self.page.evaluate("arguments[0].scrollIntoView(true)", await rerun_btn.element_handle())
        await rerun_btn.click()
        await asyncio.sleep(1)

    async def download_image(self, url: str, save_dir: Optional[str] = None, filename_prefix: str = "IMG_",
                           filename_suffix: str = "", return_data: bool = False) -> Tuple[Optional[str], Optional[bytes]]:
        """Download image by clicking the Gemini download button, with blob URL fallback.

        Strategy:
        1. Find the download button (aria-label contains "download") on the last generated
           image and trigger a Playwright download event by clicking it.
        2. If that fails (button not found / download event times out), fall back to reading
           the blob: URL via page.evaluate + fetch so we can capture the bytes.

        Args:
            url: Image URL (may be a blob: URL shown in the UI)
            save_dir: Directory to save the image
            filename_prefix: Prefix for the filename
            filename_suffix: Suffix for the filename
            return_data: Whether to return image bytes as well

        Returns:
            Tuple of (file_path, image_bytes) if return_data=True, else (file_path, None)
        """
        # Always resolve save_dir through Settings
        if save_dir is None:
            save_dir_path = self.settings.download_path
        else:
            save_dir_path = self.settings.resolve_path(save_dir)

        save_dir_str = str(save_dir_path)
        os.makedirs(save_dir_str, exist_ok=True)

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(save_dir_str, f"{filename_prefix}{timestamp}{filename_suffix}.png")

        # ── Retrying up to 3 times ──
        for attempt in range(3):
            # ── Strategy 1: click the download button and capture the download event ──
            try:
                download_btn = self.page.locator("button[aria-label*='ownload']").last
                if await download_btn.count() > 0:
                    logger.info("download_button_found", url=url[:80], attempt=attempt + 1)
                    # Focus the button first (as required by Gemini's JS handler)
                    await download_btn.focus()
                    await asyncio.sleep(0.3)

                    async with self.page.expect_download(timeout=30_000) as dl_info:
                        await download_btn.click()

                    download = await dl_info.value
                    await download.save_as(filename)
                    content = open(filename, 'rb').read() if return_data else None
                    logger.info("image_downloaded_via_button", filename=filename, size=os.path.getsize(filename))

                    if return_data:
                        return filename, content
                    return filename, None
                else:
                    logger.warning("download_button_not_found", url=url[:80], attempt=attempt + 1)
            except Exception as e:
                logger.warning("download_button_failed", error=str(e), error_type=type(e).__name__, url=url[:80], attempt=attempt + 1)

            # ── Strategy 2: blob URL via page.evaluate / fetch ──
            try:
                if url.startswith("blob:"):
                    logger.info("fetching_blob_url_via_evaluate", url=url[:80], attempt=attempt + 1)
                    b64: Optional[str] = await self.page.evaluate("""async (blobUrl) => {
                        try {
                            const img = document.querySelector(`img[src="${blobUrl}"]`);
                            if (img && img.naturalWidth > 0) {
                                const canvas = document.createElement('canvas');
                                canvas.width = img.naturalWidth;
                                canvas.height = img.naturalHeight;
                                const ctx = canvas.getContext('2d');
                                ctx.drawImage(img, 0, 0);
                                return canvas.toDataURL('image/png').split(',')[1];
                            }

                            const resp = await fetch(blobUrl);
                            const blob = await resp.blob();
                            return await new Promise((resolve, reject) => {
                                const reader = new FileReader();
                                reader.onloadend = () => {
                                    const dataUrl = reader.result;
                                    resolve(dataUrl.substring(dataUrl.indexOf(',') + 1));
                                };
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            });
                        } catch (e) {
                            return null;
                        }
                    }""", url)

                    if b64:
                        content = base64.b64decode(b64)
                        with open(filename, 'wb') as f:
                            f.write(content)
                        logger.info("image_downloaded_via_blob_eval", filename=filename, size=len(content))
                        if return_data:
                            return filename, content
                        return filename, None
                    else:
                        logger.warning("blob_eval_returned_null", url=url[:80], attempt=attempt + 1)
                else:
                    # Regular HTTP URL – use the API context
                    response = await self.context.request.get(url)
                    if response.status == 200:
                        content = await response.body()
                        with open(filename, 'wb') as f:
                            f.write(content)
                        logger.info("image_downloaded_via_api_context", filename=filename, size=len(content))
                        if return_data:
                            return filename, content
                        return filename, None
                    else:
                        logger.warning("image_download_failed", status=response.status, url=url[:80], attempt=attempt + 1)
            except Exception as e:
                logger.error("error_downloading_image_fallback", error=str(e), error_type=type(e).__name__,
                             url=url[:80], trace=traceback.format_exc(), attempt=attempt + 1)

            if attempt < 2:
                logger.info("retrying_download", attempt=attempt + 1, max_retries=3)
                await asyncio.sleep(2)

        return None, None

    async def download_response(self, response_text: str, save_dir: Optional[str] = None,
                              filename_prefix: str = "RESP_", filename_suffix: str = "") -> Optional[str]:
        """Save text response to file"""
        if not response_text:
            logger.warning("no_response_text_to_save")
            return None

        if save_dir is None:
            save_dir_path = self.settings.download_path
        else:
            save_dir_path = self.settings.resolve_path(save_dir)

        save_dir_str = str(save_dir_path)
        os.makedirs(save_dir_str, exist_ok=True)

        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(save_dir_str, f"{filename_prefix}{timestamp}{filename_suffix}.txt")

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(response_text)

            logger.info("response_saved", filename=filename)
            return filename

        except Exception as e:
            logger.error("error_saving_response", error=str(e), trace=traceback.format_exc())
            return None
        finally:
            self.generation_in_progress = False
            self.is_last_response_image = False

    @staticmethod
    async def remove_watermark(image_path: str, output_path: Optional[str] = None) -> Optional[str]:
        """Remove watermark from image using py-gemini-watermark-remover"""
        if not image_path or not os.path.exists(image_path):
            logger.warning("image_file_not_found", path=image_path)
            return None

        if not output_path:
            output_path = image_path

        try:
            from .femini_watermark_remover import process_image_custom as process_image
            
            success = process_image(
                input_path=image_path,
                output_path=output_path,
                remove=True,
                auto_detect=True
            )
            
            if success:
                logger.info("watermark_removed", path=output_path)
            else:
                logger.warning("watermark_removal_failed_or_skipped", path=output_path)
                
            return output_path

        except Exception as e:
            logger.error("error_removing_watermark", error=str(e), trace=traceback.format_exc())
            return None

    def _validate_json_keys(self, parsed: dict, required_keys: List[str]) -> List[str]:
        """Return list of top-level keys missing from parsed JSON dict."""
        return [k for k in required_keys if k not in parsed]

    async def process_request(self, request) -> Dict[str, Any]:
        """Process a request from the queue manager"""
        self.request_count += 1
        # Check for page rotation
        if self.request_count > 1 and self.request_count % self.settings.max_requests_per_page == 0:
            logger.info("rotating_page_limit_reached",
                       request_count=self.request_count,
                       limit=self.settings.max_requests_per_page)
            # Navigate to about:blank instead of closing the page.
            # In a launch_persistent_context, closing the *last* page also closes
            # the entire BrowserContext, making subsequent new_page() calls fail.
            # Navigating to blank frees the DOM/network resources without destroying the context.
            try:
                if self.page and not self.page.is_closed():
                    await self.page.goto("about:blank", wait_until="commit")
                    logger.debug("page_reset_to_blank_for_rotation")
            except Exception as e:
                logger.warning("error_resetting_page_for_rotation", error=str(e))
            # Keep self.page alive so initialize() reuses it via context.pages[0]
            # (setup() will navigate it to Gemini immediately after)


        try:
            self.retry = request.retry
            
            # Run setup for first request, if page is closed, or if reset to about:blank (post-rotation)
            needs_setup = (
                self.request_count == 1
                or not self.page
                or self.page.is_closed()
                or self.page.url in ("about:blank", "")
            )
            if needs_setup:
                logger.info("running_setup_and_login", request_count=self.request_count)
                await self.setup()
            else:
                current_account_id, current_chat_id = await self.get_current_chat_id()

                if request.chat_id:
                    if current_chat_id != request.chat_id:
                        logger.info("loading_different_chat", from_chat=current_chat_id, to_chat=request.chat_id)
                        await self.load_chat(request.account_id, request.chat_id)
                    else:
                        logger.info("already_in_requested_chat", chat_id=current_chat_id)
                else:
                    if current_chat_id:
                        logger.info("starting_new_chat_from_existing", current_chat=current_chat_id)
                        await self.load_new_chat()
                    else:
                        logger.info("already_in_new_chat")

            # Switch model based on request parameter or fallback to config
            model_to_use = getattr(request, "gemini_model", None)
            if model_to_use or self.settings.gemini_model:
                await self.select_model(model_to_use)

            # Handle image mode
            if request.is_image:
                await self.set_as_image(True, request.reference_image_name, request.reference_image_path)
            elif self.is_last_response_image:
                logger.info("deselecting_as_image")
                await self.deselect_as_image()

            # Send prompt — returns the pre-send message count atomically
            old_count = await self.send_prompt(request.prompt, force_json=request.force_json, force_text=request.force_text)

            # Get response
            if request.is_image:
                result_url, error_msg = await self.get_image_response(old_count=old_count)
                account_id, chat_id = await self.get_current_chat_id()

                if result_url:
                    # Determine if we should return image data or save to disk
                    should_return_data = request.return_image_data or self.settings.return_image_data
                    should_save_to_disk = request.download or self.settings.save_responses
                    
                    final_path = None
                    image_bytes = None
                    
                    # Download image if requested OR if we need to return data (to process watermark)
                    if should_save_to_disk or should_return_data:
                        final_path, _ = await self.download_image(
                            result_url,
                            save_dir=request.save_dir,
                            filename_suffix=request.filename_suffix,
                            return_data=False
                        )
                    
                        if final_path:
                            if self.settings.remove_watermark:
                                final_path = await self.remove_watermark(final_path)
                                logger.info("image_fully_processed", url=result_url[:60], path=final_path)
                            else:
                                logger.info("image_downloaded_without_watermark_removal", path=final_path)
                            
                            # Read image bytes if needed for response
                            if should_return_data:
                                try:
                                    with open(final_path, 'rb') as f:
                                        image_bytes = f.read()
                                except Exception as e:
                                    logger.error("error_reading_final_image_bytes", error=str(e))
                            
                            # If we ONLY wanted to return data and NOT save the file permanently
                            # we should technically delete it, but the user likely wants to keep it 
                            # if they didn't explicitly set download=false (though default is false now).
                            # For now, if should_save_to_disk is False, we keep it as a temp file? 
                            # Actually, per user request, we only download if download true.
                            # BUT we need the file for watermark removal. 
                            # Decision: Always save to disk for now if processing is needed, 
                            # but only return the 'path' in response if should_save_to_disk is True.

                    # Build response
                    response = {
                        "type": "image",
                        "url": result_url,
                        "path": final_path if should_save_to_disk else None,
                        "chat_id": chat_id,
                        "account_id": account_id,
                        "success": True
                    }
                    
                    # Add image data if requested and available
                    if should_return_data and image_bytes:
                        response["data"] = base64.b64encode(image_bytes).decode('utf-8')
                        response["size_bytes"] = len(image_bytes)
                        logger.info("image_data_encoded", size=len(image_bytes), 
                                   base64_size=len(response["data"]))
                    
                    return response

                return {
                    "type": "image",
                    "success": False,
                    "error": error_msg or "No image generated",
                    "chat_id": chat_id,
                    "account_id": account_id
                }
            else:
                response_text = await self.get_response(old_count=old_count, force_json=request.force_json, force_text=request.force_text)
                account_id, chat_id = await self.get_current_chat_id()

                if response_text:
                    should_save_to_disk = request.download or self.settings.save_responses
                    path = None
                    
                    if should_save_to_disk:
                        path = await self.download_response(
                            response_text,
                            save_dir=request.save_dir,
                            filename_suffix=request.filename_suffix
                        )
                    
                    # Build result dict
                    result_dict = {
                        "type": "text",
                        "text": response_text,
                        "path": path,
                        "chat_id": chat_id,
                        "account_id": account_id,
                        "success": True
                    }

                    # If force_json is true, attempt to parse into a 'json' key
                    if request.force_json:
                        try:
                            # try standard json first
                            result_dict["json"] = json.loads(response_text)
                        except:
                            try:
                                repaired = repair_json(response_text)
                                result_dict["json"] = json.loads(repaired)
                                # Update text to the repaired version if it was different
                                if repaired != response_text:
                                    result_dict["text"] = repaired
                            except:
                                result_dict["json"] = None

                        # --- Key validation with retry ---
                        required_keys = getattr(request, "required_json_keys", None)
                        if required_keys and result_dict.get("json") is not None:
                            key_retry = 0
                            max_keys_retries = self.settings.max_retries if request.retry else 0
                            
                            while key_retry < max_keys_retries:
                                missing = self._validate_json_keys(result_dict["json"], required_keys)
                                if not missing:
                                    break  # All keys present — done

                                key_retry += 1
                                logger.warning("json_keys_missing_retrying",
                                               missing_keys=missing,
                                               attempt=key_retry,
                                               max_retries=max_keys_retries)
                                
                                # Diagnostic screenshot and HTML dump
                                try:
                                    await self.dump_page_content(prefix="json_missing_keys")
                                except Exception as dump_err:
                                    logger.warning("failed_to_dump_on_json_missing", error=str(dump_err))

                                if key_retry >= max_keys_retries:
                                    # Exhausted retries — return failure
                                    return {
                                        "type": "text",
                                        "success": False,
                                        "error": f"Required JSON keys missing after {key_retry} retries: {missing}",
                                        "chat_id": chat_id,
                                        "account_id": account_id
                                    }

                                # Retry: new chat + resend
                                await self.load_new_chat()
                                retry_old_count = await self.send_prompt(request.prompt,
                                                                          force_json=True,
                                                                          force_text=request.force_text)
                                response_text = await self.get_response(
                                    old_count=retry_old_count,
                                    force_json=True,
                                    force_text=request.force_text,
                                    retry_count=key_retry
                                )

                                if not response_text:
                                    return {
                                        "type": "text",
                                        "success": False,
                                        "error": f"No response on key-validation retry {key_retry}",
                                        "chat_id": chat_id,
                                        "account_id": account_id
                                    }

                                # Re-parse
                                result_dict["text"] = response_text
                                try:
                                    result_dict["json"] = json.loads(response_text)
                                except:
                                    try:
                                        repaired = repair_json(response_text)
                                        result_dict["json"] = json.loads(repaired)
                                        result_dict["text"] = repaired
                                    except:
                                        result_dict["json"] = None
                                        # JSON parse failed — treat as missing all keys
                                        break

                            # Final check after loop
                            if result_dict.get("json") is not None:
                                missing = self._validate_json_keys(result_dict["json"], required_keys)
                                if missing:
                                    return {
                                        "type": "text",
                                        "success": False,
                                        "error": f"Required JSON keys missing after {key_retry} retries: {missing}",
                                        "chat_id": chat_id,
                                        "account_id": account_id
                                    }

                    return result_dict
                return {
                    "type": "text",
                    "success": False,
                    "error": "No response received",
                    "chat_id": chat_id,
                    "account_id": account_id
                }

        except Exception as e:
            self.error_count += 1
            # Diagnostic screenshot and HTML dump
            try:
                await self.dump_page_content(prefix="request_processing_error")
            except Exception as dump_err:
                logger.warning("failed_to_dump_on_request_processing_error", error=str(dump_err))

            logger.error("request_processing_error", error=str(e), trace=traceback.format_exc())
            return {"success": False, "error": str(e)}