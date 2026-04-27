import os, json, requests, re

BALE = os.environ['BALE_TOKEN']
GH_PAT = os.environ['GH_PAT']
REPO = os.environ['REPO']
GUARDNET_KEY = os.environ['GUARDNET_KEY']

API_URL = f"https://tapi.bale.ai/bot{BALE}"
GH_API = "https://api.github.com"

def send_message(chat_id, text, reply_markup=None):
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(f"{API_URL}/sendMessage", json=payload)

def answer_callback(callback_id, text=None):
    payload = {'callback_query_id': callback_id}
    if text:
        payload['text'] = text
    requests.post(f"{API_URL}/answerCallbackQuery", json=payload)

def update_state(chat_id, new_state):
    with open('bale_state.json', 'r+') as f:
        state = json.load(f)
        state[str(chat_id)] = new_state
        f.seek(0)
        json.dump(state, f)
        f.truncate()

def get_state(chat_id):
    try:
        with open('bale_state.json') as f:
            return json.load(f).get(str(chat_id))
    except:
        return None

def trigger_workflow(workflow_file, inputs):
    headers = {
        'Authorization': f'Bearer {GH_PAT}',
        'Accept': 'application/vnd.github.v3+json'
    }
    url = f"{GH_API}/repos/{REPO}/actions/workflows/{workflow_file}/dispatches"
    requests.post(url, json={'ref':'main', 'inputs': inputs}, headers=headers)

# اصلی
with open('updates.json') as f:
    updates = json.load(f).get('result', [])

for upd in updates:
    if 'message' in upd:
        msg = upd['message']
        chat = msg['chat']['id']
        text = msg.get('text', '')
        # مدیریت دستور /start
        if text == '/start':
            keyboard = {'inline_keyboard': [
                [{'text': '🎬 یوتیوب', 'callback_data': 'menu_youtube'},
                 {'text': '📦 ریلیز', 'callback_data': 'menu_release'}]
            ]}
            send_message(chat, "به ربات دانلودر خوش آمدید! لطفاً یکی از گزینه‌ها را انتخاب کنید:", keyboard)
            update_state(chat, {'step': 'main_menu'})
        # حالت‌های مختلف بر اساس state موجود
        else:
            state = get_state(chat)
            if state and state.get('step') == 'await_repo':
                repo = text.strip()
                # دریافت لیست ریلیزها از گیتهاب
                releases = requests.get(f"https://api.github.com/repos/{repo}/releases").json()
                if not releases:
                    send_message(chat, "❌ مخزن پیدا نشد یا ریلیزی ندارد.")
                else:
                    buttons = []
                    for rel in releases[:10]:
                        tag = rel['tag_name']
                        buttons.append([{'text': tag, 'callback_data': f"rel_tag:{repo}:{tag}"}])
                    send_message(chat, "📌 یک نسخه را انتخاب کنید:", {'inline_keyboard': buttons})
                    update_state(chat, {'step': 'choose_release', 'repo': repo})
            # ... ادامه مدیریت سایر state ها و callback_query
    elif 'callback_query' in upd:
        cb = upd['callback_query']
        chat = cb['message']['chat']['id']
        data = cb['data']
        cb_id = cb['id']
        answer_callback(cb_id)  # بستن دکمه
        if data == 'menu_youtube':
            keyboard = {'inline_keyboard': [
                [{'text': '🎥 بهترین کیفیت', 'callback_data': 'yt_best'}],
                [{'text': '📺 720p', 'callback_data': 'yt_720p'}],
                [{'text': '🎵 فقط صدا', 'callback_data': 'yt_audio'}]
            ]}
            send_message(chat, "کیفیت دانلود را انتخاب کنید:", keyboard)
            update_state(chat, {'step': 'choose_yt_quality'})
        elif data == 'menu_release':
            send_message(chat, "لطفاً نام مخزن را به صورت owner/repo ارسال کنید:")
            update_state(chat, {'step': 'await_repo'})
        elif data.startswith('rel_tag:'):
            _, repo, tag = data.split(':',2)
            # دریافت دارایی‌های اون ریلیز
            rel = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}").json()
            assets = rel.get('assets', [])
            buttons = []
            for asset in assets:
                name = asset['name']
                buttons.append([{'text': name, 'callback_data': f"rel_asset:{repo}:{tag}:{name}"}])
            if not assets:
                send_message(chat, "این ریلیز فایلی ندارد.")
            else:
                send_message(chat, "📎 فایل مورد نظر را انتخاب کنید:", {'inline_keyboard': buttons})
        elif data.startswith('rel_asset:'):
            _, repo, tag, asset = data.split(':',3)
            # فراخوانی workflow ریلیز
            trigger_workflow('release-downloader.yml', {
                'repo': repo, 'asset_name': asset, 'tag': tag
            })
            send_message(chat, f"✅ درخواست دانلود {asset} از {repo} دریافت شد. فایل به‌زودی ارسال می‌شود.")
        elif data.startswith('yt_'):
            quality = data
            update_state(chat, {'step': 'await_yt_url', 'quality': quality})
            send_message(chat, "لطفاً لینک ویدیو یوتیوب را ارسال کنید:")

        # سپس هنگام دریافت لینک (state 'await_yt_url')
        state = get_state(chat)
        if state and state.get('step') == 'await_yt_url':
            url = text.strip()
            quality = state['quality']
            trigger_workflow('yt-downloader.yml', {
                'url': url,
                'quality': quality,
                'chat_id': str(chat)
            })
            send_message(chat, "✅ درخواست دریافت شد. لینک دانلود به‌زودی ارسال می‌شود.")
            update_state(chat, {'step': 'main_menu'})
