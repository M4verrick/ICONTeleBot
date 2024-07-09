import os

import time
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bs4 import BeautifulSoup
import requests
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
json_cred = os.getenv("JSON_FILE")

# Google Sheets setup
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_name(json_cred, scope)
client = gspread.authorize(creds)
registration_sheet = client.open("Test Sheet").worksheet("Registration")
late_early_sheet = client.open("Test Sheet").worksheet("Check Out & In")
masterlist_sheet = client.open("Test Sheet").worksheet("Masterlist")
score_sheet = client.open("D3 Score Sheet (Practice)").worksheet(
    "Overall Day 3 Results"
)

# Initialize Telegram bot
app = Client("attendance_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Dictionary to keep track of user states
user_states = {}
user_access = {}

# Lock file path
lock_file_path = "sheet.lock"

clubs = [
    "SMU Al Khaleej",
    "SMU Apsara Cambodia",
    "SMU Barkada",
    "SMU Chao Vietnam",
    "SMU Connect China",
    "SMU Francophiles",
    "SMU Indian Cultural Society",
    "SMU Japanese Cultural Club",
    "SMU Komunitas Indonesia (SMUKI)",
    "SMU Myanmar Community",
    "SMU Roots",
    "SMU Truly Malaysia",
    "SMU Woori Sayi",
    "SMU Yim Siam",
]


def acquire_lock():
    """Acquire the lock by creating a lock file."""
    while os.path.exists(lock_file_path):
        time.sleep(0.1)  # Wait for the lock to be released
    open(lock_file_path, "w").close()  # Create the lock file


def release_lock():
    """Release the lock by deleting the lock file."""
    if os.path.exists(lock_file_path):
        os.remove(lock_file_path)


def validate_ids(ids):
    """Validate IDs against the Masterlist."""
    masterlist_ids = masterlist_sheet.col_values(1)
    invalid_ids = [id for id in ids if id not in masterlist_ids]
    if invalid_ids:
        return (
            False,
            f"❌ The following ID(s) is / are not valid:\n" + "\n".join(invalid_ids),
        )
    return True, ""


def get_names(ids):
    """Get names for the given IDs from the Masterlist."""
    masterlist = masterlist_sheet.get_all_records()
    id_name_map = {
        str(record["Student ID"]).zfill(8): record["Matriculated Name"]
        for record in masterlist
    }
    return [id_name_map[id] for id in ids]


def get_points(subclan):
    """Get points for the given subclan from the Score Sheet."""
    try:
        subclan = subclan.upper()  # Capitalize the subclan
        cell = score_sheet.find(subclan)
        if cell:
            points = score_sheet.cell(cell.row, 7).value  # Column G is the 7th column
            return points
        else:
            return None
    except Exception as e:
        print(f"Error fetching points: {e}")
        return None


def update_google_sheet(ids, action, additional_data=None):
    acquire_lock()  # Acquire lock before updating the sheet
    try:
        start_row = 1
        start_col = 2
        current_time = datetime.now().strftime("%d %b %I:%M %p")

        if action == "registration":
            sheet = registration_sheet
        else:
            sheet = late_early_sheet

        existing_ids = sheet.col_values(start_col)
        if action == "registration":
            already_registered_ids = [id for id in ids if id in existing_ids]
            if already_registered_ids:
                return (
                    False,
                    f"❌ The following ID(s) has / have already been registered:\n"
                    + "\n".join(already_registered_ids),
                )
            for id in ids:
                next_row = len(existing_ids) + start_row
                sheet.update_cell(next_row, start_col, id)
                existing_ids.append(id)
        elif action == "late_sign_in":
            for id in ids:
                if id in existing_ids:
                    # Update sign-in date and time for users who signed out early
                    cell = sheet.find(id)
                    row = cell.row
                    sheet.update_cell(
                        row, 17, current_time
                    )  # Column Q is the 17th column
                else:
                    # Record new late sign-ins
                    next_row = len(existing_ids) + start_row
                    sheet.update_cell(next_row, start_col, id)  # Column B
                    sheet.update_cell(next_row, 17, current_time)  # Column Q
                    existing_ids.append(id)
                # Check if the ID exists in the "Registration" sheet
                reg_existing_ids = registration_sheet.col_values(2)
                if id not in reg_existing_ids:
                    next_reg_row = len(reg_existing_ids) + start_row
                    registration_sheet.update_cell(next_reg_row, start_col, id)
        elif action == "early_check_out" and additional_data:
            for id in ids:
                if id in existing_ids:
                    # Update existing entry for early check-out
                    cell = sheet.find(id)
                    row = cell.row
                    sheet.update_cell(row, 12, current_time)  # Column L
                    sheet.update_cell(
                        row, 14, additional_data["expected_return"]
                    )  # Column N
                    sheet.update_cell(row, 15, additional_data["reason"])  # Column O
                else:
                    # Record new early check-out
                    next_row = len(existing_ids) + start_row
                    sheet.update_cell(next_row, start_col, id)  # Column B
                    sheet.update_cell(next_row, 12, current_time)  # Column L
                    sheet.update_cell(
                        next_row, 14, additional_data["expected_return"]
                    )  # Column N
                    sheet.update_cell(
                        next_row, 15, additional_data["reason"]
                    )  # Column O
                    existing_ids.append(id)
                # Check if the ID exists in the "Registration" sheet
                reg_existing_ids = registration_sheet.col_values(2)
                if id not in reg_existing_ids:
                    next_reg_row = len(reg_existing_ids) + start_row
                    registration_sheet.update_cell(next_reg_row, start_col, id)
        names = get_names(ids)
        if action == "early_check_out":
            return (
                True,
                "\n".join(
                    [
                        f"✅ {id} {name} has successfully checked out of camp early.\n"
                        for id, name in zip(ids, names)
                    ]
                )
                + "\nPlease don't forget to ask your freshie to rest up!",
            )
        elif action == "late_sign_in":
            return (
                True,
                "\n".join(
                    [
                        f"✅ {id} {name} has successfully checked into camp.\n"
                        for id, name in zip(ids, names)
                    ]
                )
                + "\nGo forth and seize the day, fellow adventurers!",
            )
        return (
            True,
            "✅ The following ID(s) and name(s) has /  have been recorded successfully:\n\n"
            + "\n".join([f"{id} - {name}" for id, name in zip(ids, names)]),
        )
    finally:
        release_lock()  # Release lock after updating the sheet


def check_user_access(username):
    """Check if the user's telegram handle exists in the Masterlist."""
    masterlist = masterlist_sheet.get_all_records()
    username = "@" + username
    # print(f"Username: {username}")
    user_record = next(
        (record for record in masterlist if record["Telegram Username"] == username),
        None,
    )
    if user_record:
        return True, user_record["Matriculated Name"], user_record["Role"]
    else:
        return False, None, None


MAX_CAPTION_LENGTH = 1024
MAX_ABOUT_US_LENGTH = 600  # Length limit for the About Us section


def get_club_info(url, club_name):
    """Scrape club information from the given URL."""
    print(url)
    try:
        about_us = "About Us section not found"
        key_events = "Key Events section not found"
        icon_image = None

        response = requests.get(url)
        soup = BeautifulSoup(response.content, "html.parser")

        # Extracting the icon URL
        icon = soup.find("img", {"loading": "lazy"})
        icon_url = icon["src"] if icon else None

        # Check if icon_url is not None before concatenating
        if icon_url:
            icon_url = "https://vivace.smu.edu.sg" + icon_url
            # Download the image if the icon URL is found
            image_response = requests.get(icon_url)
            if image_response.status_code == 200:
                icon_image = Image.open(BytesIO(image_response.content))

        # Extracting "About Us" section
        if club_name == "SMU Francophiles":
            with open("francophiles.txt", "r") as file:
                about_us = file.read().strip()
        else:
            about_us_section = soup.find(
                "h2", string=lambda text: text and "ABOUT US" in text.upper()
            )
            if about_us_section:
                parent_div = about_us_section.find_parent("div", class_="field_body")
                paragraphs = parent_div.find_all("p") if parent_div else []
                if paragraphs:
                    about_us = "\n\n".join(
                        f"📝 {p.get_text(strip=True)}" for p in paragraphs
                    )
                else:
                    # Handle case with only one paragraph
                    single_paragraph = about_us_section.find_next("p")
                    about_us = (
                        f"📝 {single_paragraph.get_text(strip=True)}"
                        if single_paragraph
                        else about_us
                    )

        # Extracting "Key Events" section
        key_events_section = soup.find(
            "h2", string=lambda text: text and "KEY EVENTS" in text.upper()
        )
        if key_events_section:
            parent_div = key_events_section.find_parent("div", class_="field_body")
            list_items = parent_div.find_all("li") if parent_div else []
            key_events_list = []
            for li in list_items:
                header = li.find("u")
                if header:
                    header_text = header.get_text(strip=True)
                    key_events_list.append(f"• {header_text}")
            key_events = "\n".join(key_events_list)
            if key_events_list:
                key_events += (
                    f"\n\nFor more information, please visit the club at {url}"
                )

        return {
            "icon_image": icon_image,
            "about_us": about_us,
            "key_events": key_events,
        }
    except Exception as e:
        print(f"Error fetching club info: {e}")
        return {
            "icon_image": None,
            "about_us": "Error fetching About Us.",
            "key_events": "Error fetching Key Events.",
        }


# Function to display the main menu
def show_main_menu(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔐 Login", callback_data="login")],
        ]
    )
    message.reply_text("🔸 Please log in to continue:", reply_markup=keyboard)


# Function to display the secondary menu
def show_menu(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 Submit IDs", callback_data="submit_ids")],
            [InlineKeyboardButton("📊 Retrieve Points", callback_data="get_points")],
            [
                InlineKeyboardButton(
                    "📚 Explore SMUICON Clubs", callback_data="explore_clubs"
                )
            ],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
            [InlineKeyboardButton("🚪 Exit", callback_data="exit")],
        ]
    )
    message.reply_text("🔸 Please choose an option:", reply_markup=keyboard)


# Function to display the submit menu
def show_submit_menu(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Registration", callback_data="registration")],
            [InlineKeyboardButton("⏰ Late Sign In", callback_data="late_sign_in")],
            [
                InlineKeyboardButton(
                    "🏃‍♂️ Early Check Out", callback_data="early_check_out"
                )
            ],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )
    message.reply_text("🔹 Please choose an action:", reply_markup=keyboard)


# Function to display the club list menu
def show_club_list(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(club, callback_data=f"club_{club.replace(' ', '_')}")]
            for club in clubs
        ]
        + [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    )
    message.reply_text("🔸 Choose Your CCA:", reply_markup=keyboard)


@app.on_message(filters.command("start"))
def start(client, message):
    show_main_menu(client, message)


# Handling the callback query
@app.on_callback_query()
def handle_callback_query(client, callback_query):
    data = callback_query.data

    # Answer the callback query to remove the highlight
    callback_query.answer()

    user_id = callback_query.from_user.id

    if data == "login":
        username = callback_query.from_user.username
        if username is None:
            callback_query.message.reply_text(
                "❌ Please set a Telegram username to use this bot."
            )
            return

        has_access, user_name, role = check_user_access(username)
        if has_access:
            if role == "Freshman":
                user_access[user_id] = "Freshman"
                callback_query.message.reply_text(
                    f"Welcome, {user_name}. As a Freshman, you can explore the SMUICON Clubs."
                )
                show_freshman_menu(client, callback_query.message)
            else:
                user_access[user_id] = "Allowed"
                callback_query.message.reply_text(
                    f"Welcome, {user_name}. Your role is {role}. Please select a corresponding action to continue."
                )
                show_menu(client, callback_query.message)
        else:
            user_access[user_id] = "Denied"
            callback_query.message.reply_text("❌ Access denied.")

    elif user_id in user_access and user_access[user_id] == "Denied":
        callback_query.message.reply_text("❌ Access denied.")
        return

    elif data == "submit_ids" and user_access.get(user_id) == "Allowed":
        show_submit_menu(client, callback_query.message)
    elif data == "get_points" and user_access.get(user_id) == "Allowed":
        callback_query.message.reply_text("Which subclan are you from?")
        user_states[user_id] = "get_points"
    elif data == "explore_clubs":
        show_club_list(client, callback_query.message)
    elif data.startswith("club_"):
        club_name = (
            data[len("club_") :].replace("_", " ").replace("(", " ").replace(")", " ")
        )
        url = f"https://vivace.smu.edu.sg/explore/icon/{'-'.join(club_name.lower().split())}"

        # Inform the user that data is being retrieved
        loading_message = callback_query.message.reply_text(
            "Retrieving data, please wait..."
        )

        info = get_club_info(url, club_name)
        response_message = (
            f"ℹ️ {club_name} Info:\n\n"
            f"**__About Us:__**\n{info['about_us']}\n\n"
            f"**__Key Events:__**\n{info['key_events']}"
        )

        if len(response_message) > MAX_CAPTION_LENGTH:
            response_message = (
                f"ℹ️ {club_name} Info:\n\n"
                f"**__About Us:__**\n{info['about_us'][:MAX_ABOUT_US_LENGTH]}\n\n"
                f"For more information, please visit the club at {url}"
            )

        if info["icon_image"]:
            # Save the image to a file
            icon_image_path = f"/mnt/data/{club_name}_logo.png"
            info["icon_image"].save(icon_image_path)

            # Send the image along with the message
            loading_message.delete()
            callback_query.message.reply_photo(
                photo=icon_image_path, caption=response_message
            )
        else:
            loading_message.edit_text(response_message)
    elif (
        data in ["registration", "late_sign_in", "early_check_out"]
        and user_access.get(user_id) == "Allowed"
    ):
        user_states[user_id] = data
        if data == "early_check_out":
            callback_query.message.reply_text(
                "🔸 Please send the details in the format: User ID + Expected Return Date and Time + Reason (Input 'Not coming back' for expected return if participant is not coming back).\n\nExample: 0XXXXXXX, 12/8 5:30 PM, Tuition "
            )
        else:
            callback_query.message.reply_text(
                f"🔹 Please send a list of IDs (8 digits long, starting with 0) separated by spaces for {data.replace('_', ' ')} of multiple IDs."
            )
    elif data == "help":
        callback_query.message.reply_text(
            "ℹ️ To submit IDs, key in /start and select 'Submit IDs'. For any other assistance, contact the HR team."
        )
    elif data == "exit":
        user_access.pop(user_id, None)
        callback_query.message.reply_text(
            "👋 Thank you for using the Attendance Bot. Goodbye!"
        )
        show_main_menu(client, callback_query.message)
    elif data == "main_menu":
        show_menu(client, callback_query.message)
    else:
        callback_query.message.reply_text(
            "❌ Invalid option. Please use the menu to navigate."
        )


# Function to display the freshman menu
def show_freshman_menu(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📚 Explore SMUICON Clubs", callback_data="explore_clubs"
                )
            ],
            [InlineKeyboardButton("🚪 Exit", callback_data="exit")],
        ]
    )
    message.reply_text("🔸 Please choose an option:", reply_markup=keyboard)


@app.on_message(
    filters.text & filters.create(lambda _, __, msg: not msg.text.startswith("/"))
)
def handle_ids(client, message):
    user_id = message.from_user.id

    if user_id in user_access and not user_access[user_id]:
        message.reply_text("❌ Access denied.")
        return

    if user_id in user_states:
        action = user_states[user_id]
        text = message.text
        ids = []
        additional_data = {}

        loading_message = message.reply_text("⏳ Loading... Please wait.")

        if action == "early_check_out":
            parts = text.split(",")
            if len(parts) != 3:
                loading_message.edit_text(
                    "❌ Please send the details in the correct format: User ID + Expected Return Date and Time + Reason.\n\nExample: 0XXXXXXX, 12/8 5:30 PM, Tuition "
                )
                return
            id = parts[0].strip()
            if len(id.split()) != 1:  # Check if there's exactly one ID
                loading_message.edit_text(
                    "❌ Please submit 1 ID at a time for early check out."
                )
                return
            expected_return = parts[1].strip()
            reason = parts[2].strip()
            if len(id) == 8 and id.isdigit() and id.startswith("0") and reason:
                ids = [id]
                additional_data = {
                    "expected_return": expected_return,
                    "reason": reason,
                }
            else:
                loading_message.edit_text(
                    "❌ Please ensure the User ID is valid and the Reason is not blank."
                )
                return
        elif action == "get_points":
            subclan = text.strip().upper()  # Capitalize subclan
            points = get_points(subclan)
            if points:
                loading_message.edit_text(f"🏆 {subclan} has {points} points.")
            else:
                loading_message.edit_text(
                    f"❌ Subclan '{subclan}' not found. Heres an example you should follow: M3 for Merliosa 3"
                )
            user_states.pop(user_id, None)
            show_menu(client, message)  # Prompt user for next action
            return
        else:
            ids = text.split()

        if all(len(id) == 8 and id.isdigit() and id.startswith("0") for id in ids):
            valid, validation_msg = validate_ids(ids)
            if valid:
                success, msg = update_google_sheet(ids, action, additional_data)
                loading_message.edit_text(msg)
                if success:
                    # Reset the user's state
                    user_states.pop(user_id, None)
                    # Show the main menu again
                    show_submit_menu(client, message)
            else:
                loading_message.edit_text(validation_msg)
        else:
            loading_message.edit_text(
                "❌ Please ensure all IDs are 8 digits long, start with 0, and are separated by spaces for multiple IDs (ONLY FOR REGISTRATION AND LATE SIGN INS)."
            )
    else:
        message.reply_text("🔹 Please select 'Submit IDs' from the menu to submit IDs.")


app.run()
