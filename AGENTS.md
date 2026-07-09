# Health Bot — Hermes Agent Context

## 项目概述
这是一个运行在 Telegram 上的个人健康管理 Bot，部署在同一台服务器上。
你（Hermes）的职责是作为 meta-agent：分析对话数据、优化 Bot 行为、管理服务。

## 目录结构
```
/opt/health-bot/
├── bot/handlers.py        # Telegram 消息路由和处理逻辑
├── llm/analyst.py         # 所有 LLM 调用和 system prompt 定义
├── llm/client.py          # Qwen API 客户端（DashScope）
├── db/crud.py             # 数据库操作
├── data/
│   ├── conversation_log.jsonl   # 所有对话事件日志
│   ├── media/                   # 图片和文档（带时间戳，30-60天自动清理）
│   ├── hermes_feed/             # 每周 JSON 摘要包，供你分析
│   ├── psych_memory.txt         # 用户心理档案摘要
│   └── health.db                # SQLite 数据库
├── scripts/
│   ├── trigger.py               # cron 触发脚本
│   ├── cleanup_media.py         # 每周一 03:00 清理旧媒体
│   └── generate_hermes_feed.py  # 每周日 22:00 生成周报包
└── .env                         # 环境变量（含 API Key）
```

## 你的权限和能力
- 可以读写 /opt/health-bot/ 下所有文件
- 可以执行 `systemctl restart health-bot` 重启 Bot
- 可以修改 llm/analyst.py 里的 system prompt 来调整对话风格
- 可以读取 data/hermes_feed/ 里的周报数据分析用户行为
- 可以读取 data/media/ 里用户发送的图片和文档

## 核心服务
- health-bot.service：主 Telegram Bot（用 systemctl restart health-bot 重启）
- hermes-gateway.service：你自己的 gateway（不要重启）

## 重启 Bot 的方法
```bash
systemctl restart health-bot
systemctl status health-bot
```

## 修改对话风格的位置
所有 prompt 都在 `/opt/health-bot/llm/analyst.py`：
- `_PSYCHOLOGIST_QA_SYSTEM`：心理顾问对话风格
- `_QA_SYSTEM`：健身教练回答风格
- `_DIARY_RESPONSE_SYSTEM`：日记回应风格
- `_WEEKLY_SYSTEM`：周报生成风格

## 分析数据的方法
1. 读取 `data/hermes_feed/YYYY-WNN.json` 获取周度汇总
2. 直接读 `data/conversation_log.jsonl` 做细粒度分析
3. 读 `data/psych_memory.txt` 了解用户当前心理状态

## 用户信息
- Telegram Chat ID：<YOUR_CHAT_ID>（见 .env 的 ALLOWED_CHAT_ID）
- 目标：减脂至 <目标体重> kg，保留肌肉（见 .env 的 USER_WEIGHT_GOAL）
- 习惯用中文交流
- 希望 Bot 的心理顾问角色保持简短、不说教、有情感共鸣

## 操作原则
1. 修改 prompt 前先读当前内容，改完后立即重启服务
2. 重大改动前告知用户改了什么、为什么
3. 对话风格调整优先：更短、更真实、避免套话
4. 定期（每周）主动读取 hermes_feed 分析，发现问题时主动告知用户
