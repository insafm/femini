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
        self.force_json = False
        self.force_text = False
        self.enable_paste_with_js = True

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
        Click the Sign In button/link with single selector fallback from bananabot2.py
        """
        # bananabot2.py uses: "//a[contains(@aria-label, 'Sign in') or span[text()='Sign in']]"
        selector = "//a[contains(@aria-label, 'Sign in') or span[text()='Sign in']]"

        try:
            element = self.page.locator(selector).first
            await element.wait_for(state="visible", timeout=3000)
            await element.click()
            logger.info("clicked_sign_in", selector=selector)
            await asyncio.sleep(1)
            return True
        except Exception:
            pass

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
        Logic ported from bananabot2.py: check_if_logged_in
        Returns True if 'Sign in' button matches are NOT found.
        """
        try:
            # bananabot2.py uses: "//a[contains(@aria-label, 'Sign in') or span[text()='Sign in']]"
            # If found -> False (not logged in). Else -> True.
            
            # We wait a brief moment to ensure page load/render if needed, matching bananabot slightly
            await asyncio.sleep(2) 

            selector = "//a[contains(@aria-label, 'Sign in') or span[text()='Sign in']]"
            
            # Check visibility
            element = self.page.locator(selector).first
            if await element.is_visible(timeout=3000):
                logger.debug("sign_in_button_found_marking_not_logged_in")
                return False
            
            logger.debug("sign_in_button_not_found_assuming_logged_in")
            return True

        except Exception as e:
            logger.warning("error_checking_login_status", error=str(e))
            # If error checking, safe assumption might be False to force re-login check or error out?
            # bananabot returns False on exception
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
            logger.info("setup_completed_already_logged_in", credential_key=self.credential.key)
            return

        # Not logged in, perform manual login
        logger.info("starting_manual_login", credential_key=self.credential.key)

        clicked = await self.click_sign_in()
        if not clicked:
            # Maybe already on login page
            try:
                email_input = self.page.locator("#identifierId").first
                if not await email_input.is_visible(timeout=3000):
                    logger.error("cannot_find_login_page")
                    return
            except Exception:
                logger.error("cannot_proceed_with_login")
                return

        await asyncio.sleep(1)
        await self.enter_email()
        await self.click_next_button()
        await self.enter_password()
        await self.click_next_button()
        await self.wait_for_dashboard()
        await self.close_popups()

        logger.info("setup_completed_with_manual_login", credential_key=self.credential.key)

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
        """
        # bananabot2.py: EC.presence_of_element_located((By.CSS_SELECTOR, "rich-textarea div.ql-editor"))
        selector = "rich-textarea div.ql-editor"

        try:
            element = self.page.locator(selector).first
            await element.wait_for(state="visible", timeout=10000)
            logger.debug("editor_found", selector=selector)
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

    async def send_prompt(self, prompt_text: str, force_json: bool = False, force_text: bool = False):
        """Send a prompt to Gemini"""
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

            # Send prompt - strict bananabot selector with retry/verification
            send_selector = "//button[contains(@aria-label, 'Send')]"
            
            for attempt in range(3):
                try:
                    send_button = self.page.locator(send_selector).first
                    if await send_button.is_visible(timeout=2000):
                        await send_button.click()
                        logger.debug("send_button_clicked", attempt=attempt)
                        
                        # Wait for send button to be hidden (indicates submission started)
                        try:
                            await send_button.wait_for(state="hidden", timeout=3000)
                            logger.info("prompt_sent_verified")
                            break
                        except PlaywrightTimeoutError:
                            logger.warning("send_button_still_visible_after_click", attempt=attempt)
                    else:
                        # Maybe Enter is needed or it's already sending
                        logger.info("send_button_not_visible_pressing_enter")
                        await editor.press("Enter")
                        await asyncio.sleep(1)
                        if not await send_button.is_visible(timeout=1000):
                            break
                except Exception as e:
                    logger.warning("error_during_send_attempt", attempt=attempt, error=str(e))
                    await editor.press("Enter")
                    await asyncio.sleep(0.5)

            logger.info("prompt_sent")
            await asyncio.sleep(0.5)
            await self.close_popups()

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
        chat_url = f"https://gemini.google.com/app/{chat_id}?hl=en-IN"
        if account_id:
            chat_url = f"https://gemini.google.com/u/{account_id}/app/{chat_id}?hl=en-IN"

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
            await self.page.goto(self.settings.base_url)
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

            # Wait for count to increase
            # bananabot uses WebDriverWait(..., lambda d: len(...) > old_count)
            await self.page.wait_for_function(
                f"() => document.querySelectorAll('message-content').length > {old_count}",
                timeout=timeout_seconds * 1000
            )

        except (asyncio.TimeoutError, PlaywrightTimeoutError):
            logger.warning("timeout_waiting_for_new_message", retry_count=retry_count)
            self.generation_in_progress = False
            self.is_last_response_image = False

            # Retry mechanism
            if self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt", 
                           attempt=retry_count + 1, 
                           max_retries=self.settings.max_retries)
                
                # Refresh/New Chat to clear state
                await self.load_new_chat()
                
                # Capture new baseline for retry
                retry_old_count = await self.page.locator("message-content").count()
                
                # Resend the prompt
                await self.send_prompt(self.last_prompt, force_json, force_text)
                
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
                current_text = (await last_message.text_content() or "").strip()
            
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
                                    retry_old_count = await self.page.locator("message-content").count()
                                    await self.send_prompt(self.last_prompt, force_json, force_text)
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
        if self.last_prompt and retry_count < self.settings.max_retries:
            logger.info("retrying_last_prompt_after_timeout", 
                       attempt=retry_count + 1, 
                       max_retries=self.settings.max_retries)
            await self.load_new_chat()
            retry_old_count = await self.page.locator("message-content").count()
            await self.send_prompt(self.last_prompt, force_json, force_text)
            return await self.get_response(
                old_count=retry_old_count, 
                stable_check_interval=stable_check_interval, 
                stable_cycles=stable_cycles, 
                force_json=force_json, 
                force_text=force_text, 
                retry_count=retry_count + 1
            )

        return cleaned_text if cleaned_text else None

    async def get_image_response(self, retry_count: int = 0) -> Optional[str]:
        """Wait for image generation to complete and return the URL with retry logic"""
        logger.info("waiting_for_image", retry_count=retry_count)
        
        try:
            await self.page.wait_for_selector(
                "generated-image img",
                timeout=self.settings.max_timeout * 1000
            )

            # Poll for new image src in the LAST message-content
            for _ in range(180):
                # Restrict to the last message to ensure we get the latest generation
                last_msg = self.page.locator("message-content").last
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
                    return src_highres

                await asyncio.sleep(1)

            logger.warning("no_new_image_generated", retry_count=retry_count)
            
            # Retry mechanism for missing image src
            if self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt_for_missing_image",
                           attempt=retry_count + 1,
                           max_retries=self.settings.max_retries)
                await self.send_prompt(self.last_prompt)
                return await self.get_image_response(retry_count + 1)

            return None

        except PlaywrightTimeoutError:
            logger.warning("timeout_waiting_for_image", retry_count=retry_count)
            self.generation_in_progress = False
            self.is_last_response_image = False

            # Retry mechanism with configurable max retries (stay in same chat for images)
            if self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt_for_image_in_same_chat",
                           attempt=retry_count + 1,
                           max_retries=self.settings.max_retries)
                # Don't load new chat for image retry - stay in same chat
                await self.send_prompt(self.last_prompt)
                return await self.get_image_response(retry_count + 1)

            logger.error("max_retries_exceeded_for_image", attempts=retry_count + 1, max_retries=self.settings.max_retries)
            return None

        except Exception as e:
            logger.error("error_getting_image_response", error=str(e), trace=traceback.format_exc())
            self.generation_in_progress = False
            self.is_last_response_image = False

            # Retry on error with counter (stay in same chat for images)
            if self.last_prompt and retry_count < self.settings.max_retries:
                logger.info("retrying_last_prompt_after_error_in_same_chat",
                           attempt=retry_count + 1,
                           max_retries=self.settings.max_retries)
                # Don't load new chat for image retry - stay in same chat
                await self.send_prompt(self.last_prompt)
                return await self.get_image_response(retry_count + 1)

            logger.error("max_retries_exceeded_after_error", attempts=retry_count + 1)
            return None

        finally:
            self.generation_in_progress = False
            self.is_last_response_image = True

    async def set_as_image(self, enable: bool = True, reference_starred_drive_image_name: Optional[str] = None):
        """Set the input mode to image or text"""
        await self.wait_for_completion()
        self.is_image = enable

        if enable and reference_starred_drive_image_name:
            self.reference_starred_drive_image_name = reference_starred_drive_image_name

            uploader_btn = self.page.locator("uploader").first
            await uploader_btn.click()

            drive_uploader = self.page.locator("drive-uploader").first
            await drive_uploader.wait_for(state="visible")
            await drive_uploader.click()
            await asyncio.sleep(2)

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
            toolbox_drawer = self.page.locator("toolbox-drawer").first
            await toolbox_drawer.wait_for(state="visible")
            await toolbox_drawer.click()
            await asyncio.sleep(1)

            # Robust XPath from bananabot2.py
            create_images_selector = "//toolbox-drawer-item//div[contains(text(), 'Create images')]/ancestor::button"
            create_images_btn = self.page.locator(create_images_selector).first
            
            try:
                await create_images_btn.wait_for(state="visible", timeout=5000)
                await create_images_btn.click()
                logger.debug("clicked_create_images")
                # Wait for tool selection to register
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("failed_to_click_create_images", error=str(e))
                # Fallback: try clicking by text content if XPath fails
                await self.page.locator("toolbox-drawer-item:has-text('Create images')").first.click()

    async def deselect_as_image(self):
        """Deselect image input mode"""
        try:
            deselect_btn = self.page.locator("button[aria-label='Deselect Image']").first
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
        """Download image from URL using Playwright's API context
        
        Args:
            url: Image URL to download
            save_dir: Directory to save the image
            filename_prefix: Prefix for the filename
            filename_suffix: Suffix for the filename
            return_data: Whether to return image bytes as well
            
        Returns:
            Tuple of (file_path, image_bytes) if return_data=True, else (file_path, None)
        """
        # Always resolve save_dir through Settings to ensure it stays in project root
        if save_dir is None:
            save_dir_path = self.settings.download_path
        else:
            save_dir_path = self.settings.resolve_path(save_dir)

        save_dir_str = str(save_dir_path)
        os.makedirs(save_dir_str, exist_ok=True)

        try:
            response = await self.context.request.get(url)

            if response.status == 200:
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                filename = os.path.join(save_dir_str, f"{filename_prefix}{timestamp}{filename_suffix}.png")
                
                content = await response.body()
                with open(filename, 'wb') as f:
                    f.write(content)

                logger.info("image_downloaded", filename=filename, size=len(content))

                if return_data:
                    return filename, content
                return filename, None
            else:
                logger.warning("image_download_failed", status=response.status, url=url[:80])
                return None, None

        except Exception as e:
            logger.error("error_downloading_image", error=str(e), error_type=type(e).__name__,
                        url=url[:80], trace=traceback.format_exc())
            return None, None

    async def download_response(self, response_text: str, save_dir: Optional[str] = None,
                              filename_prefix: str = "RESP_", filename_suffix: str = "") -> Optional[str]:
        """Save text response to file"""
        if not response_text:
            logger.warning("no_response_text_to_save")
            return None

        if save_dir is None:
            save_dir = str(self.settings.download_path)

        os.makedirs(save_dir, exist_ok=True)

        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(save_dir, f"{filename_prefix}{timestamp}{filename_suffix}.txt")

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

    async def remove_watermark(self, image_path: str) -> Optional[str]:
        """Remove watermark from image using OpenCV"""
        if not image_path or not os.path.exists(image_path):
            logger.warning("image_file_not_found", path=image_path)
            return None

        try:
            img = cv2.imread(image_path)
            h, w = img.shape[:2]
            x1, y1 = w - 80, h - 80
            x2, y2 = w, h

            mask = np.zeros(img.shape[:2], dtype=np.uint8)
            mask[y1:y2, x1:x2] = 255

            result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
            cv2.imwrite(image_path, result)

            logger.info("watermark_removed", path=image_path)
            return image_path

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
            try:
                if self.page:
                    await self.page.close()
            except Exception as e:
                logger.warning("error_closing_page_for_rotation", error=str(e))
            self.page = None


        try:
            # Run setup for first request or if page is closed
            if self.request_count == 1 or not self.page or self.page.is_closed():
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
                        logger.info("already_on_new_chat_page")

            # Handle image mode
            if request.is_image:
                await self.set_as_image(True, request.reference_image_name)

            # Get current message count before sending prompt to avoid race conditions
            old_count = await self.page.locator("message-content").count()

            # Send prompt
            await self.send_prompt(request.prompt, force_json=request.force_json, force_text=request.force_text)

            # Get response
            if request.is_image:
                result_url = await self.get_image_response()
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
                    "error": "No image generated",
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
                            while key_retry < self.settings.max_retries:
                                missing = self._validate_json_keys(result_dict["json"], required_keys)
                                if not missing:
                                    break  # All keys present — done

                                key_retry += 1
                                logger.warning("json_keys_missing_retrying",
                                               missing_keys=missing,
                                               attempt=key_retry,
                                               max_retries=self.settings.max_retries)
                                
                                # Diagnostic screenshot and HTML dump
                                try:
                                    await self.dump_page_content(prefix="json_missing_keys")
                                except Exception as dump_err:
                                    logger.warning("failed_to_dump_on_json_missing", error=str(dump_err))

                                if key_retry >= self.settings.max_retries:
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
                                retry_old_count = await self.page.locator("message-content").count()
                                await self.send_prompt(request.prompt,
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
            logger.error("request_processing_error", error=str(e), trace=traceback.format_exc())
            return {"success": False, "error": str(e)}