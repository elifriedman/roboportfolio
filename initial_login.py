import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

def load_dotenv(env_path=Path(__file__).parent / ".env"):
    if not Path(env_path).exists():
        print(
            f"!!ERROR!! Please put create a file called `.env` file with your username and password"
        )
        exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            key, value = line.split("=")
            os.environ[key] = value

load_dotenv()


def login_to_ibkr(url: str = "https://localhost:5000"):
    with sync_playwright() as p:
        browser = p.chromium.launch().new_context(ignore_https_errors=True)
        page = browser.new_page()
        page.goto(url)
        page.get_by_label("Username").fill(os.environ["USERNAME"])
        page.get_by_label("Password").fill(os.environ["PASSWORD"])
        page.get_by_role("button", name="Login").locator("visible=true").click()
        expect(page.get_by_text("Open the IBKR notification on your phone")).to_be_visible()
        try:
            expect(page.locator("body")).to_have_text("Client login succeeds", timeout=36000)
            return True
        except AssertionError:
            page.screenshot(path="ibkr_login_failure.png")
        return False
