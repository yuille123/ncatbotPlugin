from ncatbot.plugin import BasePlugin, CompatibleEnrollment, get_global_access_controller
from ncatbot.core.message import BaseMessage
from ncatbot.core import MessageChain, Image
from ncatbot.utils import get_log
from pathlib import Path
import aiohttp
import json
import asyncio
import hashlib
import time
from typing import List, Dict, Optional

LOG = get_log("Lolicon")

class Lolicon(BasePlugin):
    name = "Lolicon"
    version = "1.0.0"
    author = "huan-yp"
    description = "调用 Lolicon API v2 发送随机二次元图片"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache_dir = Path("plugins/Lolicon/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_index_file = self.cache_dir / "cache_index.json"
        self.cache_index = self._load_cache_index()
        self.session = None
    
    def _load_cache_index(self) -> Dict:
        """加载缓存索引"""
        if self.cache_index_file.exists():
            try:
                with open(self.cache_index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                LOG.error(f"加载缓存索引失败: {e}")
        return {}
    
    def _save_cache_index(self):
        """保存缓存索引"""
        try:
            with open(self.cache_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            LOG.error(f"保存缓存索引失败: {e}")
    
    def _get_cache_path(self, url: str) -> Path:
        """获取缓存文件路径"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{url_hash}.jpg"
    
    async def _download_image(self, url: str) -> Optional[Path]:
        """下载图片到缓存"""
        cache_path = self._get_cache_path(url)
        
        # 如果缓存存在且未过期，直接返回
        if cache_path.exists():
            cache_time = cache_path.stat().st_mtime
            if time.time() - cache_time < self.config.get("cache_expire", 86400):
                return cache_path
        
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.pixiv.net/"
            }
            
            async with self.session.get(url, headers=headers, timeout=30) as response:
                if response.status == 200:
                    content = await response.read()
                    if len(content) > 1000:
                        with open(cache_path, 'wb') as f:
                            f.write(content)
                        
                        self.cache_index[url] = {
                            "path": str(cache_path),
                            "timestamp": time.time(),
                            "size": len(content)
                        }
                        self._save_cache_index()
                        return cache_path
                else:
                    LOG.warning(f"下载图片失败: {url}, 状态码: {response.status}")
                    
        except Exception as e:
            LOG.error(f"下载图片异常: {url}, 错误: {e}")
        
        return None
    
    async def _call_lolicon_api(self, count: int = 1, r18: int = 0, tags: List[str] = None) -> List[Dict]:
        """调用 Lolicon API v2"""
        api_url = "https://api.lolicon.app/setu/v2"
        params = {
            "r18": r18,
            "num": count,
            "size": "regular"
        }
        
        if not tags:
            tags = ["萝莉"]
        
        # 限制最多3个标签
        tags = tags[:3]
        
        # 使用多个tag参数，实现AND规则
        for tag in tags:
            params[f"tag"] = tag
        
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            
            async with self.session.get(api_url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("error") == "":
                        return data.get("data", [])
                    else:
                        LOG.error(f"API 返回错误: {data.get('error')}")
                else:
                    LOG.error(f"API 请求失败: {response.status}")
        except Exception as e:
            LOG.error(f"调用 API 异常: {e}")
        
        return []
    
    def _can_access_r18(self, msg: BaseMessage) -> bool:
        """检查是否有权限访问 R18 内容"""
        if not hasattr(msg, "group_id"):
            return True
        
        access_controller = get_global_access_controller()
        if access_controller.user_has_role(str(msg.user_id), "root") or \
           access_controller.user_has_role(str(msg.user_id), "admin"):
            return True
        
        return False
    
    async def on_load(self):
        # 注册配置
        self.register_config("cache_expire", 86400, description="缓存过期时间(秒)", value_type="int")
        self.register_config("batch", 5, description="一批发送的图片数量", value_type="int")
        self.register_config("lim_f", 3, description="不使用转发的阈值", value_type="int")
        self.register_config("lim_u", 10, description="普通用户一次请求最大发送数量", value_type="int")
        self.register_config("lim_a", 30, description="超级用户一次请求最大发送数量", value_type="int")
        self.register_config("enable_r18", False, description="是否启用 R18 内容", value_type="bool")
        self.register_config("r18_private_only", True, description="R18 内容是否仅限私聊", value_type="bool")
        
        # 注册命令
        self.register_user_func("/loli", self.loli, prefix="/loli", description="发送随机二次元图片")
        self.register_user_func("/r18", self.r18, prefix="/r18", description="发送 R18 二次元图片(需要权限)")
        
        self.register_admin_func("clear_cache", self.clear_cache, permission_raise=True, description="清理图片缓存")
        self.register_admin_func("status", self.status, permission_raise=True, description="查看插件状态")
        self.register_admin_func("enable_r18", self.enable_r18, permission_raise=True, description="启用R18功能")
        self.register_admin_func("disable_r18", self.disable_r18, permission_raise=True, description="禁用R18功能")
        self.register_admin_func("set_r18_private", self.set_r18_private, permission_raise=True, description="设置R18仅限私聊")
        
        print(f"{self.name} 插件已加载")
    
    async def status(self, msg: BaseMessage):
        """查看插件状态"""
        cache_size = sum(item.get("size", 0) for item in self.cache_index.values())
        cache_count = len(self.cache_index)
        
        status_text = f"Lolicon 插件状态:\n"
        status_text += f"缓存图片数量: {cache_count} 张\n"
        status_text += f"缓存大小: {cache_size / 1024 / 1024:.2f} MB\n"
        status_text += f"R18 功能启用: {'是' if self.config['enable_r18'] else '否'}\n"
        status_text += f"R18 仅限私聊: {'是' if self.config['r18_private_only'] else '否'}"
        
        await msg.reply(status_text)
    
    async def clear_cache(self, msg: BaseMessage):
        """清理缓存"""
        try:
            for cache_path in self.cache_dir.glob("*.jpg"):
                cache_path.unlink()
            
            self.cache_index.clear()
            self._save_cache_index()
            
            await msg.reply("缓存清理完成")
        except Exception as e:
            LOG.error(f"清理缓存失败: {e}")
            await msg.reply(f"清理缓存失败: {e}")
    
    async def enable_r18(self, msg: BaseMessage):
        """启用R18功能"""
        try:
            self.config["enable_r18"] = True
            await msg.reply("✅ R18 功能已启用")
        except Exception as e:
            LOG.error(f"启用R18功能失败: {e}")
            await msg.reply(f"启用R18功能失败: {e}")
    
    async def disable_r18(self, msg: BaseMessage):
        """禁用R18功能"""
        try:
            self.config["enable_r18"] = False
            await msg.reply("❌ R18 功能已禁用")
        except Exception as e:
            LOG.error(f"禁用R18功能失败: {e}")
            await msg.reply(f"禁用R18功能失败: {e}")
    
    async def set_r18_private(self, msg: BaseMessage):
        """设置R18仅限私聊"""
        try:
            parts = msg.raw_message.split()
            if len(parts) < 2:
                await msg.reply("用法：/set_r18_private [true/false]")
                return
            
            value = parts[1].lower()
            if value in ["true", "1", "yes", "是"]:
                self.config["r18_private_only"] = True
                await msg.reply("✅ R18 内容已设置为仅限私聊使用")
            elif value in ["false", "0", "no", "否"]:
                self.config["r18_private_only"] = False
                await msg.reply("✅ R18 内容已设置为群聊可用（仅限管理员）")
            else:
                await msg.reply("❌ 参数错误，请使用 true 或 false")
        except Exception as e:
            LOG.error(f"设置R18私聊限制失败: {e}")
            await msg.reply(f"设置失败: {e}")
    
    async def send_images(self, msg: BaseMessage, images_data: List[Dict], count: int):
        """发送图片"""
        msg_chains = []
        failed_count = 0
        
        for image_data in images_data:
            url = image_data.get("urls", {}).get("regular", "")
            if url:
                cache_path = await self._download_image(url)
                if cache_path:
                    msg_chains.append(Image(str(cache_path)))
                else:
                    failed_count += 1
        
        if msg_chains:
            msg_chain = MessageChain(msg_chains)
            if hasattr(msg, "group_id"):
                await self.api.post_group_msg(msg.group_id, rtf=msg_chain)
            else:
                await self.api.post_private_msg(msg.user_id, rtf=msg_chain)
            
            if failed_count > 0:
                await msg.reply(f"⚠️ {failed_count} 张图片下载失败")
        else:
            await msg.reply("所有图片下载失败，请稍后重试")
    
    async def loli(self, msg: BaseMessage):
        """发送普通二次元图片"""
        parts = msg.raw_message.split()
        count = 1
        tags = []
        
        if len(parts) > 1:
            try:
                count = int(parts[1])
                if len(parts) > 2:
                    tags.extend(parts[2:])
            except ValueError:
                tags.extend(parts[1:])
        
        max_count = self.config["lim_a"] if get_global_access_controller().user_has_role(str(msg.user_id), "root") else self.config["lim_u"]
        count = max(1, min(max_count, count))
        
        images_data = await self._call_lolicon_api(count=count, r18=0, tags=tags)
        
        if not images_data:
            await msg.reply("获取图片失败，请稍后重试")
            return
        
        await self.send_images(msg, images_data, count)
    
    async def r18(self, msg: BaseMessage):
        """发送 R18 二次元图片"""
        if not self.config.get("enable_r18", False):
            await msg.reply("R18 功能未启用")
            return
        
        if not self._can_access_r18(msg):
            if self.config.get("r18_private_only", True):
                await msg.reply("R18 内容仅限私聊使用")
            else:
                await msg.reply("您没有权限访问 R18 内容")
            return
        
        parts = msg.raw_message.split()
        count = 1
        tags = []
        
        if len(parts) > 1:
            try:
                count = int(parts[1])
                if len(parts) > 2:
                    tags.extend(parts[2:])
            except ValueError:
                tags.extend(parts[1:])
        
        max_count = self.config["lim_a"] if get_global_access_controller().user_has_role(str(msg.user_id), "root") else self.config["lim_u"]
        count = max(1, min(max_count, count))
        
        images_data = await self._call_lolicon_api(count=count, r18=1, tags=tags)
        
        if not images_data:
            await msg.reply("获取图片失败，请稍后重试")
            return
        
        await self.send_images(msg, images_data, count)
    
    async def on_unload(self):
        """插件卸载时清理资源"""
        if self.session:
            await self.session.close()
            
        