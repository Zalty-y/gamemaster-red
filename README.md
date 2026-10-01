<div align="center">

# 🎲🧵 gamemaster-red

**The AI gamemaster layer for your Minecraft server — meet Red.**

*Chat with it. It watches the server tick by tick, acts like a gamemaster,
plays its part as an NPC, and reaches for the right tools when it needs them.*

`early development` · `Java Edition servers` · `bring your own model` · `Python / LangGraph`

</div>

---

> [!IMPORTANT]
> NOT AN OFFICIAL MINECRAFT PRODUCT OR SERVICE. NOT APPROVED BY OR ASSOCIATED
> WITH MOJANG OR MICROSOFT. (See [Legal](#legal--disclaimers) below.)

---

## What is this?

gamemaster-red wires large language models into the part of Minecraft you never
had an API for: **the server itself**.

Most AI-Minecraft projects build a bot — another player with a prompt. This one
is different: Red is not *in* the world, Red **runs** it. The server perceives
(chat, events, world state), the model reasons, and Red acts — subject to
permissions *you* configure, through an allowlisted action registry.

One project, three escalating layers. Start with whichever one fits the time
you can invest:

| Layer | What it does | Status |
|---|---|---|
| 💬 **Chat** | Invoke Red from in-game chat; answer questions, explain mechanics, summarize events | 🚧 in development |
| 🎭 **Gamemaster** | Event-driven actions: time of day, player milestones, world events → announcements, weather, spawns, rewards — triggered by the model, gated by you | 📋 planned |
| 🪙 **Roleplay** | Persistent NPCs with persona and memory that live in the world and talk to players in character | 📋 planned |

Underneath all three sits an **extensible tool layer** — the part that turns
"a chatbot on a Minecraft server" into an agent:

- 📖 **Minecraft Wiki lookup** — fetch authoritative answers at runtime instead of hoping they're in the model's training data
- 🛠️ **Crafting knowledge base** — recipe graphs the model can query, validate, and explain
- 📦 **Modpack integrations** — expose modded items/recipes (REI/JEI data) so Red speaks your pack's language
- 🔌 **Tool API** — register your own tools (MCP-compatible); permission-gated, allow-listed, auditable

## Architecture in one paragraph

gamemaster-red is a **separate Python service** (agent flow built on
[LangGraph](https://github.com/langchain-ai/langgraph)) that connects to your
server through pluggable adapters: **Adapter A** — zero-install — tails
`logs/latest.log` for events and commands via RCON; **Adapter B** — a thin,
dumb Paper plugin for structured events and native actions — is the next
experiment. All adapters speak one versioned JSON envelope (see
[`ARCHITECTURE.md`](ARCHITECTURE.md)). The server never blocks on a model
call; the service never touches Java.

## Why "Red"?

Short enough to call from chat — `/red how do I build an auto-smelter?` — and
short enough for players to actually use it. (Redstone runs the wires; Red
runs the mind.)

## Philosophy

- **Bring your own model.** OpenAI-compatible endpoints, local models via
  Ollama/LM Studio, or anything in between. No vendor lock-in, no hidden
  proxy, your API key never leaves your server.
- **The server stays yours.** Every model-initiated action goes through
  configured, permission-gated tools. Red can't OP itself. *(It will ask.)*
- **World-changing actions can require a player's confirm.** Gamemaster
  power with a seatbelt.
- **Runs on the server's box, not your laptop.** No client mod required —
  players need nothing installed.
- **No telemetry.** Your chat, your events, your keys stay on your machine
  and go only to the model endpoint *you* configured.

## Quickstart *(preview — Adapter A, API subject to change)*

```bash
pip install gamemaster-red
gamemaster-red init      # writes config.toml, probes for logs/latest.log
gamemaster-red run
```

```toml
# config.toml
[servers.survival]
log_path    = "/srv/minecraft/logs/latest.log"
rcon_host   = "127.0.0.1"
rcon_port   = 25575
rcon_password_env = "MC_RCON_PASSWORD"   # never in the file

[model]
endpoint = "https://api.openai.com/v1"   # or http://localhost:11434/v1
name     = "gpt-4o-mini"                 # or llama3.1:8b, etc.
api_key_env = "OPENAI_API_KEY"

[persona]
name  = "Red"
style = "friendly, concise, a little wry"

[permissions.red]
actions           = ["chat.send", "announce"]
cmd_exec_prefixes = ["time set", "weather ", "tell ", "say "]
```

On the server: `enable-rcon=true` + `rcon.password=…` in `server.properties`
(that's the entire install). Then type `/red hello` in game.

## Roadmap

- [ ] Adapter A: log-tail ingestion + RCON actions (chat answers via `/red`)
- [ ] Tool API: wiki lookup, crafting KB
- [ ] Trigger engine → gamemaster actions (event rules + confirm flow)
- [ ] Adapter B: Paper bridge plugin (structured events, native actions)
- [ ] NPC layer: persistent entities, per-NPC personas and memory
- [ ] Modpack data integrations (REI/JEI recipe import)
- [ ] Velocity/BungeeCord multi-server; Bedrock via Geyser — later, maybe

## Contributing

Contributions welcome — please open an issue before big changes so we can
agree on direction first. The tool API in particular is designed to be
"more tools than I'll ever have time to write."

By contributing you confirm your contribution is licensed under this
project's license and contains no Minecraft game code or assets.

## Legal & disclaimers

**Minecraft.** Minecraft is a trademark of Mojang Synergies AB, and
gamemaster-red is an independent fan project. **NOT AN OFFICIAL MINECRAFT
PRODUCT OR SERVICE. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.**
gamemaster-red is distributed as a standalone service; it contains no
Minecraft code, assets, or data files, and requires a genuine licensed copy
of Minecraft. This project follows Mojang's
[Minecraft Usage Guidelines](https://www.minecraft.net/en-us/usage-guidelines)
and the [Minecraft EULA](https://www.minecraft.net/eula). Game vocabulary
("gamemaster", "red", "redstone", "NPC") is used descriptively. "Redstone"
is also the name of unrelated third-party software products; no affiliation
or association is claimed or implied.

**AI content.** Responses are generated by third-party language models chosen
and configured by the server operator. gamemaster-red is not affiliated with,
or a party to, the terms of service of any model provider. Model output is
not monitored or verified by this project; you are responsible for your
provider's API terms, costs, and data handling. Prompts may include gameplay
context (chat text, player names, world state); no model provider is endorsed
or recommended by Mojang or Microsoft.

**Wiki content.** The wiki tool retrieves content from community wikis at
runtime and displays attribution with links. Text from
[minecraft.wiki](https://minecraft.wiki) is licensed
CC BY-NC-SA 3.0 by its contributors; see their
[Generative AI policy](https://minecraft.wiki/w/Minecraft_Wiki:Generative_AI_policy)
— the tool fetches and cites, and does not redistribute or bulk-retrain on
wiki content.

**Trademarks.** All other trademarks are the property of their respective
owners and are used for identification purposes only.

**Liability.** This software is provided "as is", without warranty of any
kind, as set out in the [LICENSE](LICENSE). If Red tells your villagers to
unionize, that's between you and your server.

## License

[MIT](LICENSE) © 2026 gamemaster-red contributors

---

*gamemaster-red — the mind behind the screen. Made by fans, for servers. 🎲*
