import os
import jmcomic
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core import GroupMessage, PrivateMessage, BaseMessage

bot = CompatibleEnrollment

class JmComicPlugin(BasePlugin):
    name = "JmComicPlugin"
    version = "0.0.1"
    author = "Your Name"
    info = "禁漫本子下载插件，支持通过/jm命令下载本子并发送PDF文件"
    dependencies = {}

    async def on_load(self):
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
        # 获取项目根目录
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
        self.base_dir = os.path.join(project_root, 'pdf')
        # jmcomic 配置
        config_path = os.path.join(os.path.dirname(__file__), "option.yml")
        import yaml
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        self.jm_option = jmcomic.JmOption.from_file(config_path)

    async def jm_download_handler(self, msg: BaseMessage):
        try:
            command_parts = msg.raw_message.strip().split()
            if len(command_parts) != 2:
                await msg.reply(text="用法: /jm <本子ID>\n例如: /jm 422866")
                return
            album_id = command_parts[1]
            if not album_id.isdigit():
                await msg.reply(text="本子ID必须是数字，例如: /jm 422866")
                return
            pdf_path = os.path.join(self.base_dir, f"{album_id}.pdf")
            if os.path.exists(pdf_path):
                if hasattr(msg, 'group_id'):
                    await self.api.post_group_file(group_id=msg.group_id, file=pdf_path)
                else:
                    await self.api.post_private_file(user_id=msg.user_id, file=pdf_path)
                return
            else:
                await msg.reply(text=f"开始下载本子 {album_id}，请稍候...")
                self.jm_option.download_album([album_id])
                if os.path.exists(pdf_path):
                    if hasattr(msg, 'group_id'):
                        await self.api.post_group_file(group_id=msg.group_id, file=pdf_path)
                    else:
                        await self.api.post_private_file(user_id=msg.user_id, file=pdf_path)
                else:
                    await msg.reply(text="未找到 PDF 文件，可能下载失败。")
        except Exception as e:
            await msg.reply(text=f"下载过程中发生错误: {str(e)}")
