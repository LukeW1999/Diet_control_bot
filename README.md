# 🏋️ Health Management Telegram Bot / 健康管理 Telegram Bot

> A personal Telegram bot for tracking diet, body composition, workouts, and daily notes — powered by Qwen Vision API.
>
> 个人使用的 Telegram 健康管理 Bot，通过图片和文字记录饮食、身体成分、力量训练，由 Qwen 视觉 API 驱动。

---

## Features / 功能

| Feature | 功能 |
|---|---|
| 📸 Parse 薄荷健康 diet screenshots | 解析薄荷健康饮食截图，自动记录三餐和热量 |
| ⚖️ Parse body composition reports | 解析体成分报告（体脂率、骨骼肌量等） |
| 💪 Log workouts via natural language | 用自然语言记录力量训练 |
| 📊 Daily calorie deficit summary at 21:30 | 每晚 21:30 推送热量缺口和月均减脂速度 |
| ☀️ Morning weather + health briefing | 每早推送曼彻斯特天气 + 昨日健康数据 |
| 📝 Work/study notes with AI classification | 16:00 提醒记录笔记，Qwen 自动分类 |
| 📔 Mood & diary recording | 支持心情日记记录 |
| 📅 Weekly health report + notes summary | 每周自动生成健康周报和笔记整理 |
| 💬 Natural language queries | 自然语言查询饮食历史、体重趋势 |
| ✏️ Conversational data correction | 对话纠错（"内脏脂肪应该是13"） |

---

## Tech Stack / 技术栈

- **Runtime**: Python 3.10+
- **Telegram**: `python-telegram-bot` v21
- **LLM / Vision**: Qwen VL Max via DashScope API (OpenAI-compatible)
- **Database**: SQLite + SQLAlchemy
- **Scheduler**: APScheduler (Europe/London timezone)
- **Weather**: Open-Meteo (free, no key required)

---

## Quick Start / 快速开始

### 1. Clone & install / 克隆并安装

```bash
git clone https://github.com/LukeW1999/Diet_control_bot.git
cd Diet_control_bot
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure / 配置

```bash
cp .env.example .env
```

Edit `.env` / 编辑 `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token        # from @BotFather
ALLOWED_CHAT_ID=your_telegram_chat_id    # send /start to get this

QWEN_API_KEY=your_dashscope_key          # DashScope API key
QWEN_VISION_MODEL=qwen-vl-max
QWEN_TEXT_MODEL=qwen-plus

USER_BMR=1916                            # your basal metabolic rate
USER_WEIGHT_GOAL=74.8                    # target weight (kg)
USER_PROTEIN_GOAL_PER_KG=1.8            # protein target per kg bodyweight
```

### 3. Run / 运行

```bash
python main.py
```

Send `/start` to your bot to get your Chat ID, then update `ALLOWED_CHAT_ID` in `.env`.

发送 `/start` 给 bot 获取你的 Chat ID，填入 `.env` 后重启。

### 4. Run as a service (Linux) / 作为系统服务运行

```bash
cat > /etc/systemd/system/health-bot.service << 'EOF'
[Unit]
Description=Health Bot
After=network.target

[Service]
WorkingDirectory=/opt/health-bot
ExecStart=/opt/health-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable health-bot && systemctl start health-bot
```

---

## Usage / 使用方式

### Send images / 发图片

| Image type | Action |
|---|---|
| 薄荷健康 daily food log screenshot | Auto-parse all meals, calories, macros |
| Body composition report screenshot | Auto-parse weight, body fat, skeletal muscle |
| Weight history chart | Bulk import historical weight data |

### Send text / 发文字

```
今天深蹲 100kg 5组5次，卧推 80kg 4组8次   → workout logged
今天体重 91.2                              → quick weight entry
昨天吃了什么                              → diet history query
多久吃过一次汉堡                          → food frequency search
内脏脂肪应该是 13，不是 42               → correct a misread value
今天和导师开了会，讨论了论文方向          → note saved (auto-classified)
今天有点累但状态还行                      → diary/mood recorded
```

### Commands / 指令

| Command | Description |
|---|---|
| `/start` | Welcome message + get Chat ID |
| `/today` | Today's calorie & nutrition summary |
| `/week` | 7-day overview with weight trend |
| `/body` | Latest body composition data |
| `/workout` | This week's training log |
| `/report` | Trigger weekly health report |

---

## Data Storage / 数据存储

```
data/
├── health.db          # SQLite — diet, body composition, workouts, diary
├── food_log.txt       # Plain text food log (grep-friendly)
└── notes/
    ├── 2026-05-24.md  # Daily notes (Markdown)
    └── ...
```

---

## Scheduled Jobs / 定时任务

| Time (UK) | Job |
|---|---|
| 08:00 | Morning briefing: weather + yesterday's stats |
| 16:00 | Notes reminder |
| 21:30 | Evening summary: today's deficit + 30-day projected fat loss |
| Monday 09:00 | Weekly health report |
| Sunday 20:00 | Weekly notes summary |

---

## Notes / 注意事项

- This is a **personal-use** project. Only one `ALLOWED_CHAT_ID` is supported.
- 仅供**个人使用**，只允许一个授权 Chat ID 访问。
- API keys should never be committed to git — `.env` is in `.gitignore`.
- API Key 不提交 git，`.env` 已加入 `.gitignore`。
- Requires a Qwen / DashScope API key — [apply here](https://dashscope.aliyun.com/).
- 需要阿里云 DashScope API Key。

---

## License

MIT — personal use, fork freely.
