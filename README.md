# 🚀 Parked Bots: The Ultimate Multi-Bot Engine

### *Stop running separate scripts for every Telegram bot. Manage, persist, and broadcast across an entire fleet from a single, beautiful master admin panel.*

[](https://www.python.org)
[suspicious link removed]
[](https://opensource.org/licenses/MIT)

---

## 🌟 The Evolution: From Single-File to Enterprise Fleet

We took a fragile, memory-wiped prototype and engineered it into a robust, battle-tested system that survives restarts, manages infinite bots, and gives you god-mode control over your entire network.

| Power Feature | The Old Way | The Parked Bots Way |
| --- | --- | --- |
| **🧠 Memory Resilience** | In-memory `dict` — wiped on every server restart. | **Atomic JSON persistence** per bot. Your data is safe. |
| **🔀 Smart Routing** | Reply routing broke instantly on restart. | **Persistent routing maps** maintain conversations seamlessly. |
| **🎁 Elite Onboarding** | One boring, hardcoded Markdown string for everyone. | **Dynamic channel-cloning** via `copy_message` (No "Forwarded" tag!). |
| **🤫 Visitor Etiquette** | Spammed return visitors with the same long welcome. | **Smart Recognition:** Return users get crisp, random acks. |
| **🕹️ Central Command** | None. You were flying completely blind. | **Interactive `/admin` panel** with full UI via the Master Bot. |
| **📄 Rich Media Replies** | Text-only channel replies. | **Full media support** (Photos, Documents, Stickers, Audio). |

---

## 🏗️ Architecture Blueprint

The ecosystem is split into clean, modular components designed to prevent circular dependencies and maximize performance:

* `config.py` — The nervous system. Houses tokens, system admins, and core file paths.
* `registry.py` — The traffic controller. Shares running applications globally across modules.
* `storage.py` — The vault. Handles atomic disk writes and persistent routing maps.
* `texts.py` — The copywriter. Manages MarkdownV2 escaping and conversational responses.
* `handlers.py` — The muscle. Processes user entry flows and routes channel replies.
* `admin_panel.py` — The cockpit. Powers the multi-step inline admin keyboard.
* `main.py` — The ignition key. Initializes, hooks up, and fires up the entire fleet.

---

## 🛠️ Launch Sequence (Quick Start)

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/parked-bots.git
cd parked-bots
pip install -r requirements.txt

```

### 2. Configure Your Core (`config.py`)

Open `config.py` and set your master parameters:

* **Set Admin IDs:** Find your numeric ID via **@userinfobot** and add it to `ADMIN_IDS`.
* **Hook up the Log Channel:** Add your `LOG_CHANNEL_ID`.

> ⚠️ **Crucial Step:** Every single bot listed in your configuration must be granted **Administrator privileges** in your Log Channel so they can read, write, and mirror content safely.

### 3. Ignition

```bash
python main.py

```

---

## 🛰️ Deep Dive: Features & Mechanics

### 🔮 Seamless Welcomes & Rich Media

When a stranger knocks on any bot's door for the first time, the bot instantly clones a specified post straight from your private log channel using Telegram’s advanced `copy_message` API.

* **Zero Footprint:** It appears as a native, bespoke message from the bot itself—no messy "Forwarded from..." tags.
* **Media Fluidity:** If your log channel post has buttons, images, or documents, the bot clones them perfectly.

### 🎛️ The Master Dashboard (`/admin`)

Accessible *only* to verified creators through the Master Bot, this inline terminal gives you total control:

```
⚙️ MASTER ADMIN PANEL
├── 📊 Global Statistics (Users, messages, daily active charts)
├── 👥 User Registry (Inspect profiles, wipe histories, or reset welcome flags)
├── 🆔 Content Router (Live-assign which channel post maps to which bot welcome)
└── 📢 Hyper-Broadcast Terminal

```

> **Note on Broadcasting:** The broadcast system features a built-in algorithmic delay queue, protecting your bot tokens from getting rate-limited or banned by Telegram's strict anti-flood policies.

---

## 🐳 Cloud Deployment Notice

Because this system relies on high-speed atomic JSON writes to keep your data intact without expensive database overhead, **an ephemeral file system will wipe your history on redeploy.**

If hosting on platforms like **Railway, Render, Fly.io, or Heroku**, you *must* mount a persistent volume at the `/data` directory path to ensure your users stay saved forever!

---

## 🤝 Contributing & Customization

We love open source! If you want to transition this project to environment variables (`.env`) or hook up an asynchronous SQL database, feel free to fork, create a feature branch, and submit a Pull Request.

*Proudly built for the developer who commands fleets, not single ships. 🚀*