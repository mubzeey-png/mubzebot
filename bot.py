import telebot
from telebot import types
import sqlite3
import os
from datetime import datetime, timedelta

# ==================== CONFIGURATION ====================
TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN_HERE'
ADMIN_ID = 123456789  # Replace with your Telegram user ID or set to None
# ======================================================

bot = telebot.TeleBot(TOKEN)

# ==================== DATABASE SETUP ====================

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()

    # Users table to track progress
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            current_step INTEGER DEFAULT 1,
            join_completed BOOLEAN DEFAULT 0,
            share_completed BOOLEAN DEFAULT 0,
            last_video_received INTEGER DEFAULT 0,
            join_date TIMESTAMP,
            last_active TIMESTAMP
        )
    ''')

    # Steps configuration table - UNLIMITED USERS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS steps_config (
            step_number INTEGER PRIMARY KEY,
            join_link TEXT,
            share_link TEXT,
            video_file_id TEXT,
            video_caption TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Admin settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT
        )
    ''')

    # Insert default admin ID if provided
    if ADMIN_ID:
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (setting_key, setting_value)
            VALUES ('admin_id', ?)
        ''', (str(ADMIN_ID),))

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")

def get_db_connection():
    """Get a database connection"""
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ==================== HELPER FUNCTIONS ====================

def is_admin(user_id):
    """Check if user is admin"""
    if ADMIN_ID and user_id == ADMIN_ID:
        return True

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'admin_id'")
    result = cursor.fetchone()
    conn.close()

    if result:
        try:
            return user_id == int(result['setting_value'])
        except:
            return False
    return False

def get_or_create_user(user_id, username):
    """Get user from database or create if not exists"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Try to get existing user
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        # Create new user
        try:
            cursor.execute('''
                INSERT INTO users (user_id, username, join_date, last_active)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username,
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()

            # Get the newly created user
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
        except sqlite3.IntegrityError:
            # User might have been created by another thread
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
    else:
        # Update last active time
        cursor.execute('''
            UPDATE users SET last_active = ? WHERE user_id = ?
        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))
        conn.commit()

    conn.close()
    return user

def get_step_config(step_number):
    """Get configuration for a specific step"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM steps_config WHERE step_number = ?", (step_number,))
    step = cursor.fetchone()
    conn.close()
    return step

def set_step_config(step_number, join_link=None, share_link=None, video_file_id=None, video_caption=None):
    """Set or update configuration for a step"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # First check if step exists
    cursor.execute("SELECT * FROM steps_config WHERE step_number = ?", (step_number,))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing step
        update_fields = []
        params = []
        
        if join_link is not None:
            update_fields.append("join_link = ?")
            params.append(join_link)
        if share_link is not None:
            update_fields.append("share_link = ?")
            params.append(share_link)
        if video_file_id is not None:
            update_fields.append("video_file_id = ?")
            params.append(video_file_id)
        if video_caption is not None:
            update_fields.append("video_caption = ?")
            params.append(video_caption)
        
        if update_fields:
            params.append(step_number)
            query = f"UPDATE steps_config SET {', '.join(update_fields)} WHERE step_number = ?"
            cursor.execute(query, params)
    else:
        # Insert new step
        cursor.execute('''
            INSERT INTO steps_config (step_number, join_link, share_link, video_file_id, video_caption)
            VALUES (?, ?, ?, ?, ?)
        ''', (step_number, join_link or '', share_link or '', video_file_id or '', video_caption or ''))
    
    conn.commit()
    conn.close()
    return True

# ==================== ADMIN FUNCTIONS ====================

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⚠️ Access denied!")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    buttons = [
        types.InlineKeyboardButton("⚡ Setup Step", callback_data="admin_setup_step"),
        types.InlineKeyboardButton("📋 View Steps", callback_data="admin_view_steps"),
        types.InlineKeyboardButton("👥 View Users", callback_data="admin_view_users"),
        types.InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
        types.InlineKeyboardButton("🔄 Reset Step", callback_data="admin_reset_step"),
        types.InlineKeyboardButton("🎬 Add Video", callback_data="admin_add_video")
    ]
    # Add buttons one below the other
    for button in buttons:
        markup.add(button)

    bot.send_message(message.chat.id, "🛠 **ADMIN PANEL** - UNLIMITED USERS", reply_markup=markup, parse_mode='Markdown')

# ==================== USER FLOW ====================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"

    # Get or create user
    user = get_or_create_user(user_id, username)

    if user:
        current_step = user['current_step']
        
        # Send welcome message with buttons in vertical layout
        send_step_buttons(user_id, current_step)

def send_step_buttons(user_id, step_number):
    """Send buttons for the current step with vertical layout"""
    # Get step configuration
    step_config = get_step_config(step_number)
    
    # Get user progress
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT join_completed, share_completed FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()

    markup = types.InlineKeyboardMarkup(row_width=1)

    if user_data:
        join_completed = bool(user_data['join_completed'])
        share_completed = bool(user_data['share_completed'])

        # Join button
        if join_completed:
            join_btn = types.InlineKeyboardButton("✅ Joined", callback_data=f"mark_join_{step_number}")
        else:
            if step_config and step_config['join_link'] and step_config['join_link'].startswith('http'):
                join_btn = types.InlineKeyboardButton("📊 Join Channel", url=step_config['join_link'])
            else:
                join_btn = types.InlineKeyboardButton("📊 Join (Not Set)", callback_data="no_link_set")

        # Share button
        if share_completed:
            share_btn = types.InlineKeyboardButton("✅ Shared", callback_data=f"mark_share_{step_number}")
        else:
            if step_config and step_config['share_link'] and step_config['share_link'].startswith('http'):
                share_btn = types.InlineKeyboardButton("📤 Share Link", url=step_config['share_link'])
            else:
                share_btn = types.InlineKeyboardButton("📤 Share (Not Set)", callback_data="no_link_set")

        # Add buttons one below the other
        markup.add(join_btn)
        markup.add(share_btn)

        # Check if both completed and video exists
        if join_completed and share_completed:
            if step_config and step_config['video_file_id']:
                markup.add(types.InlineKeyboardButton("🎬 Get Video", callback_data=f"get_video_{step_number}"))
            else:
                markup.add(types.InlineKeyboardButton("🎬 Video Not Set", callback_data="no_video"))
        else:
            # Progress indicator
            progress = ""
            if join_completed and not share_completed:
                progress = " (1/2 tasks done)"
            elif not join_completed and share_completed:
                progress = " (1/2 tasks done)"
            
            if progress:
                markup.add(types.InlineKeyboardButton(f"⏳ Progress{progress}", callback_data="progress_info"))

    # Add Admin Panel button for admin users
    if is_admin(user_id):
        markup.add(types.InlineKeyboardButton("🛠 Admin Panel", callback_data="admin_panel_btn"))

    # Create message
    message_text = f"""
🌟 **STEP {step_number} - UNLIMITED ACCESS** 🌟

📋 **TASKS TO COMPLETE:**
1️⃣ Click *Join Channel* button and join the channel
2️⃣ Click *Share Link* button and share with friends
3️⃣ Click *Get Video* to receive your reward

💡 **INSTRUCTIONS:**
• After completing each task, come back here
• Click the button again to mark as completed
• Both tasks must be completed to get video
• No limit on number of users! 🎉

✅ **YOUR PROGRESS:**
• Join Channel: {'✅ Completed' if join_completed else '❌ Not completed'}
• Share Link: {'✅ Completed' if share_completed else '❌ Not completed'}

⚡ **UNLIMITED USERS SYSTEM** ⚡
"""

    # Send new message with buttons
    bot.send_message(user_id, message_text, reply_markup=markup, parse_mode='Markdown')

# ==================== CALLBACK HANDLERS ====================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data

    # Handle simple callbacks first
    if data == "no_link_set":
        bot.answer_callback_query(call.id, "❌ Admin hasn't set this link yet")
        return

    elif data == "no_video":
        bot.answer_callback_query(call.id, "❌ No video available for this step")
        return

    elif data == "progress_info":
        bot.answer_callback_query(call.id, "Complete both tasks to get video! ✅")
        return

    # Handle admin panel button from user view
    elif data == "admin_panel_btn":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ Access denied!")
            return
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("⚡ Setup Step", callback_data="admin_setup_step"),
            types.InlineKeyboardButton("📋 View Steps", callback_data="admin_view_steps"),
            types.InlineKeyboardButton("👥 View Users", callback_data="admin_view_users"),
            types.InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
            types.InlineKeyboardButton("🔄 Reset Step", callback_data="admin_reset_step"),
            types.InlineKeyboardButton("🎬 Add Video", callback_data="admin_add_video")
        ]
        for button in buttons:
            markup.add(button)
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🛠 **ADMIN PANEL** - UNLIMITED USERS",
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return

    # Handle task completion marking
    elif data.startswith("mark_join_"):
        try:
            step_number = int(data.split("_")[2])
            conn = get_db_connection()
            cursor = conn.cursor()

            # Mark join as completed
            cursor.execute('''
                UPDATE users
                SET join_completed = 1
                WHERE user_id = ? AND current_step = ?
            ''', (user_id, step_number))

            conn.commit()
            conn.close()

            bot.answer_callback_query(call.id, "✅ Join marked as completed!")
            # Refresh buttons
            try:
                # Delete old message
                bot.delete_message(user_id, call.message.message_id)
            except:
                pass
            # Send new message with updated buttons
            send_step_buttons(user_id, step_number)
            return

        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Error updating")
            print(f"Error: {e}")
            return

    elif data.startswith("mark_share_"):
        try:
            step_number = int(data.split("_")[2])
            conn = get_db_connection()
            cursor = conn.cursor()

            # Mark share as completed
            cursor.execute('''
                UPDATE users
                SET share_completed = 1
                WHERE user_id = ? AND current_step = ?
            ''', (user_id, step_number))

            conn.commit()
            conn.close()

            bot.answer_callback_query(call.id, "✅ Share marked as completed!")
            # Refresh buttons
            try:
                # Delete old message
                bot.delete_message(user_id, call.message.message_id)
            except:
                pass
            # Send new message with updated buttons
            send_step_buttons(user_id, step_number)
            return

        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Error updating")
            print(f"Error: {e}")
            return

    # Handle video requests - NO LIMITS!
    elif data.startswith("get_video_"):
        try:
            step_number = int(data.split("_")[2])
            conn = get_db_connection()
            cursor = conn.cursor()

            # Check if user has completed both tasks
            cursor.execute('''
                SELECT join_completed, share_completed
                FROM users
                WHERE user_id = ? AND current_step = ?
            ''', (user_id, step_number))

            user_progress = cursor.fetchone()

            if user_progress and bool(user_progress['join_completed']) and bool(user_progress['share_completed']):
                # Get video for this step
                cursor.execute('''
                    SELECT video_file_id, video_caption
                    FROM steps_config
                    WHERE step_number = ?
                ''', (step_number,))

                video_data = cursor.fetchone()

                if video_data and video_data['video_file_id']:
                    try:
                        # Send the video
                        bot.send_video(
                            user_id,
                            video_data['video_file_id'],
                            caption=video_data['video_caption'] or f"🎬 **Step {step_number} Video**",
                            parse_mode='Markdown'
                        )

                        # Update user to next step
                        cursor.execute('''
                            UPDATE users
                            SET current_step = current_step + 1,
                                join_completed = 0,
                                share_completed = 0,
                                last_video_received = ?
                            WHERE user_id = ?
                        ''', (step_number, user_id))

                        conn.commit()
                        bot.answer_callback_query(call.id, "✅ Video sent! Moving to next step...")
                        
                        # DELETE the old message with buttons
                        try:
                            bot.delete_message(user_id, call.message.message_id)
                        except:
                            pass  # If can't delete, continue anyway
                        
                        # Send next step buttons in a NEW message
                        send_step_buttons(user_id, step_number + 1)

                    except Exception as e:
                        bot.answer_callback_query(call.id, "❌ Error sending video")
                        print(f"Video error: {e}")
                else:
                    bot.answer_callback_query(call.id, "❌ No video configured for this step")
            else:
                bot.answer_callback_query(call.id, "❌ Complete both tasks first!")

            conn.close()
            return

        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Error processing request")
            print(f"Get video error: {e}")
            return

    # ==================== ADMIN CALLBACKS ====================

    elif data.startswith("admin_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ Access denied!")
            return

        if data == "admin_setup_step":
            msg = bot.send_message(
                user_id,
                "⚡ **QUICK STEP SETUP** ⚡\n\n"
                "Send in this format:\n"
                "`STEP|JOIN_LINK|SHARE_LINK`\n\n"
                "**Examples:**\n"
                "• `1|https://t.me/joinchat/XXX|https://t.me/share/url?url=YYY`\n"
                "• `2|https://t.me/joinchat/AAA|https://t.me/share/url?url=BBB`\n"
                "• `3||https://t.me/share/url?url=CCC` (no join link)\n"
                "• `4|https://t.me/joinchat/DDD|` (no share link)\n\n"
                "**Note:** Videos can be added separately",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, admin_setup_step)

        elif data == "admin_view_steps":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM steps_config ORDER BY step_number")
            steps = cursor.fetchall()
            conn.close()

            if steps:
                response = "📋 **ALL CONFIGURED STEPS:**\n\n"
                for step in steps:
                    response += f"**STEP {step['step_number']}:**\n"
                    response += f"• Join: `{step['join_link'][:50] if step['join_link'] else '❌ NOT SET'}`\n"
                    response += f"• Share: `{step['share_link'][:50] if step['share_link'] else '❌ NOT SET'}`\n"
                    response += f"• Video: {'✅ SET' if step['video_file_id'] else '❌ NOT SET'}\n"
                    response += f"• Caption: {step['video_caption'][:40] if step['video_caption'] else 'No caption'}\n\n"
            else:
                response = "❌ No steps configured yet."

            bot.send_message(user_id, response, parse_mode='Markdown')

        elif data == "admin_view_users":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY current_step DESC LIMIT 50")
            users = cursor.fetchall()
            conn.close()

            if users:
                response = "👥 **RECENT USERS (Max 50):**\n\n"
                for user in users:
                    response += f"• ID: `{user['user_id']}`\n"
                    response += f"• User: @{user['username']}\n"
                    response += f"• Current Step: {user['current_step']}\n"
                    response += f"• Progress: Join {'✅' if user['join_completed'] else '❌'} | Share {'✅' if user['share_completed'] else '❌'}\n"
                    response += f"• Last Video: Step {user['last_video_received'] or 'None'}\n"
                    response += f"• Joined: {user['join_date']}\n\n"
            else:
                response = "❌ No users yet."

            bot.send_message(user_id, response, parse_mode='Markdown')

        elif data == "admin_stats":
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Total users
            cursor.execute("SELECT COUNT(*) as total FROM users")
            total_users = cursor.fetchone()['total']
            
            # Active users (last 7 days)
            week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("SELECT COUNT(*) as active FROM users WHERE last_active > ?", (week_ago,))
            active_users = cursor.fetchone()['active']
            
            # Users by step
            cursor.execute("SELECT current_step, COUNT(*) as count FROM users GROUP BY current_step ORDER BY current_step")
            steps_data = cursor.fetchall()
            
            # Steps with configuration
            cursor.execute("SELECT COUNT(*) as total FROM steps_config")
            configured_steps = cursor.fetchone()['total']
            
            # Videos configured
            cursor.execute("SELECT COUNT(*) as total FROM steps_config WHERE video_file_id != ''")
            videos_configured = cursor.fetchone()['total']
            
            # Total videos sent
            cursor.execute("SELECT SUM(last_video_received) as total FROM users WHERE last_video_received > 0")
            videos_sent = cursor.fetchone()['total'] or 0
            
            conn.close()
            
            response = "📊 **BOT STATISTICS - UNLIMITED USERS** 📊\n\n"
            response += f"👥 Total Users: **{total_users}**\n"
            response += f"🔥 Active Users (7 days): **{active_users}**\n"
            response += f"⚙️ Configured Steps: **{configured_steps}**\n"
            response += f"🎬 Videos Configured: **{videos_configured}**\n"
            response += f"📤 Total Videos Sent: **{videos_sent}**\n\n"
            
            response += "**USERS BY STEP:**\n"
            if steps_data:
                for data in steps_data:
                    response += f"Step {data['current_step']}: {data['count']} users\n"
            else:
                response += "No data available\n"
            
            response += f"\n✅ **UNLIMITED ACCESS - NO USER LIMITS!** ✅"
            
            bot.send_message(user_id, response, parse_mode='Markdown')

        elif data == "admin_reset_step":
            msg = bot.send_message(
                user_id,
                "🔄 **RESET STEP CONFIGURATION**\n\n"
                "Send step number to reset:\n"
                "Example: `2`\n\n"
                "This will clear join/share links and video for that step.",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, admin_reset_step)

        elif data == "admin_add_video":
            msg = bot.send_message(
                user_id,
                "🎬 **ADD VIDEO TO STEP**\n\n"
                "First, send the video file\n"
                "Then send: `STEP|CAPTION`\n\n"
                "Example: `1|Enjoy this exclusive video!`",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, admin_receive_video)

    bot.answer_callback_query(call.id)

# ==================== ADMIN PROCESSING ====================

def admin_setup_step(message):
    if not is_admin(message.from_user.id):
        return

    try:
        parts = message.text.split('|')
        if len(parts) < 3:
            bot.send_message(message.chat.id, "❌ Format: STEP|JOIN_LINK|SHARE_LINK")
            return

        step = int(parts[0].strip())
        join_link = parts[1].strip() if len(parts[1].strip()) > 0 else None
        share_link = parts[2].strip() if len(parts[2].strip()) > 0 else None

        # Set the configuration
        set_step_config(step, join_link, share_link)

        bot.send_message(
            message.chat.id,
            f"✅ **STEP {step} SETUP COMPLETE!** ✅\n\n"
            f"• Join Link: {'✅ SET' if join_link else '❌ NOT SET'}\n"
            f"• Share Link: {'✅ SET' if share_link else '❌ NOT SET'}\n\n"
            f"**UNLIMITED USERS CAN ACCESS THIS STEP!** 🎉\n\n"
            f"To add video: Send video file then reply with `/addvideo {step}|Your Caption`",
            parse_mode='Markdown'
        )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid format! Use: STEP|JOIN_LINK|SHARE_LINK")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

def admin_receive_video(message):
    if not is_admin(message.from_user.id):
        return

    if message.video:
        video_file_id = message.video.file_id
        video_caption = message.caption or ""

        msg = bot.send_message(
            message.chat.id,
            "✅ **Video received!**\n\n"
            "Now send: `STEP|CAPTION`\n"
            "Example: `1|Enjoy this exclusive video!`\n\n"
            "Or send video caption only: `Your caption here`\n"
            "(Will use last video sent)",
            parse_mode='Markdown'
        )
        
        # Store video info temporarily
        bot.register_next_step_handler(msg, lambda m: admin_save_video(m, video_file_id, video_caption))
    else:
        bot.send_message(message.chat.id, "❌ Please send a video file first!")

def admin_save_video(message, video_file_id, existing_caption=""):
    if not is_admin(message.from_user.id):
        return

    try:
        text = message.text.strip()
        
        # Check if format is STEP|CAPTION
        if '|' in text:
            step, caption = text.split('|', 1)
            step = int(step.strip())
            caption = caption.strip()
        else:
            # If only caption provided, ask for step
            caption = text
            msg = bot.send_message(
                message.chat.id,
                "📝 **Caption received!**\n\n"
                "Now send step number:\n"
                "Example: `1`",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, lambda m: admin_save_video_final(m, video_file_id, caption))
            return
        
        # Save video to step
        set_step_config(step, video_file_id=video_file_id, video_caption=caption)

        bot.send_message(
            message.chat.id,
            f"✅ **VIDEO ADDED TO STEP {step}!** ✅\n\n"
            f"Caption: {caption}\n\n"
            f"Users can now get this video after completing Step {step} tasks! 🎬",
            parse_mode='Markdown'
        )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid step number!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

def admin_save_video_final(message, video_file_id, caption):
    if not is_admin(message.from_user.id):
        return

    try:
        step = int(message.text.strip())
        
        # Save video to step
        set_step_config(step, video_file_id=video_file_id, video_caption=caption)

        bot.send_message(
            message.chat.id,
            f"✅ **VIDEO ADDED TO STEP {step}!** ✅\n\n"
            f"Caption: {caption}\n\n"
            f"Users can now get this video after completing Step {step} tasks! 🎬",
            parse_mode='Markdown'
        )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid step number!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

def admin_reset_step(message):
    if not is_admin(message.from_user.id):
        return

    try:
        step_number = int(message.text.strip())

        conn = get_db_connection()
        cursor = conn.cursor()

        # Clear step configuration
        cursor.execute("DELETE FROM steps_config WHERE step_number = ?", (step_number,))
        
        conn.commit()
        conn.close()

        if cursor.rowcount > 0:
            bot.send_message(
                message.chat.id,
                f"✅ **STEP {step_number} RESET COMPLETE!**\n\n"
                f"All configuration cleared for Step {step_number}.",
                parse_mode='Markdown'
            )
        else:
            bot.send_message(message.chat.id, f"❌ Step {step_number} not found")

    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid step number!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

# ==================== EASY VIDEO ADD COMMAND ====================

@bot.message_handler(commands=['addvideo'])
def admin_add_video_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⚠️ Access denied!")
        return

    if message.reply_to_message and message.reply_to_message.video:
        try:
            # Get step number and caption from command
            parts = message.text.split()
            if len(parts) < 2:
                bot.reply_to(message, "❌ Usage: /addvideo STEP|CAPTION (reply to a video)")
                return

            step_caption = parts[1].split('|', 1)
            if len(step_caption) < 2:
                bot.reply_to(message, "❌ Format: /addvideo STEP|CAPTION")
                return

            step = int(step_caption[0].strip())
            caption = step_caption[1].strip()
            video_file_id = message.reply_to_message.video.file_id

            # Save video
            set_step_config(step, video_file_id=video_file_id, video_caption=caption)

            bot.reply_to(
                message,
                f"✅ **Video added to Step {step}!** ✅\n\n"
                f"Caption: {caption}\n"
                f"Unlimited users can now access this video! 🎉",
                parse_mode='Markdown'
            )

        except ValueError:
            bot.reply_to(message, "❌ Invalid step number!")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")
    else:
        bot.reply_to(message, "❌ Please reply to a video message with this command!")

# ==================== BOT START ====================

if __name__ == "__main__":
    print("🤖 Initializing database...")
    print("✅ UNLIMITED USERS SYSTEM")
    print("✅ NO MEMBER LIMITS")

    # Clean up old database for fresh start
    if os.path.exists('bot_database.db'):
        try:
            os.remove('bot_database.db')
            print("🗑️ Removed old database for fresh start")
        except:
            print("⚠️ Could not remove old database, continuing...")

    init_db()

    if not ADMIN_ID:
        print("\n⚠️ IMPORTANT: ADMIN_ID is not set!")
        print("To get your Telegram ID:")
        print("1. Open Telegram")
        print("2. Search for @userinfobot")
        print("3. Send /start to get your ID")

        try:
            admin_input = input("\nEnter your Telegram ID (or press Enter to skip): ").strip()
            if admin_input:
                ADMIN_ID = int(admin_input)
                print(f"✅ Admin ID set to: {ADMIN_ID}")

                # Save to database
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO admin_settings (setting_key, setting_value)
                    VALUES ('admin_id', ?)
                ''', (str(ADMIN_ID),))
                conn.commit()
                conn.close()
            else:
                print("⚠️ Bot will start without admin ID set")
        except ValueError:
            print("❌ Invalid ID format. Bot will start without admin ID.")
        except Exception as e:
            print(f"❌ Error: {e}")

    print("\n" + "="*50)
    print("🤖 BOT STARTING - UNLIMITED USERS SYSTEM")
    print("="*50)
    print("\n✅ Commands for Users:")
    print("• /start - Begin or continue steps")
    print("\n✅ Commands for Admin:")
    print("• /admin - Open admin panel")
    print("• /addvideo STEP|CAPTION - Add video (reply to video)")
    print("\n⚡ Features:")
    print("• Admin panel button in welcome message for admins")
    print("• All buttons displayed vertically (one below another)")
    print("• Unlimited users - no limits!")
    print("\n🎉 UNLIMITED USERS - NO LIMITS!")
    print("="*50)

    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=5)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Bot error: {e}")