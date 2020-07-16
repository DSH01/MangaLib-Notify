import telebot
from telebot import types
import requests
import time
from threading import Thread
import xml.etree.ElementTree as ET
import pymongo
import bs4
import config

bot = telebot.TeleBot(config.token)
cluster = pymongo.MongoClient(config.mongodb_client_url)
cl = cluster["mangalib"]
db = cl["mangalib"]
rss_url = "https://mangalib.me/manga-rss/"
headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:77.0) Gecko/20100101 Firefox/77.0',
		   'Accept-language': 'en-US,en;q=0.9'}
add_to_list = False


@bot.callback_query_handler(func=lambda call: True)
def query_handler(call):
	callback = call.data.split()
	global add_to_list
	if callback[0] == 'add':
		add_to_list = False
		add_url = callback[1][20:]
		new_manga = db.find_one({"url": add_url})
		if new_manga is None:
			response = requests.get(url=rss_url + add_url, headers=headers)
			root = ET.fromstring(response.text)
			title = root[0].find("title").text
			users = [call.message.chat.id]
			last_chapter = root[0].find('item').find('title').text
			db.insert_one({"title": title, "url": add_url, "users": users, "last_chapter": last_chapter})
			bot.answer_callback_query(callback_query_id=call.id, text='Успешно добавлено!')
		else:
			if call.message.chat.id not in new_manga["users"]:
				db.update_one({"url": add_url}, {'$set': {"users": new_manga['users'] + [call.message.chat.id]}}, upsert=False)
				bot.answer_callback_query(callback_query_id=call.id, text='Успешно добавлено!')
			else:
				bot.answer_callback_query(callback_query_id=call.id, text='Эта манга уже есть в вашем списке!')
	
	if callback[0] == 'remove':
		title = " ".join(callback[1:])
		manga_to_delete = db.find_one({"title": title})
		users_on_manga = manga_to_delete['users']
		users_on_manga.remove(call.message.chat.id)
		if len(users_on_manga):
			db.update_one({"title": title}, {'$set': {"users": users_on_manga}}, upsert=False)
		else:
			db.delete_one({"title": title})
		
		bot.answer_callback_query(callback_query_id=call.id, text='Успешно удалено!')


@bot.message_handler(commands=['start'])
def start(message):
	markup = types.ReplyKeyboardMarkup()
	itembtn1 = types.KeyboardButton('🗃 Список манги')
	itembtn2 = types.KeyboardButton('➕ Добавить мангу')
	itembtn3 = types.KeyboardButton('🗑 Удалить мангу')
	markup.row(itembtn1)
	markup.row(itembtn2, itembtn3)
	bot.send_message(message.chat.id,
					 text="Чтобы добавлять, удалять и просматривать список манги - используйте кнопки внизу:",
					 reply_markup=markup)


@bot.message_handler(content_types=['text'], func=lambda message: message.text == "🗃 Список манги")
def manga_list(message):
	db_user_manga = db.find({"users": message.chat.id})
	markup = types.InlineKeyboardMarkup(row_width=1)
	for manga in db_user_manga:
		button = types.InlineKeyboardButton(text=manga["title"][5:], url="https://mangalib.me/" + manga["url"])
		markup.add(button)
	bot.send_message(message.chat.id, "*Список манги*\n\n_Чтобы перейти на страницу манги - нажмите нужную кнопку ниже:_", reply_markup=markup,
					 parse_mode="Markdown")


@bot.message_handler(content_types=['text'], func=lambda message: message.text == "➕ Добавить мангу")
def add_manga1(message):
	global add_to_list
	add_to_list = True
	bot.send_message(message.chat.id, "Напишите название, и я попробую найти.")


@bot.message_handler(content_types=['text'], func=lambda message: add_to_list)
def add_manga2(message):
	response = requests.get(f"https://mangalib.me/manga-list?dir=desc&name={message.text}&sort=rate")
	soup = bs4.BeautifulSoup(response.text, "html.parser")
	try:
		item = soup.select_one(".media-card")
		img = requests.get(
			f"https://mangalib.me/uploads/cover/{item['data-media-slug']}/cover/cover_250x350.jpg").content
		markup = types.InlineKeyboardMarkup(row_width=1)
		button = types.InlineKeyboardButton(text='Подтвердить', callback_data=f'add {item["href"]}')
		markup.add(button)
		name = item.select_one('.media-card__caption .media-card__title').getText()
		bot.send_photo(message.chat.id, photo=img,
					   caption=f"*{name}*\n\n_Если это не то что вы искали - проверьте название на самом сайте и напишите заново._",
					   reply_markup=markup, parse_mode="Markdown")
	except TypeError:
		bot.send_message(message.chat.id, "*Ничего не найдено!*", parse_mode="Markdown")


@bot.message_handler(content_types=['text'], func=lambda message: message.text == "🗑 Удалить мангу")
def remove_manga(message):
	db_user_manga = db.find({"users": message.chat.id})
	list_user_manga = [i["title"] for i in db_user_manga]
	markup = types.InlineKeyboardMarkup(row_width=1)
	for manga in list_user_manga:
		button = types.InlineKeyboardButton(text=manga[5:], callback_data=f'remove {manga}')
		markup.add(button)
	bot.send_message(message.chat.id, "*Чтобы удалить мангу, нажмите на нужную кнопку ниже:*", reply_markup=markup,
					 parse_mode="Markdown")


def send_if_new(last_chapter, title, ch_url, ch_date):
	db_chapter = db.find_one({'title': title})
	if last_chapter != db_chapter["last_chapter"]:
		db.update_one({'title': title}, {'$set': {"last_chapter": last_chapter}}, upsert=False)
		send_text = f"_Новая глава!_\n{str(ch_date)}\n\n*{title}\nГлава {last_chapter[last_chapter.find('#'):]}*"
		for user in db_chapter['users']:
			img = requests.get(f"https://mangalib.me/uploads/cover/{db_chapter['url']}/cover/cover_250x350.jpg").content
			markup = types.InlineKeyboardMarkup(row_width=1)
			button = types.InlineKeyboardButton(text='Читать', url=ch_url)
			markup.add(button)
			bot.send_photo(user, photo=img, caption=send_text, reply_markup=markup, parse_mode="Markdown")


def main_check():
	while True:
		mangas = db.find()
		for manga in mangas:
			response = requests.get(url=rss_url + manga['url'], headers=headers)
			root = ET.fromstring(response.text)
			last_chapter = root[0].find('item')
			ch_title = last_chapter.find('title').text
			m_title = root[0].find('title').text
			ch_url = last_chapter.find('guid').text
			ch_date = last_chapter.find('pubDate').text
			send_if_new(ch_title, m_title, ch_url, ch_date)
			time.sleep(1)
		time.sleep(10)


def run_bot():
	while True:
		try:
			bot.polling(none_stop=True)
		except Exception as e:
			print(e)
			time.sleep(5)


if __name__ == "__main__":
	bot_thread = Thread(target=run_bot)
	rss_thread = Thread(target=main_check)
	bot_thread.setDaemon(True)
	rss_thread.setDaemon(True)
	bot_thread.start()
	rss_thread.start()
	while True:
		pass
