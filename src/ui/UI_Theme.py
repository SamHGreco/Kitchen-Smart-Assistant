#NOTE This is how we can make it look cool haha
#Sets interface colors
BG = '#edf4f3'
CARD = '#ffffff'
INK = '#19343d'
MUTED = '#56717a'
TEAL = '#176f63'
PALE = '#dceee9'
LINE = '#cbdedb'
RED = '#9b3538'
PANEL = '#edf6f2'
SELECTED = '#c9e4dc'
PRESSED = '#bcdcd3'
FIELD = '#edf5f2'
KEYBOARD_FIELD = '#f4f8f7'
PAST_BG = '#fbe2e2'
PAST_TEXT = '#8b2626'
SOON_BG = '#fff0c8'
SOON_TEXT = '#78510d'
INVALID_BG = '#eee2fa'
INVALID_TEXT = '#69368d'
SLEEP_BG = '#000000'
SLEEP_TIME_COLOR = '#ffffff'
SLEEP_DATE_COLOR = '#cccccc'
SLEEP_HINT_COLOR = '#aaaaaa'

#Sets text sizes
FONT = 'DejaVu Sans'
APP_TITLE = 'GROCERY'
BUTTON_SIZE = 12
BUTTON_PAD_X = 14
BUTTON_PAD_Y = 10
PRODUCT_SIZE_SMALL = 21
PRODUCT_SIZE_LARGE = 25
TABLE_TEXT_SIZE = 11
TABLE_ROW_HEIGHT = 39
SLEEP_TIME_SIZE = 56
SLEEP_DATE_SIZE = 22
SLEEP_HINT_SIZE = 16
SLEEP_TIME_Y = 0.40
SLEEP_DATE_Y = 0.60
SLEEP_HINT_Y = 0.78

#Sets the reference screen size
BASE_WIDTH = 800
BASE_HEIGHT = 480
SAFETY_HEIGHT = 36

#Sets x, y, width, height
HOME_AREAS = {
    'header': (0, 0, 800, 60),
    'sensors': (16, 63, 768, 23),
    'expiry': (14, 89, 772, 30),
    'product': (14, 126, 772, 132),
    'heading': (16, 266, 768, 24),
    'table': (14, 292, 772, 134),
    'footer': (0, 428, 800, 52),
}

#Sets inventory column widths
TABLE_FRACTIONS = (0.30, 0.17, 0.19, 0.17, 0.17)

#Fits the layout to the window

def home_rects(width, height, alarm=False):
    offset = SAFETY_HEIGHT if alarm else 0
    sx = width / BASE_WIDTH
    sy = (height - offset) / BASE_HEIGHT
    return {name: (round(x*sx), offset+round(y*sy), round(w*sx), round(h*sy))
            for name, (x, y, w, h) in HOME_AREAS.items()}
