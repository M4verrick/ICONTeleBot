import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

app = Client("attendance_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Define the path to the Excel file
EXCEL_FILE_PATH = "C:/Users/Theo/Downloads/attendance.xlsx"

# Dictionary to keep track of user states
user_states = {}


def update_excel(ids):
    if os.path.exists(EXCEL_FILE_PATH):
        df = pd.read_excel(EXCEL_FILE_PATH)
    else:
        df = pd.DataFrame(columns=["ID"])

    new_ids = pd.DataFrame(ids, columns=["ID"])
    df = pd.concat([df, new_ids], ignore_index=True)
    df.to_excel(EXCEL_FILE_PATH, index=False)


# Function to display the main menu
def show_menu(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Submit IDs", callback_data="submit_ids")],
            [InlineKeyboardButton("Help", callback_data="help")],
            [InlineKeyboardButton("Exit", callback_data="exit")],
        ]
    )
    message.reply_text("Please choose an option:", reply_markup=keyboard)


@app.on_message(filters.command("start"))
def start(client, message):
    show_menu(client, message)


@app.on_callback_query()
def handle_callback_query(client, callback_query):
    data = callback_query.data

    if data == "submit_ids":
        user_states[callback_query.from_user.id] = "submit_ids"
        callback_query.message.reply_text(
            "Please send a list of IDs (8 digits long) separated by spaces."
        )
    elif data == "help":
        callback_query.message.reply_text(
            "To submit IDs, select 'Submit IDs' and follow the instructions. For any other assistance, contact the support."
        )
    elif data == "exit":
        callback_query.message.reply_text(
            "Thank you for using the Attendance Bot. Goodbye!"
        )
    else:
        callback_query.message.reply_text(
            "Invalid option. Please use the menu to navigate."
        )


@app.on_message(
    filters.text & filters.create(lambda _, __, msg: not msg.text.startswith("/"))
)
def handle_ids(client, message):
    user_id = message.from_user.id

    if user_id in user_states and user_states[user_id] == "submit_ids":
        text = message.text
        ids = text.split()

        if all(len(id) == 8 and id.isdigit() for id in ids):
            update_excel(ids)
            message.reply_text("IDs have been recorded successfully.")
            # Reset the user's state
            user_states.pop(user_id, None)
        else:
            message.reply_text(
                "Please ensure all IDs are 8 digits long and separated by spaces."
            )
    else:
        message.reply_text("Please select 'Submit IDs' from the menu to submit IDs.")


app.run()
