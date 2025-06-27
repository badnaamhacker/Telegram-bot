# -*- coding: utf-8 -*-

import logging
import sqlite3
from datetime import datetime, timedelta
import re

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    ReplyKeyboardRemove,
    InputMediaPhoto
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
)

# --- CONFIGURATION ---
# WARNING: Do not hardcode your tokens in a real-world application. Use environment variables.
BOT_TOKEN = "7998800242:AAFEdw_XQEO41qI4Q6zXiPzaal6CN7VO2Hc"
ADMIN_ID = 5156942271  # Your Telegram User ID
UPI_ID = "nksvishvakarma@oksbi"  # IMPORTANT: Replace with your actual UPI ID

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
def db_connect():
    conn = sqlite3.connect('trioconnect.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    conn = db_connect()
    cursor = conn.cursor()
    
    # User Profiles Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT,
            country TEXT,
            bio TEXT,
            is_profile_complete INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Photos Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            photo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    
    # Interactions Tables
    cursor.execute('CREATE TABLE IF NOT EXISTS dislikes (disliker_id INTEGER, disliked_id INTEGER, PRIMARY KEY(disliker_id, disliked_id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS likes (liker_id INTEGER, liked_id INTEGER, message TEXT, status TEXT DEFAULT "pending", PRIMARY KEY(liker_id, liked_id))')
    
    # Matches Table (for in-bot chat)
    cursor.execute('CREATE TABLE IF NOT EXISTS matches (user1_id INTEGER, user2_id INTEGER, PRIMARY KEY(user1_id, user2_id))')
    
    # Daily Usage Tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_views (
            user_id INTEGER,
            view_date DATE,
            total_views INTEGER DEFAULT 0,
            female_views INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, view_date)
        )
    ''')
    
    # Premium Membership Tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS premium_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_name TEXT,
            transaction_id TEXT,
            status TEXT DEFAULT "pending", -- pending, approved, rejected
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            plan_name TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    
    # Reports Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            report_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

# --- HELPER FUNCTIONS ---
def is_user_premium(user_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT end_date FROM premium_users WHERE user_id = ? AND end_date > CURRENT_TIMESTAMP", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_premium_badge(user_id):
    return " ðŸ‘‘" if is_user_premium(user_id) else ""
    
def get_user_profile_text(user_id, with_bio=True):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return "Profile not found."

    premium_badge = get_premium_badge(user_id)
    profile_text = (
        f"<b>{user['name']}{premium_badge}, {user['age']}</b>\n"
        f"<b>Gender:</b> {user['gender'].capitalize()}\n"
        f"<b>Country:</b> {user['country']}\n"
    )
    if with_bio and user['bio']:
        profile_text += f"\n<b>Bio:</b>\n<i>{user['bio']}</i>"
    return profile_text

# --- STATE DEFINITIONS FOR CONVERSATION HANDLERS ---
# --- STATE DEFINITIONS FOR CONVERSATION HANDLERS ---
(NAME, AGE, GENDER, COUNTRY, BIO, PHOTOS, 
 LIKE_MESSAGE, PREMIUM_TRANSACTION_ID, 
 ADMIN_REJECT_REASON, 
 # Broadcast States
 ADMIN_BROADCAST_CONTENT, ADMIN_BROADCAST_TARGET, ADMIN_BROADCAST_CONFIRM,
 # Delete User States
 ADMIN_DELETE_USER_ID
) = range(13)


# =============================================================================
# === START & MAIN MENU =======================================================
# =============================================================================

def start(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT is_profile_complete FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data and user_data['is_profile_complete']:
        # User has a complete profile, show main menu
        return main_menu(update, context)
    else:
        # New user or incomplete profile
        welcome_text = (
            "Hello! Welcome to <b>Trioconnect Bot</b>.\n\n"
            "Here you can find new friends, partners, and even connections for business ventures.\n\n"
            "<b>Note:</b> For the best experience, please make sure you have a Telegram @username set in your Telegram settings. "
            "This helps other users connect with you if you have a Premium Membership."
        )
        keyboard = [
            [InlineKeyboardButton("âœ… Create Profile", callback_data='create_profile')],
            [InlineKeyboardButton("â“ Help", callback_data='help'), InlineKeyboardButton("ðŸ”’ Policy & Privacy", callback_data='privacy')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return -1 # Not in a conversation yet

def main_menu(update: Update, context: CallbackContext, message_text=None):
    user_id = update.effective_user.id
    
    text = message_text if message_text else f"Welcome back, {update.effective_user.first_name}!\nWhat would you like to do?"
    
    keyboard = [
        [InlineKeyboardButton("My Profile ðŸ‘¤", callback_data='view_profile'), InlineKeyboardButton("Edit Profile ðŸ“", callback_data='edit_profile')],
        [InlineKeyboardButton("â¤ï¸ Find Match", callback_data='find_match_start')],
        [InlineKeyboardButton("My Matches & Chats ðŸ’¬", callback_data='my_matches')],
        [InlineKeyboardButton("ðŸ‘‘ Premium Membership", callback_data='premium_menu')],
        [InlineKeyboardButton("Delete Profile ðŸ—‘ï¸", callback_data='delete_profile_confirm')],
    ]

    # Show "Get Premium" button if user is not premium
    if not is_user_premium(user_id):
        keyboard.insert(3, [InlineKeyboardButton("â­ GET PREMIUM NOW! â­", callback_data='premium_menu')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    # If coming from a callback, edit the message. If from /start, reply.
    if update.callback_query:
        query = update.callback_query
        query.answer()
        query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    return -1 # End any conversation

def back_to_main_menu(update: Update, context: CallbackContext):
    return main_menu(update, context, message_text="You are back to the main menu.")

# =============================================================================
# === HELP & PRIVACY ==========================================================
# =============================================================================

def help_command(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    help_text = (
        "<b>â“ How Trioconnect Bot Works</b>\n\n"
        "1. <b>Create Your Profile:</b> Provide your name, age, gender, country, and a short bio. You can also upload photos.\n\n"
        "2. <b>Find Match:</b> Browse profiles based on your preferred gender.\n\n"
        "3. <b>Interact:</b>\n"
        "   - â¤ï¸ <b>Like:</b> Send a connection request with a custom message.\n"
        "   - ðŸ‘Ž <b>Dislike:</b> You won't see this profile again.\n"
        "   - â­ï¸ <b>Skip:</b> Move to the next profile.\n\n"
        "4. <b>Match & Chat:</b> If someone accepts your 'Like' request, you're matched! \n"
        "   - <b>Premium Users:</b> Telegram usernames are shared for direct chat.\n"
        "   - <b>Free Users:</b> You can chat with your matches inside the bot via the 'My Matches & Chats' section.\n\n"
        "Upgrade to <b>Premium</b> for unlimited swipes, a stylish profile, and direct username sharing!"
    )
    keyboard = [[InlineKeyboardButton("â¬…ï¸ Back", callback_data='back_to_start_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def privacy_policy(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    privacy_text = (
        "<b>ðŸ”’ Privacy Policy</b>\n\n"
        "Your privacy is important to us. Here's how we handle your data:\n\n"
        "- <b>Your Data:</b> We store your profile information (name, age, gender, bio, photos) to provide the matching service. Your Telegram User ID is used to identify you.\n\n"
        "- <b>Data Sharing:</b> Your profile is visible to other users. Your Telegram username is ONLY shared with a match if YOU are a Premium member and they accept your request. We never share your data with third parties.\n\n"
        "- <b>Photos:</b> Your photos are stored on Telegram's secure servers, identified by a `file_id`.\n\n"
        "- <b>Data Deletion:</b> You can delete your entire profile and all associated data at any time using the 'Delete Profile' button. This action is irreversible.\n\n"
        "- <b>Communication:</b> All chats for free users happen through the bot, acting as a relay, to protect your privacy."
    )
    keyboard = [[InlineKeyboardButton("â¬…ï¸ Back", callback_data='back_to_start_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(privacy_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def back_to_start_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    welcome_text = (
        "Hello! Welcome to <b>Trioconnect Bot</b>.\n\n"
        "Here you can find new friends, partners, and even connections for business ventures.\n\n"
        "<b>Note:</b> For the best experience, please make sure you have a Telegram @username set in your Telegram settings."
    )
    keyboard = [
        [InlineKeyboardButton("âœ… Create Profile", callback_data='create_profile')],
        [InlineKeyboardButton("â“ Help", callback_data='help'), InlineKeyboardButton("ðŸ”’ Policy & Privacy", callback_data='privacy')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


# =============================================================================
# === PROFILE CREATION CONVERSATION ===========================================
# =============================================================================
def create_profile_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    context.user_data['profile_photos'] = [] # Reset photos
    query.edit_message_text("Let's create your profile! First, what is your name?")
    return NAME

def get_name(update: Update, context: CallbackContext):
    name = update.message.text
    if '@' in name or re.search(r'\d{10}', name):
        update.message.reply_text("Your name cannot contain a '@' symbol or a 10-digit phone number. Please try again.")
        return NAME
    context.user_data['profile_name'] = name
    update.message.reply_text(f"Great, {name}! Now, what is your age? (Please enter a number between 18 and 99)")
    return AGE

def get_age(update: Update, context: CallbackContext):
    try:
        age = int(update.message.text)
        if 18 <= age <= 99:
            context.user_data['profile_age'] = age
            keyboard = [[InlineKeyboardButton("Male", callback_data='Male'),
                         InlineKeyboardButton("Female", callback_data='Female'),
                         InlineKeyboardButton("Other", callback_data='Other')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("What is your gender?", reply_markup=reply_markup)
            return GENDER
        else:
            update.message.reply_text("Please enter a valid age between 18 and 99.")
            return AGE
    except ValueError:
        update.message.reply_text("That doesn't look like a number. Please enter your age.")
        return AGE

def get_gender(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    context.user_data['profile_gender'] = query.data
    
    # Top 10 countries
    countries = ["India", "United States", "Brazil", "Indonesia", "Pakistan", "Nigeria", "Bangladesh", "Russia", "Mexico", "Japan"]
    keyboard = [[InlineKeyboardButton(c, callback_data=c)] for c in countries]
    keyboard.append([InlineKeyboardButton("Other (Type it)", callback_data='OtherCountry')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Where are you from? Select from the list or choose 'Other' to type your country.", reply_markup=reply_markup)
    return COUNTRY

def get_country(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == 'OtherCountry':
        query.edit_message_text("Please type the name of your country.")
        return COUNTRY # Stay in the same state, but wait for text input
    else:
        context.user_data['profile_country'] = query.data
        return ask_for_bio(update, context)

def get_country_text(update: Update, context: CallbackContext):
    country = update.message.text
    context.user_data['profile_country'] = country
    # We can't call query.edit_message_text here as it's a text update
    # So we call the next step directly
    return ask_for_bio(update, context, is_text_update=True)


def ask_for_bio(update: Update, context: CallbackContext, is_text_update=False):
    text = "Tell us a bit about yourself. (Max 100 words, no @usernames or phone numbers). You can also skip this step."
    keyboard = [[InlineKeyboardButton("Skip Bio", callback_data='skip_bio')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_text_update:
        update.message.reply_text(text, reply_markup=reply_markup)
    else:
        query = update.callback_query
        query.edit_message_text(text, reply_markup=reply_markup)
    
    return BIO

def get_bio(update: Update, context: CallbackContext):
    bio = update.message.text
    if len(bio.split()) > 100:
        update.message.reply_text("Your bio is too long (max 100 words). Please shorten it.")
        return BIO
    if '@' in bio or re.search(r'\d{10}', bio):
        update.message.reply_text("Your bio cannot contain a '@' symbol or a 10-digit phone number. Please try again.")
        return BIO
    context.user_data['profile_bio'] = bio
    return ask_for_photos(update, context)

def skip_bio(update: Update, context: CallbackContext):
    context.user_data['profile_bio'] = None
    query = update.callback_query
    query.answer()
    return ask_for_photos(update, context, from_callback=True)

def ask_for_photos(update: Update, context: CallbackContext, from_callback=False):
    text = (
        "Now, please upload 1 to 3 photos for your profile. Send them one by one.\n"
        "When you're done, or if you want to skip, press the 'Finish' button."
    )
    keyboard = [[InlineKeyboardButton("âœ… Finish & Save Profile", callback_data='finish_photos')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if from_callback:
        query = update.callback_query
        query.edit_message_text(text, reply_markup=reply_markup)
    else:
        update.message.reply_text(text, reply_markup=reply_markup)
    return PHOTOS

def get_photo(update: Update, context: CallbackContext):
    if len(context.user_data.get('profile_photos', [])) < 3:
        photo_file = update.message.photo[-1] # Get the highest resolution photo
        context.user_data.setdefault('profile_photos', []).append(photo_file.file_id)
        update.message.reply_text(f"Photo {len(context.user_data['profile_photos'])}/3 received. Send another or click 'Finish'.")
    else:
        update.message.reply_text("You have already uploaded the maximum of 3 photos. Please click 'Finish'.")
    return PHOTOS

def finish_profile_creation(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    # Save data to database
    conn = db_connect()
    cursor = conn.cursor()
    
    # Use INSERT OR REPLACE to handle both new creation and editing
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, name, age, gender, country, bio, is_profile_complete)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    ''', (user_id, context.user_data['profile_name'], context.user_data['profile_age'],
          context.user_data['profile_gender'], context.user_data['profile_country'],
          context.user_data.get('profile_bio')))
          
    # Delete old photos and insert new ones
    cursor.execute("DELETE FROM photos WHERE user_id = ?", (user_id,))
    if 'profile_photos' in context.user_data and context.user_data['profile_photos']:
        for file_id in context.user_data['profile_photos']:
            cursor.execute("INSERT INTO photos (user_id, file_id) VALUES (?, ?)", (user_id, file_id))

    conn.commit()
    conn.close()

    query.answer("Profile saved successfully!")
    context.user_data.clear()
    
    main_menu(update, context, message_text="Your profile has been created! Welcome to the community.")
    return ConversationHandler.END


# =============================================================================
# === VIEW & EDIT PROFILE =======================================================
# =============================================================================

def view_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    profile_text = get_user_profile_text(user_id)
    
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT file_id FROM photos WHERE user_id = ?", (user_id,))
    photos = cursor.fetchall()
    conn.close()

    keyboard = [[InlineKeyboardButton("â¬…ï¸ Back to Main Menu", callback_data='back_to_main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if photos:
        media_group = [InputMediaPhoto(p['file_id']) for p in photos]
        # Add caption to the first photo
        media_group[0].caption = profile_text
        media_group[0].parse_mode = ParseMode.HTML
        query.message.reply_media_group(media=media_group)
        # Send a separate message for the back button
        query.message.reply_text("This is your profile.", reply_markup=reply_markup)
        query.delete_message() # Delete the old menu message
    else:
        query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def edit_profile_start(update: Update, context: CallbackContext):
    # This will reuse the creation conversation handler
    # Pre-fill context.user_data with current profile info
    query = update.callback_query
    user_id = query.from_user.id
    
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT file_id FROM photos WHERE user_id = ?", (user_id,))
    photos = cursor.fetchall()
    conn.close()
    
    context.user_data['profile_name'] = user['name']
    context.user_data['profile_age'] = user['age']
    context.user_data['profile_gender'] = user['gender']
    context.user_data['profile_country'] = user['country']
    context.user_data['profile_bio'] = user['bio']
    context.user_data['profile_photos'] = [p['file_id'] for p in photos]
    
    query.answer("Starting profile edit...")
    query.edit_message_text("Let's edit your profile. What is your name?")
    return NAME

def delete_profile_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    text = ("<b>âš ï¸ Are you sure you want to delete your profile?</b>\n\n"
            "This action is permanent and cannot be undone. All your data, matches, and chats will be lost.")
    keyboard = [
        [InlineKeyboardButton("Yes, Delete My Profile", callback_data='delete_profile_execute')],
        [InlineKeyboardButton("No, Keep My Profile", callback_data='back_to_main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def delete_profile_execute(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM photos WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM likes WHERE liker_id = ? OR liked_id = ?", (user_id, user_id))
    cursor.execute("DELETE FROM dislikes WHERE disliker_id = ? OR disliked_id = ?", (user_id, user_id))
    cursor.execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
    cursor.execute("DELETE FROM daily_views WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM premium_users WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM premium_requests WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    query.answer("Your profile has been deleted.")
    
    # Send back to the initial start menu
    welcome_text = "Your profile has been successfully deleted. We're sorry to see you go. You can always create a new profile by pressing the button below."
    keyboard = [[InlineKeyboardButton("âœ… Create Profile", callback_data='create_profile')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


# =============================================================================
# === FIND MATCH ==============================================================
# =============================================================================

def find_match_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    text = "Who are you interested in meeting?"
    keyboard = [
        [InlineKeyboardButton("Men ðŸ‘¨", callback_data='match_gender_Male'),
         InlineKeyboardButton("Women ðŸ‘©", callback_data='match_gender_Female')],
        [InlineKeyboardButton("Anyone ðŸ§‘â€ðŸ¤â€ðŸ§‘", callback_data='match_gender_Any')],
        [InlineKeyboardButton("â¬…ï¸ Back", callback_data='back_to_main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)

def find_match_gender_selected(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    gender_preference = query.data.split('_')[-1] # 'Male', 'Female', 'Any'
    context.user_data['match_gender_preference'] = gender_preference
    
    # Check limits for free users
    if not is_user_premium(user_id):
        conn = db_connect()
        cursor = conn.cursor()
        today = datetime.now().date()
        cursor.execute("SELECT total_views, female_views FROM daily_views WHERE user_id = ? AND view_date = ?", (user_id, today))
        views = cursor.fetchone()
        
        if views:
            if views['total_views'] >= 20:
                query.answer("You have reached your daily limit of 20 profiles.", show_alert=True)
                query.edit_message_text("You've seen all your profiles for today! Come back tomorrow or get Premium for unlimited access.",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ‘‘ Get Premium", callback_data='premium_menu')]]))
                return
            if gender_preference == 'Female' and views['female_views'] >= 2:
                query.answer("You've reached your daily limit for female profiles.", show_alert=True)
                query.edit_message_text("You've reached your free daily limit for viewing female profiles. Get Premium to see more!",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ‘‘ Get Premium", callback_data='premium_menu')]]))
                return
        conn.close()

    show_match_profile(update, context)

def show_match_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    gender_preference = context.user_data.get('match_gender_preference')

    conn = db_connect()
    cursor = conn.cursor()

    # Base query to find a potential match
    sql = """
        SELECT u.user_id, u.name, u.age, u.gender, u.country, u.bio
        FROM users u
        WHERE u.user_id != ?
        AND u.is_profile_complete = 1
        AND u.user_id NOT IN (SELECT liked_id FROM likes WHERE liker_id = ?)
        AND u.user_id NOT IN (SELECT disliked_id FROM dislikes WHERE disliker_id = ?)
        AND u.user_id NOT IN (SELECT reported_id FROM reports WHERE reporter_id = ?)
    """
    params = [user_id, user_id, user_id, user_id]

    if gender_preference != 'Any':
        sql += " AND u.gender = ?"
        params.append(gender_preference)

    sql += " ORDER BY RANDOM() LIMIT 1" # Get a random profile
    
    cursor.execute(sql, tuple(params))
    candidate = cursor.fetchone()

    if not candidate:
        query.answer("No more profiles to show right now!", show_alert=True)
        query.edit_message_text("Looks like you've seen everyone for now. Check back later!",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Back to Main Menu", callback_data='back_to_main_menu')]]))
        return

    # Update daily view counts for free users
    if not is_user_premium(user_id):
        today = datetime.now().date()
        total_increment = 1
        female_increment = 1 if candidate['gender'] == 'Female' else 0

        # Special rule for 'Any' category
        if gender_preference == 'Any':
             cursor.execute("SELECT female_views, total_views FROM daily_views WHERE user_id = ? AND view_date = ?", (user_id, today))
             views = cursor.fetchone()
             if views and candidate['gender'] == 'Female' and views['female_views'] / max(1, views['total_views']) >= 0.3:
                 # If female ratio is already high, try to find a male profile instead
                 # This is a simplified logic. A more robust system would re-query.
                 # For now, we'll just skip to the next logic iteration.
                 conn.close()
                 # Calling the function again to get another profile
                 return show_match_profile(update, context)

        cursor.execute('''
            INSERT INTO daily_views (user_id, view_date, total_views, female_views) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, view_date) DO UPDATE SET
            total_views = total_views + excluded.total_views,
            female_views = female_views + excluded.female_views
        ''', (user_id, today, total_increment, female_increment))
        conn.commit()


    context.user_data['current_match_id'] = candidate['user_id']
    profile_text = get_user_profile_text(candidate['user_id'])
    
    # Add stylish design for premium viewers
    if is_user_premium(user_id):
        profile_text = f"âœ¨-- Stylist View --âœ¨\n\n{profile_text}\n\nâœ¨------------------âœ¨"
        
    cursor.execute("SELECT file_id FROM photos WHERE user_id = ?", (candidate['user_id'],))
    photos = cursor.fetchall()
    conn.close()
    
    # Buttons for interaction
    keyboard = [
        [InlineKeyboardButton("â¤ï¸ Like", callback_data='like_profile'), InlineKeyboardButton("ðŸ‘Ž Dislike", callback_data='dislike_profile')],
        [InlineKeyboardButton("â­ï¸ Skip", callback_data='skip_profile'), InlineKeyboardButton("ðŸš¨ Report", callback_data='report_profile')],
        [InlineKeyboardButton("â¬…ï¸ Back to Main Menu", callback_data='back_to_main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.answer()
    if photos:
        media_group = [InputMediaPhoto(p['file_id']) for p in photos]
        media_group[0].caption = profile_text
        media_group[0].parse_mode = ParseMode.HTML
        query.message.reply_media_group(media=media_group)
        query.message.reply_text("What do you think?", reply_markup=reply_markup)
        query.delete_message()
    else:
        query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


def like_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("Great! Send a short message (max 100 words) to introduce yourself. This will be sent with your request.")
    return LIKE_MESSAGE

def send_like_message(update: Update, context: CallbackContext):
    message_text = update.message.text
    if len(message_text.split()) > 100:
        update.message.reply_text("Your message is too long (max 100 words). Please try again.")
        return LIKE_MESSAGE

    liker_id = update.effective_user.id
    liked_id = context.user_data.get('current_match_id')

    if not liked_id:
        update.message.reply_text("Something went wrong. Please try again from the main menu.")
        return main_menu(update, context)

    # Save the like to the database
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO likes (liker_id, liked_id, message, status) VALUES (?, ?, ?, 'pending')", (liker_id, liked_id, message_text))
    conn.commit()
    conn.close()

    # Notify the liked user
    liker_profile_summary = get_user_profile_text(liker_id, with_bio=False)
    notification_text = (
        "ðŸŽ‰ You've received a new connection request!\n\n"
        f"<b>From:</b>\n{liker_profile_summary}\n\n"
        f"<b>Message:</b>\n<i>\"{message_text}\"</i>\n\n"
        "What would you like to do?"
    )
    keyboard = [
        [InlineKeyboardButton("âœ… Accept", callback_data=f"accept_like_{liker_id}"),
         InlineKeyboardButton("âŒ Reject", callback_data=f"reject_like_{liker_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        context.bot.send_message(chat_id=liked_id, text=notification_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        update.message.reply_text("Your request has been sent! We will notify you of their response.")
    except Exception as e:
        logger.error(f"Failed to send like notification to {liked_id}: {e}")
        update.message.reply_text("Could not send the request. The user might have blocked the bot.")

    # Show the next profile to the liker
    # Creating a dummy query object to pass to the function
    class DummyQuery:
        def __init__(self, message, from_user):
            self.message = message
            self.from_user = from_user
        def answer(self): pass
    
    dummy_update = Update(update.update_id, message=update.message)
    dummy_query = DummyQuery(update.message, update.effective_user)
    dummy_update.callback_query = dummy_query
    
    show_match_profile(dummy_update, context)
    return ConversationHandler.END


def accept_like(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    accepted_by_id = query.from_user.id
    liker_id = int(query.data.split('_')[-1])

    # Update like status
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE likes SET status = 'accepted' WHERE liker_id = ? AND liked_id = ?", (liker_id, accepted_by_id))
    
    # Create match record for both users for in-bot chat
    # To avoid duplicates, we store with lower ID first
    user1 = min(liker_id, accepted_by_id)
    user2 = max(liker_id, accepted_by_id)
    cursor.execute("INSERT OR IGNORE INTO matches (user1_id, user2_id) VALUES (?, ?)", (user1, user2))

    conn.commit()
    conn.close()

    # Check if the liker is premium
    liker_is_premium = is_user_premium(liker_id)
    
    liker_info = context.bot.get_chat(liker_id)
    accepter_info = context.bot.get_chat(accepted_by_id)
    liker_username = f"@{liker_info.username}" if liker_info.username else "N/A"
    accepter_username = f"@{accepter_info.username}" if accepter_info.username else "N/A"

    if liker_is_premium:
        # Share usernames
        query.edit_message_text(f"It's a match! You can now contact {liker_info.first_name} directly on Telegram: {liker_username}")
        context.bot.send_message(chat_id=liker_id, text=f"ðŸŽ‰ Your request was accepted! You can now contact {accepter_info.first_name} directly on Telegram: {accepter_username}")
    else:
        # Free user -> In-bot chat
        query.edit_message_text(f"It's a match with {liker_info.first_name}! You can now chat with them inside the bot via the 'My Matches & Chats' section.")
        context.bot.send_message(chat_id=liker_id, text=f"ðŸŽ‰ Your request was accepted by {accepter_info.first_name}! You can now chat with them inside the bot via the 'My Matches & Chats' section.")


def reject_like(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("You have rejected the request.")
    
    rejected_by_id = query.from_user.id
    liker_id = int(query.data.split('_')[-1])

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE likes SET status = 'rejected' WHERE liker_id = ? AND liked_id = ?", (liker_id, rejected_by_id))
    conn.commit()
    conn.close()
    
    rejected_by_user = context.bot.get_chat(rejected_by_id)
    query.edit_message_text("You have rejected the request.")
    context.bot.send_message(chat_id=liker_id, text=f"Unfortunately, {rejected_by_user.first_name} has declined your connection request. Keep searching!")


def dislike_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    disliker_id = query.from_user.id
    disliked_id = context.user_data.get('current_match_id')

    if disliked_id:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO dislikes (disliker_id, disliked_id) VALUES (?, ?)", (disliker_id, disliked_id))
        conn.commit()
        conn.close()

    query.answer("Profile disliked. You won't see it again.")
    show_match_profile(update, context)


def skip_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("Skipped.")
    show_match_profile(update, context)

def report_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    reporter_id = query.from_user.id
    reported_id = context.user_data.get('current_match_id')
    
    if reported_id:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reports (reporter_id, reported_id) VALUES (?, ?)", (reporter_id, reported_id))
        conn.commit()
        conn.close()
        
        # Notify admin
        try:
            reporter_info = context.bot.get_chat(reporter_id)
            reported_info = context.bot.get_chat(reported_id)
            admin_msg = (
                f"ðŸš¨ New Report!\n\n"
                f"<b>Reporter:</b> {reporter_info.first_name} (ID: {reporter_id})\n"
                f"<b>Reported:</b> {reported_info.first_name} (ID: {reported_id})"
            )
            context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to send report to admin: {e}")

    query.answer("Profile reported. Our team will review it.", show_alert=True)
    show_match_profile(update, context)


# =============================================================================
# === IN-BOT CHAT SYSTEM ======================================================
# =============================================================================

def my_matches(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT user1_id, user2_id FROM matches WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
    matches = cursor.fetchall()
    
    if not matches:
        query.answer("You have no matches yet.", show_alert=True)
        return

    keyboard = []
    for match in matches:
        other_user_id = match['user2_id'] if match['user1_id'] == user_id else match['user1_id']
        try:
            other_user_info = context.bot.get_chat(other_user_id)
            premium_badge = get_premium_badge(other_user_id)
            button_text = f"Chat with {other_user_info.first_name}{premium_badge}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"chatwith_{other_user_id}")])
        except Exception as e:
            logger.warning(f"Could not get info for user {other_user_id}: {e}")
            
    keyboard.append([InlineKeyboardButton("â¬…ï¸ Back to Main Menu", callback_data='back_to_main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Here are your matches. Select one to start chatting."
    query.edit_message_text(text, reply_markup=reply_markup)
    conn.close()

def start_chat_session(update: Update, context: CallbackContext):
    query = update.callback_query
    other_user_id = int(query.data.split('_')[1])
    
    context.user_data['chatting_with'] = other_user_id
    other_user_info = context.bot.get_chat(other_user_id)
    
    query.answer()
    text = (
        f"You are now chatting with <b>{other_user_info.first_name}</b>.\n"
        "Any message you send here will be forwarded to them.\n"
        "Type `/stopchat` to end the conversation and return to the main menu."
    )
    query.edit_message_text(text, parse_mode=ParseMode.HTML)

def relay_chat_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    other_user_id = context.user_data.get('chatting_with')

    if not other_user_id:
        # This message is not part of a chat session, ignore it or handle differently
        return

    # Check if the other user is also in a chat session with this user
    # This is a bit complex without a global state manager, we'll rely on the bot sending messages
    
    sender_name = update.effective_user.first_name
    message_text = update.message.text
    
    try:
        # Send message to the other user
        context.bot.send_message(
            chat_id=other_user_id,
            text=f"<b>{sender_name}:</b> {message_text}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Failed to relay message from {user_id} to {other_user_id}: {e}")
        update.message.reply_text("Could not send your message. The other user might have blocked the bot. The chat session has ended.")
        stop_chat(update, context)

def stop_chat(update: Update, context: CallbackContext):
    if 'chatting_with' in context.user_data:
        del context.user_data['chatting_with']
    
    main_menu(update, context, message_text="You have ended the chat session.")


# =============================================================================
# === PREMIUM MEMBERSHIP ======================================================
# =============================================================================
PREMIUM_PLANS = {
    '1week': {'price': 30, 'duration_days': 7},
    '2week': {'price': 55, 'duration_days': 14},
    '3week': {'price': 80, 'duration_days': 21},
    '4week': {'price': 99, 'duration_days': 28},
}

def premium_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    if is_user_premium(user_id):
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT plan_name, end_date FROM premium_users WHERE user_id = ?", (user_id,))
        plan = cursor.fetchone()
        conn.close()
        
        text = (
            "ðŸ‘‘ <b>Your Premium Status</b> ðŸ‘‘\n\n"
            f"<b>Plan:</b> {plan['plan_name']}\n"
            f"<b>Expires on:</b> {datetime.fromisoformat(plan['end_date']).strftime('%d %B %Y, %I:%M %p')}\n\n"
            "Thank you for being a premium member!"
        )
        keyboard = [[InlineKeyboardButton("â¬…ï¸ Back to Main Menu", callback_data='back_to_main_menu')]]
    else:
        text = "ðŸ‘‘ <b>Get Premium Membership!</b> ðŸ‘‘\n\nUnlock these amazing features:\nâœ… Unlimited Swipes (no daily limits)\nâœ… Stylish Profile Design\nâœ… Premium Badge ðŸ‘‘\nâœ… No Ads\nâœ… Share Telegram Usernames on Match\n\nChoose your plan:"
        keyboard = [
            [InlineKeyboardButton(f"1 Week - â‚¹{PREMIUM_PLANS['1week']['price']}", callback_data='buy_premium_1week')],
            [InlineKeyboardButton(f"2 Weeks - â‚¹{PREMIUM_PLANS['2week']['price']}", callback_data='buy_premium_2week')],
            [InlineKeyboardButton(f"3 Weeks - â‚¹{PREMIUM_PLANS['3week']['price']}", callback_data='buy_premium_3week')],
            [InlineKeyboardButton(f"4 Weeks - â‚¹{PREMIUM_PLANS['4week']['price']}", callback_data='buy_premium_4week')],
            [InlineKeyboardButton("â¬…ï¸ Back", callback_data='back_to_main_menu')],
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.answer()
    query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def select_premium_plan(update: Update, context: CallbackContext):
    query = update.callback_query
    plan_key = query.data.split('_')[-1]
    plan_details = PREMIUM_PLANS[plan_key]
    context.user_data['selected_plan'] = plan_key
    
    text = (
        f"You have selected the <b>{plan_key.replace('week', ' Week')}</b> plan for <b>â‚¹{plan_details['price']}</b>.\n\n"
        "<b>Instructions:</b>\n"
        f"1. Pay the amount to the following UPI ID: `{UPI_ID}`\n"
        "2. After payment, copy the Transaction ID (or UTR number).\n"
        "3. Send the Transaction ID back here.\n\n"
        "Our admin will verify your payment and activate your membership shortly. Please be patient."
    )
    keyboard = [[InlineKeyboardButton("â¬…ï¸ Cancel", callback_data='premium_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.answer()
    query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    return PREMIUM_TRANSACTION_ID

def receive_transaction_id(update: Update, context: CallbackContext):
    transaction_id = update.message.text
    user_id = update.effective_user.id
    plan_key = context.user_data.get('selected_plan')

    if not plan_key:
        update.message.reply_text("Something went wrong. Please select a plan again.")
        return main_menu(update, context)

    # Save request to database
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO premium_requests (user_id, plan_name, transaction_id) VALUES (?, ?, ?)",
                   (user_id, plan_key, transaction_id))
    conn.commit()
    conn.close()
    
    # Notify Admin
    user_info = update.effective_user
    plan_details = PREMIUM_PLANS[plan_key]
    admin_msg = (
        "ðŸ’³ New Premium Request!\n\n"
        f"<b>User:</b> {user_info.first_name} (ID: {user_id})\n"
        f"<b>Plan:</b> {plan_key.replace('week', ' Week')} ({plan_details['duration_days']} days)\n"
        f"<b>Amount:</b> â‚¹{plan_details['price']}\n"
        f"<b>Transaction ID:</b> `{transaction_id}`\n\n"
        "Please go to the Admin Panel to approve or reject."
    )
    context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode=ParseMode.HTML)

    update.message.reply_text("Thank you! Your request has been submitted. The admin will review it soon. You will be notified upon approval.")
    del context.user_data['selected_plan']
    return main_menu(update, context)


# =============================================================================
# === ADMIN PANEL =============================================================
# =============================================================================

def admin_panel(update: Update, context: CallbackContext):
    text = "ðŸ‘‘ Welcome to the Admin Panel ðŸ‘‘"
    keyboard = [
        [InlineKeyboardButton("ðŸ“Š User Statistics", callback_data='admin_stats')],
        [InlineKeyboardButton("ðŸ“¢ Broadcast Message", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("ðŸš¨ View Reports", callback_data='admin_reports')],
        [InlineKeyboardButton("âœ… Premium Requests", callback_data='admin_premium_requests')],
        [InlineKeyboardButton("ðŸ—‘ï¸ Delete a User", callback_data='admin_delete_user_start')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(text, reply_markup=reply_markup)

def admin_stats(update: Update, context: CallbackContext):
    query = update.callback_query
    conn = db_connect()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE gender = 'Male'")
    male_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE gender = 'Female'")
    female_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE gender = 'Other'")
    other_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM premium_users WHERE end_date > CURRENT_TIMESTAMP")
    premium_users = cursor.fetchone()[0]
    
    text = (
        f"ðŸ“Š <b>Bot Statistics</b>\n\n"
        f"<b>Total Users:</b> {total_users}\n"
        f"  - Male: {male_users}\n"
        f"  - Female: {female_users}\n"
        f"  - Other: {other_users}\n\n"
        f"<b>Active Premium Users:</b> {premium_users}\n"
        f"<b>Free Users:</b> {total_users - premium_users}"
    )
    keyboard = [[InlineKeyboardButton("â¬…ï¸ Back to Admin Panel", callback_data='admin_panel_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    conn.close()

def admin_panel_back(update: Update, context: CallbackContext):
    query = update.callback_query
    text = "ðŸ‘‘ Welcome to the Admin Panel ðŸ‘‘"
    keyboard = [
        [InlineKeyboardButton("ðŸ“Š User Statistics", callback_data='admin_stats')],
        [InlineKeyboardButton("ðŸ“¢ Broadcast Message", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("ðŸš¨ View Reports", callback_data='admin_reports')],
        [InlineKeyboardButton("âœ… Premium Requests", callback_data='admin_premium_requests')],
        [InlineKeyboardButton("ðŸ—‘ï¸ Delete a User", callback_data='admin_delete_user_start')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)

def admin_premium_requests(update: Update, context: CallbackContext):
    query = update.callback_query
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM premium_requests WHERE status = 'pending'")
    requests = cursor.fetchall()
    
    if not requests:
        query.answer("No pending requests.", show_alert=True)
        return

    text = "<b>Pending Premium Requests:</b>\n\n"
    keyboard = []
    for req in requests:
        user_info = context.bot.get_chat(req['user_id'])
        plan_details = PREMIUM_PLANS[req['plan_name']]
        text += (
            f"<b>Req ID:</b> {req['request_id']}\n"
            f"<b>User:</b> {user_info.first_name} ({req['user_id']})\n"
            f"<b>Plan:</b> {req['plan_name']} (â‚¹{plan_details['price']})\n"
            f"<b>TXN ID:</b> `{req['transaction_id']}`\n"
            f"-------------------\n"
        )
        keyboard.append([
            InlineKeyboardButton(f"âœ… Approve #{req['request_id']}", callback_data=f"admin_approve_{req['request_id']}"),
            InlineKeyboardButton(f"âŒ Reject #{req['request_id']}", callback_data=f"admin_reject_{req['request_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("â¬…ï¸ Back to Admin Panel", callback_data='admin_panel_back')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    conn.close()

def admin_approve_request(update: Update, context: CallbackContext):
    query = update.callback_query
    request_id = int(query.data.split('_')[-1])

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM premium_requests WHERE request_id = ?", (request_id,))
    req = cursor.fetchone()

    if not req:
        query.answer("Request not found.", show_alert=True)
        conn.close()
        return

    user_id = req['user_id']
    plan_key = req['plan_name']
    duration_days = PREMIUM_PLANS[plan_key]['duration_days']
    
    start_date = datetime.now()
    end_date = start_date + timedelta(days=duration_days)

    cursor.execute("UPDATE premium_requests SET status = 'approved' WHERE request_id = ?", (request_id,))
    cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, plan_name, start_date, end_date) VALUES (?, ?, ?, ?)",
                   (user_id, plan_key, start_date, end_date))
    conn.commit()
    conn.close()

    # Notify user
    context.bot.send_message(
        chat_id=user_id,
        text=f"ðŸŽ‰ Congratulations! Your <b>{plan_key.replace('week', ' Week')}</b> premium membership has been approved! "
             f"It is valid until {end_date.strftime('%d %B %Y')}. Enjoy the premium features!"
    )
    query.answer(f"Request #{request_id} approved!")
    # Refresh the list
    admin_premium_requests(update, context)

def admin_reject_request_start(update: Update, context: CallbackContext):
    query = update.callback_query
    request_id = int(query.data.split('_')[-1])
    context.user_data['rejecting_request_id'] = request_id
    query.answer()
    query.edit_message_text(f"You are rejecting request #{request_id}. Please provide a reason for rejection (e.g., 'Payment not received', 'Incorrect transaction ID'). This message will be sent to the user.")
    return ADMIN_REJECT_REASON

def admin_reject_request_finish(update: Update, context: CallbackContext):
    reason = update.message.text
    request_id = context.user_data['rejecting_request_id']
    
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM premium_requests WHERE request_id = ?", (request_id,))
    req = cursor.fetchone()
    if req:
        user_id = req['user_id']
        cursor.execute("UPDATE premium_requests SET status = 'rejected' WHERE request_id = ?", (request_id,))
        conn.commit()
        # Notify user
        context.bot.send_message(
            chat_id=user_id,
            text=f"âš ï¸ Your premium membership request has been rejected.\n\n<b>Reason:</b> {reason}\n\nPlease check the details and try again, or contact support if you believe this is a mistake."
        )
        update.message.reply_text(f"Request #{request_id} has been rejected. The user has been notified.")
    else:
        update.message.reply_text("Request not found.")
    
    conn.close()
    del context.user_data['rejecting_request_id']
    admin_panel(update, context) # Go back to admin panel
    return ConversationHandler.END


# TODO: Implement Admin Broadcast and other admin features in a similar fashion.
# For brevity, leaving these as placeholders to be developed.# =============================================================================
# === ADMIN BROADCAST CONVERSATION ============================================
# =============================================================================
def admin_broadcast_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    keyboard = [[InlineKeyboardButton("Cancel Broadcast", callback_data='admin_panel_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        "Please send the message you want to broadcast.\n"
        "It can be text, a photo with a caption, or a video with a caption.",
        reply_markup=reply_markup
    )
    return ADMIN_BROADCAST_CONTENT

def admin_broadcast_get_content(update: Update, context: CallbackContext):
    message = update.effective_message
    
    # Store the message content
    if message.text:
        context.chat_data['broadcast_text'] = message.text
        context.chat_data['broadcast_photo'] = None
        context.chat_data['broadcast_video'] = None
    elif message.photo:
        context.chat_data['broadcast_text'] = message.caption
        context.chat_data['broadcast_photo'] = message.photo[-1].file_id # Highest res
        context.chat_data['broadcast_video'] = None
    elif message.video:
        context.chat_data['broadcast_text'] = message.caption
        context.chat_data['broadcast_photo'] = None
        context.chat_data['broadcast_video'] = message.video.file_id
    else:
        message.reply_text("Unsupported message type. Please send text, a photo, or a video.")
        return ADMIN_BROADCAST_CONTENT

    # Ask for target audience
    keyboard = [
        [InlineKeyboardButton("All Users", callback_data='broadcast_target_all')],
        [InlineKeyboardButton("Male Users", callback_data='broadcast_target_Male')],
        [InlineKeyboardButton("Female Users", callback_data='broadcast_target_Female')],
        [InlineKeyboardButton("Premium Users", callback_data='broadcast_target_premium')],
        [InlineKeyboardButton("Free Users", callback_data='broadcast_target_free')],
        [InlineKeyboardButton("Cancel", callback_data='admin_panel_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message.reply_text("Message received. Who should receive this broadcast?", reply_markup=reply_markup)
    return ADMIN_BROADCAST_TARGET

def admin_broadcast_get_target(update: Update, context: CallbackContext):
    query = update.callback_query
    target = query.data.split('_')[-1] # all, Male, Female, premium, free
    context.chat_data['broadcast_target'] = target

    query.answer()
    keyboard = [
        [InlineKeyboardButton("âœ… Yes, Send Now", callback_data='broadcast_confirm_yes')],
        [InlineKeyboardButton("âŒ No, Cancel", callback_data='admin_panel_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"You are about to send a broadcast to: <b>{target.capitalize()} Users</b>.\n\nAre you sure?", 
                            reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    return ADMIN_BROADCAST_CONFIRM

def admin_broadcast_execute(update: Update, context: CallbackContext):
    query = update.callback_query
    query.edit_message_text("Broadcast in progress... Please wait. This may take a while.", reply_markup=None)

    target = context.chat_data['broadcast_target']
    
    conn = db_connect()
    cursor = conn.cursor()

    sql_query = "SELECT user_id FROM users"
    conditions = []

    if target == 'Male':
        conditions.append("gender = 'Male'")
    elif target == 'Female':
        conditions.append("gender = 'Female'")
    
    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)

    cursor.execute(sql_query)
    all_user_ids = [row['user_id'] for row in cursor.fetchall()]

    if target == 'premium':
        cursor.execute("SELECT user_id FROM premium_users WHERE end_date > CURRENT_TIMESTAMP")
        target_user_ids = [row['user_id'] for row in cursor.fetchall()]
    elif target == 'free':
        cursor.execute("SELECT user_id FROM premium_users WHERE end_date > CURRENT_TIMESTAMP")
        premium_ids = {row['user_id'] for row in cursor.fetchall()}
        target_user_ids = [uid for uid in all_user_ids if uid not in premium_ids]
    else:
        target_user_ids = all_user_ids
    
    conn.close()

    # Get content from context
    text = context.chat_data.get('broadcast_text')
    photo_id = context.chat_data.get('broadcast_photo')
    video_id = context.chat_data.get('broadcast_video')

    sent_count = 0
    failed_count = 0

    for user_id in target_user_ids:
        try:
            if photo_id:
                context.bot.send_photo(chat_id=user_id, photo=photo_id, caption=text, parse_mode=ParseMode.HTML)
            elif video_id:
                context.bot.send_video(chat_id=user_id, video=video_id, caption=text, parse_mode=ParseMode.HTML)
            else:
                context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Could not send broadcast to {user_id}: {e}")
            failed_count += 1
    
    result_message = (
        f"ðŸ“¢ <b>Broadcast Complete!</b>\n\n"
        f"<b>Target:</b> {target.capitalize()} Users\n"
        f"<b>Total Users in Target Group:</b> {len(target_user_ids)}\n"
        f"<b>Messages Sent Successfully:</b> {sent_count}\n"
        f"<b>Failed to Send:</b> {failed_count} (users may have blocked the bot)"
    )
    
    keyboard = [[InlineKeyboardButton("â¬…ï¸ Back to Admin Panel", callback_data='admin_panel_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(result_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    # Clean up context data
    for key in ['broadcast_text', 'broadcast_photo', 'broadcast_video', 'broadcast_target']:
        if key in context.chat_data:
            del context.chat_data[key]
            
    return ConversationHandler.END
velopment.", show_alert=True)

def admin_reports(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("Reports feature is under development.", show_alert=True)

def admin_delete_user_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("Delete user feature is under development.", show_alert=True)
    # NEW FUNCTION FOR ADMIN TO VIEW ANY USER PROFILE
def admin_view_user(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Please provide a User ID. Usage: /viewuser <USER_ID>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        update.message.reply_text("Invalid User ID. Please provide a number.")
        return

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_user_id,))
    user_data = cursor.fetchone()

    if not user_data:
        update.message.reply_text(f"No profile found for User ID: {target_user_id}")
        conn.close()
        return

    # User profile text
    profile_text = get_user_profile_text(target_user_id)
    
    # User photos
    cursor.execute("SELECT file_id FROM photos WHERE user_id = ?", (target_user_id,))
    photos = cursor.fetchall()
    conn.close()
    
    update.message.reply_text(f"--- Admin View: Profile for {target_user_id} ---")

    if photos:
        media_group = [InputMediaPhoto(p['file_id']) for p in photos]
        media_group[0].caption = profile_text
        media_group[0].parse_mode = ParseMode.HTML
        context.bot.send_media_group(chat_id=update.effective_chat.id, media=media_group)
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text=profile_text, parse_mode=ParseMode.HTML)
    
# --- ERROR HANDLER ---
def error_handler(update: Update, context: CallbackContext) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


def main() -> None:
    """Run the bot."""
    # Setup database on start
    setup_database()

    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Profile Creation/Editing Conversation
    profile_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_profile_start, pattern='^create_profile$'),
            CallbackQueryHandler(edit_profile_start, pattern='^edit_profile$')
        ],
        states={
            NAME: [MessageHandler(Filters.text & ~Filters.command, get_name)],
            AGE: [MessageHandler(Filters.text & ~Filters.command, get_age)],
            GENDER: [CallbackQueryHandler(get_gender)],
            COUNTRY: [
                CallbackQueryHandler(get_country, pattern='^(?!OtherCountry$).*'),
                CallbackQueryHandler(get_country, pattern='^OtherCountry$'),
                MessageHandler(Filters.text & ~Filters.command, get_country_text)
            ],
            BIO: [MessageHandler(Filters.text & ~Filters.command, get_bio), CallbackQueryHandler(skip_bio, pattern='^skip_bio$')],
            PHOTOS: [MessageHandler(Filters.photo, get_photo), CallbackQueryHandler(finish_profile_creation, pattern='^finish_photos$')]
        },
        fallbacks=[CommandHandler('start', start)],
        allow_reentry=True
    )
    
    # Like message conversation
    like_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(like_profile, pattern='^like_profile$')],
        states={
            LIKE_MESSAGE: [MessageHandler(Filters.text & ~Filters.command, send_like_message)]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    # Premium purchase conversation
    premium_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_premium_plan, pattern='^buy_premium_')],
        states={
            PREMIUM_TRANSACTION_ID: [MessageHandler(Filters.text & ~Filters.command, receive_transaction_id)]
        },
        fallbacks=[CallbackQueryHandler(premium_menu, pattern='^premium_menu$')]
    )

    # Admin Reject Reason conversation
    admin_reject_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_reject_request_start, pattern='^admin_reject_')],
        states={
            ADMIN_REJECT_REASON: [MessageHandler(Filters.text & ~Filters.command, admin_reject_request_finish)]
        },
        fallbacks=[CommandHandler('admin', admin_panel)]
    )
    
        # Broadcast Conversation Handler
    broadcast_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern='^admin_broadcast_start$')],
        states={
            ADMIN_BROADCAST_CONTENT: [MessageHandler(Filters.text | Filters.photo | Filters.video, admin_broadcast_get_content)],
            ADMIN_BROADCAST_TARGET: [CallbackQueryHandler(admin_broadcast_get_target, pattern='^broadcast_target_')],
            ADMIN_BROADCAST_CONFIRM: [CallbackQueryHandler(admin_broadcast_execute, pattern='^broadcast_confirm_yes$')],
        },
        fallbacks=[CallbackQueryHandler(admin_panel_back, pattern='^admin_panel_back$')],
        per_user=False,  # Important for admin conversations
        per_chat=True,   # To store data in chat_data
    )
    
    # --- Main Handlers ---
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(profile_conv_handler)
    dispatcher.add_handler(like_conv_handler)
    dispatcher.add_handler(premium_conv_handler)
    dispatcher.add_handler(broadcast_conv_handler)

    # In-bot chat handler (must have lower priority)
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command & Filters.private, relay_chat_message), group=1)
    dispatcher.add_handler(CommandHandler("stopchat", stop_chat))

    # --- CallbackQuery Handlers for Menus and Actions ---
    dispatcher.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    dispatcher.add_handler(CallbackQueryHandler(privacy_policy, pattern='^privacy$'))
    dispatcher.add_handler(CallbackQueryHandler(back_to_start_menu, pattern='^back_to_start_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(view_profile, pattern='^view_profile$'))
    dispatcher.add_handler(CallbackQueryHandler(delete_profile_confirm, pattern='^delete_profile_confirm$'))
    dispatcher.add_handler(CallbackQueryHandler(delete_profile_execute, pattern='^delete_profile_execute$'))
    dispatcher.add_handler(CallbackQueryHandler(find_match_start, pattern='^find_match_start$'))
    dispatcher.add_handler(CallbackQueryHandler(find_match_gender_selected, pattern='^match_gender_'))
    dispatcher.add_handler(CallbackQueryHandler(dislike_profile, pattern='^dislike_profile$'))
    dispatcher.add_handler(CallbackQueryHandler(skip_profile, pattern='^skip_profile$'))
    dispatcher.add_handler(CallbackQueryHandler(report_profile, pattern='^report_profile$'))
    dispatcher.add_handler(CallbackQueryHandler(accept_like, pattern='^accept_like_'))
    dispatcher.add_handler(CallbackQueryHandler(reject_like, pattern='^reject_like_'))
    dispatcher.add_handler(CallbackQueryHandler(premium_menu, pattern='^premium_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(my_matches, pattern='^my_matches$'))
    dispatcher.add_handler(CallbackQueryHandler(start_chat_session, pattern='^chatwith_'))

    # --- Admin Handlers ---
    admin_filter = Filters.user(user_id=ADMIN_ID)
    dispatcher.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    dispatcher.add_handler(admin_reject_conv_handler) # Add conversation handler for admin
    dispatcher.add_handler(CallbackQueryHandler(admin_stats, pattern='^admin_stats$', pass_user_data=True, pass_chat_data=True))
    dispatcher.add_handler(CallbackQueryHandler(admin_panel_back, pattern='^admin_panel_back$'))
    dispatcher.add_handler(CallbackQueryHandler(admin_premium_requests, pattern='^admin_premium_requests$'))
    dispatcher.add_handler(CallbackQueryHandler(admin_approve_request, pattern='^admin_approve_'))
    # Placeholder admin handlers
    dispatcher.add_handler(CallbackQueryHandler(admin_broadcast_start, pattern='^admin_broadcast_start$'))
    dispatcher.add_handler(CallbackQueryHandler(admin_reports, pattern='^admin_reports$'))
    dispatcher.add_handler(CallbackQueryHandler(admin_delete_user_start, pattern='^admin_delete_user_start$'))


    # Error handler
    dispatcher.add_error_handler(error_handler)

    # Start the Bot
    updater.start_polling()
    logger.info("Bot started successfully!")
    updater.idle()


if __name__ == '__main__':
    main()