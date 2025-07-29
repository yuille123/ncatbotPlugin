import os
import jmcomic
import asyncio
import tempfile
import io
import shutil
import time
from pathlib import Path
from PIL import Image
from contextlib import contextmanager
import yaml

from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core import GroupMessage, PrivateMessage, BaseMessage

bot = CompatibleEnrollment  # 兼容回调函数注册器

class JmComicPlugin(BasePlugin):
    name = "JmComicPlugin"  # 插件名称
    version = "0.0.1"  # 插件版本
    author = "Your Name"  # 插件作者
    info = "禁漫本子下载插件，支持通过/jm命令下载本子并发送PDF文件"  # 插件描述
    dependencies = {}  # 插件依赖，格式: {"插件名": "版本要求"}

    async def on_load(self):
        # 插件加载时执行的操作
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")

        # 注册本子下载功能
        self.register_user_func(
            name="jm_download",
            handler=self.jm_download_handler,
            prefix="/jm",
            description="下载禁漫本子并发送PDF文件",
            usage="/jm <本子ID>",
            examples=["/jm 422866", "/jm 123456"],
            tags=["download", "comic", "jm", "pdf"],
            metadata={"category": "download"}
        )

        # 注册配置项
        self.register_config(
            key="temp_path",
            default="./temp",
            description="临时文件路径",
            value_type="string"
        )

        # 创建临时目录
        temp_path = self.data.get('config', {}).get('temp_path', './temp')
        os.makedirs(temp_path, exist_ok=True)
        
        # 确保临时目录是绝对路径
        self.temp_path = os.path.abspath(temp_path)

    @contextmanager
    def safe_temp_file(self, filename):
        """安全的临时文件管理器，自动清理文件"""
        temp_file = None
        try:
            # 直接使用指定文件名创建临时文件
            temp_file = os.path.join(self.temp_path, filename)
            yield temp_file
        finally:
            # 确保文件被清理
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    print(f"清理临时文件失败: {e}")

    def cleanup_temp_directory(self):
        """清理临时目录中的旧文件"""
        try:
            if os.path.exists(self.temp_path):
                # 清理超过1小时的临时文件
                current_time = time.time()
                for item in os.listdir(self.temp_path):
                    item_path = os.path.join(self.temp_path, item)
                    if os.path.isfile(item_path):
                        # 检查文件修改时间
                        file_time = os.path.getmtime(item_path)
                        if current_time - file_time > 3600:  # 1小时
                            try:
                                os.remove(item_path)
                            except Exception as e:
                                print(f"清理旧文件失败: {e}")
                    elif os.path.isdir(item_path):
                        # 检查目录修改时间
                        dir_time = os.path.getmtime(item_path)
                        if current_time - dir_time > 3600:  # 1小时
                            try:
                                shutil.rmtree(item_path)
                            except Exception as e:
                                print(f"清理旧目录失败: {e}")
        except Exception as e:
            print(f"清理临时目录失败: {e}")

    async def jm_download_handler(self, msg: BaseMessage):
        """处理/jm命令，下载指定ID的本子"""
        try:
            # 清理旧的临时文件
            self.cleanup_temp_directory()
            
            # 解析命令参数
            command_parts = msg.raw_message.strip().split()
            if len(command_parts) != 2:
                await msg.reply(text="用法: /jm <本子ID>\n例如: /jm 422866")
                return

            album_id = command_parts[1]
            
            # 验证ID是否为数字
            if not album_id.isdigit():
                await msg.reply(text="本子ID必须是数字，例如: /jm 422866")
                return

            await msg.reply(text=f"开始下载本子 {album_id}，请稍候...")

            # 使用现有的配置文件
            config_path = os.path.join(os.path.dirname(__file__), "option.yml")
            
            # 读取 base_dir
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            base_dir = None
            if config and 'dir_rule' in config and 'base_dir' in config['dir_rule']:
                base_dir = config['dir_rule']['base_dir']
            if not base_dir:
                base_dir = self.temp_path
            base_dir = os.path.abspath(base_dir)
            
            # 创建下载选项
            option = jmcomic.create_option_by_file(config_path)
            
            # 设置临时下载路径
            option.download_path = self.temp_path

            # 在后台线程中执行下载
            def download_task():
                try:
                    # 下载本子
                    jmcomic.download_album(album_id, option)
                    
                    # 查找下载的文件 - 智能搜索多个位置
                    temp_album_dir = os.path.join(base_dir, str(album_id))
                    
                    # 检查多个可能的目录位置
                    possible_dirs = []
                    # base_dir 下所有子目录
                    for item in os.listdir(base_dir):
                        item_path = os.path.join(base_dir, item)
                        if os.path.isdir(item_path):
                            possible_dirs.append(item_path)
                    # 当前目录下所有子目录
                    current_dir = os.getcwd()
                    for item in os.listdir(current_dir):
                        item_path = os.path.join(current_dir, item)
                        if os.path.isdir(item_path):
                            possible_dirs.append(item_path)
                    
                    # 收集所有包含图片或PDF的文件夹
                    album_dirs = []
                    for dir_path in possible_dirs:
                        if os.path.exists(dir_path):
                            has_files = False
                            for root, dirs, files in os.walk(dir_path):
                                for file in files:
                                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
                                        has_files = True
                                        break
                                if has_files:
                                    break
                            if has_files:
                                album_dirs.append(dir_path)
                    
                    if not album_dirs:
                        return False, f"未找到包含图片或PDF文件的下载目录。搜索的目录: {possible_dirs}"
                    
                    pdf_buffers = []
                    errors = []
                    for album_dir in album_dirs:
                        # 查找PDF文件
                        pdf_files = []
                        for root, dirs, files in os.walk(album_dir):
                            for file in files:
                                if file.lower().endswith('.pdf'):
                                    pdf_files.append(os.path.join(root, file))
                        if not pdf_files:
                            # 如果没有找到PDF，尝试查找图片文件并转换
                            image_files = []
                            for root, dirs, files in os.walk(album_dir):
                                for file in files:
                                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                                        image_files.append(os.path.join(root, file))
                            if not image_files:
                                errors.append(f"目录 {album_dir} 未找到PDF或图片文件")
                                continue
                            image_files.sort()
                            pdf_buffer = io.BytesIO()
                            images = []
                            for img_path in image_files:
                                try:
                                    img = Image.open(img_path)
                                    if img.mode != 'RGB':
                                        img = img.convert('RGB')
                                    images.append(img)
                                except Exception as e:
                                    print(f"处理图片 {img_path} 时出错: {e}")
                                    continue
                            if not images:
                                errors.append(f"目录 {album_dir} 没有可用的图片文件")
                                continue
                            images[0].save(pdf_buffer, format='PDF', save_all=True, append_images=images[1:])
                            pdf_buffer.seek(0)
                            pdf_buffers.append((os.path.basename(album_dir), pdf_buffer))
                            shutil.rmtree(album_dir, ignore_errors=True)
                        else:
                            pdf_files.sort()
                            for pdf_path in pdf_files:
                                try:
                                    with open(pdf_path, 'rb') as f:
                                        pdf_data = f.read()
                                    pdf_buffers.append((os.path.basename(album_dir), io.BytesIO(pdf_data)))
                                except Exception as e:
                                    print(f"读取PDF文件 {pdf_path} 时出错: {e}")
                                    errors.append(f"读取PDF文件 {pdf_path} 时出错: {e}")
                                    continue
                            shutil.rmtree(album_dir, ignore_errors=True)
                    if pdf_buffers:
                        return True, pdf_buffers  # 返回PDF文件列表 (文件夹名, buffer)
                    else:
                        return False, "\n".join(errors) if errors else "无法读取任何PDF文件"
                    
                except Exception as e:
                    return False, f"处理失败: {str(e)}"

            # 异步执行下载
            loop = asyncio.get_event_loop()
            success, result = await loop.run_in_executor(None, download_task)
            
            if success:
                # 发送所有PDF
                for idx, (folder_name, pdf_buffer) in enumerate(result, 1):
                    filename = f"{album_id}_{folder_name}_{idx}.pdf"
                    with self.safe_temp_file(filename) as temp_pdf_path:
                        with open(temp_pdf_path, 'wb') as f:
                            f.write(pdf_buffer.read())
                        if hasattr(msg, 'group_id'):
                            await self.api.post_group_file(group_id=msg.group_id, file=temp_pdf_path)
                        else:
                            await self.api.post_private_file(user_id=msg.user_id, file=temp_pdf_path)
                    
            else:
                await msg.reply(text=result)

        except Exception as e:
            await msg.reply(text=f"下载过程中发生错误: {str(e)}")
