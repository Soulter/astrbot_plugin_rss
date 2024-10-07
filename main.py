import aiohttp, time, re, logging
from lxml import etree
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from util.plugin_dev.api.v1.bot import Context, AstrMessageEvent, CommandResult
from .data_handler import DataHandler
from .rss import RSSItem
from typing import List

class Main:
    def __init__(self, context: Context) -> None:
        self.NAMESPACE = "astrbot_plugin_rss"
        self.logger = logging.getLogger("astrbot")
        self.context = context
        self.data_handler = DataHandler()
        self.context.register_commands(self.NAMESPACE, "rss", "rss 订阅指令", 1, self.rss)
        
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        
        # 为每个订阅添加定时任务
        for url, info in self.data_handler.data.items():
            if url == "rsshub_endpoints" or url == "settings":
                continue
            for user, sub_info in info["subscribers"].items():
                self.scheduler.add_job(self.cron_task_callback, 'cron', **self.parse_cron_expr(sub_info["cron_expr"]), args=[url, user])
    
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
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                text = await resp.read()
                return self.data_handler.parse_channel_info(text)
            
    async def cron_task_callback(self, url: str, user: str):
        '''定时任务回调'''
        self.logger.info(f"RSS 定时任务触发: {url} - {user}")
        last_update = self.data_handler.data[url]["subscribers"][user]["last_update"]
        latest_link = self.data_handler.data[url]["subscribers"][user]["latest_link"]
        max_items_per_poll = self.data_handler.data["settings"]["max_items_per_poll"]
        # 拉取 RSS
        rss_items = await self.poll_rss(url, user, num=max_items_per_poll, after_timestamp=last_update, after_link=latest_link)
        max_ts = last_update
        for item in rss_items:
            # 发送消息
            # TODO: 折叠
            use_t2i = self.data_handler.data["settings"]["t2i"]
            command_result = CommandResult().message(f"频道 {item.chan_title} 有更新了！\n---\n标题: {item.title}\n链接: {item.link}\n---\n{item.description}\n").use_t2i(use_t2i)
            await self.context.send_message(user, command_result)
            self.data_handler.data[url]["subscribers"][user]["last_update"] = time.time()
            self.data_handler.save_data()
            max_ts = max(max_ts, item.pubDate_timestamp)
        # 更新最后更新时间
        if rss_items:
            self.data_handler.data[url]["subscribers"][user]["last_update"] = max_ts
            self.data_handler.data[url]["subscribers"][user]["latest_link"] = rss_items[0].link
            self.data_handler.save_data()
        
        
    async def poll_rss(self, url: str, user: str, num: int = -1, after_timestamp: int = 0, after_link: str = "") -> List[RSSItem]:
        '''从站点拉取RSS信息'''
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    self.logger.error(f"rss: 无法正常打开站点 {url}")
                    return
                text = await resp.read()
                root = etree.fromstring(text)
                items = root.xpath("//item")
                
                cnt = 0
                rss_items = []
                
                for item in items:
                    try:
                        chan_title = self.data_handler.data[url]["info"]["title"] if url in self.data_handler.data else "未知频道"
                        
                        title = item.xpath("title")[0].text
                        if len(title) > self.data_handler.data["settings"]["title_max_length"]:
                            title = title[:self.data_handler.data["settings"]["title_max_length"]] + "..."
                        
                        link = item.xpath("link")[0].text
                        if not re.match(r'^https?://', link):
                            link = self.data_handler.get_root_url(url) + link
                        
                        description = item.xpath("description")[0].text
                        
                        description = self.data_handler.strip_html(description)
                        if len(description) > self.data_handler.data["settings"]["description_max_length"]:
                            description = description[:self.data_handler.data["settings"]["description_max_length"]] + "..."
                        
                        if item.xpath("pubDate"):
                            # 根据 pubDate 判断是否为新内容
                            pub_date = item.xpath("pubDate")[0].text
                            pub_date_parsed = time.strptime(pub_date.replace("GMT", "+0000"), "%a, %d %b %Y %H:%M:%S %z")
                            pub_date_timestamp = int(time.mktime(pub_date_parsed))
                            if pub_date_timestamp > after_timestamp:
                                rss_items.append(RSSItem(chan_title, title, link, description, pub_date, pub_date_timestamp))
                                cnt += 1
                                if num != -1 and cnt >= num:
                                    break
                            else:
                                break
                        else:
                            # 根据 link 判断是否为新内容
                            if link != after_link:
                                rss_items.append(RSSItem(chan_title, title, link, description, "", 0))
                                cnt += 1
                                if num != -1 and cnt >= num:
                                    break
                            else:
                                break
                        
                    except Exception as e:
                        self.logger.error(f"rss: 解析 {url} 失败: {str(e)}")
                        await self.context.send_message(user, CommandResult().message(f"rss 定时任务: 解析 {url} 失败: {str(e)}"))
                        break

                return rss_items
                
    async def rss(self, message: AstrMessageEvent, context: Context):
        args = message.message_str.split(" ")
        help_msg = "【RSS 订阅】\n\n指令描述\n---\n/rss rsshub add <url>: 添加一个 rsshub endpoint\n/rss rsshub list: 列出所有 rsshub endpoint\n/rss rsshub remove <idx>: 删除一个 rsshub endpoint\n/rss add <idx> <route> <cron_expr>: 通过 rsshub 路由订阅\n/rss add-url <url> <cron_expr>: 直接订阅\n/rss list: 列出所有订阅\n/rss remove <idx>: 删除订阅\n/rss get <idx>: 获取最新一条订阅内容"
        cron_tutorial = "cron 表达式格式：\n* * * * *，分别表示分钟 小时 日 月 星期，* 表示任意值，支持范围和逗号分隔。例：\n1. 0 0 * * * 表示每天 0 点触发。\n2. 0/5 * * * * 表示每 5 分钟触发。\n3. 0 9-18 * * * 表示每天 9 点到 18 点触发。\n5. 0 0 1,15 * * 表示每月 1 号和 15 号 0 点触发。\n星期的取值范围是 0-6，0 表示星期天。"
        help_msg += "\n\n" + cron_tutorial
        if len(args) < 2:
            return CommandResult().message(help_msg).use_t2i(False)
        if args[1] == "rsshub":
            return await self.rsshub_subcommand(message, context)
        elif args[1] == "add":
            return await self.add_subcommand(message, context)
        elif args[1] == "add-url":
            return await self.add_url_subcommand(message, context)
        elif args[1] == "list":
            return await self.list_subcommand(message, context)
        elif args[1] == "remove":
            return await self.remove_subcommand(message, context)
        elif args[1] == "get":
            return await self.get_subcommand(message, context)
        else:
            return CommandResult().message(help_msg).use_t2i(False)
        
    async def get_subcommand(self, message: AstrMessageEvent, context: Context):
        '''直接获取最新一条订阅内容'''
        args = message.message_str.split(" ")
        if len(args) < 3:
            return CommandResult().message("参数不足, 请使用 /rss get <idx> idx 请查已经添加的订阅").use_t2i(False)
        idx = int(args[2])
        subs_urls = self.data_handler.get_subs_channel_url(message.unified_msg_origin)
        if idx < 0 or idx >= len(subs_urls):
            return CommandResult().message("索引越界, 请使用 /rss list 查看已经添加的订阅").use_t2i(False)
        url = subs_urls[idx]
        rss_items = await self.poll_rss(url, message.unified_msg_origin, 1)
        if not rss_items:
            return CommandResult().message("没有新的订阅内容")
        item = rss_items[0]
        return CommandResult().message(f"频道 {item.chan_title} 最新 Feed\n---\n标题: {item.title}\n链接: {item.link}\n---\n{item.description}\n").use_t2i(False)
          
    async def rsshub_subcommand(self, message: AstrMessageEvent, context: Context):
        args = message.message_str.split(" ")
        if len(args) < 3:
            return CommandResult().message("参数不足。用法：/rss rsshub add <url> | list | remove <idx>")
        if args[2] == "add":
            if len(args) < 4:
                return CommandResult().message("参数不足")
            if args[3].endswith("/"):
                args[3] = args[3][:-1]
            self.data_handler.data["rsshub_endpoints"].append(args[3])
            self.data_handler.save_data()
            return CommandResult().message("添加成功")
        elif args[2] == "list":
            ret = "当前 Bot 添加的 rsshub endpoint：\n"
            return CommandResult().message(ret + "\n".join([f"{i}: {x}" for i, x in enumerate(self.data_handler.data["rsshub_endpoints"])]))
        elif args[2] == "remove":
            if len(args) < 4:
                return CommandResult().message("参数不足")
            idx = int(args[3])
            if idx < 0 or idx >= len(self.data_handler.data["rsshub_endpoints"]):
                return CommandResult().message("索引越界")
            self.data_handler.data["rsshub_endpoints"].pop(idx)
            self.data_handler.save_data()
            return CommandResult().message("删除成功")
        else:
            return CommandResult().message("未知子命令")
        
    async def add_subcommand(self, message: AstrMessageEvent, context: Context):
        '''添加 rsshub 订阅（路由）'''
        args = message.message_str.split(" ")
        if len(args) < 9:
            return CommandResult().message("参数不足")
        idx = int(args[2])
        if idx < 0 or idx >= len(self.data_handler.data["rsshub_endpoints"]):
            return CommandResult().message("索引越界, 请使用 /rss rsshub list 查看已经添加的 rsshub endpoint").use_t2i(False)
        route = args[3]
        if not route.startswith("/"):
            return CommandResult().message("路由必须以 / 开头")
        url = self.data_handler.data["rsshub_endpoints"][idx] + route
        cron_expr = " ".join(args[4:9])
        
        ret = await self._add_url(url, cron_expr, message)
        if isinstance(ret, CommandResult):
            return ret
        else:
            chan_title = ret["title"]
            chan_desc = ret["description"]
        
        self.scheduler.add_job(self.cron_task_callback, 'cron', **self.parse_cron_expr(cron_expr), args=[url, message.unified_msg_origin])
                
        return CommandResult().message(f"添加成功。频道信息：\n标题: {chan_title}\n描述: {chan_desc}").use_t2i(False)
    
    async def add_url_subcommand(self, message: AstrMessageEvent, context: Context):
        '''直接通过 feed 链接添加订阅'''
        args = message.message_str.split(" ")
        if len(args) < 8:
            return CommandResult().message("参数不足")
        ret = await self._add_url(args[2], " ".join(args[3:8]), message)
        if isinstance(ret, CommandResult):
            return ret
        else:
            chan_title = ret["title"]
            chan_desc = ret["description"]
            
        self.scheduler.add_job(self.cron_task_callback, 'cron', **self.parse_cron_expr(" ".join(args[3:8])), args=[args[2], message.unified_msg_origin])
        
        return CommandResult().message(f"添加成功。频道信息：\n标题: {chan_title}\n描述: {chan_desc}").use_t2i(False)
    
    async def _add_url(self, url: str, cron_expr: str, message: AstrMessageEvent):
        user = message.unified_msg_origin
        if url in self.data_handler.data:
            latest_item = await self.poll_rss(url, user, 1)
            self.data_handler.data[url]["subscribers"][user] = {
                "cron_expr": cron_expr,
                "last_update": latest_item[0].pubDate_timestamp,
                "latest_link": latest_item[0].link,
            }
        else:
            try:
                title, desc = await self.parse_channel_info(url)
                latest_item = await self.poll_rss(url, user, 1)
            except Exception as e:
                return CommandResult().error(f"解析频道信息失败: {str(e)}").use_t2i(False)
                    
            self.data_handler.data[url] = {
                "subscribers": {
                    user: {
                        "cron_expr": cron_expr,
                        "last_update": latest_item[0].pubDate_timestamp,
                        "latest_link": latest_item[0].link,
                    }
                },
                "info": {
                    "title": title,
                    "description": desc,
                }
            }
        self.data_handler.save_data()
        return self.data_handler.data[url]["info"]
    
    async def list_subcommand(self, message: AstrMessageEvent, context: Context):
        user = message.unified_msg_origin
        ret = "当前订阅的频道：\n"
        subs_urls = self.data_handler.get_subs_channel_url(user)
        cnt = 0
        for url in subs_urls:
            info = self.data_handler.data[url]['info']
            ret += f"{cnt}. {info['title']} - {info['description']}\n"
            cnt += 1
        return CommandResult().message(ret).use_t2i(False)
    
    async def remove_subcommand(self, message: AstrMessageEvent, context: Context):
        args = message.message_str.split(" ")
        if len(args) < 3:
            return CommandResult().message("参数不足")
        idx = int(args[2])
        keys = list(self.data_handler.data.keys())
        if idx < 0 or idx >= len(keys):
            return CommandResult().message("索引越界, 请使用 /rss list 查看已经添加的订阅").use_t2i(False)
        self.data_handler.data.pop(keys[idx])
        self.data_handler.save_data()
        return CommandResult().message("删除成功")