# gamemaster-red — MVP Milestone Spec

**Status:** buildable · One file per milestone. This one scopes the first
release: Tracks 1 and 3 (Docker + uv) on Adapter Logtail, serving the
ARCHITECTURE.md §12 requirement — a non-specialist answering in chat without
reading anything but the README.

The genre line: [ARCHITECTURE.md](ARCHITECTURE.md) is the permanent contract —
violations there are bugs. This file is the buildable slice of it — violations
here are just unfinished work. Design lives exclusively in ARCHITECTURE.md;
this file **references, never restates**, so there is one place to fix when a
decision changes.

**Freeze rule:** the first release tag stamps this file, and it freezes.
Post-ship changes need a `BREAKING` note against the shipped release. The next
milestone is written from MVP's *measured* results (§3), not from this file's
optimism.

---

## 1. What ships

Everything ARCHITECTURE.md specifies for the Logtail path, delivered through
two of the three §12.2 tracks:

| track | surface | status |
|---|---|---|
| 🐳 compose | Track 1 — full spec in ARCHITECTURE.md §12.3 (build it verbatim) | MVP |
| 🐍 uvx / uv tool | Track 3 — decision §12.5, user surface §12.5 | MVP |
| 🧩 plugin + wizard | Track 2 — spec §12.4, unscheduled | deferred (§6) |

## 2. In scope

| area | ships | design lives at |
|---|---|---|
| Adapter Logtail | complete mechanics — inode+offset tail, brand regex pack, serialized RCON, reply channel | §4 (all) |
| Invocation | `/red <text>` only; `@red` mentions deferred (#6) | §4.4 |
| Ingestion | `chat.message`, join/leave/death/advancement, `raw.line` stored-not-fed | §3.1, §4.1 |
| Actions | `chat.send`, `cmd.exec`, `announce`, `world.time`/`world.weather` sugar | §3.2 registry (Logtail column) |
| Permission gate | allowlist + `needs_confirm` + JSONL audit; `op` not allowlistable | §6.2 |
| Sessions & memory | `events`, `sessions`, `context_buffer`, `triggers` tables; named-volume persistence | §6.3, §12.3.4 |
| LLM client | BYO OpenAI-compatible endpoint; tool-loop budgets | §6.4 |
| Tools | registry + budget enforcement ships; wiki lookup ships; **crafting KB ships only if §3 stays green, else defers; MCP surface defers** ← the one judgment call in this table; flip it against evidence, not taste | §6.4 |
| Triggers | rule engine + service clock approximation (documented *approximate*) | §7 |
| CLI | `init`, `doctor`, `demo`, `run`, `service`; `setup` = same code path as `init`, browser wizard defers with #12 | §12.6 |
| Eyes-only mode | no-RCON degraded start, stated in `doctor`, never silent | §12.3.3 |
| Demo profile | `compose.demo.yml` brings its own Paper server | §12.3.5 |

**Out of scope for build, in scope for honesty:** `world.*`/`entity.*`
Bridge-column actions return `unknown_action` until their adapter exists;
§12.3.1 case 3 (different machine) is a documented "not yet" with a `doctor`
line pointing at #9.

## 3. Acceptance budget — the definition of done

Moved from ARCHITECTURE.md §12.1 (the doctrine — config is an output, never an
input — stays there). Measure every row before tagging the first release;
**any row failing = not shippable**. Publish the measured numbers in the
release notes; they are the input to the next milestone's scoping.

| metric | ceiling | Track-1 measured | Track-3 measured |
|---|---|---|---|
| copy first command → first in-game reply | ≤ 5 min | — | — |
| files read before first reply | README only | — | — |
| hand-edited config files before first reply | 0 (secrets excepted) | — | — |
| server restarts caused by us | 0 (compose) | — | — |
| failure that says only what broke, not what to do | 0 | — | — |
| commands a user must remember | 1 (`run`, and it's usually a service) | — | — |

Track-2 rows (restart 1 on plugin drop, wizard pairing) join this table when
#12 is scheduled.

## 4. Conformance & acceptance tests

The milestone-owned half of the old §9 (the permanent half — contract suite,
simulated server — stays in ARCHITECTURE.md §9):

1. **Golden-log tests** (§8): per-brand fixtures in `testdata/`; a failing
   fixture is a release blocker.
2. **Hostile-environment matrix** (modded servers rely on Logtail until a
   Bridge port exists): golden log fixtures from Fabric/Forge servers *with
   mods loaded* (interleaved/reformatted lines); RCON via third-party bridges
   (e.g. FTB RCON) — host/port/auth already configurable, reconnect must be
   safe; hybrids may mishandle RCON concurrency, which §4.2's serialized
   one-in-flight command covers.
3. **Matrix smoke:** vanilla + Paper, real MC versions tagged in release
   notes = "tested against".
4. **`demo` passes offline** (ARCHITECTURE.md §9.2's canned stream + fake
   RCON): install → demo → model reply with no server, no Minecraft, no JVM.
5. **`doctor` is the acceptance surface** (§12.6): every row of its spec
   (log advancing, parse rate, RCON reach+auth, endpoint latency, sqlite
   writable, clock offset) has a check that emits `ok` or `fix:` — a shipped
   check that can only say *what broke* fails §3's row 5.

## 5. Deferred, specified, scheduled-nowhere → issues

The old §13 became GitHub issues (claimable, closeable): #6 mention hook ·
#7 ambient opt-in · #8 token budgets · #9 cross-machine logs · #10 Bridge
auth · #11 registry surface. #11 gates *publish*, not build.

## 6. Deferred list (specified in ARCHITECTURE.md, unscheduled)

Promotion rule: a bullet becomes its own `M<n>-<name>.md` **when someone opens
the first implementation issue for it** — scheduling, not interest.

- **Track 2 — drop-in plugin + first-run wizard** · spec §12.4 (unchanged,
  six hard requirements) · tripwire #12 · its acceptance rows join §3 then.
- **Hybrid cores** (Cardboard, Arclight, Mohist, …) as certified targets —
  Red runs natively per loader (Logtail anywhere, Bridge ports per-platform);
  nobody should need a hybrid to run Red. (Logtail's log+RCON generally works
  on hybrids since they write standard logs and speak RCON —
  community-tested, not certified.) ← moved from §10; a milestone may
  certify, not the architecture.
- **Ambient chat mode** (§4.4) — opt-in, probability-gated, off by default;
  shape decided by #7, budgets by #8.
- **`@red` mention routing** — #6.
- **Crafting KB + MCP surfaces** (§6.4) — unless §3 stays green with them in.
- **`npcs` memory table** (§6.3) — realized via Bridge `entity.*` (§10), so
  it waits on the Bridge milestone, not on this one.
- **Cross-machine logs** (§12.3.1 case 3) — #9.
