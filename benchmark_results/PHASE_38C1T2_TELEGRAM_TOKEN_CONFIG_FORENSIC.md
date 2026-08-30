# Phase 38C.1T.2 — Telegram Token Configuration Forensic

**Timestamp:** 2026-08-28T17:56:00+07:00  
**Repository Root:** `C:\Users\Nguyen Cong Thong\Desktop\AI attendance`

---

## Canonical Token Variable

**`TELEGRAM_BOT_TOKEN`**

---

## Configuration Mechanism

**Environment variable (primary) with .env file support via pydantic-settings**

The project uses `pydantic-settings.BaseSettings` which automatically loads from:
1. Environment variables (highest priority)
2. `.env` file (if present, optional)

---

## Exact Configuration Path

```
app/config/settings.py → Settings.telegram.bot_token
```

---

## Code Locations

| Component | File & Lines | Description |
|-----------|--------------|-------------|
| Settings Definition | `app/config/settings.py:207-228` | `TelegramConfig` class with `bot_token: Optional[str]` |
| Settings Loading | `app/config/settings.py:318-399` | `Settings` class inheriting `BaseSettings` with `env_file=".env"` |
| Startup Validation | `app/bootstrap/startup_validation.py:266-304` | `_validate_telegram()` method |
| Telegram Bot Init | `app/attendance/policy_engine/telegram_bot.py:208-237` | `TelegramBot.__init__()` |
| Token Validation | `app/attendance/policy_engine/telegram_bot.py:42-69` | `validate_bot_token()` function |
| Factory Creation | `app/attendance/policy_engine/factory.py:246-247` | `create_telegram_bot()` call |
| Main App Startup | `app/main.py:28-45` | Lifespan loads settings |

---

## Token Flow Trace

```
1. Environment variable TELEGRAM_BOT_TOKEN (or .env file)
         ↓
2. pydantic-settings BaseSettings loads via SettingsConfigDict(env_file='.env')
         ↓
3. Settings.telegram.bot_token populated
         ↓
4. StartupValidator._validate_telegram() checks settings.telegram.bot_token
         ↓
5. TelegramBot.__init__() uses bot_token or os.environ.get('TELEGRAM_BOT_TOKEN')
         ↓
6. TelegramBot passed to NotificationQueue and TelegramWorker
         ↓
7. TelegramWorker sends notifications via TelegramBot.send_message()
```

---

## .env File Support

| Property | Value |
|----------|-------|
| **Supported** | ✅ Yes |
| **Required** | ❌ No |
| **Mechanism** | `pydantic-settings BaseSettings` with `SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')` |
| **Note** | `.env` file is optional; environment variables take precedence |

---

## Existing Config Files

| File | Status |
|------|--------|
| `.env` | ❌ NOT FOUND |
| `config.yaml` | ❌ NOT FOUND |
| `config.yml` | ❌ NOT FOUND |
| `settings.yaml` | ❌ NOT FOUND |
| `settings.yml` | ❌ NOT FOUND |
| `system.yaml` | ❌ NOT FOUND |
| `config.json` | ❌ NOT FOUND |
| `settings.json` | ❌ NOT FOUND |

**Result:** `NO_SECRET_CONFIG_FILE` — No existing configuration file for secrets exists.

---

## Startup Validation

**Location:** `app/bootstrap/startup_validation.py:266-304`

**Behavior:**
- If `TELEGRAM_BOT_TOKEN` not configured → **WARN** (notifications disabled, not a startup failure)
- If configured → Validates token format (regex: `^\d+:[A-Za-z0-9_-]{35,}$`)
- Strict mode available (raises exception), defaults to `False` (warn only)

---

## Windows Configuration Procedure

### Method: Environment Variable

The project expects the token as an environment variable. Three scopes available:

| Scope | Persistence | Use Case |
|-------|-------------|----------|
| **Process** | Current terminal session only | Temporary testing |
| **User** | Persists across sessions (recommended) | Development |
| **System** | Persists for all users | Production servers |

### PowerShell Commands

```powershell
# Temporary (current session only)
$env:TELEGRAM_BOT_TOKEN='your_token_here'

# Persistent (User scope - recommended)
[Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', 'your_token_here', 'User')

# Persistent (System scope - requires admin)
[Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', 'your_token_here', 'Machine')
```

### CMD Commands

```cmd
REM Temporary (current session only)
set TELEGRAM_BOT_TOKEN=your_token_here

REM Persistent (User scope - recommended)
setx TELEGRAM_BOT_TOKEN your_token_here

REM Persistent (System scope - requires admin)
setx TELEGRAM_BOT_TOKEN your_token_here /M
```

### Verification

```powershell
# Check if set
$env:TELEGRAM_BOT_TOKEN

# Or via Python
python -c "import os; print(os.environ.get('TELEGRAM_BOT_TOKEN', 'NOT SET'))"
```

---

## Git/Security Status

| Check | Result |
|-------|--------|
| `.gitignore` protects `.env` | ✅ Yes (`.env`, `.env.local`, `.env.*.local` listed) |
| Secrets in repository | ❌ No |
| Token in logs protected | ✅ Yes (`SecurityConfig.no_secrets_in_logs=true`, `token_env_only=true`) |
| Security config location | `app/config/settings.py:306-315` |

---

## Live Test Requirements

| Variable | Type | Required | Default |
|----------|------|----------|---------|
| `TELEGRAM_LIVE_TEST` | boolean | No | `false` |
| `TELEGRAM_TEST_CHAT_ID` | string | **Yes** (when live_test=true) | None |

**Validation Locations:**
- `app/bootstrap/startup_validation.py:291-304`
- `app/attendance/policy_engine/telegram_bot.py:280-325`

**Behavior:** Only sends test messages when:
1. `TELEGRAM_LIVE_TEST=true` AND
2. `TELEGRAM_TEST_CHAT_ID` is set AND
3. Target chat_id matches configured test chat_id

---

## New Files Required

**❌ NO** — No new configuration files need to be created. The existing mechanism is complete.

---

## User Action Required

1. **Set `TELEGRAM_BOT_TOKEN` environment variable** (required for notifications)
   - Get token from [@BotFather](https://t.me/BotFather) on Telegram
   - Set as User environment variable (recommended for persistence)

2. **Optional: Enable live testing**
   ```powershell
   $env:TELEGRAM_LIVE_TEST='true'
   $env:TELEGRAM_TEST_CHAT_ID='your_test_chat_id'
   ```
   - Get chat_id by messaging the bot and checking updates, or use [@userinfobot](https://t.me/userinfobot)

---

## Final Status

**TELEGRAM_TOKEN_CONFIGURATION:** Environment variable `TELEGRAM_BOT_TOKEN` via pydantic-settings (with optional .env support)

**CONFIGURATION_PATH:** `app/config/settings.py → Settings.telegram.bot_token`

**ENV_FILE_REQUIRED:** NO

**USER_ACTION:** Set `TELEGRAM_BOT_TOKEN` environment variable (User scope recommended)

**PHASE_38C2:** NOT_STARTED

**PHASE_39:** NOT_STARTED

---

**END PHASE 38C.1T.2.**