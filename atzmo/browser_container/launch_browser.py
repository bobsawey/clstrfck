"""Launch a Chromium browser using Playwright for automation demos."""

from playwright.sync_api import sync_playwright


def main() -> None:
    """Open a browser window and perform basic input actions."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://example.com")

        # Demonstrate control over input devices
        page.mouse.move(100, 100)
        page.mouse.click(100, 100)
        page.keyboard.type("hello from atzmo")
        page.touchscreen.tap(150, 150)

        # Keep the browser open for manual exploration
        page.wait_for_timeout(30000)


if __name__ == "__main__":
    main()
