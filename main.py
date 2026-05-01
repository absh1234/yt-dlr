import json
import os
import sys
import time
import requests

# ========== خواندن تنظیمات از config.json ==========
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    print("❌ فایل config.json پیدا نشد. لطفاً آن را در کنار اسکریپت ایجاد کنید.")
    sys.exit(1)
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)
BALE_TOKEN = config["BALE_BOT_TOKEN"]
GH_PAT = config["GH_PAT"]
REPO = config["REPO_FULL_NAME"]
GUARDNET_KEY = config.get("GUARDNET_API_KEY", "")
XRAY_CONFIG = config.get("XRAY_CONFIG", "")  # اگر نیاز داشتید اضافه کنید
BASE_URL = f"https://tapi.bale.ai/bot{BALE_TOKEN}"
GH_API = "https://api.github.com"
HEADERS_GH = {
    "Authorization": f"Bearer {GH_PAT}",
    "Accept": "application/vnd.github.v3+json",
}
STATE_FILE = "local_state.json"
OFFSET_FILE = "local_offset"


# ========== بقیه توابع (send_message, answer_callback, ...) ==========
# دقیقاً همان توابعی که در نسخه قبلی بودند را اینجا کپی کنید:
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{BASE_URL}/sendMessage", json=payload)


def answer_callback(cb_id):
    requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": cb_id})


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_user_state(chat_id):
    return load_state().get(str(chat_id), {})


def set_user_state(chat_id, new_state):
    state = load_state()
    state[str(chat_id)] = new_state
    save_state(state)


def dispatch_workflow(workflow_file, inputs):
    url = f"{GH_API}/repos/{REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": "main", "inputs": inputs}
    resp = requests.post(url, headers=HEADERS_GH, json=payload)
    return resp.status_code == 204


# ========== منوها ==========
MAIN_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "🎬 یوتیوب", "callback_data": "menu_youtube"},
            {"text": "📦 ریلیز", "callback_data": "menu_release"},
        ]
    ]
}
YT_QUALITY_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "🎥 بهترین کیفیت", "callback_data": "yt_best"}],
        [{"text": "📺 720p", "callback_data": "yt_720p"}],
        [{"text": "🎵 فقط صدا", "callback_data": "yt_audio"}],
    ]
}


# ========== پردازش یک آپدیت (همان منطق قبلی) ==========
def process_update(upd):
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()
        if text == "/start":
            set_user_state(chat_id, {"step": "main"})
            send_message(chat_id, "به ربات دانلودر خوش آمدید!", MAIN_KEYBOARD)
            return
        state = get_user_state(chat_id)
        step = state.get("step", "main")
        if step == "await_repo":
            repo = text.split()[0]
            r = requests.get(f"{GH_API}/repos/{repo}", headers=HEADERS_GH)
            if r.status_code != 200:
                send_message(chat_id, "❌ مخزن یافت نشد.")
                return
            rel_resp = requests.get(
                f"{GH_API}/repos/{repo}/releases?per_page=10", headers=HEADERS_GH
            )
            if rel_resp.status_code != 200 or not rel_resp.json():
                send_message(chat_id, "❌ ریلیزی برای این مخزن موجود نیست.")
                return
            releases = rel_resp.json()
            keyboard = {"inline_keyboard": []}
            for rel in releases[:10]:
                tag = rel["tag_name"]
                keyboard["inline_keyboard"].append(
                    [{"text": tag, "callback_data": f"rel_tag:{repo}:{tag}"}]
                )
            send_message(chat_id, "📌 یک نسخه را انتخاب کنید:", keyboard)
            set_user_state(chat_id, {"step": "choose_release", "repo": repo})

        elif step == "await_yt_url":
            quality = state.get("quality", "best")
            url = text.strip()
            set_user_state(
                chat_id, {"step": "await_vpn", "quality": quality, "url": url}
            )
            send_message(chat_id, "🔗 لطفا کانفیگ های خود را ارسال کنید")
        elif step == "await_vpn":
            quality = state.get("quality", "best")
            url = state.get("url")
            vpn = text.strip()  # raw multi-line VPN configs

            success = dispatch_workflow(
                "yt-downloader.yml",
                {
                    "url": url,
                    "quality": quality,
                    "target_chat_id": str(chat_id),
                    "vpn_configs": vpn,
                },
            )
            if success:
                send_message(chat_id, "✅ درخواست دریافت شد. ویدیو به‌زودی ارسال می‌شود.")
            else:
                send_message(chat_id, "❌ خطا در ارتباط با گیت‌هاب.")
            set_user_state(chat_id, {"step": "main"})

        else:
            send_message(chat_id, "لطفاً یکی از گزینه‌ها را انتخاب کنید.", MAIN_KEYBOARD)
    elif "callback_query" in upd:
        cb = upd["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        data = cb["data"]
        answer_callback(cb["id"])
        if data in ("menu_youtube", "yt_start"):
            send_message(chat_id, "کیفیت مورد نظر را انتخاب کنید:", YT_QUALITY_KEYBOARD)
            set_user_state(chat_id, {"step": "choose_yt_quality"})
        elif data in ("menu_release", "rel_start"):
            send_message(chat_id, "لطفاً نام مخزن را به صورت `owner/repo` ارسال کنید:")
            set_user_state(chat_id, {"step": "await_repo"})
        elif data in ("yt_best", "yt_720p", "yt_audio"):
            quality_map = {"yt_best": "best", "yt_720p": "720p", "yt_audio": "audio"}
            quality = quality_map[data]
            set_user_state(chat_id, {"step": "await_yt_url", "quality": quality})
            send_message(chat_id, "لطفاً لینک یوتیوب را ارسال کنید:")
        elif data.startswith("rel_tag:"):
            _, repo, tag = data.split(":", 2)
            rel_resp = requests.get(
                f"{GH_API}/repos/{repo}/releases/tags/{tag}", headers=HEADERS_GH
            )
            if rel_resp.status_code != 200:
                send_message(chat_id, "❌ خطا در دریافت اطلاعات نسخه.")
                return
            assets = rel_resp.json().get("assets", [])
            if not assets:
                send_message(chat_id, "این نسخه فایلی ندارد.")
                return
            keyboard = {"inline_keyboard": []}
            for asset in assets:
                name = asset["name"]
                keyboard["inline_keyboard"].append(
                    [{"text": name, "callback_data": f"rel_asset:{repo}:{tag}:{name}"}]
                )
            send_message(chat_id, "📎 فایل مورد نظر را انتخاب کنید:", keyboard)
            set_user_state(chat_id, {"step": "choose_asset", "repo": repo, "tag": tag})
        elif data.startswith("rel_asset:"):
            _, repo, tag, asset_name = data.split(":", 3)
            success = dispatch_workflow(
                "release-downloader.yml",
                {
                    "repo": repo,
                    "asset_name": asset_name,
                    "tag": tag,
                    "target_chat_id": str(chat_id),
                },
            )
            if success:
                send_message(
                    chat_id,
                    f"✅ درخواست دانلود `{asset_name}` ثبت شد. فایل به‌زودی ارسال می‌شود.",
                )
            else:
                send_message(chat_id, "❌ خطا در ارتباط با گیت‌هاب.")
            set_user_state(chat_id, {"step": "main"})


# ========== حلقه اصلی ==========
if __name__ == "__main__":
    offset = 0
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            offset = int(f.read().strip())
    print("ربات محلی فعال شد. منتظر پیام‌ها...")
    while True:
        try:
            resp = requests.get(
                f"{BASE_URL}/getUpdates", params={"offset": offset + 1, "timeout": 10}
            ).json()
            for upd in resp.get("result", []):
                process_update(upd)
                offset = upd["update_id"]
                with open(OFFSET_FILE, "w") as f:
                    f.write(str(offset))
        except Exception as e:
            print(f"خطا: {e}")
            time.sleep(5)
