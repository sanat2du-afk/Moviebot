
import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from rapidfuzz import process, fuzz
from imdb import IMDb

# Environment Variables
API_ID = int(os.environ.get("28473056"))
API_HASH = os.environ.get("")
BOT_TOKEN = os.environ.get("")
MONGO_URI = os.environ.get("")
LOG_CHANNEL = int(os.environ.get(""))
FORCE_SUB_CHANNEL = os.environ.get("")
AUTO_DELETE_TIME = int(os.environ.get("AUTO_DELETE_TIME", 300))

app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["MovieDB"]
collection = db["files"]

ia = IMDb()

SEARCH_CACHE = {}
PAGE_SIZE = 5

# ---------------- UTIL FUNCTIONS ---------------- #

def clean_query(text):
    text = re.sub(r"\b(1080p|720p|480p|hdrip|bluray|x264|hindi|english|esubs)\b", "", text, flags=re.I)
    text = re.sub(r"[^a-zA-Z0-9 ]", "", text)
    return text.strip().lower()

def detect_type(file_name):
    season = re.search(r"S(\d+)", file_name, re.I)
    episode = re.search(r"E(\d+)", file_name, re.I)
    if season and episode:
        return "series", int(season.group(1)), int(episode.group(1))
    return "movie", None, None

async def create_indexes():
    await collection.create_index("file_name")
    await collection.create_index("type")
    await collection.create_index("season")
    await collection.create_index("episode")

async def fetch_imdb(query):
    try:
        search = ia.search_movie(query)
        if not search:
            return None
        movie = ia.get_movie(search[0].movieID)
        title = movie.get("title", "N/A")
        year = movie.get("year", "N/A")
        rating = movie.get("rating", "N/A")
        genres = ", ".join(movie.get("genres", []))
        plot = movie.get("plot outline", "No description available.")
        poster = movie.get("cover url")
        caption = f"""
🎬 <b>{title} ({year})</b>

⭐ <b>Rating:</b> {rating}
🎭 <b>Genres:</b> {genres}

📝 <b>Story:</b>
{plot}
"""
        return poster, caption
    except:
        return None

async def hybrid_search(query):
    query = clean_query(query)
    regex_filter = {"file_name": {"$regex": query, "$options": "i"}}
    results = []
    async for file in collection.find(regex_filter).limit(20):
        results.append(file)
    if results:
        return results

    all_files = []
    async for file in collection.find({}):
        all_files.append(file)
    names = [f["file_name"] for f in all_files]
    matches = process.extract(query, names, scorer=fuzz.token_sort_ratio, limit=15)
    final = []
    for name, score, index in matches:
        if score > 65:
            final.append(all_files[index])
    return final

def get_page_buttons(key, page):
    files = SEARCH_CACHE.get(key, [])
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    buttons = []
    for file in files[start:end]:
        buttons.append([InlineKeyboardButton(file["file_name"][:40], callback_data=f"file#{file['file_id']}")])
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Back", callback_data=f"page#{key}#{page-1}"))
    if end < len(files):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page#{key}#{page+1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(buttons)

# ---------------- SAVE FILES ---------------- #

@app.on_message(filters.chat(LOG_CHANNEL))
async def save_files(client, message):
    if message.document or message.video:
        file = message.document or message.video
        file_name = file.file_name.lower()
        file_type, season, episode = detect_type(file_name)
        await collection.insert_one({
            "file_name": file_name,
            "file_id": file.file_id,
            "type": file_type,
            "season": season,
            "episode": episode
        })

# ---------------- SEARCH ---------------- #

@app.on_message(filters.group & filters.text)
async def search_movie(client, message):
    query = message.text
    results = await hybrid_search(query)
    if not results:
        return await message.reply("❌ Movie/Series Not Found")
    key = f"{message.chat.id}_{message.id}"
    SEARCH_CACHE[key] = results
    markup = get_page_buttons(key, 0)
    await message.reply("🎬 Select your file:", reply_markup=markup)

    poster_data = await fetch_imdb(query)
    if poster_data:
        poster, caption = poster_data
        try:
            await message.reply_photo(poster, caption=caption, parse_mode="html")
        except:
            await message.reply_text(caption, parse_mode="html")

# ---------------- CALLBACK ---------------- #

@app.on_callback_query()
async def callback_handler(client, query):
    data = query.data
    if data.startswith("file#"):
        file_id = data.split("#")[1]
        msg = await query.message.reply_document(file_id)
        await asyncio.sleep(AUTO_DELETE_TIME)
        await msg.delete()
    elif data.startswith("page#"):
        _, key, page = data.split("#")
        page = int(page)
        markup = get_page_buttons(key, page)
        await query.message.edit_reply_markup(markup)
    await query.answer()

async def main():
    await create_indexes()
    await app.start()
    print("Bot started successfully")
    await idle()

from pyrogram import idle

app.run()
