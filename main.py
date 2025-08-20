import aiohttp
import asyncio
import time
import re
import logging
from lxml import etree
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp

from .data_handler import DataHandler
from .pic_handler import RssImageHandler
from .rss import RSSItem
from .translate import baidu_translate
from typing import List

@register(
    "astrbot_plugin_rss",
    "Soulter",
    "RSS订阅插件",
    "1.1.0",
    "https://github.com/Soulter/astrbot_plugin_rss",
)
class RssPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.logger = logging.getLogger("astrbot")
        self.context = context
        self.config = config
        self.data_handler = DataHandler()
        self.pic_handler = RssImageHandler()

        self.title_max_length = config.get("title_max_length")
        self.description_max_length = config.get("description_max_length")
        self.max_items_per_poll = config.get("max_items_per_poll")
        self.t2i = config.get("t2i")
        self.is_hide_url = config.get("is_hide_url")
        self.is_read_pic = config.get("pic_config").get("is_read_pic")
        self.is_adjust_pic = config.get("pic_config").get("is_adjust_pic")
        self.max_pic_item = config.get("pic_config").get("max_pic_item")
        self.is_compose = config.get("compose")

        baidu_conf = config.get("baidu_translate", {})
        self.baidu_appid = baidu_conf.get("app_id", "")
        self.baidu_key = baidu_conf.get("secret_key", "")
        self.translate_title = baidu_conf.get("translate_title", False)

        self.pic_handler = RssImageHandler(self.is_adjust_pic)
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        self._fresh_asyncIOScheduler()

    def parse_cron_expr(self, cron_expr: str):
        fields = cron_expr.split(" ")
        return {
            "minute": fields[0],
            "hour": fields[1],
            "day": fields[2],
            "month": fields[3],
            "day_of_week": fields[4],
        }

    async def parse_channel_info(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        try:
            async with aiohttp.ClientSession(
                trust_env=True,
                connector=connector,
                timeout=timeout,
                headers=headers
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        self.logger.error(f"rss: 无法正常打开站点 {url}")
                        return None
                    return await resp.read()
        except Exception as e:
            self.logger.error(f"rss: 请求站点 {url} 发生错误: {e}")
            return None

    async def cron_task_callback(self, url: str, user: str):
        if url not in self.data_handler.data:
            return
        if user not in self.data_handler.data[url]["subscribers"]:
            return

        self.logger.info(f"RSS 定时任务触发: {url} - {user}")
        last_update = self.data_handler.data[url]["subscribers"][user]["last_update"]
        latest_link = self.data_handler.data[url]["subscribers"][user]["latest_link"]
        max_items_per_poll = self.max_items_per_poll

        rss_items = await self.poll_rss(
            url,
            num=max_items_per_poll,
            after_timestamp=last_update,
            after_link=latest_link,
        )
        max_ts = last_update

        platform_name, message_type, session_id = user.split(":")

        if platform_name == "aiocqhttp" and self.is_compose:
            nodes = []
            for item in rss_items:
                comps = await self._get_chain_components(item)
                node = Comp.Node(uin=0, name="Astrbot", content=comps)
                nodes.append(node)
                max_ts = max(max_ts, item.pubDate_timestamp)
            if nodes:
                msc = MessageChain(chain=nodes, use_t2i_=self.t2i)
                await self.context.send_message(user, msc)
        else:
            for item in rss_items:
                comps = await self._get_chain_components(item)
                msc = MessageChain(chain=comps, use_t2i_=self.t2i)
                await self.context.send_message(user, msc)
                max_ts = max(max_ts, item.pubDate_timestamp)

        if rss_items:
            self.data_handler.data[url]["subscribers"][user]["last_update"] = max_ts
            self.data_handler.data[url]["subscribers"][user]["latest_link"] = rss_items[0].link
            self.data_handler.save_data()
            self.logger.info(f"RSS 定时任务 {url} 推送成功 - {user}")
        else:
            self.logger.info(f"RSS 定时任务 {url} 无消息更新 - {user}")

    async def poll_rss(
        self,
        url: str,
        num: int = -1,
        after_timestamp: int = 0,
        after_link: str = "",
    ) -> List[RSSItem]:
        text = await self.parse_channel_info(url)
        if text is None:
            return []
        root = etree.fromstring(text)
        items = root.xpath("//item")
        cnt = 0
        rss_items = []
        for item in items:
            try:
                chan_title = self.data_handler.data[url]["info"]["title"] if url in self.data_handler.data else "未知频道"
                title = item.xpath("title")[0].text
                if len(title) > self.title_max_length:
                    title = title[: self.title_max_length] + "..."

                link = item.xpath("link")[0].text
                if not re.match(r"^https?://", link):
                    link = self.data_handler.get_root_url(url) + link

                description = item.xpath("description")[0].text
                pic_url_list = self.data_handler.strip_html_pic(description)
                description = self.data_handler.strip_html(description)
                if len(description) > self.description_max_length:
                    description = description[: self.description_max_length] + "..."

                if item.xpath("pubDate"):
                    pub_date = item.xpath("pubDate")[0].text
                    pub_date_parsed = time.strptime(
                        pub_date.replace("GMT", "+0000"),
                        "%a, %d %b %Y %H:%M:%S %z",
                    )
                    pub_date_timestamp = int(time.mktime(pub_date_parsed))
                    if pub_date_timestamp > after_timestamp:
                        rss_items.append(
                            RSSItem(
                                chan_title,
                                title,
                                link,
                                description,
                                pub_date,
                                pub_date_timestamp,
                                pic_url_list,
                            )
                        )
                        cnt += 1
                        if num != -1 and cnt >= num:
                            break
                    else:
                        break
                else:
                    if link != after_link:
                        rss_items.append(
                            RSSItem(chan_title, title, link, description, "", 0, pic_url_list)
                        )
                        cnt += 1
                        if num != -1 and cnt >= num:
                            break
                    else:
                        break
            except Exception as e:
                self.logger.error(f"rss: 解析Rss条目 {url} 失败: {e}")
                break
        return rss_items

    def parse_rss_url(self, url: str) -> str:
        if not re.match(r"^https?://", url):
            if not url.startswith("/"):
                url = "/" + url
            url = "https://" + url
        return url

    def _fresh_asyncIOScheduler(self):
        self.logger.info("刷新定时任务")
        self.scheduler.remove_all_jobs()
        for url, info in self.data_handler.data.items():
            if url in ("rsshub_endpoints", "settings"):
                continue
            for user, sub_info in info["subscribers"].items():
                self.scheduler.add_job(
                    self.cron_task_callback,
                    "cron",
                    **self.parse_cron_expr(sub_info["cron_expr"]),
                    args=[url, user],
                )

    async def _add_url(self, url: str, cron_expr: str, message: AstrMessageEvent):
        user = message.unified_msg_origin
        if url in self.data_handler.data:
            latest_item = await self.poll_rss(url)
            self.data_handler.data[url]["subscribers"][user] = {
                "cron_expr": cron_expr,
                "last_update": latest_item[0].pubDate_timestamp,
                "latest_link": latest_item[0].link,
            }
        else:
            try:
                text = await self.parse_channel_info(url)
                title, desc = self.data_handler.parse_channel_text_info(text)
                latest_item = await self.poll_rss(url)
            except Exception as e:
                return message.plain_result(f"解析频道信息失败: {e}")
            self.data_handler.data[url] = {
                "subscribers": {
                    user: {
                        "cron_expr": cron_expr,
                        "last_update": latest_item[0].pubDate_timestamp,
                        "latest_link": latest_item[0].link,
                    }
                },
                "info": {"title": title, "description": desc},
            }
        self.data_handler.save_data()
        return self.data_handler.data[url]["info"]

    async def _get_chain_components(self, item: RSSItem):
        item.description = await baidu_translate(
            item.description, self.baidu_appid, self.baidu_key
        )
        if self.translate_title:
            item.title = await baidu_translate(
                item.title, self.baidu_appid, self.baidu_key
            )

        comps = []
        comps.append(Comp.Plain(f"频道 {item.chan_title} 最新 Feed\n---\n标题: {item.title}\n---\n"))
        if not self.is_hide_url:
            comps.append(Comp.Plain(f"链接: {item.link}\n---\n"))
        comps.append(Comp.Plain(item.description + "\n---\n"))
        if self.is_read_pic and item.pic_urls:
            temp_max_pic_item = len(item.pic_urls) if self.max_pic_item == -1 else self.max_pic_item
            for pic_url in item.pic_urls[:temp_max_pic_item]:
                base64str = await self.pic_handler.modify_corner_pixel_to_base64(pic_url)
                if base64str is None:
                    comps.append(Comp.Plain("图片链接读取失败\n"))
                    continue
                comps.append(Comp.Image.fromBase64(base64str))
        return comps

    def _is_url_or_ip(self, text: str) -> bool:
        url_pattern = r"^(?:http|https)://.+$"
        ip_pattern = r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
        return bool(re.match(url_pattern, text) or re.match(ip_pattern, text))

    @filter.command_group("rss", alias={"RSS"})
    def rss(self):
        pass

    @rss.group("rsshub")
    def rsshub(self, event: AstrMessageEvent):
        pass

    @rsshub.command("add")
    async def rsshub_add(self, event: AstrMessageEvent, url: str):
        if url.endswith("/"):
            url = url[:-1]
        if not self._is_url_or_ip(url):
            yield event.plain_result("请输入正确的URL")
            return
        if url in self.data_handler.data["rsshub_endpoints"]:
            yield event.plain_result("该RSSHub端点已存在")
            return
        self.data_handler.data["rsshub_endpoints"].append(url)
        self.data_handler.save_data()
        yield event.plain_result("添加成功")

    @rsshub.command("list")
    async def rsshub_list(self, event: AstrMessageEvent):
        ret = "当前Bot添加的rsshub endpoint：\n"
        yield event.plain_result(
            ret + "\n".join([f"{i}: {x}" for i, x in enumerate(self.data_handler.data["rsshub_endpoints"])])
        )

    @rsshub.command("remove")
    async def rsshub_remove(self, event: AstrMessageEvent, idx: int):
        if idx < 0 or idx >= len(self.data_handler.data["rsshub_endpoints"]):
            yield event.plain_result("索引越界")
            return
        self.data_handler.data["rsshub_endpoints"].pop(idx)
        self.data_handler.save_data()
        yield event.plain_result("删除成功")

    @rss.command("add")
    async def add_command(
        self,
        event: AstrMessageEvent,
        idx: int,
        route: str,
        minute: str,
        hour: str,
        day: str,
        month: str,
        day_of_week: str,
    ):
        if idx < 0 or idx >= len(self.data_handler.data["rsshub_endpoints"]):
            yield event.plain_result("索引越界, 请使用 /rss rsshub list 查看已经添加的 rsshub endpoint")
            return
        if not route.startswith("/"):
            yield event.plain_result("路由必须以 / 开头")
            return
        url = self.data_handler.data["rsshub_endpoints"][idx] + route
        cron_expr = f"{minute} {hour} {day} {month} {day_of_week}"
        ret = await self._add_url(url, cron_expr, event)
        if isinstance(ret, MessageEventResult):
            yield ret
            return
        yield event.plain_result(f"添加成功。频道信息：\n标题: {ret['title']}\n描述: {ret['description']}")

    @rss.command("add-url")
    async def add_url_command(
        self,
        event: AstrMessageEvent,
        url: str,
        minute: str,
        hour: str,
        day: str,
        month: str,
        day_of_week: str,
    ):
        cron_expr = f"{minute} {hour} {day} {month} {day_of_week}"
        ret = await self._add_url(url, cron_expr, event)
        if isinstance(ret, MessageEventResult):
            yield ret
            return
        yield event.plain_result(f"添加成功。频道信息：\n标题: {ret['title']}\n描述: {ret['description']}")

    @rss.command("list")
    async def list_command(self, event: AstrMessageEvent):
        user = event.unified_msg_origin
        ret = "当前订阅的频道：\n"
        subs_urls = self.data_handler.get_subs_channel_url(user)
        for cnt, url in enumerate(subs_urls):
            info = self.data_handler.data[url]["info"]
            ret += f"{cnt}. {info['title']} - {info['description']}\n"
        yield event.plain_result(ret)

    @rss.command("remove")
    async def remove_command(self, event: AstrMessageEvent, idx: int):
        subs_urls = self.data_handler.get_subs_channel_url(event.unified_msg_origin)
        if idx < 0 or idx >= len(subs_urls):
            yield event.plain_result("索引越界, 请使用 /rss list 查看已经添加的订阅")
            return
        url = subs_urls[idx]
        self.data_handler.data[url]["subscribers"].pop(event.unified_msg_origin)
        self.data_handler.save_data()
        self._fresh_asyncIOScheduler()
        yield event.plain_result("删除成功")

    @rss.command("get")
    async def get_command(self, event: AstrMessageEvent, idx: int):
        subs_urls = self.data_handler.get_subs_channel_url(event.unified_msg_origin)
        if idx < 0 or idx >= len(subs_urls):
            yield event.plain_result("索引越界, 请使用 /rss list 查看已经添加的订阅")
            return
        url = subs_urls[idx]
        rss_items = await self.poll_rss(url)
        if not rss_items:
            yield event.plain_result("没有新的订阅内容")
            return
        item = rss_items[0]
        platform_name, message_type, session_id = event.unified_msg_origin.split(":")
        comps = await self._get_chain_components(item)
        if platform_name == "aiocqhttp" and self.is_compose:
            node = Comp.Node(uin=0, name="Astrbot", content=comps)
            yield event.chain_result([node]).use_t2i(self.t2i)
        else:
            yield event.chain_result(comps).use_t2i(self.t2i)
