# Deployment

This project runs as a long-lived Discord bot worker. It does not need a public HTTP port.

## Required Environment Variables

```dotenv
DISCORD_BOT_TOKEN=your_discord_bot_token
ACCOUNTS_DIR=/app/accounts
```

`DISCORD_WEBHOOK_URL` is not required for the private Discord panel flow.

## Data Persistence

User accounts are stored as JSON files under `ACCOUNTS_DIR`.

For production, mount `ACCOUNTS_DIR` to persistent storage. If the platform filesystem is ephemeral and no disk is attached, user account data will be lost on restart or redeploy.

## Local Docker

Create a local `.env` containing `DISCORD_BOT_TOKEN`, then run:

```powershell
docker compose up -d --build
```

Account files will be stored in local `accounts/`.

## Render

Use `render.yaml` as a Blueprint or create a Background Worker manually:

- Environment: Docker
- Dockerfile: `Dockerfile`
- Environment variables:
  - `DISCORD_BOT_TOKEN`
  - `ACCOUNTS_DIR=/app/accounts`
- Persistent disk:
  - Mount path: `/app/accounts`

## Railway / Other Docker Hosts

Deploy the Dockerfile as a worker service. Set:

```dotenv
DISCORD_BOT_TOKEN=your_discord_bot_token
ACCOUNTS_DIR=/app/accounts
```

Attach a persistent volume at `/app/accounts`.

## Health Check

After deployment, check logs for:

```text
機器人 <name> 已上線。輸入「run」即可開啟操作介面。
```

Then send `run` in a Discord channel where the bot can read messages. The bot should DM you the private control panel.
