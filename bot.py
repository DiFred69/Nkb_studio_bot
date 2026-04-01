import telebot
from telebot import types
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")


bot = telebot.TeleBot(TOKEN)

# ---------------- DATABASE ----------------

conn = sqlite3.connect("voice_tasks.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
username TEXT PRIMARY KEY,
user_id INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks(
id INTEGER PRIMARY KEY AUTOINCREMENT,
username TEXT,
phrase TEXT,
voice_id TEXT,
approved INTEGER
)
""")

conn.commit()

# ---------------- STATES ----------------

user_states = {}
waiting_for_reason = {}

# ---------------- FILE PARSER ----------------

def parse_task_file(filepath):

    users = {}
    username = None
    current_phrase = None

    with open(filepath, "r", encoding="utf-8") as f:

        for line in f:
            line = line.rstrip()

            if line.startswith("User:"):
                username = line.replace("User:", "").strip().lstrip("@")
                users[username] = []
                current_phrase = None

            elif line.startswith("-"):
                if current_phrase and username:
                    users[username].append(current_phrase.strip())

                current_phrase = line[1:].strip()

            elif line != "":
                if current_phrase is not None:
                    current_phrase += "\n" + line

        if current_phrase and username:
            users[username].append(current_phrase.strip())

    return users

# ---------------- SEND PHRASE ----------------

def send_phrase(user_id, username):

    cursor.execute(
        "SELECT id, phrase FROM tasks WHERE username=? AND approved IS NULL",
        (username,)
    )

    tasks = cursor.fetchall()

    if not tasks:
        bot.send_message(user_id, "✅ Усі фрази виконані!")
        return

    task_id, phrase = tasks[0]

    user_states[user_id] = task_id

    bot.send_message(
        user_id,
        f"🎙 Озвуч фразу:\n\n{phrase}"
    )

# ---------------- START ----------------

@bot.message_handler(commands=["start"])
def start(message):

    username = message.from_user.username
    user_id = message.chat.id

    if not username:
        bot.send_message(user_id, "⚠️ У тебе немає username.")
        return

    cursor.execute(
        "INSERT OR REPLACE INTO users(username,user_id) VALUES(?,?)",
        (username, user_id)
    )
    conn.commit()

    bot.send_message(user_id, f"👋 Привіт @{username}!")

    send_phrase(user_id, username)

# ---------------- VOICE ----------------

@bot.message_handler(content_types=["voice"])
def voice(message):

    user_id = message.chat.id
    username = message.from_user.username

    if user_id not in user_states:
        bot.send_message(user_id, "Напиши /start")
        return

    task_id = user_states[user_id]

    cursor.execute(
        "UPDATE tasks SET voice_id=? WHERE id=?",
        (message.voice.file_id, task_id)
    )
    conn.commit()

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "✅ Відправити на перевірку",
            callback_data=f"send_{task_id}"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "🔄 Перезаписати",
            callback_data=f"redo_{task_id}"
        )
    )

    bot.send_message(
        user_id,
        "Відправити на перевірку?",
        reply_markup=markup
    )

# ---------------- USER BUTTONS ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("send_") or call.data.startswith("redo_"))
def user_buttons(call):

    task_id = int(call.data.split("_")[1])

    if call.data.startswith("redo_"):
        bot.send_message(call.message.chat.id, "🔄 Запиши голос ще раз.")
        return

    cursor.execute(
        "SELECT username, phrase, voice_id FROM tasks WHERE id=?",
        (task_id,)
    )

    username, phrase, voice_id = cursor.fetchone()

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "✅ Прийняти",
            callback_data=f"approve_{task_id}"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "❌ Відхилити",
            callback_data=f"reject_{task_id}"
        )
    )

    bot.send_message(
        ADMIN_ID,
        f"🎧 Озвучка від @{username}\n\n{phrase}"
    )

    bot.send_voice(
        ADMIN_ID,
        voice_id,
        reply_markup=markup
    )

    bot.send_message(call.message.chat.id, "✅ Відправлено на перевірку")

# ---------------- ADMIN BUTTONS ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def admin_buttons(call):

    if call.message.chat.id != ADMIN_ID:
        return

    task_id = int(call.data.split("_")[1])

    cursor.execute(
        "SELECT username, phrase FROM tasks WHERE id=?",
        (task_id,)
    )

    username, phrase = cursor.fetchone()

    cursor.execute(
        "SELECT user_id FROM users WHERE username=?",
        (username,)
    )

    user = cursor.fetchone()

    user_id = user[0] if user else None

    if call.data.startswith("approve_"):

        cursor.execute(
            "UPDATE tasks SET approved=1 WHERE id=?",
            (task_id,)
        )

        conn.commit()

        if user_id:
            bot.send_message(
                user_id,
                f"✅ Фраза прийнята:\n{phrase}"
            )

            send_phrase(user_id, username)

    elif call.data.startswith("reject_"):

        waiting_for_reason[call.from_user.id] = {
        "task_id": task_id,
        "user_id": user_id
    }

    bot.send_message(
        ADMIN_ID,
            f"✏️ Напиши причину відхилення:\n{phrase}"
        )

    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=None
    )

# ---------------- REJECT REASON ----------------

@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_reason, content_types=["text"])
def reject_reason(message):

    if message.from_user.id not in waiting_for_reason:
        return

    data = waiting_for_reason[message.from_user.id]

    task_id = data["task_id"]
    user_id = data["user_id"]

    # 🔥 одразу видаляємо, щоб не повторювалось
    del waiting_for_reason[message.from_user.id]

    cursor.execute(
        "UPDATE tasks SET approved=0 WHERE id=?",
        (task_id,)
    )
    conn.commit()

    bot.send_message(
        user_id,
        f"❌ Озвучку відхилено\n\nПричина:\n{message.text}\n\n🔄 Запиши ще раз."
    )

    del waiting_for_reason[message.from_user.id]

    conn.commit()

    if user_id:
        bot.send_message(
            user_id,
            f"❌ Озвучку відхилено\n\nПричина:\n{reason}\n\nЗапиши ще раз."
        )

    del waiting_for_reason[message.from_user.id]

# ---------------- FILE UPLOAD ----------------

@bot.message_handler(content_types=["document"])
def upload_file(message):

    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ Тільки адмін.")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)

    os.makedirs("uploads", exist_ok=True)

    filepath = os.path.join("uploads", message.document.file_name)

    with open(filepath, "wb") as f:
        f.write(downloaded)

    users_tasks = parse_task_file(filepath)

    for username, phrases in users_tasks.items():

        for phrase in phrases:

            cursor.execute(
                "INSERT INTO tasks(username,phrase,voice_id,approved) VALUES(?,?,?,NULL)",
                (username, phrase, None)
            )

        conn.commit()

        cursor.execute(
            "SELECT user_id FROM users WHERE username=?",
            (username,)
        )

        user = cursor.fetchone()

        if user:
            bot.send_message(
                user[0],
                f"🔔 Тобі призначили {len(phrases)} фраз\nНапиши /start"
            )

    bot.send_message(ADMIN_ID, "✅ Файл оброблено")

# ---------------- RUN ----------------

print("✅ Бот запущений...")

bot.infinity_polling()