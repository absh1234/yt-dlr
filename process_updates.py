#!/usr/bin/env python3
import argparse, json, os, sys, requests, re

# دریافت آرگومان‌ها
parser = argparse.ArgumentParser()
parser.add_argument('--token', required=True, help='Bale Bot Token')
parser.add_argument('--gh_pat', required=True, help='GitHub Personal Access Token')
parser.add_argument('--repo', required=True, help='Repository (owner/name)')
parser.add_argument('--guardnet_key', required=True, help='Guardnet API Key')
parser.add_argument('--chat_id', required=True, help='Default chat ID for errors')
args = parser.parse_args()

BALE_TOKEN = args.token
GH_PAT = args.gh_pat
REPO = args.repo
GUARDNET_KEY = args.guardnet_key
CHAT_ID_FALLBACK = args.chat_id

BASE_URL = f"https://tapi.bale.ai/bot{BALE_TOKEN}"
GH_API = "https://api.github.com"
HEADERS_GH = {
    "Authorization": f"Bearer {GH_PAT}",
    "Accept": "application/vnd.github.v3+json"
}

# توابع کمکی
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{BASE_URL}/sendMessage", json=payload)

def answer_callback(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    requests.post(f"{BASE_URL}/answerCallbackQuery", json=payload)

def update_state(chat_id, new_state):
    state = load_state()
    state[str(chat_id)] = new_state
    save_state(state)

def get_state(chat_id):
    return load_state().get(str(chat_id))

def load_state():
    try:
        with open('bale_state.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_state(state):
    with open('bale_state.json', 'w') as f:
        json.dump(state, f, indent=2)

def trigger_workflow(workflow_file, inputs):
    url = f"{GH_API}/repos/{REPO}/actions/workflows/{workflow_file}/dispatches"
    r = requests.post(url, headers=HEADERS_GH, json={"ref":"main","inputs":inputs})
    return r.status_code

# منوها
MAIN_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "🎬 یوتیوب", "callback_data": "menu_youtube"},
         {"text": "📦 ریلیز", "callback_data": "menu_release"}]
    ]
}

YT_QUALITY_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "🎥 بهترین کیفیت", "callback_data": "yt_best"}],
        [{"text": "📺 720p", "callback_data": "yt_720p"}],
        [{"text": "🎵 فقط صدا", "callback_data": "yt_audio"}]
    ]
}

# پردازش اصلی
with open('updates.json', 'r') as f:
    data = json.load(f)

updates = data.get('result', [])
if not updates:
    sys.exit(0)

for upd in updates:
    if 'message' in upd:
        msg = upd['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '').strip()

        if text == '/start':
            update_state(chat_id, {'step': 'main'})
            send_message(chat_id, "به ربات دانلودر خوش آمدید! لطفاً یک گزینه را انتخاب کنید:", MAIN_KEYBOARD)
            continue

        state = get_state(chat_id) or {'step': 'main'}
        if state['step'] == 'await_repo':
            repo_name = text.split()[0]
            resp = requests.get(f"{GH_API}/repos/{repo_name}", headers=HEADERS_GH)
            if resp.status_code != 200:
                send_message(chat_id, "❌ مخزن یافت نشد. لطفاً دوباره امتحان کنید.")
                continue
            rel_resp = requests.get(f"{GH_API}/repos/{repo_name}/releases?per_page=10", headers=HEADERS_GH)
            if rel_resp.status_code != 200 or not rel_resp.json():
                send_message(chat_id, "❌ هیچ ریلیزی برای این مخزن پیدا نشد.")
                continue
            releases = rel_resp.json()
            keyboard = {"inline_keyboard": []}
            for rel in releases[:10]:
                tag = rel['tag_name']
                keyboard['inline_keyboard'].append([{"text": tag, "callback_data": f"rel_tag:{repo_name}:{tag}"}])
            send_message(chat_id, "📌 یک نسخه را انتخاب کنید:", keyboard)
            update_state(chat_id, {'step': 'choose_release', 'repo': repo_name})

        elif state['step'] == 'await_yt_url':
            quality = state.get('quality', 'best')
            url = text
            trigger_workflow('yt-downloader.yml', {
                'url': url,
                'quality': quality,
                'chat_id': str(chat_id)
            })
            send_message(chat_id, "✅ درخواست دریافت شد. لینک دانلود به‌زودی ارسال می‌شود.")
            update_state(chat_id, {'step': 'main'})
        else:
            send_message(chat_id, "لطفاً یکی از گزینه‌های منو را انتخاب کنید.", MAIN_KEYBOARD)

    elif 'callback_query' in upd:
        cb = upd['callback_query']
        chat_id = cb['message']['chat']['id']
        cb_id = cb['id']
        data = cb['data']

        answer_callback(cb_id)

        if data in ('menu_youtube', 'yt_start'):
            send_message(chat_id, "کیفیت مورد نظر را انتخاب کنید:", YT_QUALITY_KEYBOARD)
            update_state(chat_id, {'step': 'choose_yt_quality'})

        elif data in ('menu_release', 'rel_start'):
            send_message(chat_id, "لطفاً نام مخزن را به صورت owner/repo ارسال کنید:")
            update_state(chat_id, {'step': 'await_repo'})

        elif data in ('yt_best', 'yt_720p', 'yt_audio'):
            quality_map = {'yt_best': 'best', 'yt_720p': '720p', 'yt_audio': 'audio'}
            quality = quality_map[data]
            update_state(chat_id, {'step': 'await_yt_url', 'quality': quality})
            send_message(chat_id, "لطفاً لینک ویدیو یوتیوب را ارسال کنید:")

        elif data.startswith('rel_tag:'):
            _, repo, tag = data.split(':', 2)
            rel_url = f"{GH_API}/repos/{repo}/releases/tags/{tag}"
            rel_resp = requests.get(rel_url, headers=HEADERS_GH)
            if rel_resp.status_code != 200:
                send_message(chat_id, "❌ خطا در دریافت اطلاعات ریلیز.")
                continue
            rel_data = rel_resp.json()
            assets = rel_data.get('assets', [])
            if not assets:
                send_message(chat_id, "این ریلیز فایلی برای دانلود ندارد.")
                continue
            keyboard = {"inline_keyboard": []}
            for asset in assets:
                name = asset['name']
                keyboard['inline_keyboard'].append([{"text": name, "callback_data": f"rel_asset:{repo}:{tag}:{name}"}])
            send_message(chat_id, "📎 فایل مورد نظر را انتخاب کنید:", keyboard)
            update_state(chat_id, {'step': 'choose_asset', 'repo': repo, 'tag': tag})

        elif data.startswith('rel_asset:'):
            _, repo, tag, asset_name = data.split(':', 3)
            trigger_workflow('release-downloader.yml', {
                'repo': repo,
                'asset_name': asset_name,
                'tag': tag
            })
            send_message(chat_id, f"✅ درخواست دانلود `{asset_name}` از `{repo}` دریافت شد. فایل به‌زودی در بله ارسال می‌شود.")
            update_state(chat_id, {'step': 'main'})

        else:
            print(f"callback ناشناخته: {data}")
