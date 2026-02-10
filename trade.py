import sys
import time
import logging
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def _ci_button_xpath(text: str) -> str:
    """Return a case-insensitive XPath that matches button text roughly.

    Uses normalize-space + translate to perform a lowercase contains check.
    """
    return (
        "//button[contains(translate(normalize-space(.),"
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '" + text.lower() + "')]"
    )


def main(url: str = "https://sasdmwin.cc/#/transaction"):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger(__name__)

    # allow passing URL as first arg
    if len(sys.argv) > 1:
        url = sys.argv[1]

    # Try Chrome first, then fall back to Edge if Chrome isn't available
    driver = None
    chrome_error = None

    # --- Attempt Chrome ---
    try:
        service = Service(ChromeDriverManager().install())
        chrome_options = webdriver.ChromeOptions()

        # Allow user to override Chrome binary via CHROME_BIN env var
        chrome_bin = os.getenv("CHROME_BIN")
        if not chrome_bin:
            # Common Windows install locations
            possible = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for p in possible:
                if os.path.exists(p):
                    chrome_bin = p
                    break

        if chrome_bin:
            chrome_options.binary_location = chrome_bin
            logger.info("Using Chrome binary at %s", chrome_bin)
        else:
            logger.info("Chrome binary not found locally; will try Edge fallback.")

        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Chrome WebDriver started")
        except Exception as e:
            chrome_error = e
            logger.warning("Chrome driver failed to start: %s", e)

    except Exception as e:
        chrome_error = e
        logger.warning("Failed to prepare Chrome WebDriver: %s", e)

    # --- Fallback to Edge if Chrome not available ---
    if driver is None:
        try:
            logger.info("Attempting to start Edge as a fallback...")
            # Import Edge-specific pieces lazily
            from selenium.webdriver.edge.options import Options as EdgeOptions
            from selenium.webdriver.edge.service import Service as EdgeService
            from webdriver_manager.microsoft import EdgeChromiumDriverManager

            edge_driver_path = EdgeChromiumDriverManager().install()
            edge_options = EdgeOptions()

            # Allow override via EDGE_BIN env var
            edge_bin = os.getenv("EDGE_BIN")
            if not edge_bin:
                possible_edge = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                ]
                for p in possible_edge:
                    if os.path.exists(p):
                        edge_bin = p
                        break

            if edge_bin:
                edge_options.binary_location = edge_bin
                logger.info("Using Edge binary at %s", edge_bin)
            else:
                logger.info("Edge binary not found in common locations. webdriver will try default.")

            driver = webdriver.Edge(service=EdgeService(edge_driver_path), options=edge_options)
            logger.info("Edge WebDriver started")

        except Exception as e:
            logger.exception("Failed to start Edge WebDriver fallback: %s", e)
            # Raise the most helpful error: chrome_error if present, else this one
            raise chrome_error or e

    try:
        logger.info("Navigating to %s", url)
        driver.get(url)

        # Wait for page body to be present
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Try clicking 'start matching' (case-insensitive)
        try:
            xpath = _ci_button_xpath("start matching")
            start_matching_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            start_matching_button.click()
            logger.info("Clicked 'start matching'")
        except Exception as e:
            logger.warning("Could not find/click 'start matching': %s", e)

        # Loop to click 'Start trading' up to N times, stop when not found
        for i in range(10):
            try:
                xpath = _ci_button_xpath("start trading")
                start_trading_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                start_trading_button.click()
                logger.info("Clicked 'Start trading' (%d)", i + 1)
                time.sleep(2)
            except Exception as e:
                logger.info("'Start trading' not found or finished: %s", e)
                break

    finally:
        try:
            driver.quit()
            logger.info("Browser closed")
        except Exception:
            pass


if __name__ == "__main__":
    main()