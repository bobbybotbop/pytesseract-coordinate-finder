import pyautogui
import os
import sys
import pytesseract
import argparse
import time


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Set the path to the Tesseract executable (change this according to your system)
pytesseract.pytesseract.tesseract_cmd = resource_path(r"Tesseract-OCR/tesseract.exe")

os.environ['TESSDATA_PREFIX'] = resource_path(r"Tesseract-OCR/tessdata")

# Function to locate and click on the "Multiplayer" button
def locate_text(word, letter=None, debug=False):
    width = pyautogui.size()[0]
    height = pyautogui.size()[1]
    # Take a screenshot of the Minecraft window
    screenshot = pyautogui.screenshot()
    
    # Perform OCR on the screenshot to extract text
    text = pytesseract.image_to_string(screenshot)

    # Check if the text "Multiplayer" is present in the extracted text
    if word in text:
        if debug:
            print("Word located")
        # If the text is found, get the bounding box of the text        print("
              
        location = text.find(word)
        box = pytesseract.image_to_boxes(screenshot)
        if debug:
            print(box)
        # Split the string into lines
        lines = box.strip().split('\n')

        # Initialize a variable to store the word
        string = ''

        # Iterate through each line
        for line in lines:
            # Split the line by spaces
            parts = line.split()
            # Get the first part in the line
            first_part = parts[0]
            # Append the character to the word
            string += first_part
        if debug:
            print(string)

        # Check if the word 'Multiplayer' is in the formed word
        if word in string:
            if debug:
                print("Word found.")
            start_index = string.find(word)
            if debug:
                print(start_index)
            end_index = start_index + len(word) - 1
            if debug:
                print(end_index)
            word_index = list(range(start_index, end_index + 1))
            #print(f"Indices of 'Multiplayer': {word_index}")
            # Iterate through each line
            better_list = []
            for line in lines:
                # Split the line by spaces
                parts = line.split()
                better_list.append(parts)
            if debug:
                print(better_list)
                print("Done")
            my_dict = {}
            if debug:
                print(word_index)
            for i in range(len(word_index)):
                if debug:
                    print(i)
                my_list = better_list[word_index[0]+i]
                if debug:
                    print(my_list)
                # Convert numerical strings to integers
                values = [int(item) for item in my_list[1:]]
                if debug:
                    print(values)
                # Create the dictionary
                key = my_list[0]
                count = 2
                while key in my_dict:
                    key = f"{my_list[0]}({count})"
                    count += 1
                my_dict[key] = values
            multiplayer_dict = my_dict
            
            even = False
            if debug:
                print(multiplayer_dict)
                print("printed")
            if not letter:
                if debug:
                    print("No letter given")
                length = len(word)
                middle_index = length // 2
                if length % 2 == 0:
                    # If the length of the string is even, return the middle two characters
                    letter = word[middle_index - 1:middle_index + 1]
                    even = True
                else:
                    # If the length of the string is odd, return the middle character
                    letter = word[middle_index]

            def move(letter, height):
                left = multiplayer_dict[letter][0]
                bottom = multiplayer_dict[letter][1]
                right = multiplayer_dict[letter][2]
                top = multiplayer_dict[letter][3]
                if debug:
                    print(left, bottom, right, top)
                width_diff = abs(left-right)
                width = left+width_diff/2
                tall_diff = abs(bottom-top)
                tall = bottom+tall_diff/2
                coords = (width, height-tall)
                if debug:
                    print(coords)
                return coords
            if not even:
                coords = move(letter, height)
            if even:
                coords1 = move(letter[0], height)
                coords2 = move(letter[1], height)
                width1 = coords1[0]
                width2 = coords2[0]
                width_diff = abs(width1-width2)
                if debug:
                    print(width_diff)
                width = width1+width_diff/2
                if debug:
                    print(width)
                coords = (width, coords1[1])
                if debug:
                    print(coords)
            return coords
        
        else:
            print("Cannot find word")
    else:
        print("Word not located.")

def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Find a word on the screen via OCR and return/move to its coordinates."
    )
    parser.add_argument("word", nargs="?", help="Word to search for (single word, not a sentence).")
    parser.add_argument(
        "--letter",
        default=None,
        help="Optional: specific letter within the word to target.",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move the mouse to the detected coordinates (safer than clicking).",
    )
    parser.add_argument(
        "--click",
        action="store_true",
        help="Click the detected coordinates.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.5,
        help="Mouse move duration in seconds (default: 0.5).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay before moving/clicking (seconds).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print verbose OCR/box debugging output.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])

    # Backwards-compatible default behavior
    word = args.word or "Single"
    coords = locate_text(word, args.letter, debug=args.debug)

    if coords is None:
        sys.exit(1)

    print(f"coords: {coords}")

    if args.delay > 0:
        time.sleep(args.delay)

    if args.move or args.click:
        pyautogui.moveTo(coords[0], coords[1], duration=args.duration)

    if args.click:
        pyautogui.click()
