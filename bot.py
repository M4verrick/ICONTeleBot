import os
import time
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from bs4 import BeautifulSoup
import requests
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import emoji

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
registration_sheet = client.open("[Day 1 MASTERLIST] Registration List").worksheet(
    "Registration"
)
late_early_sheet = client.open("[Day 1 MASTERLIST] Registration List").worksheet(
    "Check Out & In"
)
masterlist_sheet = client.open("[Day 1 MASTERLIST] Registration List").worksheet("Masterlist")
score_sheet = client.open("[ACTUAL CAMP] Score Sheet").worksheet("Final Points")
contact_sheet = client.open("Important Contacts")
venue_sheet = client.open(
    "Facilities Booking for ICON Camp 2024"
).worksheet("Updated 30 July")
total_strength_sheet = client.open("[Day 1 MASTERLIST] Registration List").worksheet(
    "Camp Strength"
)
bidding_sheet = client.open("[ACTUAL CAMP] Score Sheet").worksheet("Overall Day 3 Results")

# Constants
MAX_CAPTION_LENGTH = 1024
MAX_ABOUT_US_LENGTH = 600  # Length limit for the About Us section
BOOKINGS_PER_PAGE = 5

# Initialize Telegram bot
app = Client("icon_camp_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Dictionary to keep track of user states
user_states = {}
# Dictionary to keep track of user sessions
user_sessions = {}

# Lock file path
lock_file_path = "sheet.lock"

# List of clubs
clubs = [
    "🇸🇬 SMU Roots",
    "🇵🇭 SMU Barkada", 
    "🇹🇭 SMU Yim Siam",
    "🇰🇷 SMU Woori Sayi",
    "🇦🇪 SMU Al Khaleej",
    "🇫🇷 SMU Francophiles",
    "🇻🇳 SMU Chao Vietnam",
    "🇨🇳 SMU Connect China",
    "🇲🇾 SMU Truly Malaysia",
    "🇰🇭 SMU Apsara Cambodia",
    "🇲🇲 SMU Myanmar Community",
    "🇯🇵 SMU Japanese Cultural Club",
    "🇮🇳 SMU Indian Cultural Society",
    "🇮🇩 SMU Komunitas Indonesia (SMUKI)",
]

# Essential Links
essential_links = [
    ("Student Perks", "https://t.me/joinchat/TxqQuSdtT1fWlFFt"),
    ("SMUSA", "https://t.me/smusasg"),
    ("Ask SMU", "https://t.me/ask_smu"),
    ("SMU ICON", "https://t.me/smuicon"),
    ("SMU SMUX", "https://t.me/smuxplorationcrew"),
    ("SMU SSU", "https://t.me/SMUSportsUnion"),
    ("SMU SICS", "https://t.me/smu_sics"),
    ("SMU ACF", "https://t.me/smuacf"),   
    ("Sumo Cum Laude", "https://t.me/sumocumlaude"),
    ("SMU Success Plus", "https://t.me/smusuccessplus"),
    ("SMU New Buffet Clearers", "https://t.me/+R-PNbWWJqXxhYzU9"),
]

# ThreadPoolExecutor for handling concurrent requests
executor = ThreadPoolExecutor(max_workers=10)

# Utility Functions
def acquire_lock():
    """Acquire the lock by creating a lock file."""
    while os.path.exists(lock_file_path):
        time.sleep(0.1)  # Wait for the lock to be released
    open(lock_file_path, "w").close()  # Create the lock file

def release_lock():
    """Release the lock by deleting the lock file."""
    if os.path.exists(lock_file_path):
        os.remove(lock_file_path)

# User Validation
def validate_ids(ids):
    """Validate IDs against the Masterlist."""
    masterlist_ids = masterlist_sheet.col_values(1)
    invalid_ids = [id for id in ids if id not in masterlist_ids]
    if invalid_ids:
        return False, f"❌ The following ID(s) is / are not valid:\n" + "\n".join(invalid_ids) + "\nPlease re-submit ID(s) again."
    return True, ""

def check_user_access(username):
    """Check if the user's telegram handle exists in the Masterlist."""
    # print(username)
    expected_headers = ["Student ID", "Matriculated Name", "Telegram Username", "Role", "SUBCLAN"]
    masterlist = masterlist_sheet.get_all_records(expected_headers=expected_headers)
    username = "@" + username
    user_record = next(
        (record for record in masterlist if record["Telegram Username"] == username), None)

    if user_record:
        matriculated_name = user_record.get("Matriculated Name")
        role = user_record.get("Role")
        subclan = user_record.get("SUBCLAN")
        return True, matriculated_name, role, subclan
    else:
        return False, None, None, None

def get_names(ids):
    """Get names for the given IDs from the Masterlist."""
    expected_headers = ["Student ID", "Matriculated Name", "Telegram Username", "Role"]
    masterlist = masterlist_sheet.get_all_records(expected_headers=expected_headers)
    id_name_map = {str(record["Student ID"]).zfill(8): record["Matriculated Name"] for record in masterlist}
    return [id_name_map[id] for id in ids]

def handle_allowed_user(client, callback_query, data):
    session_data = user_sessions[callback_query.from_user.id]
    # print(f"USER SESSIONS: {user_sessions}")
    role = session_data.get("role")
    subclan = session_data.get("subclan")
    user_id = callback_query.from_user.id
    # print(user_id)
    # print(user_sessions)
    if user_id not in user_sessions:
        callback_query.message.reply_text("❌ Access denied. Please login by pressing /start to continue.")
        return

    handlers = {
        "submit_ids": lambda: show_submit_menu(client, callback_query.message, role),
        "get_overall_subclan_points": lambda: handle_get_overall_points(client, callback_query, role, subclan),
        "get_d3_currency": lambda: handle_get_d3_currency(client, callback_query, role, subclan),
        "points_matters": lambda: show_points_matters(client, callback_query.message),
        "explore_clubs": lambda: show_club_list(client, callback_query.message),
        "contact_person": lambda: show_positions(client, callback_query.message),
        "view_links": lambda: show_essential_links(client, callback_query.message),
        "view_bookings": lambda: show_oc_booking_months(client, callback_query.message, get_oc_bookings()),
        "show_strength": lambda: handle_show_strength(callback_query),
        "view_campus_map": lambda: handle_view_campus_map(callback_query),
        "fort_siloso": lambda: handle_sentosa_location_request(callback_query, "fort_siloso"),
        "madame_tussauds": lambda: handle_sentosa_location_request(callback_query, "madame_tussauds"),
        "sentosa_guide": lambda: show_sentosa_guide(client, callback_query.message),
        "fort_siloso_map": lambda: handle_fort_siloso_map_request(client, callback_query),
        "soss_cis": lambda: handle_sentosa_location_request(callback_query, "soss_cis"),
        "food_in_smu": lambda: show_food_in_smu(client, callback_query.message),
        "help": lambda: callback_query.message.reply_text("ℹ️ Key in /start to get started."),
        "begin_adventure": lambda: handle_begin_adventure(callback_query),
        "exit": lambda: handle_logout(callback_query),
        "main_menu": lambda: show_menu_and_clear_state(client, callback_query.message, user_id),
        "view_schedule": lambda: handle_get_schedule(client, callback_query, role, subclan),
        "get_schedule_day 1": lambda: handle_view_day_schedule(callback_query, "Day 1"),
        "get_schedule_day 3": lambda: handle_view_day_schedule(callback_query, "Day 3"),
        "view_booklets": lambda: handle_view_booklets(callback_query),  # New handler for viewing booklets
    }

    # Dynamic handlers for data with prefixes
    dynamic_handlers = {
        "m_": lambda d: handle_view_dates(callback_query, d),
        "d_": lambda d: handle_view_facility_types(callback_query, d),
        "f_": lambda d: handle_view_facility_type(callback_query, d),
        "fp_": lambda d: handle_view_facility_type(callback_query, d),
        "position_": lambda d: handle_view_contact(callback_query, d),
        "club_": lambda d: handle_view_club(callback_query, d),
    }

    if data in handlers:
        handlers[data]()
    else:
        for prefix, handler in dynamic_handlers.items():
            if data.startswith(prefix):
                handler(data)
                return

        if data in ["registration", "late_sign_in", "early_check_out"]:
            handle_submit_action(callback_query, data)
        else:
            callback_query.message.reply_text("❌ Invalid option. Press /start to log in.")

# User Login and Logout
def handle_login(callback_query, user_username):
    username = user_username

    if username is None:
        callback_query.message.reply_text("❌ Please set a Telegram username to use this bot.")
        return

    has_access, user_name, role, subclan = check_user_access(username)
    if has_access:
        user_sessions[callback_query.from_user.id] = {
            "username": username,
            "role": role,
            "subclan": subclan,
        }
        with open("misc/storyline.txt", "r", encoding="utf-8") as file:
            storyline = file.read().strip()

        callback_query.message.reply_text(
            f"Greetings, {user_name}.\n\n{storyline}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔥Begin Your Adventure Now🔥",
                            callback_data="begin_adventure",
                        )
                    ]
                ]
            ),
        )
    else:
        callback_query.message.reply_text("❌ Access denied. Please login by pressing /start to continue.")
        return

def handle_begin_adventure(callback_query):
    user_username = callback_query.from_user.username
    user_id = callback_query.from_user.id
    _, user_name, _, _ = check_user_access(user_username)
    session_data = user_sessions[user_id]
    role = session_data.get("role")
    subclan = session_data.get("subclan")

    if role == "Freshmen":
        callback_query.message.reply_text(
            f"Welcome to the Island Of Chronosia, Adventurer {user_name}! We hope that these 3 days of ICON Camp will kick start your University life at SMU :D"
        )
    else:
        callback_query.message.reply_text(
            f"Welcome back, {user_name}. Your role in ICON CAMP 2024 is {role}.\nPlease select a corresponding action to continue."
        )
    show_menu(app, callback_query.message)

def handle_logout(callback_query):
    user_id = callback_query.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    callback_query.message.reply_text("👋 You have been logged out. Have a good day!")
    show_login_menu(client, callback_query.message)

# Schedule
def parse_schedule_d1(file_path):
    with open(file_path, 'r', encoding = 'utf-8') as file:
        data = file.read()
    
    subclan_schedules = {}
    subclan_name = None
    schedule = ""
    
    lines = data.splitlines()
    for line in lines:
        if line.startswith("Schedule for "):
            if subclan_name:
                subclan_schedules[subclan_name] = schedule.strip()
            subclan_name = line.replace("Schedule for ", "").strip(":")
            schedule = ""
        elif line.strip():
            schedule += line + "\n"
            if not line.startswith("*"):
                schedule += "\n"
    
    if subclan_name:
        subclan_schedules[subclan_name] = schedule.strip()
    
    return subclan_schedules

def parse_schedule_d3(file_path):
    with open(file_path, 'r', encoding = 'utf-8') as file:
        data = file.read()
    
    subclan_schedules = {}
    subclan_name = None
    schedule = ""
    
    lines = data.splitlines()
    for line in lines:
        if line.startswith("Schedule for "):
            if subclan_name:
                subclan_schedules[subclan_name] = schedule.strip()
            subclan_name = line.replace("Schedule for ", "").strip(":")
            schedule = ""
        elif line.strip():
            schedule += line + "\n"
            if not line.startswith("*"):
                schedule += "\n"
    
    if subclan_name:
        subclan_schedules[subclan_name] = schedule.strip()
    
    return subclan_schedules

file_path_d1 = 'movement/all_subclans_schedule_d1.txt'
schedule_d1 = parse_schedule_d1(file_path_d1)

file_path_d3 = 'movement/all_subclans_schedule_d3.txt'
schedule_d3 = parse_schedule_d3(file_path_d3)

def handle_get_schedule(client, callback_query, role, subclan):
    user_id = callback_query.from_user.id
    # Display the submenu for selecting the day
    callback_query.message.reply_text(
        "Please select the day for the schedule:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏳ Day 1️⃣", callback_data="get_schedule_day 1")],
                [InlineKeyboardButton("⏳ Day 3️⃣", callback_data="get_schedule_day 3")],
                [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
            ]
        )
    )

# Updated function to handle retrieving the schedule based on the role and day
def handle_get_schedule_message(loading_message, role, subclan, text, day):
    subclan = subclan if role == "Facilitator" else text.strip().upper()
    subclan_schedule = None

    if day == "Day 1":
        subclan_schedule = schedule_d1.get(subclan)
    elif day == "Day 3":
        subclan_schedule = schedule_d3.get(subclan)

    if not subclan_schedule:
        loading_message.edit_text(
            "❌ Subclan not found. Please enter a valid subclan.",
        )
        return

    schedule_message = f"Schedule for {subclan}:\n\n"
    schedule_message += f"**{day.upper()} STATION GAMES**\n{subclan_schedule}\n\n"

    # Add the "Back to Menu" button
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back to Schedule Menu", callback_data="view_schedule")]]
    )
    
    loading_message.edit_text(schedule_message.strip(), reply_markup=reply_markup)

def handle_view_day_schedule(callback_query, day):

    user_id = callback_query.from_user.id
    user_session = user_sessions.get(user_id)
    if not user_session:
        callback_query.message.reply_text("❌ Access denied. Please login by pressing /start to continue.")
        return
    
    role = user_session.get("role")
    subclan = user_session.get("subclan")

    if role == "Facilitator":
        loading_message = callback_query.message.reply_text("Retrieving schedule, please wait...")
        handle_get_schedule_message(loading_message, role, subclan, None, day)
    else:
        callback_query.message.reply_text("Which subclan schedule do you want to check?")
        user_states[user_id] = f"get_schedule_{day.lower()}"

# Get points
def get_points(subclan):
    """Get points for the given subclan from the Score Sheet."""
    try:
        subclan = subclan.upper()  # Capitalize the subclan
        cell = score_sheet.find(subclan)
        if cell:
            points = score_sheet.cell(cell.row, 10).value  # Column J
            return points
        else:
            return None
    except Exception as e:
        print(f"Error fetching points: {e}")
        return None

def handle_get_overall_subclan_points(loading_message, role, subclan, text):
    subclan_to_check = subclan if role == "Facilitator" else text.strip().upper()
    points = get_points(subclan_to_check)
    
    if points:
        message_text = f"🏆 {subclan_to_check} has {points} points."
    else:
        message_text = f"❌ Subclan '{subclan_to_check}' not found. Please key in a proper subclan again."
    
    reply_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 Back to Points Menu", callback_data="points_matters")]
        ]
    )
    loading_message.edit_text(message_text, reply_markup=reply_markup)

def handle_get_overall_points(client, callback_query, role, subclan):
    if role == "Facilitator":
        loading_message = callback_query.message.reply_text("Retrieving points, please wait...")
        handle_get_overall_subclan_points(loading_message, role, subclan, None)
    else:
        callback_query.message.reply_text("Which subclan do you want to check?")
        user_states[callback_query.from_user.id] = "get_overall_subclan_points"

# Get D3 Currency
def get_d3_currency(subclan):
    """Get points for the given subclan from the Score Sheet."""
    try:
        subclan = subclan.upper()  # Capitalize the subclan
        cell = bidding_sheet.find(subclan)
        if cell:
            points = bidding_sheet.cell(cell.row, 8).value  # Column H
            return points
        else:
            return None
    except Exception as e:
        print(f"Error fetching points: {e}")
        return None

def handle_get_d3_currency_points(loading_message, role, subclan, text):
    subclan_to_check = subclan if role == "Facilitator" else text.strip().upper()
    points = get_d3_currency(subclan_to_check)
    
    if points:
        message_text = f"🏆 {subclan_to_check} has {points} Day 3 credits."
    else:
        message_text = f"❌ Subclan '{subclan_to_check}' not found. Please key in a proper subclan again."
    
    reply_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 Back to Points Menu", callback_data="points_matters")]
        ]
    )
    loading_message.edit_text(message_text, reply_markup=reply_markup)

def handle_get_d3_currency(client, callback_query, role, subclan):
    if role == "Facilitator":
        loading_message = callback_query.message.reply_text("Retrieving points, please wait...")
        handle_get_d3_currency_points(loading_message, role, subclan, None)
    else:
        callback_query.message.reply_text("Which subclan do you want to check?")
        user_states[callback_query.from_user.id] = "get_d3_currency"


# Bookings
def get_oc_bookings():
    """Fetch and return confirmed bookings grouped by month, date, and facility type."""
    all_values = venue_sheet.get_all_values()

    headers = all_values[0]
    data_rows = all_values[1:]

    col_indices = {header: index for index, header in enumerate(headers)}

    facility_col = col_indices["Facility"]
    facility_type_col = col_indices["Facility Type"]
    booking_date_col = col_indices["Booking Date"]
    booking_start_time_col = col_indices["Booking Start Time"]
    booking_end_time_col = col_indices["Booking End Time"]
    booking_status_col = col_indices["BookingStatus"]
    booking_ref_col = col_indices["Booking Reference Number"]

    bookings_by_month = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in data_rows:
        if row[booking_status_col].lower() == "confirmed":
            booking_date = row[booking_date_col]
            month = datetime.strptime(booking_date, "%d-%b-%Y").strftime("%Y-%m")
            date = datetime.strptime(booking_date, "%d-%b-%Y").strftime("%d-%b-%Y")
            facility_type = row[facility_type_col]
            bookings_by_month[month][date][facility_type].append(
                {
                    "Facility": row[facility_col],
                    "Booking Date": booking_date,
                    "Booking Start Time": row[booking_start_time_col],
                    "Booking End Time": row[booking_end_time_col],
                    "Booking Reference Number": row[booking_ref_col],
                }
            )

    for month in bookings_by_month:
        for date in bookings_by_month[month]:
            for facility_type in bookings_by_month[month][date]:
                bookings_by_month[month][date][facility_type].sort(
                    key=lambda x: datetime.strptime(x["Booking Date"], "%d-%b-%Y")
                )

    return bookings_by_month

def show_oc_booking_months(client, message, bookings_by_month):
    """Display months as buttons for the user's confirmed bookings."""
    unique_months = sorted(bookings_by_month.keys())
    buttons = [
        [InlineKeyboardButton(month, callback_data=f"m_{month}")] for month in unique_months
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    )

    reply_markup = InlineKeyboardMarkup(buttons)
    message.reply_text("📅 **Your Booking Months** 📅", reply_markup=reply_markup)

def show_oc_booking_dates(client, message, month, bookings_by_month):
    """Display dates as buttons for the user's confirmed bookings within the selected month."""
    unique_dates = sorted(bookings_by_month[month].keys())
    buttons = [
        [InlineKeyboardButton(date, callback_data=f"d_{month}_{date.replace(' ', '_')}")]
        for date in unique_dates
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Back to Months", callback_data="view_bookings")]
    )

    reply_markup = InlineKeyboardMarkup(buttons)
    message.reply_text(f"📅 **Booking Dates for {month}** 📅", reply_markup=reply_markup)

def show_oc_booking_facility_types(client, message, month, date, bookings_by_month):
    """Display facility types as buttons for the user's confirmed bookings within the selected date."""
    unique_facility_types = sorted(bookings_by_month[month][date].keys())
    buttons = [
        [
            InlineKeyboardButton(
                facility_type,
                callback_data=f"f_{month}_{date.replace(' ', '_')}_{facility_type}",
            )
        ]
        for facility_type in unique_facility_types
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Back to Dates", callback_data=f"m_{month}")]
    )
    reply_markup = InlineKeyboardMarkup(buttons)
    message.reply_text(f"📅 **Facility Types for {date}** 📅", reply_markup=reply_markup)

def show_bookings_for_facility_type(client, message, month, date, facility_type, bookings_by_month, page=1):
    """Display the bookings for the selected facility type with pagination."""
    bookings = bookings_by_month.get(month, {}).get(date, {}).get(facility_type, [])
    if not bookings:
        message.reply_text(f"No bookings found for {facility_type} on {date}.")
        return

    start_index = (page - 1) * BOOKINGS_PER_PAGE
    end_index = start_index + BOOKINGS_PER_PAGE
    paginated_bookings = bookings[start_index:end_index]

    message_text = f"📅 **Bookings for {facility_type} on {date}** 📅\n\n"
    for booking in paginated_bookings:
        message_text += (
            f"**Facility**: {booking['Facility']}\n"
            f"**Date**: {booking['Booking Date']}\n"
            f"**Start Time**: {booking['Booking Start Time']}\n"
            f"**End Time**: {booking['Booking End Time']}\n"
            f"**Booking Reference Number**: {booking['Booking Reference Number']}\n"
            "-----------------------------\n"
        )

    buttons = []
    if page > 1:
        buttons.append(
            InlineKeyboardButton(
                "⬅️ Previous",
                callback_data=f"fp_{month}_{date.replace(' ', '_')}_{facility_type}_{page - 1}",
            )
        )
    if end_index < len(bookings):
        buttons.append(
            InlineKeyboardButton(
                "➡️ Next",
                callback_data=f"fp_{month}_{date.replace(' ', '_')}_{facility_type}_{page + 1}",
            )
        )
    buttons.append(
        InlineKeyboardButton(
            "🔙 Back to Facility Types",
            callback_data=f"d_{month}_{date.replace(' ', '_')}",
        )
    )

    reply_markup = InlineKeyboardMarkup([buttons])
    message.reply_text(message_text, reply_markup=reply_markup)

def handle_view_dates(callback_query, data):
    month = data[len("m_") :]
    bookings_by_month = get_oc_bookings()
    show_oc_booking_dates(app, callback_query.message, month, bookings_by_month)

def handle_view_facility_types(callback_query, data):
    parts = data.split("_")
    month = parts[1]
    date = parts[2].replace("_", " ")
    bookings_by_month = get_oc_bookings()
    show_oc_booking_facility_types(app, callback_query.message, month, date, bookings_by_month)

def handle_view_facility_type(callback_query, data):
    parts = data.split("_")
    month = parts[1]
    date = parts[2].replace("_", " ")
    facility_type = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 1
    bookings_by_month = get_oc_bookings()
    show_bookings_for_facility_type(app, callback_query.message, month, date, facility_type, bookings_by_month, page)

# Faci and Freshman Booklet
def handle_view_booklets(callback_query):
    user_id = callback_query.from_user.id
    user_session = user_sessions.get(user_id)
    role = user_session.get("role")
    
    # File paths for booklets
    facilitator_booklet_path = "booklet/Official ICON FACILITATORS HANDBOOK.pdf"
    Freshmen_booklet_path = "booklet/Official ICON FRESHIE HANDBOOK.pdf"

    if role == "Facilitator":
        send_booklet(callback_query, facilitator_booklet_path, "Facilitator Handbook.pdf")
    elif role == "Freshmen":
        send_booklet(callback_query, Freshmen_booklet_path, "Freshman Handbook.pdf")
    else:
        callback_query.message.reply_text("❌ You do not have access to view booklets.")
    
def send_booklet(callback_query, booklet_path, new_file_name):
    loading_message = callback_query.message.reply_text("📖 Retrieving booklet, please wait...")
    try:
        with open(booklet_path, "rb") as pdf_file:
            keyboard = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
                ]
            )
            loading_message.delete()
            callback_query.message.reply_document(pdf_file, file_name=new_file_name,reply_markup=keyboard )
    except FileNotFoundError:
        loading_message.edit_text("❌ Booklet not found.")


# Club Information Functions
def get_club_info(url, club_name):
    """Scrape club information from the given URL."""
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
            with open("misc/francophiles.txt", "r") as file:
                about_us = file.read().strip()
        else:
            about_us_section = soup.find(
                "h2", string=lambda text: text and "ABOUT US" in text.upper()
            )
            if about_us_section:
                parent_div = about_us_section.find_parent("div", class_="field_body")
                paragraphs = parent_div.find_all("p") if parent_div else []
                if paragraphs:
                    about_us = "\n\n".join(f"📝 {p.get_text(strip=True)}" for p in paragraphs)
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
                key_events += f"\n\nFor more information, please visit the club at {url}"

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

def handle_view_club(callback_query, data):

    club_name = (
        data[len("club_") :].replace("_", " ").replace("(", " ").replace(")", " ")
    )
    club_name = emoji.replace_emoji(club_name,replace ='')
    # print(f"club name: {club_name}")
    url = f"https://vivace.smu.edu.sg/explore/icon/{'-'.join(club_name.lower().split())}"

    # Inform the user that data is being retrieved
    loading_message = callback_query.message.reply_text("Retrieving data, please wait...")

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

    buttons = [[InlineKeyboardButton("🔙 Back to Club Menu", callback_data="explore_clubs")]]
    reply_markup = InlineKeyboardMarkup(buttons)

    if info["icon_image"]:
        # Save the image to a file
        icon_image_path = f"clubs/{club_name}_logo.png"
        info["icon_image"].save(icon_image_path)

        # Send the image along with the message
        loading_message.delete()
        callback_query.message.reply_photo(
            photo=icon_image_path, caption=response_message, reply_markup=reply_markup
        )
    else:
        loading_message.edit_text(response_message)
        callback_query.message.reply_text(response_message, reply_markup=reply_markup)

def show_club_list(client, message):
    """Display the club list menu."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(club, callback_data=f"club_{club.replace(' ', '_')}")]
            for club in clubs
        ]
        + [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    )
    message.reply_text("❤️ **Select A Club To View**", reply_markup=keyboard)

# Attendance Matters
def handle_early_check_out(loading_message, text):
    parts = text.split(",")
    if len(parts) != 3:
        loading_message.edit_text(
            "❌ Please send the details in the correct format: \n**User ID, Expected Return Date and Time, Reason.**\n\nExample: 0XXXXXXX, 12/8 5:30 PM, Tuition."
        )
        return

    id, expected_return, reason = map(str.strip, parts)
    if not is_valid_id(id):
        loading_message.edit_text("❌ Please submit a valid ID for early check out.")
        return

    additional_data = {
        "expected_return": expected_return,
        "reason": reason,
    }
    update_google_sheet_for_action(loading_message, [id], "early_check_out", additional_data)

def handle_default_action(loading_message, text, action, role):
    ids = text.split()
    if not all(is_valid_id(id) for id in ids):
        loading_message.edit_text("❌ Please ensure all IDs are 8 digits long, start with 0, and are separated by spaces for multiple IDs.")
        return

    update_google_sheet_for_action(loading_message, ids, action)

def is_valid_id(id):
    return len(id) == 8 and id.isdigit() and id.startswith("0")

def update_google_sheet_for_action(loading_message, ids, action, additional_data=None):
    valid, validation_msg = validate_ids(ids)
    if not valid:
        loading_message.edit_text(validation_msg)
        return

    future = executor.submit(update_google_sheet, ids, action, additional_data)
    success, msg = future.result()
    loading_message.edit_text(msg)

    if success:
        user_states.pop(loading_message.chat.id, None)  # Remove state
        show_submit_menu(app, loading_message, user_sessions.get(loading_message.chat.id).get("role"))

# Google Sheet Update Functions
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
            "✅ The following ID(s) and name(s) has / have been recorded successfully:\n\n"
            + "\n".join([f"{id} - {name}" for id, name in zip(ids, names)]),
        )
    finally:
        release_lock()  # Release lock after updating the sheet


# Essential Links
def show_essential_links(client, message):
    """Display the list of essential links."""
    links_message = "🔗 **Essential Links** 🔗\n\n"
    for name, url in essential_links:
        links_message += f"[{name}]({url})\n"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    )

    message.reply_text(links_message, reply_markup=keyboard, disable_web_page_preview=True)

# Clan Menu
def show_clans_menu(client, message):
    """Display the clans menu."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Merliosa", callback_data="clan_merliosa")],
            [InlineKeyboardButton("Durio", callback_data="clan_durio")],
            [InlineKeyboardButton("Orchidium", callback_data="clan_orchidium")],
            [InlineKeyboardButton("Quilapius", callback_data="clan_quilapius")],
            [InlineKeyboardButton("🔙 Back to Login Menu", callback_data="login_menu")],
        ]
    )
    message.reply_text("🔸 Select A Clan To View:", reply_markup=keyboard)

def handle_clan_selection(callback_query, clan):
    """Handle the selection of a clan and send the corresponding PNG."""
    png_files = {
        "merliosa": "clan/merliosa.png",
        "durio": "clan/durio.png",
        "orchidium": "clan/orchidium.png",
        "quilapius": "clan/quilapius.png",
    }
    png_file = png_files.get(clan)

    if png_file and os.path.exists(png_file):
        callback_query.message.reply_photo(
            photo=open(png_file, "rb"),
            caption=f"Welcome to Clan {clan.capitalize()}!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back to Clans", callback_data="clans")]]
            ),
        )
    else:
        callback_query.message.reply_text(
            "❌ Error 404 not found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back to Clans", callback_data="clans")]]
            ),
        )

# Menu Display Functions
def show_login_menu(client, message):
    """Display the main menu."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔐 Login", callback_data="login")],
            [InlineKeyboardButton("🔰 Clans", callback_data="clans")],
        ]
    )
    message.reply_text("🔸 Please log in to continue:", reply_markup=keyboard)

def clear_user_state(user_id):
    """Clear the user state."""
    if user_id in user_states:
        del user_states[user_id]

def show_menu_and_clear_state(client, message, user_id):
    clear_user_state(user_id)
    show_menu(client, message)


def show_menu(client, message):
    # print(message)
    user_id = message.chat.id
    # print(f"USER ID: {user_id}")
    user_session = user_sessions.get(user_id)
    # print("IM showing menu!!!")
    if not user_session:
        message.reply_text("❌ Access denied. Please login by pressing /start to continue.")
        return
    role = user_session.get("role")
    # subclan = user_session.get("subclan")
    keyboard = []

    # Add OC specific options
    if role in ["OC"]:
        keyboard.append(
            [
                    InlineKeyboardButton("📚 View Bookings", callback_data="view_bookings")
            ]
        )
        
    if role in ["OC", "Game Master"]:
        keyboard.append(
            [
                    InlineKeyboardButton("💪 Camp Strength", callback_data="show_strength")
            ]
        )

    # Add attendance tracking for Facilitator, Clanhead, OC roles
    if role in ["Facilitator", "Clan Head", "OC", "Game Master"]:
        keyboard.append([InlineKeyboardButton("✍️ Attendance", callback_data="submit_ids")])
    if role in ["Facilitator", "Freshmen"]:
        keyboard.append([InlineKeyboardButton("📖 Booklet", callback_data="view_booklets")])  # New option for Booklets
    if role in ["Facilitator", "OC", "Clan Head"]:
        keyboard.append(
            [
                InlineKeyboardButton("👾 Points Matters", callback_data="points_matters"),
                InlineKeyboardButton("📅 View Schedule", callback_data="view_schedule"),
            ],
        )

    # Add common options for all roles
    common_options = [
        [InlineKeyboardButton("📞 Important Contacts", callback_data="contact_person")],
        [InlineKeyboardButton("☀️ Sentosa Guide", callback_data="sentosa_guide")],
        [InlineKeyboardButton("❤️ SMU ICON Clubs", callback_data="explore_clubs"),
         InlineKeyboardButton("🔗 Essential Links", callback_data="view_links")],
        [InlineKeyboardButton("🍽 Food in SMU", callback_data="food_in_smu"),
         InlineKeyboardButton("🗺️ Campus Map", callback_data="view_campus_map")],  # Added Food in SMU option
        [InlineKeyboardButton("🚪Log Out", callback_data="exit")],
    ]

    keyboard.extend(common_options)

    reply_markup = InlineKeyboardMarkup(keyboard)
    message.reply_text(" 🤩 **Please Choose An Action:**", reply_markup=reply_markup)

def show_points_matters(client, message):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📊 Retrieve Day 3 Credits",
                    callback_data="get_d3_currency",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Retrieve Cumulative Subclan Points",
                    callback_data="get_overall_subclan_points",
                )
            ],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )
    message.reply_text("**👾 Points Matters**", reply_markup=keyboard)

def show_submit_menu(client, message, role):
    """Display the submit menu."""
    keyboard = []

    if role in ["OC", "Game Master"]:
        keyboard.append([InlineKeyboardButton("📝 Registration", callback_data="registration")])

    keyboard.extend(
        [
            [InlineKeyboardButton("⏰ Late Sign In", callback_data="late_sign_in")],
            [InlineKeyboardButton("🏃‍♂️ Early Check Out", callback_data="early_check_out")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )

    reply_markup = InlineKeyboardMarkup(keyboard)
    message.reply_text("✍️ **Please Choose An Action:**", reply_markup=reply_markup)

# Guides
def show_sentosa_guide(client, message):
    """Display the Sentosa Guide menu."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗺️ Fort Siloso Map", callback_data="fort_siloso_map")],
            [
                InlineKeyboardButton(
                    "📍Directions to Fort Siloso", callback_data="fort_siloso"
                )
            ],
            [
                InlineKeyboardButton(
                    "📍 Directions to Madame Tussauds", callback_data="madame_tussauds"
                )
            ],
            [InlineKeyboardButton("📍 Directions to SOSS/CIS", callback_data="soss_cis")],

            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )
    message.reply_text("**☀️ Sentosa Guide**", reply_markup=keyboard)

def handle_sentosa_location_request(callback_query, action):
    user_id = callback_query.from_user.id
    user_states[user_id] = action
    callback_query.message.reply_text(
        "Please share your location to get directions.",
        reply_markup=ReplyKeyboardMarkup(
            [
                [KeyboardButton("📍 Share Location", request_location=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )

def handle_fort_siloso_map_request(client, callback_query):
    loading_message = callback_query.message.reply_text("Retrieving... please wait.")
    try:
        with open("misc/Fort Siloso Map.pdf", "rb") as pdf:
            keyboard = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
                ]
            )
            callback_query.message.reply_document(
                pdf,
                file_name="Fort Siloso Map.pdf", reply_markup=keyboard  # Specify the desired file name here
            )
        loading_message.delete()
    except FileNotFoundError:
        loading_message.edit_text("❌ Fort Siloso Map not found.")


def show_food_in_smu(client, message):
    """Display the Food in SMU menu option."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🍽 Food in SMU",
                    url="https://www.smu.edu.sg/campus-life/visiting-smu/food-beverages-listing",
                )
            ],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
        ]
    )
    message.reply_text("🍽 **Food in SMU**", reply_markup=keyboard)

def handle_view_campus_map(callback_query):
    """Handle the callback query to view the campus map."""
    loading_message = callback_query.message.reply_text("Retrieving campus map, please wait...")

    try:
        with open("misc/campus map.jpg", "rb") as photo:
            keyboard = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
                ]
            )
            loading_message.delete()
            callback_query.message.reply_photo(photo, caption="🏫 **Campus Map** 🏫", reply_markup=keyboard)
    except FileNotFoundError:
        loading_message.edit_text("❌ Campus map image not found.")

# Contacts
def show_positions(client, message):
    """Display the list of positions available to contact."""
    positions = ["Co-chair", "HR", "Programmes", "Operations", "Logistics"]
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(position, callback_data=f"position_{position}")]
            for position in positions
        ]
        + [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    )
    message.reply_text("📞 **Choose A Position To Contact:**", reply_markup=keyboard)

def get_contact_info(position):
    """Fetch and return contact information for the given position."""
    contact_sheet = client.open("Important Contacts").sheet1  # Adjust if necessary
    records = contact_sheet.get_all_records()

    contacts = [
        f"{record['Name']} ({record['Position']}): {record['Telegram']}"
        for record in records
        if record["Position"] == position
    ]

    if contacts:
        return "\n".join(contacts)
    else:
        return "No contacts found for this position."

def handle_view_contact(callback_query, data):
    position = data[len("position_") :]
    loading_message = callback_query.message.reply("Retrieving contacts, please wait...")
    contact_info = get_contact_info(position)
    if contact_info:
        loading_message.edit_text(
            f"📞 **Contacts for {position}**:\n\n{contact_info}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back to Contact List", callback_data="contact_person")]
                ]
            ),
        )
    else:
        loading_message.edit_text(
            "No contacts found!",
            reply_markup=InlineKeyboardMarkup(
                [InlineKeyboardButton("🔙 Back to Contact List", callback_data="contact_person")]
            ),
        )

# Camp Strength
def get_strength_summary():
    """Retrieve the present and total strength for each subclan from the Camp Strength sheet."""
    expected_headers = ["Subclan", "Present", "Total"]
    strength_data = total_strength_sheet.get_all_records(expected_headers=expected_headers)
    strength_summary = {record["Subclan"]: f"{record['Present']} / {record['Total']}" for record in strength_data}
    return strength_summary

def handle_show_strength(callback_query):
    """Handle the callback query to show subclan strength."""
    strength_summary = get_strength_summary()
    subclan_sections = {
        "OC": [],
        "GM": [],
        "CH": [],
        "DURIO": [],
        "ORCHIDIUM": [],
        "MERLIOSA": [],
        "QUILAPIUS": [],
        "MC": [],
    }

    clan_totals = {
        "DURIO": {"present": 0, "total": 0},
        "ORCHIDIUM": {"present": 0, "total": 0},
        "MERLIOSA": {"present": 0, "total": 0},
        "QUILAPIUS": {"present": 0, "total": 0},
    }

    for subclan, summary in strength_summary.items():
        present, total = map(int, summary.split(" / "))
        full_status = " ✅ (FULL) " if present == total else ""

        if subclan == "OC":
            subclan_sections["OC"].append(f"{subclan}: {summary}{full_status}")
        if subclan == "MC":
            subclan_sections["MC"].append(f"{subclan}: {summary}{full_status}")
        elif subclan == "GM":
            subclan_sections["GM"].append(f"{subclan}: {summary}{full_status}")
        elif subclan == "CH":
            subclan_sections["CH"].append(f"{subclan}: {summary}{full_status}")
        elif subclan.startswith("D"):
            subclan_sections["DURIO"].append(f"{subclan}: {summary}{full_status}")
            clan_totals["DURIO"]["present"] += present
            clan_totals["DURIO"]["total"] += total
        elif subclan.startswith("O") and subclan != "OC":
            subclan_sections["ORCHIDIUM"].append(f"{subclan}: {summary}{full_status}")
            clan_totals["ORCHIDIUM"]["present"] += present
            clan_totals["ORCHIDIUM"]["total"] += total
        elif subclan.startswith("M"):
            subclan_sections["MERLIOSA"].append(f"{subclan}: {summary}{full_status}")
            clan_totals["MERLIOSA"]["present"] += present
            clan_totals["MERLIOSA"]["total"] += total
        elif subclan.startswith("Q"):
            subclan_sections["QUILAPIUS"].append(f"{subclan}: {summary}{full_status}")
            clan_totals["QUILAPIUS"]["present"] += present
            clan_totals["QUILAPIUS"]["total"] += total

    summary_message = "🏆 **Subclan Strength Summary** 🏆\n\n"
    summary_message += "\n".join(subclan_sections["OC"]) + "\n"
    summary_message += "\n".join(subclan_sections["GM"]) + "\n"
    summary_message += "\n".join(subclan_sections["CH"]) + "\n"
    summary_message += "\n".join(subclan_sections["MC"]) + "\n\n"

    summary_message += (
        f"**DURIO ( {clan_totals['DURIO']['present']} / {clan_totals['DURIO']['total']} )**:\n"
        + "\n".join(subclan_sections["DURIO"])
        + "\n\n"
    )
    summary_message += (
        f"**ORCHIDIUM ( {clan_totals['ORCHIDIUM']['present']} / {clan_totals['ORCHIDIUM']['total']} )**:\n"
        + "\n".join(subclan_sections["ORCHIDIUM"])
        + "\n\n"
    )
    summary_message += (
        f"**MERLIOSA ( {clan_totals['MERLIOSA']['present']} / {clan_totals['MERLIOSA']['total']} )**:\n"
        + "\n".join(subclan_sections["MERLIOSA"])
        + "\n\n"
    )
    summary_message += (
        f"**QUILAPIUS ( {clan_totals['QUILAPIUS']['present']} / {clan_totals['QUILAPIUS']['total']} )**:\n"
        + "\n".join(subclan_sections["QUILAPIUS"])
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    )

    callback_query.message.reply_text(summary_message, reply_markup=keyboard)

def handle_submit_action(callback_query, data):
    user_id = callback_query.from_user.id
    session_data = user_sessions[user_id]
    role = session_data.get("role")
    subclan = session_data.get("subclan")
    # clear_user_state(user_id)  # Clear previous actions before setting the new state

    user_states[user_id] = data
    if data == "early_check_out":
        callback_query.message.reply_text(
            "🔸 Please send the details in the format:\n**User ID + Expected Return Date and Time + Reason**. (Input 'Not coming back' for expected return if participant is not coming back).\n\nExample: 0XXXXXXX, 12/8 5:30 PM, Tuition",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🔙 Back to Attendance Menu", callback_data="submit_ids")
                    ]
                ]
            ),
        )
    elif data == "registration":
        if role in ["OC", "Game Master"]:
            callback_query.message.reply_text(
                "🔸 Please send a list of IDs (8 digits long, starting with 0) separated by spaces for registration of multiple IDs.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("🔙 Back to Attendance Menu", callback_data="submit_ids")
                        ]
                    ]
                ),
            )
        else:
            callback_query.message.reply_text(
                "❌ You do not have permission to register users.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("🔙 Back to Attendance Menu", callback_data="submit_ids")
                        ]
                    ]
                ),
            )
    else:
        callback_query.message.reply_text(
            f"🔸 Please send a list of IDs (8 digits long, starting with 0) separated by spaces for {data.replace('_', ' ')} of multiple IDs.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🔙 Back to Attendance Menu", callback_data="submit_ids")
                    ]
                ]
            ),
        )

# Command Handlers
@app.on_message(filters.command("start"))
def start(client, message):
    user_id = message.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    show_login_menu(client, message)

@app.on_message(filters.command("main_menu"))
def show_main_menu_command(client, message):
    user_id = message.from_user.id
    
    # Check if the user is already in a session
    if user_id in user_sessions:
        session_data = user_sessions[user_id]
        role = session_data.get("role")
        subclan = session_data.get("subclan")

        # User is validated, show the main menu
        show_menu(client, message)
    else:
        # User is not validated, ask them to log in with /start
        message.reply_text(
            "❌ Access denied. Please login by pressing /start to continue."
        )

@app.on_callback_query()
def handle_callback_query(client, callback_query):
    data = callback_query.data

    # Answer the callback query to remove the highlight
    callback_query.answer()

    user_id = callback_query.from_user.id
    user_username = callback_query.from_user.username

    clear_user_state(user_id)

    def default_handler():
        if user_id not in user_sessions:
            callback_query.message.reply_text(
                "❌ Access denied. Please login by pressing /start to continue."
            )
        else:
            handle_allowed_user(client, callback_query, data)

    handlers = {
        "login": lambda: handle_login(callback_query, user_username),
        "login_menu": lambda: show_login_menu(client, callback_query.message),
        "clans": lambda: show_clans_menu(client, callback_query.message),
        "exit": lambda: handle_logout(callback_query),
    }

    if data.startswith("clan_"):
        clan = data[len("clan_") :]
        handle_clan_selection(callback_query, clan)
    else:
        handler = handlers.get(data, default_handler)
        handler()

@app.on_message(filters.location)
def handle_location(client, message):
    user_location = message.location
    latitude = user_location.latitude
    longitude = user_location.longitude
    user_id = message.from_user.id

    if user_id in user_states:
        action = user_states.pop(user_id)
        if action == "fort_siloso":
            destination = "Fort+Siloso,+Sentosa"
            maps_url = f"https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={destination}"
        elif action == "madame_tussauds":
            destination = "Madame+Tussauds,+Sentosa"
            maps_url = f"https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={destination}"
        elif action == "soss_cis":
            # New option for SOSS/CIS directions
            destination = "SMU+School+of+Social+Sciences+%26+College+of+Integrative+Studies+(SOSS/CIS)"
            maps_url = f"https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={destination}"
        else:
            maps_url = None

        if maps_url:
            message.reply_text(
                f"Here is the direction to your destination:\n{maps_url}",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
                )
            )
        else:
            message.reply_text(
                "Location received but no action found.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
                )
            )
    else:
        message.reply_text(
            "Location received but no action found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
            )
        )
@app.on_message(filters.text & filters.create(lambda _, __, msg: not msg.text.startswith("/")))
def handle_client_input(client, message):
    user_id = message.from_user.id

    if user_id not in user_sessions:
        message.reply_text("❌ Access denied. Please login by pressing /start to continue.")
        return

    session_data = user_sessions.get(user_id, {})
    role = session_data.get("role")
    subclan = session_data.get("subclan")

    if user_id not in user_states:
        message.reply_text("🔹 Please choose an appropriate action from the menu.")
        return

    action = user_states[user_id]
    text = message.text.strip()
    loading_message = message.reply_text("⏳ Loading... Please wait.")

    if action in ["get_schedule_day 1", "get_schedule_day 3"]:
        # Schedule retrieval does not require ID validation
        day = "Day 1" if action == "get_schedule_day 1" else "Day 3"
        handle_get_schedule_message(loading_message, role, subclan, text, day)
    elif action == "early_check_out":
        handle_early_check_out(loading_message, text)
    elif action == "get_overall_subclan_points":
        handle_get_overall_subclan_points(loading_message, role, subclan, text)
    elif action == "get_d3_currency":
        handle_get_d3_currency_points(loading_message, role, subclan, text)
    else:
        handle_default_action(loading_message, text, action, role)

app.run()
