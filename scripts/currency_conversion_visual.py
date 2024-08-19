from selenium import webdriver
import easyocr

reader = easyocr.Reader(["en"], gpu=True)

def ocr_screenshot(driver, bounds=None):
    screenshot = driver.get_screenshot_as_png()
    if bounds is not None:
        image = Image.open(io.BytesIO(screenshot))
        image = image.crop(bounds)
        screenshot = io.BytesIO()
        image.save(screenshot, format="PNG")
        screenshot = screenshot.getvalue()
    res = reader.readtext(screenshot)
    return res

def move_and_click(actions, target):
    x, y = target
    actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()

def make_mean(r):
    return np.array(r[0]).mean(axis=0).astype(np.int32)

# coding: utf-8
driver = webdriver.Remote("http://efgpu:4444", options=options)
actions = webdriver.ActionChains(driver)

## LOG IN ##
driver.get("https://www.interactivebrokers.co.uk/sso/Login?RL=1&locale=en_US")
driver.find_element("id", "xyz-field-username").send_keys("elfman054")
driver.find_element("id", "xyz-field-password").send_keys("def")
driver.find_element("xpath", "//button[@type='submit']").click()

# TODO WAIT

## get to convert currency screen ##
driver.find_element("xpath", "(.//*[normalize-space(text()) and normalize-space(.)='Portfolio'])[1]/following::button[1]").click()
x, y = np.array([r for r in res if "order ticket" in r[1].lower()][0][0]).mean(axis=0).astype(np.int32)
actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()
res = reader.readtext(driver.get_screenshot_as_png())
x, y = np.array([r for r in res if "convert currency" in r[1].lower()][0][0]).mean(axis=0).astype(np.int32)
actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()

## choose currencies ##
driver.find_element("id", "cp-from-currency-dropdown").click()
    
res = reader.readtext(driver.get_screenshot_as_png())
ils_positions = [make_mean(r) for r in res if "ils" in r[1].lower()]
x, y = min(ils_positions, key=lambda s: s[0])
actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()

driver.find_element("id", "cp-tif-dropdown").click()
res = reader.readtext(driver.get_screenshot_as_png())
usds = [make_mean(r) for r in res if "usd" in r[1].lower()]
x, y = min(usds, key=lambda s: s[0])
actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()

[make_mean(r) for r in res if "balance" in r[1].lower()]
balances = [make_mean(r) for r in res if "balance" in r[1].lower()]
x, y = min(balances, key=lambda s: s[0])
actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()

## submit ##
actions.scroll_by_amount(0, 200).perform()
res = reader.readtext(driver.get_screenshot_as_png())
x, y = np.array([r for r in res if "submit" in r[1].lower()][0][0]).mean(axis=0).astype(np.int32)
actions.move_by_offset(x, y).click().move_by_offset(-x, -y).perform()
