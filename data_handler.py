import os
import json
from urllib.parse import urlparse
from lxml import etree
from bs4 import BeautifulSoup
import re

class DataHandler:
    def __init__(self, config_path="data/astrbot_plugin_rss_data.json", default_config=None):
        self.config_path = config_path
        self.default_config = default_config or {
            "rsshub_endpoints": []
        }
        self.data = self.load_data()

    def get_subs_channel_url(self, user_id) -> list:
        """获取用户订阅的频道 url 列表"""
        subs_url = []
        for url, info in self.data.items():
            if url == "rsshub_endpoints" or url == "settings":
                continue
            if user_id in info["subscribers"]:
                subs_url.append(url)
        return subs_url

    def load_data(self):
        """从数据文件中加载数据"""
        if not os.path.exists(self.config_path):
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.default_config, indent=2, ensure_ascii=False))
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_data(self):
        """保存数据到数据文件"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def parse_channel_text_info(self, text):
        """解析RSS/Atom频道信息"""
        root = etree.fromstring(text)
        # 检测是否为 Atom 格式
        is_atom = root.tag == "feed" or root.tag.endswith("}feed")

        if is_atom:
            # Atom 格式：标题在根元素中，描述可能在 subtitle 中
            nsmap = {"atom": "http://www.w3.org/2005/Atom"}
            title_nodes = root.xpath("//atom:title", namespaces=nsmap)
            if not title_nodes:
                # 尝试无命名空间
                title_nodes = root.xpath("//*[local-name()='title']")
            subtitle_nodes = root.xpath("//atom:subtitle", namespaces=nsmap)
            if not subtitle_nodes:
                # 尝试无命名空间
                subtitle_nodes = root.xpath("//*[local-name()='subtitle']")
            title = title_nodes[0].text.strip() if title_nodes and title_nodes[0].text else "未知频道"
            description = subtitle_nodes[0].text.strip() if subtitle_nodes and subtitle_nodes[0].text else ""
        else:
            # RSS 格式
            title_nodes = root.xpath("//title")
            description_nodes = root.xpath("//description")
            title = title_nodes[0].text.strip() if title_nodes and title_nodes[0].text else "未知频道"
            description = description_nodes[0].text.strip() if description_nodes and description_nodes[0].text else ""
        return title, description

    def strip_html_pic(self, html)-> list[str]:
        """解析HTML内容，提取图片地址
        """
        soup = BeautifulSoup(html, "html.parser")
        ordered_content = []

        # 处理图片节点
        for img in soup.find_all('img'):
            img_src = img.get('src')
            if img_src:
                ordered_content.append(img_src)

        return ordered_content

    def strip_html(self, html):
        """去除HTML标签"""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()
        return re.sub(r"\n+", "\n", text)

    def get_root_url(self, url):
        """获取URL的根域名"""
        parsed_url = urlparse(url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}"
