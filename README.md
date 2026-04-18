# 🤖 Jarvis AI Desktop Assistant

**Jarvis** is a production-ready, agentic AI desktop assistant that automates complex tasks through voice, text, or gestures. Built with an **Electron** frontend, **FastAPI** backend, and powered by **LLM orchestration**, Jarvis provides seamless automation across your entire system.

## 🌟 Overview

Jarvis follows an **agentic pipeline architecture** where user input is processed through multiple intelligent layers:

1. **Input Layer**: Voice (Whisper STT), Text, or Gestures
2. **Intent Detection**: AI-powered understanding of user requests
3. **Orchestrator**: LLM-based decision-making layer (NVIDIA NIM or Ollama)
4. **Specialized Agents**: Task-specific execution modules
5. **Execution Layer**: Direct interaction with APIs, OS, and browsers
6. **Feedback Loop**: Results returned with context-aware responses

This architecture ensures accurate interpretation, efficient execution, and seamless automation of complex tasks.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                               │
│  Voice (Whisper) │ Text (Chat) │ Gestures (Vision) │ Wake Word  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   INTENT DETECTION ENGINE                        │
│         Heuristic Parser + LLM Planner (JSON routing)           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AI ORCHESTRATOR                               │
│    NVIDIA NIM (Llama 3.1 70B) or Ollama (Mistral 7B)           │
│         Selects appropriate agent based on task                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SPECIALIZED AGENTS                             │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐ │
│  │ System       │ Web Agent    │ Vision       │ File & App   │ │
│  │ Control      │ (Browser)    │ Agent        │ Builder      │ │
│  │ Agent        │              │              │              │ │
│  └──────────────┴──────────────┴──────────────┴──────────────┘ │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐ │
│  │ WhatsApp     │ Google       │ Food &       │ Learning     │ │
│  │ Automation   │ Services     │ Grocery      │ Assistant    │ │
│  └──────────────┴──────────────┴──────────────┴──────────────┘ │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXECUTION LAYER                               │
│    APIs │ Operating System │ Browser │ External Services        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MEMORY & FEEDBACK                              │
│    SQLite (Structured) + ChromaDB (Vector) + TTS Response       │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

- **Backend**: `backend/app` — FastAPI with async skills, safety confirmations, and memory management
- **Frontend**: `electron/` — Floating window with **Ctrl+Shift+J** global hotkey
- **Skills**: `backend/app/skills/*.py` — Auto-loaded modular agents
- **Memory**: SQLite for structured data + ChromaDB for semantic search
- **LLM**: NVIDIA NIM (primary) or Ollama (fallback) for intelligent routing

---

## ✨ Key Features

### 🎯 Core Capabilities

- **🎤 Voice Control**: Whisper-powered speech-to-text with optional Porcupine wake word ("Hey Jarvis")
- **💬 Natural Language**: Conversational interface with context-aware responses
- **🖥️ System Control**: Manage applications, processes, volume, brightness, WiFi
- **🌐 Web Automation**: Browser control via Playwright (search, navigate, scrape)
- **👁️ Vision Mode**: Real-time screen understanding with NVIDIA vision models
- **📱 WhatsApp Integration**: Send/receive messages with automatic QR linking
- **🍕 Food & Grocery**: Smart ordering from Swiggy, Zomato, Blinkit, Zepto
- **📧 Google Services**: Gmail, Calendar, Drive, Docs, Sheets integration
- **📁 File Management**: Create, read, organize, and share files
- **💻 Code Assistant**: Generate code, explain snippets, build Next.js apps
- **🎓 Learning Assistant**: Course search, study plans, progress tracking
- **📰 News & Weather**: Real-time updates from NewsAPI and OpenWeatherMap
- **🧠 Memory System**: Remembers preferences and context across sessions

### 🚀 Advanced Features

- **Agentic Pipeline**: Multi-layer decision-making for complex task execution
- **Safety Confirmations**: Prevents destructive operations without user approval
- **Gesture Control**: Hand tracking for touchless interaction
- **Clipboard Intelligence**: Summarize, translate, and analyze clipboard content
- **Alert System**: Custom rules for system monitoring (CPU, RAM, etc.)
- **Morning Briefing**: Aggregated daily summary of news, weather, and calendar
- **Presentation Generator**: Create PowerPoint presentations from prompts
- **File Sharing**: Upload and generate shareable links

---

## 📋 Prerequisites

### Required

- **Python 3.11+**
- **Node.js 18+** (for Electron and WhatsApp bridge)
- **Ollama** (if not using NVIDIA NIM) — `ollama pull mistral:7b`
- **Playwright browsers**: `playwright install chromium`

### Optional

- **NVIDIA NIM API Key** — For Llama 3.1 70B (faster, more capable)
- **Porcupine Access Key** — For wake word detection
- **Google Cloud OAuth** — For Gmail, Calendar, Drive
- **OpenWeatherMap API Key** — For weather updates
- **NewsAPI Key** — For news headlines
- **AWS Bedrock** — For Claude-powered app builder

---

## 🛠️ Installation

### 1. Backend Setup

```powershell
# Navigate to backend
cd jarvis-assistant\backend

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Configure environment
copy ..\.env.example .env
# Edit .env with your API keys
```

### 2. Environment Configuration

Edit `backend/.env`:

```env
# LLM Configuration (choose one)
NIM_API_KEY=your_nvidia_nim_key_here
NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NIM_FAST_MODEL=meta/llama-3.1-8b-instruct
NIM_SMART_MODEL=meta/llama-3.1-70b-instruct

# OR use Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral:7b

# Optional Services
PORCUPINE_ACCESS_KEY=your_picovoice_key
PORCUPINE_KEYWORD_PATH=hello-vibe_en_wasm_v4_0_0.ppn
OPENWEATHER_API_KEY=your_openweather_key
NEWS_API_KEY=your_newsapi_key

# Google OAuth
GOOGLE_CREDENTIALS_PATH=credentials.json
GOOGLE_TOKEN_PATH=token.json

# WhatsApp Bridge
WHATSAPP_NODE_URL=http://127.0.0.1:3000

# Vision Mode
VISION_FAST_MODEL=nvidia/nemotron-3-nano-vl-8b-v1
VISION_SMART_MODEL=meta/llama-3.2-90b-vision-instruct
VISION_PASSIVE_INTERVAL=4
VISION_ACTIVE_INTERVAL=1

# AWS Bedrock (optional, for app builder)
BEDROCK_ENABLED=false
AWS_REGION=us-east-1
```

### 3. Google Services Setup (Optional)

For Gmail, Calendar, and Drive integration:

1. Create OAuth **Desktop** client in [Google Cloud Console](https://console.cloud.google.com/)
2. Download credentials JSON
3. Set paths in `.env`
4. Run one-time authentication:

```powershell
$env:GOOGLE_OAUTH_LOCAL="1"
python -c "from app.services.google_client import get_credentials; from app.config import get_settings; s=get_settings(); print(get_credentials(s.google_credentials_path, s.google_token_path))"
```

### 4. WhatsApp Bridge Setup

```powershell
# Navigate to WhatsApp integration
cd jarvis-assistant\integrations\jarvis-whatsapp-automation

# Install dependencies
npm install

# Start the bridge
node index.js
# OR use the helper scripts:
# Windows: start.bat
# Linux/Mac: ./start.sh
```

**First-time setup:**
1. The bridge will display a QR code in the terminal
2. Open WhatsApp on your phone → Settings → Linked Devices
3. Tap "Link a Device" and scan the QR code
4. Session is saved in `auth/` folder for future use

**Troubleshooting:** See `integrations/jarvis-whatsapp-automation/TROUBLESHOOTING.md`

### 5. Frontend Setup

```powershell
# Navigate to Electron app
cd jarvis-assistant\electron

# Install dependencies
npm install

# Start the app
npm start
```

---

## 🚀 Running Jarvis

### Start All Services

**Terminal 1 - Backend:**
```powershell
cd jarvis-assistant\backend
.\.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

**Terminal 2 - WhatsApp Bridge (Optional):**
```powershell
cd jarvis-assistant\integrations\jarvis-whatsapp-automation
node index.js
```

**Terminal 3 - Frontend:**
```powershell
cd jarvis-assistant\electron
npm start
```

### Quick Access

- **Global Hotkey**: Press **Ctrl+Shift+J** to show/hide Jarvis
- **API Health**: http://127.0.0.1:8765/health
- **WhatsApp QR**: http://127.0.0.1:3000/qr
- **WhatsApp Health**: http://127.0.0.1:3000/health

---

## 📚 Usage Examples

### Voice Commands

```
"Hey Jarvis, what's the weather today?"
"Open YouTube and play relaxing music"
"Send a WhatsApp message to 917349340870 saying hello"
"Order biryani from Swiggy"
"Create a presentation about AI"
"What's on my calendar today?"
"Increase volume to 50%"
"Search Google for Python tutorials"
```

### Text Commands

```
send Our system follows an agentic pipeline architecture to 917349340870
order pizza from Zomato
create a Next.js app for a todo list
summarize my clipboard
check my Gmail
set brightness to 30%
open calculator
```

### WhatsApp Integration

**Send messages:**
```
send hello to 917349340870
whatsapp 917349340870 How are you doing?
message 917349340870 saying Meeting at 3 PM
```

**Receive messages:**
- Incoming WhatsApp messages are automatically processed
- Jarvis generates intelligent replies
- Replies are queued for your approval in the notification center

---

## 🎯 Skill Modules

| Skill | Description | Key Actions |
|-------|-------------|-------------|
| **browser_agent** | Web automation via Playwright | Google search, YouTube, tab management |
| **whatsapp** | WhatsApp messaging via Baileys | Send messages, auto-reply to incoming |
| **food_grocery** | Smart food ordering | Search, cart, order from Swiggy/Zomato/Blinkit/Zepto |
| **system_control** | OS-level control | Apps, volume, brightness, WiFi, processes |
| **file_manager** | File operations | Create, read, organize, delete files |
| **code_assistant** | Code generation | Generate, explain, write files, build apps |
| **gmail** | Email management | Read, send, search emails |
| **calendar** | Calendar operations | List events, create appointments |
| **drive** | Google Drive | Upload, download, search files |
| **docs** | Google Docs | Create, read, update documents |
| **sheets** | Google Sheets | Create, update spreadsheets |
| **maps** | Location services | Directions, places, navigation |
| **weather** | Weather updates | Current conditions, forecasts |
| **news** | News headlines | Latest news from various sources |
| **clipboard** | Clipboard intelligence | Summarize, translate, analyze |
| **gesture_control** | Hand tracking | Touchless interaction |
| **presentation** | PPT generation | Create presentations from prompts |
| **file_share** | File sharing | Upload and generate share links |
| **briefing** | Daily summary | Morning aggregate of news/weather/calendar |
| **alerts** | System monitoring | Custom alert rules for CPU/RAM |
| **memory_skill** | Context retention | Store and recall preferences |
| **learning_*** | Learning assistant | Course search, study plans, progress |

---

## 🔌 API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service health check |
| GET | `/api/system/metrics` | CPU, RAM, network stats |
| POST | `/api/chat` | Text-based interaction |
| POST | `/api/voice` | Voice input (audio file) |
| POST | `/api/execute` | Direct skill execution |
| GET | `/api/skills` | List all available skills |

### WhatsApp Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/update_status` | Bridge status updates (QR, connection) |
| POST | `/incoming` | Incoming WhatsApp messages |
| GET | `/api/whatsapp/qr` | Get current QR code |
| GET | `/api/notifications` | Pending reply approvals |
| POST | `/api/notifications/approve` | Approve pending reply |
| POST | `/api/notifications/reject` | Reject pending reply |

### Vision Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/vision/start` | Start vision mode |
| POST | `/api/vision/stop` | Stop vision mode |
| POST | `/api/vision/analyze` | Analyze current screen |
| GET | `/api/vision/status` | Vision mode status |
| POST | `/api/vision/voice/start` | Enable voice triggers |
| POST | `/api/vision/overlay` | Configure overlay settings |

### Food & Grocery Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/food/addresses` | List saved addresses |
| POST | `/api/food/addresses` | Add new address |
| POST | `/api/food/addresses/active` | Set active address |
| DELETE | `/api/food/addresses/{label}` | Delete address |

### Wake Word Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/wake/start` | Start wake word listener |
| POST | `/api/wake/stop` | Stop wake word listener |

---

## 🔒 Security & Safety

### Safety Confirmations

Destructive operations require explicit user confirmation when `REQUIRE_CONFIRMATION_DESTRUCTIVE=true`:

- File deletion, renaming, moving
- Process termination
- System-wide changes

### Best Practices

- **Run locally**: API should only listen on `127.0.0.1`
- **Authentication**: Enable `AUTH_ENABLED=true` for production
- **API keys**: Never commit `.env` files to version control
- **WhatsApp**: Use only on personal accounts, respect ToS
- **Permissions**: Grant only necessary OS permissions

---

## 🐛 Troubleshooting

### WhatsApp Issues

**QR code not displaying:**
```powershell
cd integrations\jarvis-whatsapp-automation
node reset_auth.js
node index.js
```

**Connection keeps dropping:**
- Close WhatsApp Web in all browsers
- Ensure only one bridge instance is running
- Check phone is connected to internet

**Messages not sending:**
- Verify bridge is connected: http://127.0.0.1:3000/health
- Check backend logs for parameter extraction
- Ensure phone number format: country code + number (e.g., 917349340870)

See detailed guide: `integrations/jarvis-whatsapp-automation/TROUBLESHOOTING.md`

### Backend Issues

**LLM not responding:**
- Check NIM API key is valid
- Verify Ollama is running: `ollama list`
- Check backend logs for errors

**Skills not loading:**
- Ensure all dependencies are installed
- Check Python version: `python --version` (3.11+)
- Verify virtual environment is activated

**Google services failing:**
- Re-run OAuth flow
- Check credentials.json is valid
- Verify token.json has correct permissions

### Frontend Issues

**Hotkey not working:**
- Check if another app uses Ctrl+Shift+J
- Restart Electron app
- Check system permissions for global shortcuts

**UI not updating:**
- Clear Electron cache
- Restart frontend
- Check WebSocket connection to backend

---

## 📁 Project Structure

```
jarvis-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Configuration management
│   │   ├── dependencies.py      # Dependency injection
│   │   ├── core/
│   │   │   ├── pipeline.py      # Agentic pipeline orchestration
│   │   │   ├── skill_router.py  # Skill routing logic
│   │   │   ├── skill_registry.py # Skill auto-discovery
│   │   │   ├── safety.py        # Safety confirmations
│   │   │   └── memory/          # SQLite + ChromaDB
│   │   ├── services/
│   │   │   ├── llm.py           # LLM planner (NIM/Ollama)
│   │   │   ├── stt_whisper.py   # Speech-to-text
│   │   │   ├── tts_pyttsx3.py   # Text-to-speech
│   │   │   ├── wake_porcupine.py # Wake word detection
│   │   │   ├── google_client.py  # Google OAuth
│   │   │   └── intent_engine.py  # Intent detection
│   │   └── skills/              # Modular skill agents
│   │       ├── browser_agent.py
│   │       ├── whatsapp.py
│   │       ├── food_grocery.py
│   │       ├── system_control.py
│   │       ├── file_manager.py
│   │       ├── code_assistant.py
│   │       └── ... (20+ skills)
│   ├── requirements.txt
│   └── .env
├── electron/
│   ├── main.js                  # Electron main process
│   ├── preload.js               # Secure IPC bridge
│   ├── renderer/                # UI components
│   └── package.json
├── integrations/
│   └── jarvis-whatsapp-automation/
│       ├── index.js             # Baileys WhatsApp bridge
│       ├── reset_auth.js        # Auth reset utility
│       ├── start.bat            # Windows launcher
│       ├── start.sh             # Linux/Mac launcher
│       ├── TROUBLESHOOTING.md   # WhatsApp troubleshooting
│       ├── QUICK_SETUP.md       # 5-minute setup guide
│       └── auth/                # Session storage
├── .env.example
└── README.md
```

---

## 🔧 Advanced Configuration

### AWS Bedrock Integration

For Claude-powered app builder:

```env
BEDROCK_ENABLED=true
AWS_REGION=us-east-1
BEDROCK_CLAUDE_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
# Use either AWS credentials or bearer token
AWS_BEARER_TOKEN_BEDROCK=your_token_here
```

### Custom Wake Word

1. Create custom keyword at [Picovoice Console](https://console.picovoice.ai/)
2. Download `.ppn` file
3. Set `PORCUPINE_KEYWORD_PATH` in `.env`

### Vision Mode

Launch the overlay:

```powershell
cd backend
python run_vision_overlay.py
```

Voice triggers:
- "Jarvis, look at this" — Activate vision analysis
- "Jarvis, stop watching" — Deactivate vision mode

---

## 🤝 Contributing

Contributions are welcome! Areas for improvement:

- Additional skill modules
- Enhanced vision capabilities
- Mobile app integration
- Multi-language support
- Voice cloning for TTS
- Advanced gesture recognition

---

## 📄 License

This project is provided for personal and educational use. Third-party services (NVIDIA NIM, Picovoice, Google, OpenWeather, NewsAPI, WhatsApp) are subject to their respective terms of service.

---

## 🙏 Acknowledgments

- **NVIDIA NIM** — LLM inference
- **Baileys** — WhatsApp Web API
- **Playwright** — Browser automation
- **Whisper** — Speech recognition
- **Porcupine** — Wake word detection
- **FastAPI** — Backend framework
- **Electron** — Desktop application

---

## 📞 Support

For issues and questions:

1. Check the troubleshooting section above
2. Review skill-specific documentation in `backend/app/skills/`
3. Check WhatsApp guide: `integrations/jarvis-whatsapp-automation/TROUBLESHOOTING.md`
4. Review backend logs for detailed error messages

---

## 🚀 Roadmap

- [ ] Mobile companion app
- [ ] Multi-user support
- [ ] Cloud sync for preferences
- [ ] Plugin marketplace
- [ ] Advanced automation workflows
- [ ] Integration with more services (Slack, Discord, Telegram)
- [ ] Voice cloning for personalized TTS
- [ ] Offline mode with local models

---

**Built with ❤️ for seamless AI-powered automation**
