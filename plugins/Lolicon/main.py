from ncatbot.plugin import BasePlugin, get_global_access_controller
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
    author = "FunEnn"
    description = "调用 Lolicon API v2 发送随机二次元图片"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache_dir = Path("plugins/Lolicon/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_index_file = self.cache_dir / "cache_index.json"
        self.cache_index = self._load_cache_index()
        self.session = None
    
    def _load_cache_index(self) -> Dict:
        if self.cache_index_file.exists():
            try:
                with open(self.cache_index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                LOG.error(f"加载缓存索引失败: {e}")
        return {}
    
    def _save_cache_index(self):
        try:
            with open(self.cache_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            LOG.error(f"保存缓存索引失败: {e}")
    
    def _get_cache_path(self, url: str) -> Path:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        # 添加时间戳避免缓存冲突
        timestamp = int(time.time() / 3600)  # 每小时更新一次
        return self.cache_dir / f"{url_hash}_{timestamp}.jpg"
    
    async def _download_image(self, url: str) -> Optional[Path]:
        cache_path = self._get_cache_path(url)
        
        # 缩短缓存过期时间，增加随机性
        cache_expire = self.config.get("cache_expire", 3600)  # 改为1小时
        if cache_path.exists():
            cache_time = cache_path.stat().st_mtime
            if time.time() - cache_time < cache_expire:
                return cache_path
        
        max_retries = 1
        for retry in range(max_retries):
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.pixiv.net/"
                }
                
                timeout = aiohttp.ClientTimeout(total=self.config.get("download_timeout", 10), connect=3)
                async with self.session.get(url, headers=headers, timeout=timeout) as response:
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
                        if retry == max_retries - 1:
                            break
                        
            except asyncio.TimeoutError:
                LOG.warning(f"下载图片超时 (重试 {retry + 1}/{max_retries}): {url}")
                if retry == max_retries - 1:
                    break
                await asyncio.sleep(0.5)
            except Exception as e:
                LOG.error(f"下载图片异常 (重试 {retry + 1}/{max_retries}): {url}, 错误: {e}")
                if retry == max_retries - 1:
                    break
                await asyncio.sleep(0.5)
        
        return None
    
    async def _download_images_concurrent(self, urls: List[str]) -> List[Optional[Path]]:
        async def download_single(url: str) -> Optional[Path]:
            return await self._download_image(url)
        
        semaphore = asyncio.Semaphore(5)
        
        async def download_with_semaphore(url: str) -> Optional[Path]:
            async with semaphore:
                return await download_single(url)
        
        tasks = [download_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _call_lolicon_api(self, count: int = 1, r18: int = 0, tags: List[str] = None) -> List[Dict]:
        api_url = "https://api.lolicon.app/setu/v2"
        params = {
            "r18": r18,
            "num": count,
            "size": "regular"
        }
        
        if not tags:
            tags = ["萝莉"]
        
        tags = tags[:3]
        
        for tag in tags:
            params[f"tag"] = tag
        
        # 添加随机参数避免重复
        import random
        params["uid"] = random.randint(1, 999999)
        params["excludeAI"] = 1
        
        max_retries = 2
        for retry in range(max_retries):
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                
                timeout = aiohttp.ClientTimeout(total=self.config.get("api_timeout", 15), connect=5)
                async with self.session.get(api_url, params=params, headers=headers, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("error") == "":
                            return data.get("data", [])
                        else:
                            LOG.error(f"API 返回错误: {data.get('error')}")
                            if retry == max_retries - 1:
                                return []
                    else:
                        LOG.error(f"API 请求失败: {response.status}")
                        if retry == max_retries - 1:
                            return []
                        
            except asyncio.TimeoutError:
                LOG.error(f"API 请求超时 (重试 {retry + 1}/{max_retries})")
                if retry == max_retries - 1:
                    return []
                await asyncio.sleep(1)
            except Exception as e:
                LOG.error(f"调用 API 异常 (重试 {retry + 1}/{max_retries}): {e}")
                if retry == max_retries - 1:
                    return []
                await asyncio.sleep(0.5)
        
        return []
    
    def _can_access_r18(self, msg: BaseMessage) -> bool:
        if not hasattr(msg, "group_id"):
            return True
        
        access_controller = get_global_access_controller()
        if access_controller.user_has_role(str(msg.user_id), "root") or \
           access_controller.user_has_role(str(msg.user_id), "admin"):
            return True
        
        return False
    
    async def on_load(self):
        # 自动清理过期缓存
        await self._cleanup_expired_cache()
        
        self.register_config("cache_expire", 3600, description="缓存过期时间(秒)", value_type="int")
        self.register_config("batch", 5, description="一批发送的图片数量", value_type="int")
        self.register_config("lim_f", 3, description="不使用转发的阈值", value_type="int")
        self.register_config("lim_u", 10, description="用户一次请求最大发送数量", value_type="int")
        self.register_config("enable_r18", False, description="是否启用 R18 内容", value_type="bool")
        self.register_config("r18_private_only", True, description="R18 内容是否仅限私聊", value_type="bool")
        self.register_config("api_timeout", 30, description="API请求超时时间(秒)", value_type="int")
        self.register_config("download_timeout", 20, description="图片下载超时时间(秒)", value_type="int")
        self.register_config("send_retry_count", 3, description="发送消息重试次数", value_type="int")
        self.register_config("batch_delay", 0.5, description="批次间延迟时间(秒)", value_type="float")
        
        self.register_user_func("/loli", self.loli, prefix="/loli", description="发送随机二次元图片")
        self.register_user_func("/r18", self.r18, prefix="/r18", description="发送 R18 二次元图片(需要权限)")
        
        self.register_admin_func("clear_cache", self.clear_cache, permission_raise=True, description="清理图片缓存")
        self.register_admin_func("status", self.status, permission_raise=True, description="查看插件状态")
        self.register_admin_func("enable_r18", self.enable_r18, permission_raise=True, description="启用R18功能")
        self.register_admin_func("disable_r18", self.disable_r18, permission_raise=True, description="禁用R18功能")
        
        print(f"{self.name} 插件已加载")
    
    async def _cleanup_expired_cache(self):
        """清理过期缓存"""
        try:
            cache_expire = self.config.get("cache_expire", 3600)
            current_time = time.time()
            cleaned_count = 0
            
            for cache_path in self.cache_dir.glob("*.jpg"):
                try:
                    cache_time = cache_path.stat().st_mtime
                    if current_time - cache_time > cache_expire:
                        cache_path.unlink()
                        cleaned_count += 1
                except Exception:
                    continue
            
            if cleaned_count > 0:
                LOG.info(f"自动清理了 {cleaned_count} 个过期缓存文件")
        except Exception as e:
            LOG.error(f"自动清理缓存失败: {e}")
    
    async def status(self, msg: BaseMessage):
        cache_size = sum(item.get("size", 0) for item in self.cache_index.values())
        cache_count = len(self.cache_index)
        
        status_text = f"Lolicon 插件状态:\n"
        status_text += f"缓存图片数量: {cache_count} 张\n"
        status_text += f"缓存大小: {cache_size / 1024 / 1024:.2f} MB\n"
        status_text += f"R18 功能启用: {'是' if self.config['enable_r18'] else '否'}\n"
        status_text += f"R18 仅限私聊: {'是' if self.config['r18_private_only'] else '否'}\n"
        
        api_status = await self._check_api_status()
        status_text += f"API接口状态: {api_status}"
        
        await msg.reply(status_text)
    
    async def _check_api_status(self) -> str:
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            api_url = "https://api.lolicon.app/setu/v2"
            params = {"r18": 0, "num": 1, "size": "regular"}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            
            start_time = time.time()
            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            
            async with self.session.get(api_url, params=params, headers=headers, timeout=timeout) as response:
                response_time = time.time() - start_time
                
                if response.status == 200:
                    data = await response.json()
                    if data.get("error") == "" and data.get("data"):
                        return f"✅ 正常 (响应时间: {response_time:.2f}s)"
                    else:
                        return f"❌ API返回错误: {data.get('error', '未知错误')}"
                else:
                    return f"❌ HTTP错误: {response.status}"
                    
        except asyncio.TimeoutError:
            return "❌ 连接超时"
        except Exception as e:
            return f"❌ 连接失败: {str(e)}"
    
    async def clear_cache(self, msg: BaseMessage):
        try:
            # 清理所有缓存文件，包括带时间戳的文件
            for cache_path in self.cache_dir.glob("*.jpg"):
                cache_path.unlink()
            
            self.cache_index.clear()
            self._save_cache_index()
            
            await msg.reply("缓存清理完成")
        except Exception as e:
            LOG.error(f"清理缓存失败: {e}")
            await msg.reply(f"清理缓存失败: {e}")
    
    async def enable_r18(self, msg: BaseMessage):
        try:
            self.config["enable_r18"] = True
            await msg.reply("✅ R18 功能已启用")
        except Exception as e:
            LOG.error(f"启用R18功能失败: {e}")
            await msg.reply(f"启用R18功能失败: {e}")
    
    async def disable_r18(self, msg: BaseMessage):
        try:
            self.config["enable_r18"] = False
            await msg.reply("❌ R18 功能已禁用")
        except Exception as e:
            LOG.error(f"禁用R18功能失败: {e}")
            await msg.reply(f"禁用R18功能失败: {e}")
    
    async def send_images(self, msg: BaseMessage, images_data: List[Dict], count: int):
        urls = []
        for image_data in images_data:
            url = image_data.get("urls", {}).get("regular", "")
            if url:
                urls.append(url)
        
        if not urls:
            await msg.reply("没有可用的图片链接")
            return
        
        await msg.reply("正在获取图片，请稍候...")
        cache_paths = await self._download_images_concurrent(urls)
        
        msg_chains = []
        failed_count = 0
        
        for i, cache_path in enumerate(cache_paths):
            if isinstance(cache_path, Exception):
                LOG.error(f"下载图片异常: {cache_path}")
                failed_count += 1
                continue
                
            if cache_path and cache_path.exists():
                msg_chains.append(Image(str(cache_path)))
            else:
                failed_count += 1
        
        if not msg_chains:
            await msg.reply("所有图片下载失败，请稍后重试")
            return
        
        batch_size = min(self.config.get("batch", 5), len(msg_chains))
        total_sent = 0
        total_failed = 0
        
        for i in range(0, len(msg_chains), batch_size):
            batch = msg_chains[i:i + batch_size]
            msg_chain = MessageChain(batch)
            
            max_retries = 2
            for retry in range(max_retries):
                try:
                    if hasattr(msg, "group_id"):
                        await self.api.post_group_msg(msg.group_id, rtf=msg_chain)
                    else:
                        await self.api.post_private_msg(msg.user_id, rtf=msg_chain)
                    
                    total_sent += len(batch)
                    break
                    
                except Exception as e:
                    LOG.error(f"发送图片失败 (重试 {retry + 1}/{max_retries}): {e}")
                    if retry == max_retries - 1:
                        total_failed += len(batch)
                        LOG.error(f"发送图片最终失败: {e}")
                    else:
                        await asyncio.sleep(0.5)
            
            if i + batch_size < len(msg_chains):
                await asyncio.sleep(self.config.get("batch_delay", 0.2))
        
        if failed_count > 0:
            await msg.reply(f"发送完成！成功: {total_sent}张，失败: {failed_count}张")
    
    async def loli(self, msg: BaseMessage):
        parts = msg.raw_message.split()
        count = 1
        tags = []
        
        if len(parts) > 1:
            try:
                count = int(parts[1])
                if len(parts) > 2:
                    tags = [parts[2]]
            except ValueError:
                tags = [parts[1]] if parts[1] else []
        
        max_count = self.config["lim_u"]
        count = max(1, min(max_count, count))
        
        images_data = await self._call_lolicon_api(count=count, r18=0, tags=tags)
        
        if not images_data:
            await msg.reply("获取图片失败，请稍后重试")
            return
        
        await self.send_images(msg, images_data, count)
    
    async def r18(self, msg: BaseMessage):
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
                    tags = [parts[2]]
            except ValueError:
                tags = [parts[1]] if parts[1] else []
        
        max_count = self.config["lim_u"]
        count = max(1, min(max_count, count))
        
        images_data = await self._call_lolicon_api(count=count, r18=1, tags=tags)
        
        if not images_data:
            await msg.reply("获取图片失败，请稍后重试")
            return
        
        await self.send_images(msg, images_data, count)
    
    async def on_unload(self):
        if self.session:
            await self.session.close()
            
        