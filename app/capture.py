
import pyautogui
import cv2
import numpy as np


def capture_screen():
    """Capture the current screen as an OpenCV image."""
    screenshot = pyautogui.screenshot()
    return cv2.cvtColor(
        np.array(screenshot),
        cv2.COLOR_RGB2BGR,
    )


def select_region(image):
    """Let the user select the Instagram list area."""
    region = cv2.selectROI(
        "Select the Instagram list area",
        image,
        showCrosshair=True,
        fromCenter=False,
    )
    cv2.destroyAllWindows()

    x, y, width, height = map(int, region)

    if width == 0 or height == 0:
        return None

    return x, y, width, height


def configure_region():
    """Wait briefly, capture the screen, and select a region."""
    print("Switch to Instagram. Capturing in 5 seconds...")
    pyautogui.sleep(5)

    image = capture_screen()
    return select_region(image)
