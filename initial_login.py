# coding: utf-8
import os
import easyocr
from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By


class ScreenShot:
    def __init__(self):
        self.reader = easyocr.Reader(["en"], gpu=False)
        self.screenshot_results = None

    def new_screenshot(self, driver, bounds=None):
        screenshot = driver.get_screenshot_as_png()
        if bounds is not None:
            image = Image.open(io.BytesIO(screenshot))
            image = image.crop(bounds)
            screenshot = io.BytesIO()
            image.save(screenshot, format="PNG")
            screenshot = screenshot.getvalue()
        res = self.reader.readtext(screenshot)
        self.screenshot_results = res
        return res

    def new_screenshot_if_needed(self, driver, bounds=None):
        if self.screenshot_results is None:
            self.new_screenshot()

    def get_text_location(self, text, format="xyxy"):
        if self.screenshot_results is None:
            raise ValueError(f"Please call reader.new_screenshot(driver) first")
        ocr_results = self.screenshot_results
        bounds = [bounds for bounds, screen_text, conf in ocr_results if text.lower() in screen_text.lower()]
        if len(bounds) == 0:
            return
        out = [(p1[0], p1[1], p2[0], p3[1]) for p1, p2, p3, p4 in bounds]
        return out


class SiteController:
    def __init__(self, url: str = "http://localhost:4444"):
        self.driver = webdriver.Remote(url, options=webdriver.FirefoxOptions())

    def get(self, url):
        self.driver.get(url)

    def move_and_click(self, x, y):
        actions = webdriver.ActionChains(self.driver)
        actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()

    def enter_text(self, text):
        actions = webdriver.ActionChains(self.driver)
        actions.send_keys(text).perform()

    def find_and_enter_text(self, element_text, input_text, screenshot, which_index: int = 0, offset: int = 4):
        self.find_and_click(element_text, screenshot, which_index, offset)
        self.enter_text(input_text)

    def find_and_click(self, element_text, screenshot, which_index: int = 0, offset: int = 4):
        screenshot.new_screenshot_if_needed(self.driver)
        result = screenshot.get_text_location(element_text)
        if result is None:
            return
        result = result[which_index]
        x1, y1, x2, y2 = result
        x, y = x1 + offset, y1 + offset
        self.move_and_click(x, y)

    def wait_for_text(self, text, timeout: int = 120):
        wait = WebDriverWait(self.driver, timeout=timeout)
        wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{text}')]")))


def login_to_ibkr(url: str = "https://ibkr:5000"):
    site = SiteController()
    site.get(url)
    screenshotter = ScreenShot()
    screenshotter.new_screenshot(site.driver)
    site.find_and_enter_text("Username", os.environ.get("USER", "elfman054"), screenshotter)
    site.find_and_enter_text("Password", os.environ["PASS"], screenshotter)
    site.find_and_click("Login", screenshotter, which_index=1)
    site.wait_for_text(text="succeeds", timeout=240)
    return site, screenshotter
