# cp_discord — your terminal sessions, on your phone

Every Code Puppy session gets its own Discord thread. Watch what the agent is
doing, approve gates with a tap, and steer it mid-run by just typing — from
the sofa or from the train.

**One bot, any number of sessions.** One session automatically holds the
Discord connection (the "broker"); the others attach to it. If it goes away,
another takes over within 30 seconds.

## Terminal input mirroring

When the bridge is enabled, CLI prompts submitted to the agent are posted to
that session's thread as **Terminal input**, in both report and stream modes.
The observer uses `user_prompt_submit(prompt, session_id)`, returns `None`, and
never replaces the prompt. Reports use the existing mailbox and chunking path;
this is best-effort reporting, not a durable transcript.

**Privacy:** any terminal prompt may contain sensitive information (passwords,
keys, private code or personal data). Enabling the bridge shares that text with
people who can read the session thread. No attachments are uploaded by this
feature. The text is what the core submits after attachment parsing and
sanitization, not a byte-for-byte terminal keystroke log.

This is **not a slash-command audit**: handled commands and shell passthroughs
that do not submit a prompt are not recorded. Mid-run steering that bypasses
`user_prompt_submit` is also outside its scope. Discord-originated idle inputs
are not echoed; typing the same text in the terminal still produces a report.
Subagent/nested runs and the CLI's automatic continuation prompts are excluded.

Compatibility was checked against Code Puppy **0.0.851**. Its steering queue and
idle handoff preserve a marked string, but attachment parsing and sanitization
do not. A reversible wrapper around `cli_runner.run_prompt_with_attachments`
carries provenance in task-local context through these conversions. Nested runs
are rejected via `agent_execution_context`; the CLI continuation call is
recognized by its `next_prompt` local's object identity plus the source call
site, never by prompt text matching.
That continuation check is core-version-sensitive and should be reviewed when
upgrading. Calls outside the CLI wrapper are deliberately not mirrored.

---

## 1. Discord server and channel

1. In Discord: **`+`** at the bottom left → **Create My Own** → *For me and my
   friends*. The name does not matter.
2. Inside the server: **`+`** next to *Text Channels* → create one, e.g.
   `#puppy`.

> A private server for yourself is the normal case. The bot creates **private
> threads** in this channel — one per session.

## 2. Create the bot

1. https://discord.com/developers/applications → **New Application**
2. **Bot** in the sidebar → **Add Bot**
3. **Reset Token** → copy it. **This is a password.** It is shown once.
4. Scroll to **Privileged Gateway Intents** →
   turn on **MESSAGE CONTENT INTENT** → *Save Changes*

> Without that switch every chat message arrives **empty**. The outbound
> direction (terminal → Discord) still works, typing back does not — and
> nothing tells you why.

## 3. Invite the bot

1. **OAuth2** in the sidebar → **URL Generator**
2. Scopes: **`bot`**
3. Bot Permissions:
   - Send Messages
   - Create Private Threads
   - Send Messages in Threads
   - Manage Threads
   - Read Message History
   - Add Reactions
4. Copy the generated URL at the bottom, open it, pick your server,
   **Authorize**.

## 4. Collect the IDs

First, once: **Settings → Advanced → Developer Mode** on.

| What | How |
|---|---|
| **Channel ID** | right-click `#puppy` → *Copy Channel ID* |
| **Your user ID** | right-click your own name → *Copy User ID* |
| **Bot token** | from step 2 |

## 5. Install py-cord

Code Puppy does not ship the Discord library:

```powershell
uv pip install --python "$env:APPDATA\uv\tools\code-puppy\Scripts\python.exe" "py-cord>=2.8.1,<3"
```

Without it Code Puppy starts normally and just says:
*"the Discord bridge needs py-cord"*.

## 6. Configure

In `~\.code_puppy\puppy.cfg`:

```ini
cp_discord_enabled    = 1
discord_bot_token     = YOUR_BOT_TOKEN
cp_discord_channel_id = 1234567890123456789

discord_approvers     = discord:9876543210987654321=yourname
discord_allow_from    = discord:9876543210987654321=yourname
```

**Format:** `discord:<your-user-id>=<any-name>`. Separate several with commas.

**The two roles are independent** — neither implies the other:

| Key | Role | May |
|---|---|---|
| `discord_approvers` | APPROVER | answer gates (Approve/Deny) |
| `discord_allow_from` | TALKER | send instructions to the agent |

> Miss out `discord_allow_from` and your chat messages are **discarded
> silently** — no check mark, no error. You want both lines.

### Optional

```ini
cp_discord_mode     = report     ; or: stream  (default: report)
cp_discord_autojoin = 1          ; pull approvers into new threads automatically
cp_discord_tool_log = 0          ; drop the tool list from reports (default: on)
```

- **`report`** — one status line while it works, a report when it parks.
  Quiet, good on a phone.
- **`stream`** — follow the output as it happens.
- **`cp_discord_tool_log = 0`** — reports keep the agent's answer and the
  gates but drop the `-> tool` / `<- tool (n ms)` inventory. That list is the
  bulk of a long report; turn it off if you only care what the agent *said*.
  Takes effect on the next tool, no restart needed.

Every value can also come from the environment (`CP_DISCORD`,
`DISCORD_BOT_TOKEN`, `CP_DISCORD_CHANNEL_ID`, `CP_DISCORD_MODE`,
`CP_DISCORD_AUTOJOIN`, `CP_DISCORD_TOOL_LOG`, `DISCORD_ALLOW_FROM`,
`DISCORD_APPROVERS`) — the environment wins.

## 7. Deploy the plugin

```powershell
cd C:\Projekte_prv\arnonuem\cp_plugins
powershell -ExecutionPolicy Bypass -File deploy.ps1 cp_discord
```

Copies the plugin to `~\.code_puppy\plugins\cp_discord\`.

## 8. Start

Restart Code Puppy. A thread named after your project appears in the channel.

**Check:** type "hello" into the thread. You should get a  and an answer.

---

## When something does not work

**Restart every session after a deploy.** Plugins load at startup only, and
*any* session can be the one holding the Discord connection — if that one
runs the old code the path is broken even though all the others are current.

| Symptom | Cause |
|---|---|
| No thread appears | `py-cord` missing (step 5), or wrong token / channel ID |
| Buttons say *"did not respond in time"* | The broker session runs old code → restart all sessions |
| Chat: nothing happens, no check mark | `discord_allow_from` missing (step 6) |
| Chat: check mark, but no reaction | You are typing in an **old** thread. A restarted session creates a **new** one |
| Message sits there while nothing runs | Handled by the plugin itself (C8); no core patch needed |
| Buttons say "expired" while the agent still waits | Fixed — they now stay pressable for as long as the agent is waiting |

**Buttons stay pressable while the agent is waiting.** They used to expire
after 120 seconds, which made them useless in the one situation they exist
for: being away from the machine. A gate only gets a deadline when **no**
terminal prompt is open — nobody is at the PC to answer it then either, and
the waiting thread needs some way to end.

The "did not respond in time" message after 3 seconds means something else:
*nobody* answered — the press never arrived.

> **The buttons live in the broker session.** If the session holding the
> Discord connection restarts, older buttons stop answering. Press one and
> nothing happens? Answer at the PC, or start a new turn.

## Security

- The bot token is a **password**. Anyone holding it can post as your bot.
  Do not commit it.
- Threads are **private**: whoever was not added sees nothing and writes
  nothing.
- An **unauthorized** sender gets no reaction, no delivery, and their text
  reaches **no** log. That is deliberate.
- **TALKER is global**, not per session: a second name in
  `discord_allow_from` may steer **every** one of your sessions. Irrelevant
  for single-user setups, worth knowing with more people.
