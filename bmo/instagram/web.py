"""
bmo_instagram_web.py — Playwright-based Instagram poster for BMO.
Uses a real headless Chromium browser so Instagram never blocks it.

How it works:
  1. First run: opens browser, logs in with credentials, saves cookies to disk
  2. Future runs: loads saved cookies — no login needed (lasts weeks)
  3. Posts feed photos and stories through the Instagram web UI

Install: pip install playwright && playwright install chromium
"""

import os
import json
import time
import asyncio
import threading
import queue
from datetime import datetime

from bmo.paths import IG_COOKIES_FILE as COOKIES_FILE, IG_TMP_DIR as _IG_TMP_DIR

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("[INSTAGRAM-WEB] playwright not installed. Run: pip install playwright && playwright install chromium", flush=True)


class InstagramWebPoster:
    """
    Posts to Instagram using a real headless Chromium browser.
    No API tokens, no sessionid rotation — just cookies that last weeks.
    """

    IG_URL = "https://www.instagram.com"

    def __init__(self, username: str, password: str, headless: bool = True):
        self.username  = username
        self.password  = password
        self.headless  = True  # Force headless to be True as requested by user
        self.logged_in = False
        self._pw       = None
        self._browser  = None
        self._context  = None
        self._page     = None
        self._task_queue = queue.Queue()
        self._dispatcher_active = False
        os.makedirs(_IG_TMP_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)

    # ── Browser lifecycle ─────────────────────────────────────────────────────
    def start(self):
        if not HAS_PLAYWRIGHT:
            return False
        try:
            print(f"[INSTAGRAM-WEB] Starting Playwright browser (headless={self.headless})...", flush=True)
            self._pw = sync_playwright().start()

            # Use a real Android device fingerprint — Instagram barely detects this
            device = self._pw.devices["Pixel 5"]

            self._browser = self._pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-extensions",
                ],
            )
            self._context = self._browser.new_context(
                **device,                              # mobile viewport + UA
                locale="en-US",
                timezone_id="America/New_York",
                permissions=["notifications"],
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )

            # Patch navigator.webdriver to undefined (key anti-bot fix)
            self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
            """)

            self._page = self._context.new_page()
            return True
        except Exception as e:
            print(f"[INSTAGRAM-WEB] Browser start failed: {e}", flush=True)
            return False


    def stop(self):
        if getattr(self, "_dispatcher_active", False):
            self._task_queue.put(None)
            time.sleep(0.5)
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ── Cookie management ─────────────────────────────────────────────────────
    def _save_cookies(self):
        cookies = self._context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"[INSTAGRAM-WEB] Cookies saved ({len(cookies)} cookies).", flush=True)

    def _load_cookies(self) -> bool:
        if not os.path.exists(COOKIES_FILE):
            return False
        try:
            with open(COOKIES_FILE) as f:
                cookies = json.load(f)
            self._context.add_cookies(cookies)
            print(f"[INSTAGRAM-WEB] Loaded {len(cookies)} saved cookies.", flush=True)
            return True
        except Exception as e:
            print(f"[INSTAGRAM-WEB] Cookie load failed: {e}", flush=True)
            return False

    def _is_logged_in(self, force_goto: bool = True):
        """Check if the current session is authenticated.
        Returns True/False when it could actually determine the state, or
        None if a transient error (network, timeout, ...) prevented checking
        — callers should NOT treat None the same as a confirmed logout."""
        try:
            # 1. Fast check: is sessionid in our cookies?
            cookies = self._context.cookies()
            has_session = any(c.get("name") == "sessionid" for c in cookies)
            if not has_session:
                return False

            if force_goto:
                # 2. Visual check: go to home page and make sure login prompts are gone
                self._page.goto(self.IG_URL, timeout=15000)
                time.sleep(2)

            # If we are on the login page, we are not logged in
            if "accounts/login" in self._page.url:
                return False

            # If we see a login button, we are NOT logged in
            if self._page.locator("button:has-text('Log in')").count() > 0:
                return False
            if self._page.locator("text='Log in'").count() > 0:
                return False

            return True
        except Exception as e:
            print(f"[INSTAGRAM-WEB] Login check failed (transient?): {e}", flush=True)
            return None

    # ── Login ─────────────────────────────────────────────────────────────────
    def login(self) -> bool:
        """Log in and save cookies. Returns True on success."""
        print("[INSTAGRAM-WEB] Logging in via browser...", flush=True)
        try:
            page = self._page

            # Go directly to login page
            page.goto(f"{self.IG_URL}/accounts/login/", timeout=30000,
                      wait_until="domcontentloaded")
            time.sleep(5)  # let JS render fully

            # Dismiss GDPR / cookie consent wall if present
            for consent_text in ["Allow all cookies", "Accept all", "Allow essential and optional cookies"]:
                try:
                    btn = page.locator(f"button:has-text('{consent_text}')").first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        print(f"[INSTAGRAM-WEB] Dismissed cookie consent: {consent_text}", flush=True)
                        time.sleep(2)
                        break
                except Exception:
                    pass

            # Save debug screenshot so we can see what loaded
            shot = os.path.join(_IG_TMP_DIR, "ig_login_debug.png")
            page.screenshot(path=shot)
            print(f"[INSTAGRAM-WEB] Debug screenshot: {shot}", flush=True)


            # Try multiple selector strategies for username field
            username_sel = None
            for sel in [
                "input[name='username']",
                "input[autocomplete='username']",
                "input[aria-label='Phone number, username, or email']",
                "input[type='text']",
            ]:
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    username_sel = sel
                    print(f"[INSTAGRAM-WEB] Found username field: {sel}", flush=True)
                    break
                except Exception:
                    continue

            if not username_sel:
                # Take another screenshot to show what's on page
                page.screenshot(path=shot)
                print(f"[INSTAGRAM-WEB] Could not find login form. See: {shot}", flush=True)
                return False

            # Fill username
            page.click(username_sel)
            page.type(username_sel, self.username, delay=80)
            time.sleep(0.5)

            # Fill password
            pwd_sel = None
            for sel in [
                "input[name='password']",
                "input[type='password']",
                "input[aria-label='Password']",
            ]:
                try:
                    page.wait_for_selector(sel, timeout=5000)
                    pwd_sel = sel
                    break
                except Exception:
                    continue

            if not pwd_sel:
                print("[INSTAGRAM-WEB] Could not find password field.", flush=True)
                return False

            page.click(pwd_sel)
            page.type(pwd_sel, self.password, delay=80)
            time.sleep(0.5)

            # Click login button
            clicked = False
            for sel in [
                "button[type='submit']",
                "[type='submit']",
                "button:has-text('Log in')",
                "button:has-text('Log In')",
                "text='Log in'",
                "text='Log In'",
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0:
                        print(f"[INSTAGRAM-WEB] Clicking login button: {sel}", flush=True)
                        btn.click(force=True, timeout=3000)
                        clicked = True
                        break
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] Failed clicking with selector {sel}: {e}", flush=True)
                    continue

            # Fallback 1: Direct JavaScript click fallback
            time.sleep(1)
            if "accounts/login" in page.url:
                print("[INSTAGRAM-WEB] Still on login page. Trying direct JavaScript click fallback...", flush=True)
                try:
                    js_clicked = page.evaluate("""
                        () => {
                            const btn = document.querySelector('button[type="submit"]') || 
                                        document.querySelector('[type="submit"]') ||
                                        Array.from(document.querySelectorAll('button, div, span, [role="button"]')).find(el => {
                                            const txt = el.textContent.trim().toLowerCase();
                                            return txt === 'log in' || txt === 'login';
                                        });
                            if (btn) {
                                btn.click();
                                return btn.tagName + " (" + btn.textContent.trim() + ")";
                            }
                            return null;
                        }
                    """)
                    if js_clicked:
                        print(f"[INSTAGRAM-WEB] JS click fallback successfully triggered on: {js_clicked}", flush=True)
                    else:
                        print("[INSTAGRAM-WEB] JS click fallback could not find any button.", flush=True)
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] JS click fallback error: {e}", flush=True)

            # Fallback 2: Enter key press
            time.sleep(1)
            if "accounts/login" in page.url:
                print("[INSTAGRAM-WEB] Still on login page. Sending Enter key to password field to force submit...", flush=True)
                try:
                    page.focus(pwd_sel)
                    page.press(pwd_sel, "Enter")
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] Failed to send Enter key: {e}", flush=True)

            # Wait for navigation away from accounts/login
            print("[INSTAGRAM-WEB] Waiting for post-submit navigation...", flush=True)
            try:
                page.wait_for_url(lambda url: "accounts/login" not in url, timeout=15000)
                print(f"[INSTAGRAM-WEB] Navigated away from login page. New URL: {page.url}", flush=True)
            except Exception as e:
                print(f"[INSTAGRAM-WEB] Timed out waiting for URL change: {e}. Current URL: {page.url}", flush=True)

            # Let's wait a couple seconds for JS to process any post-login screens
            time.sleep(5)
            page.screenshot(path=shot)
            print(f"[INSTAGRAM-WEB] Post-login screenshot: {shot}", flush=True)

            # Check if security challenge occurred
            if "challenge" in page.url:
                print("[INSTAGRAM-WEB] ⚠ SECURITY CHALLENGE/CHECKPOINT DETECTED! Instagram is requesting verification.", flush=True)
                print(f"[INSTAGRAM-WEB] Please check screenshot: {shot}", flush=True)

            # Check for visible error messages if still on login page
            if "accounts/login" in page.url:
                print("[INSTAGRAM-WEB] ✗ Still on login page. Checking for visible error messages...", flush=True)
                for err_sel in ["#loginForm p[role='alert']", "[role='alert']", "text='incorrect'"]:
                    try:
                        err_el = page.locator(err_sel).first
                        if err_el.is_visible(timeout=2000):
                            print(f"[INSTAGRAM-WEB] Alert found on page: {err_el.text_content()}", flush=True)
                    except Exception:
                        pass

            # Dismiss "Save login info" / "Turn on notifications" dialogs
            for dismiss_text in ["Not now", "Not Now", "Skip", "Later", "Cancel"]:
                try:
                    btn = page.locator(f"text='{dismiss_text}'").last
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        time.sleep(1)
                except Exception:
                    pass

            # Verify login (fast check without interrupting redirects)
            if self._is_logged_in(force_goto=False):
                self._save_cookies()
                self.logged_in = True
                print("[INSTAGRAM-WEB] ✓ Login successful! Cookies saved.", flush=True)
                return True
            # Fallback with forced goto just in case
            elif self._is_logged_in(force_goto=True):
                self._save_cookies()
                self.logged_in = True
                print("[INSTAGRAM-WEB] ✓ Login successful on fallback check! Cookies saved.", flush=True)
                return True
            else:
                print("[INSTAGRAM-WEB] ✗ Still not logged in after submit.", flush=True)
                return False

        except Exception as e:
            print(f"[INSTAGRAM-WEB] Login error: {e}", flush=True)
            return False

    def connect(self) -> bool:
        """Verify credentials. Browser is opened on-demand for actions."""
        if self.username and self.password:
            self.logged_in = True
            print("[INSTAGRAM-WEB] Connected (lazy/on-demand browser enabled).", flush=True)
            return True
        print("[INSTAGRAM-WEB] Connection failed: missing credentials.", flush=True)
        return False

    def _execute_with_browser(self, func, *args):
        """Helper to run a browser action with a temporary Playwright instance to save memory and CPU."""
        print("[INSTAGRAM-WEB] Launching on-demand Chromium browser...", flush=True)
        t_start = time.time()
        
        # 1. Start browser
        if not self.start():
            return "Instagram browser start failed."
        
        # 2. Login or load cookies
        logged_in   = False
        login_check = self._is_logged_in(force_goto=True) if self._load_cookies() else False

        if login_check is True:
            logged_in = True
            self.logged_in = True
            print("[INSTAGRAM-WEB] ✓ Restored session from cookies.", flush=True)
        elif login_check is None:
            # Couldn't verify due to a transient error — the cookies might
            # still be perfectly good, so don't delete them or attempt a
            # fresh automated login (which Instagram is likely to challenge).
            print("[INSTAGRAM-WEB] Could not verify session — leaving cookies in place, try again shortly.", flush=True)
        else:
            print("[INSTAGRAM-WEB] Cookies expired or missing — doing fresh login.", flush=True)
            try:
                os.remove(COOKIES_FILE)
            except Exception:
                pass
            if self.login():
                logged_in = True
                self.logged_in = True

        if not logged_in:
            self.stop()
            return "Instagram login failed."

        # 3. Execute the function
        try:
            print(f"[INSTAGRAM-WEB] Executing browser action: {func.__name__}...", flush=True)
            res = func(*args)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[INSTAGRAM-WEB] Browser action failed: {e}\n{tb}", flush=True)
            res = f"Instagram action failed: {e}"
        finally:
            # 4. Stop browser completely to free up 100% of memory and CPU!
            self.stop()
            print(f"[INSTAGRAM-WEB] Closed on-demand browser. Active time: {time.time()-t_start:.1f}s", flush=True)

        return res

    # ── Post photo to feed ────────────────────────────────────────────────────
    def post_photo(self, image_path: str, caption: str) -> str:
        return self._execute_with_browser(self._post_photo_impl, image_path, caption)

    def _post_photo_impl(self, image_path: str, caption: str) -> str:
        if not self.logged_in:
            return "Instagram browser not connected."
        if not os.path.exists(image_path):
            return f"Image not found: {image_path}"
        try:
            print(f"[INSTAGRAM-WEB] Posting photo using DESKTOP flow: {image_path}", flush=True)
            
            # Create a dedicated Desktop context to bypass mobile PWA weirdness
            desktop_context = self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                locale="en-US"
            )
            # Transfer auth cookies from the mobile context
            desktop_context.add_cookies(self._context.cookies())
            page = desktop_context.new_page()

            # Navigate home
            try:
                page.goto(self.IG_URL, timeout=15000)
                # networkidle often times out on Instagram due to constant polling, so we ignore timeouts here
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            time.sleep(2)

            # Dismiss blocking popups (Save Info, Notifications)
            for popup_text in ["Not now", "Not Now", "Cancel"]:
                try:
                    page.locator(f"text='{popup_text}'").last.click(timeout=2000, force=True)
                    time.sleep(1)
                except Exception:
                    pass

            # Click "Create" in the left sidebar
            try:
                # Desktop sidebar Create button (Target the text span, which is very reliable)
                create_btn = page.get_by_text("Create", exact=True).first
                if not create_btn.is_visible(timeout=3000):
                    create_btn = page.locator("svg[aria-label='New post'], svg[aria-label='New Post']").locator("..").first
                create_btn.click(force=True)
                time.sleep(2)
                
                # Check if a submenu appeared ("Post", "Live Video")
                post_submenu = page.get_by_text("Post", exact=True).first
                if post_submenu.is_visible(timeout=2000):
                    post_submenu.click(force=True)
                    print("[INSTAGRAM-WEB] Selected 'Post' from Create submenu.", flush=True)
                    time.sleep(2)
            except Exception as e:
                desktop_context.close()
                return f"Instagram post failed: Could not click Create button on desktop. {e}"

            # Upload the photo (The modal has a hidden input[type='file'])
            try:
                # Wait for the modal to fully render the file input
                file_input = page.locator("input[type='file']").first
                file_input.wait_for(state="attached", timeout=5000)
                file_input.set_input_files(image_path)
                print("[INSTAGRAM-WEB] Uploaded photo via Desktop UI.", flush=True)
                time.sleep(3)
            except Exception as e:
                desktop_context.close()
                return f"Instagram post failed: Could not inject file into desktop modal. {e}"

            # Click Next twice (Bypass crop & filter screens)
            for step in ["crop", "filters"]:
                try:
                    page.get_by_role("button", name="Next").first.click()
                    time.sleep(2)
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] Warning: Desktop Next ({step}) button not found: {e}", flush=True)

            # Add caption
            try:
                caption_box = page.locator("div[aria-label='Write a caption...']").first
                caption_box.click()
                caption_box.fill(caption)
                print("[INSTAGRAM-WEB] Filled caption.", flush=True)
                time.sleep(1)
            except Exception as e:
                print(f"[INSTAGRAM-WEB] Caption error on desktop: {e}", flush=True)

            # Click Share
            try:
                page.get_by_role("button", name="Share").first.click()
                print("[INSTAGRAM-WEB] Clicked Share button.", flush=True)
                # Wait for upload to complete
                time.sleep(10)
            except Exception as e:
                desktop_context.close()
                return f"Instagram post failed: Could not click Share on desktop. {e}"

            # Clean up
            self._context.add_cookies(desktop_context.cookies())
            self._save_cookies()
            desktop_context.close()

            print("[INSTAGRAM-WEB] ✓ Photo posted via Desktop flow!", flush=True)
            return "Instagram post published! ✓"

        except Exception as e:
            print(f"[INSTAGRAM-WEB] Post error: {e}", flush=True)
            return f"Instagram post failed: {e}"

    # ── Post story ────────────────────────────────────────────────────────────
    def post_story(self, image_path: str) -> str:
        return self._execute_with_browser(self._post_story_impl, image_path)

    def _post_story_impl(self, image_path: str) -> str:
        if not self.logged_in:
            return "Instagram browser not connected."
        if not os.path.exists(image_path):
            return f"Image not found: {image_path}"
        try:
            print(f"[INSTAGRAM-WEB] Posting story: {image_path}", flush=True)
            page = self._page

            page.goto(self.IG_URL, timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(2)

            # Dismiss blocking popups aggressively (Save Info, Add to Home Screen, etc.)
            for popup_text in ["Not now", "Cancel", "Skip", "Close"]:
                try:
                    popup_btn = page.locator(f"text='{popup_text}'").last
                    popup_btn.click(timeout=2000, force=True)
                    print(f"[INSTAGRAM-WEB] Dismissed popup: {popup_text}", flush=True)
                    time.sleep(1)
                except Exception:
                    pass

            # Sweep close icons and dynamic banner dismissals
            try:
                page.evaluate("""
                    () => {
                        const dismissTexts = ['not now', 'cancel', 'close', 'skip', 'later', 'no thanks'];
                        const buttons = Array.from(document.querySelectorAll('button, [role="button"], span, a'));
                        buttons.forEach(btn => {
                            const txt = btn.textContent.trim().toLowerCase();
                            if (dismissTexts.includes(txt)) {
                                if (btn.offsetParent !== null) btn.click();
                            }
                        });
                        
                        const svgs = Array.from(document.querySelectorAll('svg'));
                        svgs.forEach(svg => {
                            const label = (svg.getAttribute('aria-label') || '').toLowerCase();
                            if (label.includes('close') || label.includes('dismiss') || label.includes('cancel')) {
                                const btn = svg.closest('button') || svg.closest('[role="button"]') || svg;
                                if (btn && btn.offsetParent !== null) btn.click();
                            }
                        });
                    }
                """)
                time.sleep(1)
            except Exception:
                pass

            # 1. Register page-wide file chooser interceptor to completely prevent OS dialog deadlocks
            uploaded = False
            def handle_file_chooser(file_chooser):
                try:
                    print(f"[INSTAGRAM-WEB] Intercepted file chooser event page-wide! Setting files...", flush=True)
                    file_chooser.set_files(image_path)
                    nonlocal uploaded
                    uploaded = True
                    print("[INSTAGRAM-WEB] Page-wide file chooser successfully processed!", flush=True)
                except Exception as ex:
                    print(f"[INSTAGRAM-WEB] Error setting files on intercepted chooser: {ex}", flush=True)

            page.on("filechooser", handle_file_chooser)

            # 2. Path A: Direct DOM input injection (Safe, Fast, Bypasses all clicks)
            try:
                print("[INSTAGRAM-WEB] Analyzing DOM file inputs for direct injection...", flush=True)
                inputs_info = page.evaluate("""
                    () => {
                        const inputs = Array.from(document.querySelectorAll("input[type='file']"));
                        return inputs.map((input, idx) => {
                            const rect = input.getBoundingClientRect();
                            let textContext = '';
                            let parent = input.parentElement;
                            for (let i = 0; i < 8; i++) {
                                if (!parent) break;
                                textContext += ' ' + parent.textContent + ' ' + (parent.getAttribute('aria-label') || '') + ' ' + (parent.className || '');
                                parent = parent.parentElement;
                            }
                            textContext = textContext.toLowerCase();
                            
                            let type = 'unknown';
                            if (textContext.includes('story') || textContext.includes('your story')) {
                                type = 'story';
                            } else if (textContext.includes('post') || textContext.includes('feed') || textContext.includes('create') || textContext.includes('new')) {
                                type = 'post';
                            }
                            
                            return {
                                index: idx,
                                type: type,
                                top: rect.top,
                                left: rect.left,
                                isVisible: rect.width > 0 || rect.height > 0 || input.offsetParent !== null
                            };
                        });
                    }
                """)
                
                print(f"[INSTAGRAM-WEB] Found DOM file inputs: {inputs_info}", flush=True)
                
                # Order the inputs by suitability for story:
                candidate_indices = []
                for info in inputs_info:
                    if info['type'] == 'story':
                        candidate_indices.append(info['index'])
                
                for info in inputs_info:
                    if info['top'] < 250 and info['index'] not in candidate_indices:
                        candidate_indices.append(info['index'])
                        
                for info in inputs_info:
                    if info['index'] not in candidate_indices:
                        candidate_indices.append(info['index'])
                        
                # Direct injection loop
                for idx in candidate_indices:
                    try:
                        print(f"[INSTAGRAM-WEB] Trying direct injection on input index {idx}...", flush=True)
                        page.locator("input[type='file']").nth(idx).set_input_files(image_path)
                        time.sleep(4)
                        
                        # Verify if composer loaded
                        composer_loaded = page.evaluate("""
                            () => {
                                const elements = Array.from(document.querySelectorAll('button, div, span, [role="button"]'));
                                return elements.some(el => {
                                    const txt = el.textContent.trim().toLowerCase();
                                    return txt.includes('next') || txt.includes('story') || txt.includes('share') || txt.includes('your story');
                                });
                            }
                        """)
                        if composer_loaded:
                            print(f"[INSTAGRAM-WEB] Direct injection on input index {idx} succeeded! Story composer loaded.", flush=True)
                            uploaded = True
                            break
                    except Exception as e:
                        print(f"[INSTAGRAM-WEB] Direct injection on input index {idx} failed: {e}", flush=True)
            except Exception as e:
                print(f"[INSTAGRAM-WEB] DOM file input analysis failed: {e}", flush=True)

            # 3. Path B: Direct "Your story" bubble click (Protected by page-wide interceptor)
            if not uploaded:
                try:
                    print("[INSTAGRAM-WEB] Direct injection didn't trigger composer. Clicking 'Your story' bubble...", flush=True)
                    your_story_btn = page.locator("text='Your story'").first
                    if your_story_btn.is_visible(timeout=3000):
                        your_story_btn.click(force=True, timeout=3000)
                        # Wait for page-wide interceptor to resolve the file setting
                        for _ in range(10):
                            if uploaded:
                                break
                            time.sleep(0.5)
                        if uploaded:
                            print("[INSTAGRAM-WEB] Direct bubble click upload succeeded!", flush=True)
                            time.sleep(3)
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] Bubble click upload failed/bypassed: {e}", flush=True)

            # 4. Path C: Standard '+' click & 'Story' menu selection (Protected by page-wide interceptor)
            if not uploaded:
                clicked_plus = False
                for sel in [
                    "svg[aria-label='New post']",
                    "svg[aria-label='New Post']",
                    "svg[aria-label='Create']",
                    "[aria-label='New post']",
                    "[aria-label='New Post']",
                    "[aria-label='Create']"
                ]:
                    try:
                        plus_btn = page.locator(sel).first
                        parent = plus_btn.locator("xpath=./ancestor::button[1] | ./ancestor::div[@role='button'][1] | .").first
                        if parent.count() > 0 and parent.is_visible():
                            print(f"[INSTAGRAM-WEB] Clicking '+' icon button natively with selector: {sel}", flush=True)
                            parent.click(force=True, timeout=3000)
                            clicked_plus = True
                            break
                    except Exception:
                        continue

                # JS click fallback for '+' button
                if not clicked_plus:
                    print("[INSTAGRAM-WEB] Trying JS fallback to click '+' button...", flush=True)
                    try:
                        js_plus = page.evaluate("""
                            () => {
                                const svg = document.querySelector('svg[aria-label="New post"]') || 
                                            document.querySelector('svg[aria-label="New Post"]') ||
                                            document.querySelector('svg[aria-label="Create"]');
                                if (svg) {
                                    const btn = svg.closest('button') || svg.closest('[role="button"]') || svg;
                                    btn.click();
                                    return true;
                                }
                                return false;
                            }
                        """)
                        if js_plus:
                            clicked_plus = True
                            print("[INSTAGRAM-WEB] '+' button clicked via JS fallback.", flush=True)
                    except Exception as e:
                        print(f"[INSTAGRAM-WEB] JS '+' click failed: {e}", flush=True)

                # Bottom bar geometry clicker fallback for '+' button
                if not clicked_plus:
                    print("[INSTAGRAM-WEB] Trying bottom bar geometry clicker as fallback...", flush=True)
                    try:
                        geom_clicked = page.evaluate("""
                            () => {
                                const navs = Array.from(document.querySelectorAll('div, nav, footer'));
                                for (let el of navs) {
                                    const rect = el.getBoundingClientRect();
                                    const style = window.getComputedStyle(el);
                                    if (style.position === 'fixed' && rect.bottom >= window.innerHeight - 5 && rect.width > 250) {
                                        const items = Array.from(el.querySelectorAll('a, button, [role="link"], [role="button"]'));
                                        const uniqueItems = [];
                                        const seenX = new Set();
                                        items.forEach(item => {
                                            const r = item.getBoundingClientRect();
                                            const centerX = Math.round(r.left + r.width / 2);
                                            if (r.width > 0 && r.height > 0 && !seenX.has(centerX)) {
                                                seenX.add(centerX);
                                                uniqueItems.push({ el: item, x: centerX });
                                            }
                                        });
                                        uniqueItems.sort((a, b) => a.x - b.x);
                                        if (uniqueItems.length >= 3) {
                                            const targetIdx = Math.floor(uniqueItems.length / 2);
                                            uniqueItems[targetIdx].el.click();
                                            return "Clicked item " + targetIdx + " out of " + uniqueItems.length + " in bottom bar";
                                        }
                                    }
                                }
                                return null;
                            }
                        """)
                        if geom_clicked:
                            print(f"[INSTAGRAM-WEB] '+' clicked via bottom bar geometry: {geom_clicked}", flush=True)
                            clicked_plus = True
                    except Exception as e:
                        print(f"[INSTAGRAM-WEB] Geometry bottom bar click failed: {e}", flush=True)

                # Wait 2 seconds for popup menu to render
                time.sleep(2)

                # Click "Story" menu option natively
                try:
                    print("[INSTAGRAM-WEB] Clicking 'Story' option in popup...", flush=True)
                    story_btn = page.locator("text='Story'").last
                    story_btn.click(force=True, timeout=3000)
                    for _ in range(10):
                        if uploaded:
                            break
                        time.sleep(0.5)
                    if uploaded:
                        print("[INSTAGRAM-WEB] Story menu click upload succeeded!", flush=True)
                        time.sleep(3)
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] 'Story' menu click failed: {e}", flush=True)

            # 5. Path D: Absolute Fallbacks (No clicks, direct input population)
            if not uploaded:
                try:
                    page.locator("input[type='file']").last.set_input_files(image_path)
                    print("[INSTAGRAM-WEB] Fallback direct injection into last input succeeded.", flush=True)
                    uploaded = True
                    time.sleep(3)
                except Exception:
                    pass

            if not uploaded:
                try:
                    page.locator("input[type='file']").first.set_input_files(image_path)
                    print("[INSTAGRAM-WEB] Fallback direct injection into first input succeeded.", flush=True)
                    uploaded = True
                    time.sleep(3)
                except Exception as ex:
                    shot = os.path.join(_IG_TMP_DIR, "ig_create_debug.png")
                    page.screenshot(path=shot)
                    print(f"[INSTAGRAM-WEB] Direct story file upload fallback failed: {ex}. See {shot}", flush=True)
                    return "Instagram story failed: Could not upload file."

            # Switch to Story tab if it appears
            try:
                story_tab = page.locator("button:has-text('Story')").first
                if story_tab.is_visible(timeout=3000):
                    story_tab.click()
                    time.sleep(1)
            except Exception:
                pass

            # Click Next buttons to get through crop/filter screens
            for _ in range(3):
                try:
                    next_btn = page.locator("button:has-text('Next')").first
                    if next_btn.is_visible(timeout=3000):
                        next_btn.click()
                        time.sleep(2)
                except Exception:
                    break

            # Wait for upload to complete and preview to show
            print("[INSTAGRAM-WEB] Waiting for story preview to render...", flush=True)
            time.sleep(8)

            # Share (Retry loop with JavaScript)
            shared = False

            # Direct Python-based Share Clicker (Extremely robust and instant)
            for text_val in ["Your story", "Your Story", "Share", "Share to story", "Share to Story", "Share to"]:
                try:
                    share_btn = page.locator(f"text='{text_val}'").last
                    if share_btn.is_visible(timeout=2000):
                        print(f"[INSTAGRAM-WEB] Found final share button natively: '{text_val}'. Clicking...", flush=True)
                        share_btn.click(force=True)
                        shared = True
                        break
                except Exception as e:
                    print(f"[INSTAGRAM-WEB] Direct Python share click failed for '{text_val}': {e}", flush=True)

            if not shared:
                print("[INSTAGRAM-WEB] Native share buttons not visible/clickable. Proceeding to JS-based solver...", flush=True)
                for attempt in range(8):
                    try:
                        js_code = """
                        () => {
                            const viewportWidth = window.innerWidth;
                            const viewportHeight = window.innerHeight;
                            
                            // Find all potential interactive elements
                            const elements = Array.from(document.querySelectorAll('div, button, span, [role="button"], a, svg, path'));
                            const candidates = [];
                            
                            elements.forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (rect.width === 0 || rect.height === 0) return;
                                
                                const txt = el.textContent.trim().toLowerCase();
                                const label = (el.getAttribute('aria-label') || '').toLowerCase();
                                
                                let titleText = '';
                                const title = el.querySelector('title');
                                if (title) titleText = title.textContent.toLowerCase();
                                
                                const centerX = rect.left + rect.width / 2;
                                const centerY = rect.top + rect.height / 2;
                                
                                let score = 0;
                                const allText = (txt + ' ' + label + ' ' + titleText).trim();
                                const matchesText = allText.includes('share') || allText.includes('story') || allText.includes('next') || allText.includes('your');
                                
                                if (matchesText) {
                                    // Score based on exact text matches
                                    if (allText.includes('share a story') || allText.includes('share to story')) {
                                        score += 500;
                                    } else if (allText.includes('your story')) {
                                        score += 450;
                                    } else if (allText.includes('share')) {
                                        score += 400;
                                    } else if (allText.includes('next')) {
                                        score += 300;
                                    } else if (allText.includes('story')) {
                                        score += 200;
                                    }
                                }
                                
                                // Massive bonus if inside a dialog/modal container (e.g. share confirmation overlay)
                                const isInsideDialog = el.closest('[role="dialog"]') || el.closest('div[class*="dialog"]') || el.closest('div[class*="modal"]');
                                if (isInsideDialog) {
                                    score += 1000;
                                }
                                
                                // Middle bottom region criteria (only enforced if NOT inside a modal/dialog)
                                const isNearHorizontalCenter = Math.abs(centerX - viewportWidth / 2) < (viewportWidth * 0.25);
                                const isNearBottom = rect.bottom >= viewportHeight * 0.6;
                                
                                // Crucial safety check: The element must NEVER be at the top of the viewport
                                // (this avoids misidentifying the stories tray or headers at the top)
                                const isNotAtTop = rect.top >= 220 && centerY >= viewportHeight * 0.4;
                                
                                if (isNotAtTop && (isInsideDialog || (isNearHorizontalCenter && isNearBottom))) {
                                    if (el.tagName.toLowerCase() === 'button' || el.getAttribute('role') === 'button') {
                                        score += 100;
                                    } else if (el.tagName.toLowerCase() === 'svg' || el.tagName.toLowerCase() === 'path') {
                                        score += 50;
                                    } else {
                                        score += 10;
                                    }
                                    
                                    // Distance penalties (only applied to non-dialog elements)
                                    if (!isInsideDialog) {
                                        const distFromCenterX = Math.abs(centerX - viewportWidth / 2);
                                        score -= distFromCenterX / 5;
                                    }
                                    
                                    candidates.push({ el, score });
                                }
                            });
                            
                            if (candidates.length > 0) {
                                candidates.sort((a, b) => b.score - a.score);
                                const bestCandidate = candidates[0].el;
                                const clickTarget = bestCandidate.closest('button') || bestCandidate.closest('[role="button"]') || bestCandidate.closest('div[class*="html-div"]') || bestCandidate;
                                
                                // Mobile event dispatcher
                                try { clickTarget.focus(); } catch(e){}
                                
                                // Trigger mousedown, mouseup, click
                                const mouseEvents = ['mousedown', 'mouseup', 'click'];
                                mouseEvents.forEach(evtType => {
                                    const evt = new MouseEvent(evtType, {
                                        bubbles: true,
                                        cancelable: true,
                                        view: window
                                    });
                                    clickTarget.dispatchEvent(evt);
                                });
                                
                                // Trigger touchstart, touchend
                                try {
                                    const touchStart = new TouchEvent('touchstart', { bubbles: true, cancelable: true });
                                    clickTarget.dispatchEvent(touchStart);
                                    const touchEnd = new TouchEvent('touchend', { bubbles: true, cancelable: true });
                                    clickTarget.dispatchEvent(touchEnd);
                                } catch(e){}
                                
                                return "Clicked candidate via mobile events: " + clickTarget.tagName + " (" + clickTarget.textContent.trim() + ") with score " + candidates[0].score;
                            }
                            
                            // 2. Simple text-based fallback
                            for (let el of elements) {
                                const txt = el.textContent.trim().toLowerCase();
                                const rect = el.getBoundingClientRect();
                                if (rect.top < 220 || rect.height === 0 || rect.width === 0) {
                                    continue;
                                }
                                if (txt === 'share' || txt === 'next' || txt === 'your story' || txt === 'share to story' || txt.includes('share a story')) {
                                    const clickTarget = el.closest('button') || el.closest('[role="button"]') || el;
                                    clickTarget.click();
                                    return "Simple text fallback clicked: " + txt;
                                }
                            }
                            return null;
                        }
                        """
                        clicked_txt = page.evaluate(js_code)
                        if clicked_txt:
                            print(f"[INSTAGRAM-WEB] Clicked share button: '{clicked_txt}'", flush=True)
                            shared = True
                            break
                    except Exception as e:
                        print(f"[INSTAGRAM-WEB] Share button click attempt failed: {e}", flush=True)
                    time.sleep(2)

            if not shared:
                dom_dump = os.path.join(_IG_TMP_DIR, "ig_share_debug.html")
                with open(dom_dump, "w") as f:
                    f.write(page.content())
                print(f"[INSTAGRAM-WEB] Could not find final share button. See {dom_dump}", flush=True)
                page.keyboard.press("Enter")

            time.sleep(5)
            self._save_cookies()
            print("[INSTAGRAM-WEB] ✓ Story posted!", flush=True)
            return "Instagram story posted! ✓"

        except Exception as e:
            print(f"[INSTAGRAM-WEB] Story error: {e}", flush=True)
            return f"Instagram story failed: {e}"

    def get_followers(self) -> str:
        return self._execute_with_browser(self._get_followers_impl)

    def _get_followers_impl(self) -> str:
        try:
            page = self._page
            page.goto(f"{self.IG_URL}/{self.username}/", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
            # Extract from meta or page content
            el = page.locator("meta[name='description']").get_attribute("content")
            if el:
                import re
                m = re.search(r"([\d,]+)\s+Followers", el)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return "N/A"
