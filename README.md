# astrbot-plugin-rss

Get Everything You Want to Know / 获取你想知道的一切。

支持通过 RSSHub 路由和直接 URL 订阅 RSS 源，并定时获取最新的 RSS 内容。

## 功能

- 添加、列出和删除 RSSHub endpoint
- 通过 RSSHub 路由订阅 RSS 源
- 直接通过 URL 订阅 RSS 源
- 列出所有订阅
- 删除订阅
- 获取最新一条订阅内容

## 指令描述

### RSSHub 相关指令

- `/rss rsshub add <url>`: 添加一个 RSSHub endpoint
- `/rss rsshub list`: 列出所有 RSSHub endpoint
- `/rss rsshub remove <idx>`: 删除一个 RSSHub endpoint

### 订阅相关指令

- `/rss add <idx> <route> <cron_expr>`: 通过 RSSHub 路由订阅
- `/rss add-url <url> <cron_expr>`: 直接订阅
- `/rss list`: 列出所有订阅
- `/rss remove <idx>`: 删除订阅
- `/rss get <idx>`: 获取最新一条订阅内容

## Cron 表达式教程

Cron 表达式格式：`* * * * *`，分别表示分钟、小时、日、月、星期，`*` 表示任意值，支持范围和逗号分隔。例：

1. `0 0 * * *` 表示每天 0 点触发。
2. `0/5 * * * *` 表示每 5 分钟触发。
3. `0 9-18 * * *` 表示每天 9 点到 18 点触发。
4. `0 0 1,15 * *` 表示每月 1 号和 15 号 0 点触发。

星期的取值范围是 0-6，0 表示星期天。

## 安装

参考 AstrBot 安装插件方式。

## 配置

插件成功启动后，配置文件位于 `data/astrbot_plugin_rss_data.json`]。

其中 `settings` 部分为插件配置，目前支持的配置项有：

```
"settings": {
    "title_max_length": 30, # 推送的标题最大长度。
    "description_max_length": 500, # 推送的描述最大长度。
    "t2i": false # 是否需要将文字转换为图片发送。
}
```

## 限制

由于 QQ 官方对主动消息限制较为严重，因此主动推送不支持 qqofficial 消息平台。

## 贡献

欢迎提交 issue 和 pull request 来帮助改进这个项目。