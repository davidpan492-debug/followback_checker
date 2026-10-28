
import cv2
import pytesseract


pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def recognize_text(cropped_image):
    """Enlarge an image and recognize the text inside it."""
    gray = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)

    enlarged = cv2.resize(
        gray,
        None,
        fx=2,
        fy=2,
        interpolation=cv2.INTER_CUBIC,
    )

    return pytesseract.image_to_string(
        enlarged,
        config="--psm 6",
    )
