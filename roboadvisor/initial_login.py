from playwright.sync_api import sync_playwright, expect


def login_to_ibkr(username: str, password: str, url: str = "https://localhost:5000"):
    with sync_playwright() as p:
        browser = p.chromium.launch().new_context(ignore_https_errors=True)
        page = browser.new_page()
        page.goto(url)
        page.get_by_label("Username").fill(username)
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Login").locator("visible=true").click()
        expect(page.get_by_text("Open the IBKR notification on your phone")).to_be_visible()
        try:
            expect(page.locator("body")).to_have_text("Client login succeeds", timeout=36000)
            return True
        except AssertionError:
            page.screenshot(path="ibkr_login_failure.png")
        return False
