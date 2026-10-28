"""
Periodic_screenshots.py
 
Takes periodic screenshots of a Power BI report using a headless browser
(Playwright), and saves a JSON file next to each screenshot with details
about the capture.
 
Each cycle: refresh the page, wait 30 seconds for it to load, take the
screenshot. By default the cycle repeats every hour.
 
Setup (once):
    pip install playwright
    playwright install chromium
 
Log in (once, and again whenever your Microsoft session expires):
    python Periodic_screenshots.py --url "https://app.powerbi.com/groups/.../reports/..." --login
 
Run it (Ctrl+C to stop):
    python Periodic_screenshots.py --url "https://app.powerbi.com/..."
 
Tip: set DEFAULT_URL below so you can skip --url (and use VS Code's Run button).
"""
 
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
 
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
 
# Paste your Power BI report link here to skip typing --url every time.
DEFAULT_URL = ""
 
# The saved browser profile (your Microsoft login lives here).
# Keep this folder out of GitHub: add "browser_profile/" to .gitignore.
PROFILE_DIR = Path("browser_profile")
 
# Signs that we got bounced to a Microsoft login page instead of the report.
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com", "login.microsoft.com")
 
# Elements Power BI uses for report visuals (charts, cards, tables).
VISUAL_SELECTOR = "visual-container, .visual-container, .visualContainer"
 
VIEWPORT = {"width": 1920, "height": 1080}
 
 
def parse_args():
    parser = argparse.ArgumentParser(description="Periodic Power BI screenshots.")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="Power BI report link (or set DEFAULT_URL in the script)")
    parser.add_argument("--interval", type=int, default=3600,
                        help="Seconds between refreshes/screenshots (default: 3600 = 1 hour)")
    parser.add_argument("--load-wait", type=int, default=30,
                        help="Seconds to wait after loading/refreshing before the screenshot (default: 30)")
    parser.add_argument("--timeout", type=int, default=60,
                        help="Max seconds to wait for the page to respond (default: 60)")
    parser.add_argument("--output", default="screenshots",
                        help="Folder to save screenshots in (default: screenshots)")
    parser.add_argument("--once", action="store_true",
                        help="Take one screenshot and exit (good for testing)")
    parser.add_argument("--login", action="store_true",
                        help="Open a visible browser so you can sign in with Microsoft")
    parser.add_argument("--show", action="store_true",
                        help="Show the browser window while running (helps with troubleshooting)")
    parser.add_argument("--not-powerbi", action="store_true",
                        help="Don't check for Power BI charts (for testing on other websites)")
    args = parser.parse_args()
 
    if not args.url:
        parser.error("No report URL. Pass --url or set DEFAULT_URL at the top of the script.")
    return args
 
 
def open_browser(p, headless):
    """Open Chromium using the saved profile, so the Microsoft login is remembered."""
    PROFILE_DIR.mkdir(exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport=VIEWPORT,
    )
 
 
def is_login_page(url):
    return any(host in url for host in LOGIN_HOSTS)
 
 
def login(url):
    """Open a real browser window so you can sign in with Microsoft by hand."""
    with sync_playwright() as p:
        context = open_browser(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        print("Sign in with Microsoft in the browser window.")
        print('When asked "Stay signed in?", choose Yes.')
        input("Once the report is showing, press Enter here to save the login...")
        context.close()
    print(f"Login saved in the '{PROFILE_DIR}' folder. You can now run without --login.")
 
 
def load_or_refresh(page, args, first_run):
    """Open the report the first time; after that, refresh it."""
    timeout_ms = args.timeout * 1000
    # Power BI keeps connections open forever, so don't wait for "network idle".
    if first_run or page.url in ("", "about:blank") or is_login_page(page.url):
        page.goto(args.url, timeout=timeout_ms, wait_until="domcontentloaded")
        return "load"
    page.reload(timeout=timeout_ms, wait_until="domcontentloaded")
    return "refresh"
 
 
def take_screenshot(page, args, output_dir, first_run):
    """Refresh the page, wait for it to load, screenshot it, and save the details."""
    started = datetime.now()
    stamp = started.strftime("%Y-%m-%d_%H-%M-%S")
    image_path = output_dir / f"{stamp}.png"
    meta_path = output_dir / f"{stamp}.json"
 
    metadata = {
        "timestamp": started.isoformat(timespec="seconds"),
        "url_requested": args.url,
        "interval_seconds": args.interval,
        "load_wait_seconds": args.load_wait,
        "timeout_seconds": args.timeout,
        "screenshot_file": image_path.name,
    }
 
    try:
        metadata["action"] = load_or_refresh(page, args, first_run)
        print(f"[{stamp}] Page {metadata['action']}ed. Waiting {args.load_wait} seconds...")
 
        if is_login_page(page.url):
            metadata.update({
                "success": False,
                "session_expired": True,
                "url_final": page.url,
                "error": "Redirected to Microsoft login. Run again with --login.",
            })
            page.screenshot(path=str(image_path))
            print(f"[{stamp}] Login expired. Run with --login to sign in again.")
        else:
            # Give the page time to fully load and draw.
            page.wait_for_timeout(args.load_wait * 1000)
 
            visuals = None
            if not args.not_powerbi:
                # Normally the charts are already there after 30 seconds and this
                # returns instantly. If not, keep waiting up to --timeout.
                page.wait_for_selector(VISUAL_SELECTOR, timeout=args.timeout * 1000)
                visuals = page.locator(VISUAL_SELECTOR).count()
 
            page.screenshot(path=str(image_path))
            metadata.update({
                "success": True,
                "session_expired": False,
                "url_final": page.url,
                "page_title": page.title(),
                "visuals_found": visuals,
            })
            print(f"[{stamp}] Saved {image_path.name} ({metadata['page_title']})")
 
    except PlaywrightTimeout:
        # Save whatever is on screen so you can see what went wrong.
        try:
            page.screenshot(path=str(image_path))
        except Exception:
            pass
        metadata.update({
            "success": False,
            "url_final": page.url,
            "error": "Timed out waiting for the page or the report's visuals to load",
        })
        print(f"[{stamp}] Timed out. Check {image_path.name} to see why.")
    except Exception as e:
        metadata.update({"success": False, "error": str(e)})
        print(f"[{stamp}] Error: {e}")
 
    metadata["duration_seconds"] = round((datetime.now() - started).total_seconds(), 2)
    meta_path.write_text(json.dumps(metadata, indent=2))
    return metadata["duration_seconds"]
 
 
def run(args):
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
 
    if not PROFILE_DIR.exists():
        print("No saved login found. That's fine for public reports; "
              "run with --login first if the report needs a sign-in.")
 
    with sync_playwright() as p:
        context = open_browser(p, headless=not args.show)
        page = context.pages[0] if context.pages else context.new_page()
        print(f"Capturing {args.url} every {args.interval} seconds "
              f"({args.load_wait}s load wait). Press Ctrl+C to stop.")
 
        first_run = True
        try:
            while True:
                duration = take_screenshot(page, args, output_dir, first_run)
                first_run = False
                if args.once:
                    break
                # Keep a steady schedule by subtracting the time the capture took.
                time.sleep(max(0, args.interval - duration))
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            context.close()
 
 
if __name__ == "__main__":
    args = parse_args()
    if args.login:
        login(args.url)
    else:
        run(args)
 