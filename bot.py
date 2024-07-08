import os
import time
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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

# Initialize Telegram bot
app = Client("attendance_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Dictionary to keep track of user states
user_states = {}

# Lock file path
lock_file_path = "sheet.lock"


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
                        f"✅ {id} {name} has successfully checked out of camp early. Please don't forget to ask your freshie to rest up!"
                        for id, name in zip(ids, names)
                    ]
                ),
            )
        elif action == "late_sign_in":
            return (
                True,
                "\n".join(
                    [
                        f"✅ {id} {name} has successfully checked into camp. Now go forth and seize the day together!"
                        for id, name in zip(ids, names)
                    ]
                ),
            )
        return (
            True,
            "✅ The following IDs and names have been recorded successfully:\n\n"
            + "\n".join([f"{id} - {name}" for id, name in zip(ids, names)]),
        )
    finally:
        release_lock()  # Release lock after updating the sheet


# Function to display the main menu
def show_menu(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 Submit IDs", callback_data="submit_ids")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
            [InlineKeyboardButton("🚪 Exit", callback_data="exit")],
        ]
    )
    message.reply_text("🔸 Please choose an option:", reply_markup=keyboard)


# Function to display the secondary menu
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


@app.on_message(filters.command("start"))
def start(client, message):
    show_menu(client, message)


@app.on_callback_query()
def handle_callback_query(client, callback_query):
    data = callback_query.data

    if data == "submit_ids":
        show_submit_menu(client, callback_query.message)
    elif data in ["registration", "late_sign_in", "early_check_out"]:
        user_states[callback_query.from_user.id] = data
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
        callback_query.message.reply_text(
            "👋 Thank you for using the Attendance Bot. Goodbye!"
        )
    elif data == "main_menu":
        show_menu(client, callback_query.message)
    else:
        callback_query.message.reply_text(
            "❌ Invalid option. Please use the menu to navigate."
        )


@app.on_message(
    filters.text & filters.create(lambda _, __, msg: not msg.text.startswith("/"))
)
def handle_ids(client, message):
    user_id = message.from_user.id

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
                    show_menu(client, message)
            else:
                loading_message.edit_text(validation_msg)
        else:
            loading_message.edit_text(
                "❌ Please ensure all IDs are 8 digits long, start with 0, and are separated by spaces for multiple IDs (ONLY FOR REGISTRATION AND LATE SIGN INS)."
            )
    else:
        message.reply_text("🔹 Please select 'Submit IDs' from the menu to submit IDs.")


app.run()
