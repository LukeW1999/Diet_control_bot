# 🏋️ Health Management Telegram Bot / 健康管理 Telegram Bot

> A personal Telegram bot for tracking diet, body composition, workouts, and daily notes — powered by Qwen Vision API.
>
> 个人使用的 Telegram 健康管理 Bot，通过图片和文字记录饮食、身体成分、力量训练，由 Qwen 视觉 API 驱动。

---

## Features / 功能

| Feature | 功能 |
|---|---|
| 📸 Parse 薄荷健康 diet screenshots | 解析薄荷健康饮食截图，自动记录三餐和热量 |
| ⚖️ Parse body composition reports | 解析体成分报告（体脂率、骨骼肌量等），支持多图相册发送 |
| 💪 Log workouts via natural language | 用自然语言记录力量训练 |
| 📊 Daily calorie deficit summary at 21:30 | 每晚 21:30 推送热量缺口和月均减脂速度 |
| ☀️ Morning briefing with Nietzsche quote | 每早推送天气 + 昨日健康数据 + 查拉图斯特拉金句 |
| 📝 Work/study notes with AI classification | 16:00 提醒记录笔记，Qwen 自动分类 |
| 📔 Mood & diary recording | 支持心情日记，AI 心理顾问回应 |
| 📅 Weekly health report + notes summary | 每周自动生成健康周报和笔记整理 |
| 💬 Natural language queries | 自然语言查询饮食历史、体重趋势 |
| ✏️ Conversational data correction | 对话纠错（"骨骼肌量应该是 xx"） |
| 👤 Dynamic BMR via /profile | 根据体重自动计算基础代谢，随减脂进度更新 |

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

USER_WEIGHT_GOAL=75.0                    # target weight (kg)
USER_PROTEIN_GOAL_PER_KG=1.8            # protein target per kg bodyweight
```

### 3. Set up quotes (first run) / 初始化金句库

```bash
python scripts/setup_quotes.py
```

This downloads the Zarathustra text and extracts quotes into `data/zarathustra_quotes.txt`.

初始化《查拉图斯特拉如是说》金句库（仅首次需要）。

### 4. Set personal profile / 设置个人资料

After starting the bot, send:

```
/update age 25
/update height 175
/update gender male
```

BMR will be calculated automatically from your profile + current weight.

个人资料存储在本地数据库，不会上传至 GitHub。

### 5. Run / 运行

```bash
python main.py
```

Send `/start` to your bot to get your Chat ID, then update `ALLOWED_CHAT_ID` in `.env`.

### 6. Run as a service (Linux) / 作为系统服务运行

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
| Body composition report (1–3 screenshots as album) | Auto-parse and merge all body metrics |
| Weight history chart | Bulk import historical weight data |

### Send text / 发文字

```
今天深蹲 100kg 5组5次，卧推 80kg 4组8次   → workout logged
今天体重 85.0                              → quick weight entry
昨天吃了什么                              → diet history query
多久吃过一次放纵餐                        → food frequency search
骨骼肌量应该是 35，不是 30               → correct a misread value
今天学了 XXX，思考了 YYY                  → note saved (auto-classified)
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
| `/profile` | View personal profile + current BMR |
| `/update age 25` | Set age (stored locally only) |
| `/update height 175` | Set height in cm |
| `/update goal 75.0` | Set target weight |

---

## Data Storage / 数据存储

```
data/
├── health.db               # SQLite — diet, body composition, workouts, diary
├── food_log.txt            # Plain text food log (grep-friendly)
├── zarathustra_quotes.txt  # Generated locally, not in git
└── notes/
    ├── 2026-01-01.md       # Daily notes (Markdown)
    └── ...
```

All personal data (health metrics, diary, notes) stays on your server — never in git.

---

## Scheduled Jobs / 定时任务

| Time (UK) | Job |
|---|---|
| 08:00 | Morning briefing: weather + yesterday's stats + Nietzsche quote |
| 16:00 | Notes reminder |
| 21:30 | Evening summary: today's deficit + 30-day projected fat loss |
| Monday 09:00 | Weekly health report |
| Sunday 20:00 | Weekly notes summary |

---

## Notes / 注意事项

- This is a **personal-use** project. Only one `ALLOWED_CHAT_ID` is supported.
- 仅供**个人使用**，只允许一个授权 Chat ID 访问。
- API keys should never be committed to git — `.env` is in `.gitignore`.
- Personal data (age, height, weight) is stored in local SQLite only.
- Requires a Qwen / DashScope API key — [apply here](https://dashscope.aliyun.com/).

---

## License

MIT — personal use, fork freely.
