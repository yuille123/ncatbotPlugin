# plugins/BilibiliParser/main.py

import re
import aiohttp
import json
import os
import asyncio
import requests
import qrcode
from io import BytesIO
import time
import sqlite3
from cryptography.fernet import Fernet
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core import MessageChain, Image, Text
from ncatbot.utils import get_log

bot = CompatibleEnrollment
_log = get_log(__name__)

PARSE_HINT_TEXT = "正在解析....."

# 全局cookies存储
cookies_holder = {}

class BilibiliParser(BasePlugin):
    name = "BilibiliParser"
    version = "1.0.0"
    db_dir = os.path.join(os.path.dirname(__file__), "db")
    db_path = os.path.join(db_dir, "bilibili_cookies.db")
    key_path = os.path.join(db_dir, "bilibili_cookie.key")

    async def on_load(self):
        """插件加载时初始化数据库和密钥，并注册事件与功能"""
        self._init_db_and_key()
        self.cookies = await self.load_cookies()
        _log.info(f"BilibiliParser插件已加载，当前cookies: {bool(self.cookies)}")

        # 同步cookies到全局变量
        await sync_cookies_to_global(self.cookies)

        # 注册消息处理器
        bot.group_event()(handle_message)
        bot.private_event()(handle_message)

        # 注册扫码登录功能
        self.register_admin_func(
            "bparser_login",
            self.handle_login_command,
            prefix="/bparser_login",
            description="B站扫码登录",
            usage="/bparser_login",
            examples=["/bparser_login"]
        )

    async def on_unload(self):
        _log.info("BilibiliParser插件已卸载")

    def _init_db_and_key(self):
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            '''CREATE TABLE IF NOT EXISTS cookies
               (id INTEGER PRIMARY KEY, data TEXT)'''
        )
        conn.commit()
        conn.close()
        if not os.path.exists(self.key_path):
            key = Fernet.generate_key()
            with open(self.key_path, "wb") as f:
                f.write(key)
        with open(self.key_path, "rb") as f:
            self._fernet = Fernet(f.read())

    async def load_cookies(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT data FROM cookies WHERE id=1")
        row = c.fetchone()
        conn.close()
        if row:
            try:
                decrypted = self._fernet.decrypt(row[0].encode()).decode()
                return json.loads(decrypted)
            except Exception:
                return None
        return None

    async def save_cookies(self, cookies):
        encrypted = self._fernet.encrypt(json.dumps(cookies).encode()).decode()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM cookies WHERE id=1")
        c.execute("INSERT INTO cookies (id, data) VALUES (?, ?)", (1, encrypted))
        conn.commit()
        conn.close()
        self.cookies = cookies
        # 同步到全局变量
        await sync_cookies_to_global(cookies)

    async def handle_login_command(self, msg):
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://passport.bilibili.com/login"
            }
            qr_res = requests.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                headers=headers
            )
            if qr_res.status_code != 200 or "application/json" not in qr_res.headers.get("Content-Type", ""):
                await msg.reply(text=f"登录二维码API响应异常，内容：{qr_res.text[:200]}")
                return
            try:
                qr_json = qr_res.json()
            except Exception:
                await msg.reply(text=f"二维码API返回内容无法解析为JSON，内容：{qr_res.text[:200]}")
                return

            qr_data = qr_json.get('data')
            if not qr_data or 'url' not in qr_data or 'qrcode_key' not in qr_data:
                await msg.reply(text=f"二维码API返回内容缺少必要字段，内容：{qr_json}")
                return

            qr_url = qr_data['url']
            qrcode_key = qr_data['qrcode_key']

            qr_img = qrcode.make(qr_url)
            buf = BytesIO()
            qr_img.save(buf, format='PNG')
            buf.seek(0)

            img_dir = "./tmp"
            if not os.path.exists(img_dir):
                os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, f"bili_qr_{int(time.time())}.png")
            try:
                with open(img_path, "wb") as f:
                    f.write(buf.getvalue())
                await msg.reply(text="请使用B站APP扫描二维码登录（3分钟内有效）")
                await msg.reply(image=img_path)
            except Exception:
                await msg.reply(text="二维码图片保存或发送失败，请重试")
                return

            asyncio.create_task(self.check_login_status_bili(msg, qrcode_key))

        except Exception as e:
            await msg.reply(text=f"登录失败: {str(e)}")

    async def check_login_status_bili(self, msg, qrcode_key):
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://passport.bilibili.com/login"
            }
            for _ in range(30):
                await asyncio.sleep(7)
                try:
                    check_res = requests.get(
                        f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}",
                        headers=headers
                    )
                    if "application/json" not in check_res.headers.get("Content-Type", ""):
                        continue
                    status_data = check_res.json()['data']
                except Exception:
                    continue

                if status_data['code'] == 0:
                    self.cookies = {
                        'SESSDATA': requests.utils.dict_from_cookiejar(
                            check_res.cookies
                        ).get('SESSDATA', '')
                    }
                    await self.save_cookies(self.cookies)
                    await msg.reply(text="✅ B站登录成功！")
                    return

                if status_data['code'] == 86038:
                    await msg.reply(text="❌ 二维码已过期，请重新登录")
                    return

                if status_data['code'] == 86061:
                    await msg.reply(text="二维码已扫描，请在APP上确认登录")
                    continue

            await msg.reply(text="❌ 登录超时，请重试")

        except Exception as e:
            await msg.reply(text=f"登录状态检查失败: {str(e)}")
            
    async def check_login_status(self, msg):
        """检查登录状态"""
        check_url = "https://passport.bilibili.com/qrcode/getLoginInfo"
        data = {
            "oauthKey": self.oauthKey,
            "gourl": "https://www.bilibili.com/"
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Referer": "https://passport.bilibili.com/login"
        }
        while True:
            await asyncio.sleep(5)
            async with aiohttp.ClientSession() as session:
                async with session.post(check_url, data=data, headers=headers) as resp:
                    text = await resp.text()
                    try:
                        result = json.loads(text)
                    except Exception as e:
                        await msg.reply(text=f"登录状态检查失败: {e}\n返回内容: {text[:200]}")
                        return

                    if result.get('status'):
                        if result['data'] == -4:  # 二维码未扫描
                            continue
                        elif result['data'] == -5:  # 二维码已扫描未确认
                            await msg.reply(text="二维码已扫描，请在APP上确认登录")
                            continue
                        else:  # 登录成功
                            cookies = resp.cookies
                            await self.save_cookies(dict(cookies))
                            await msg.reply(text="登录成功！cookies已保存")
                            return

async def handle_message(msg):
    """处理包含B站链接的消息或卡片"""
    text = msg.raw_message

    cq_json_match = re.match(r"\[CQ:json,data=(.+)\]", text)
    if cq_json_match:
        try:
            json_str = cq_json_match.group(1)
            json_str = (
                json_str.replace('&#44;', ',')
                        .replace('&quot;', '"')
                        .replace('&amp;', '&')
            )
            card_data = json.loads(json_str)
            meta = card_data.get("meta", {})
            detail = meta.get("detail_1", {})
            url = detail.get("qqdocurl", "") or detail.get("url", "")
            b23_match = re.search(r"(b23\.tv/[a-zA-Z0-9]+)", url)
            if b23_match:
                await msg.reply(text=PARSE_HINT_TEXT)
                video_id = await resolve_short_url("https://" + b23_match.group(1))
                if video_id:
                    await process_bilibili_video(msg, video_id)
                    await try_send_video_file(msg, video_id)
                return
        except Exception as e:
            _log.error(f"解析CQ:json卡片失败: {e}")

    bvid_match = re.search(r"BV([a-zA-Z0-9]{10})", text)
    aid_match = re.search(r"av(\d+)", text)
    short_match = re.search(r"(b23\.tv/[a-zA-Z0-9]+)", text)
    video_id = None

    if bvid_match:
        video_id = f"bvid=BV{bvid_match.group(1)}"
    elif aid_match:
        video_id = f"aid={aid_match.group(1)}"
    elif short_match:
        video_id = await resolve_short_url("https://" + short_match.group(1))

    if video_id:
        await msg.reply(text=PARSE_HINT_TEXT)
        await process_bilibili_video(msg, video_id)
        await try_send_video_file(msg, video_id)

async def resolve_short_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=False) as resp:
            if resp.status == 302:
                location = resp.headers.get('Location', '')
                match = re.search(r"video/(?:av(\d+)|BV([a-zA-Z0-9]{10}))", location)
                if match:
                    if match.group(1):
                        return f"aid={match.group(1)}"
                    elif match.group(2):
                        return f"bvid={match.group(2)}"
    return None

async def process_bilibili_video(msg, video_id):
    api_url = f"https://api.bilibili.com/x/web-interface/view?{video_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/"
    }
    try:
        async with aiohttp.ClientSession(cookies=cookies_holder.get("cookies")) as session:
            async with session.get(api_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    video_info = data.get('data')
                    if not video_info:
                        await msg.reply(text="未获取到视频信息，可能视频不存在或接口变更")
                        return
                    title = video_info.get('title', '')
                    desc = video_info.get('desc', '')
                    if len(desc) > 100:
                        desc = desc[:100] + "..."
                    cover_url = video_info.get('pic', '')
                    stats = video_info.get('stat', {})
                    owner = video_info.get('owner', {})
                    author = owner.get('name', '')
                    play = stats.get('view', 0)
                    danmaku = stats.get('danmaku', 0)
                    like = stats.get('like', 0)
                    coin = stats.get('coin', 0)
                    favorite = stats.get('favorite', 0)
                    reply = stats.get('reply', 0)

                    def fmt_num(n):
                        try:
                            n = int(n)
                            if n >= 10000:
                                return f"{n/10000:.1f}万"
                            return str(n)
                        except Exception:
                            return str(n)

                    info_text = (
                        f"作者: {author}\n"
                        f"播放: {fmt_num(play)} | 弹幕: {fmt_num(danmaku)}\n"
                        f"点赞: {fmt_num(like)} | 投币: {fmt_num(coin)}\n"
                        f"收藏: {fmt_num(favorite)} | 评论: {fmt_num(reply)}\n"
                        f"标题: {title}"
                    )
                    message = MessageChain([
                        Image(cover_url),
                        Text(info_text)
                    ])
                    await msg.reply(rtf=message)
                else:
                    await msg.reply(text="获取视频信息失败，请稍后再试")
    except Exception as e:
        _log.error(f"处理Bilibili视频出错: {str(e)}")
        await msg.reply(text="处理视频信息时发生错误")

async def try_send_video_file(msg, video_id):
    try:
        api_url = f"https://api.bilibili.com/x/web-interface/view?{video_id}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as resp:
                data = await resp.json()
                video_info = data.get('data')
                if not video_info:
                    return
                cid = video_info.get('cid')
                bvid = video_info.get('bvid')
                aid = video_info.get('aid')
                if not cid:
                    return

        playurl_api = f"https://api.bilibili.com/x/player/playurl?cid={cid}"
        if bvid:
            playurl_api += f"&bvid={bvid}"
        else:
            playurl_api += f"&aid={aid}"
        playurl_api += "&qn=80"

        async with aiohttp.ClientSession() as session:
            async with session.get(playurl_api, headers=headers) as resp:
                play_data = await resp.json()
                durl = play_data.get("data", {}).get("durl", [])
                if not durl:
                    return
                video_url = durl[0].get("url")
                if not video_url:
                    return

        tmp_dir = "./tmp"
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir, exist_ok=True)
        video_path = os.path.abspath(os.path.join(tmp_dir, f"bili_{bvid or aid}_{cid}.mp4"))
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, headers=headers) as resp:
                with open(video_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)

        is_private = hasattr(msg, "user_id") and not hasattr(msg, "group_id")
        api = bot.api

        if is_private:
            await msg.reply(text="当前私聊不允许解析哦~")
        else:
            group_id = getattr(msg, "group_id", None)
            if group_id:
                await api.post_group_file(group_id=group_id, video=video_path)
    except Exception as e:
        _log.error(f"下载或发送B站视频失败: {str(e)}")

async def sync_cookies_to_global(cookies):
    """同步cookies到全局变量"""
    cookies_holder["cookies"] = cookies