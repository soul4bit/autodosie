# autodosie_bot

`AutoDosie` now has two runtime surfaces in one repo:

- `autodosie-web`: main website for `autodosie.ru`
- `autodosie-bot`: Telegram bot kept as an additional channel

Both reuse the same Python service layer for VIN and Russian plate checks.

## Current scope

- `FastAPI` website with:
  - landing page and search form
  - report page for `VIN` or Russian plate
  - JSON endpoint: `/api/check?q=...`
  - health endpoint: `/health`
- `aiogram 3` Telegram bot with:
  - `/start`, `/help`, `/check`, `/checkvin`
  - optional `/checkgibdd` flow
- current default provider: `free`
- deploy via GitHub Actions over SSH
- production target: `systemd + nginx`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install --no-build-isolation -e .
cp .env.example .env
```

Fill `.env`, then:

```bash
autodosie-web
```

Website defaults to `http://127.0.0.1:8000`.

If you also want the bot locally:

```bash
autodosie-bot
```

## Environment

Minimal site-oriented config:

```env
BOT_TOKEN=
LOG_LEVEL=INFO
VEHICLE_DATA_PROVIDER=free
REQUEST_TIMEOUT_SECONDS=20
GIBDD_CAPTCHA_WAIT_SECONDS=45
GIBDD_CAPTCHA_POLL_INTERVAL_SECONDS=5
SITE_NAME=AutoDosie
SITE_URL=https://autodosie.ru
WEB_HOST=127.0.0.1
WEB_PORT=8000
```

Notes:

- `BOT_TOKEN` is optional for the website.
- `BOT_TOKEN` is required only if you also run `autodosie-bot`.

## Production layout

Expected server paths:

- repo work tree: `/home/autobot/apps/autodosie_bot`
- env file: `/home/autobot/apps/shared/autodosie_bot.env`
- venv: `/home/autobot/.venvs/autodosie_bot`

System services installed by bootstrap:

- `autodosie-web.service`
- `autodosie-bot.service`
- `nginx` with `autodosie.ru` virtual host

## One-time server bootstrap

Copy `deploy/` to the server and run as `root`:

```bash
cd /root/autodosie_deploy
chmod +x bootstrap-server.sh
./bootstrap-server.sh
```

Bootstrap will:

- create app directories
- install `rsync` and `nginx` if missing
- install `systemd` units
- install `nginx` config for `autodosie.ru`
- create `/home/autobot/apps/shared/autodosie_bot.env`
- enable `autodosie-web.service`, `autodosie-bot.service`, `nginx`

After bootstrap:

1. Add the GitHub Actions public key to `/home/autobot/.ssh/authorized_keys`
2. Edit `/home/autobot/apps/shared/autodosie_bot.env`
3. Point `autodosie.ru` and `www.autodosie.ru` to the server IP
4. Push to `main`

## GitHub Actions deploy

Workflow file: [`.github/workflows/deploy.yml`](./.github/workflows/deploy.yml)

Required repository secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PORT` if SSH is not on `22`

Each push to `main` does this:

1. syncs the repo to `/home/autobot/apps/autodosie_bot/`
2. updates the venv
3. reinstalls the project in editable mode
4. restarts `autodosie-web.service`
5. restarts `autodosie-bot.service` only if `BOT_TOKEN` is set
6. validates and reloads `nginx`

## Domain cutover

Once DNS points to the server, verify:

```bash
curl -I http://autodosie.ru
systemctl status autodosie-web.service --no-pager
systemctl status nginx --no-pager
journalctl -u autodosie-web.service -n 100 --no-pager
```

Then add TLS, for example with `certbot`:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d autodosie.ru -d www.autodosie.ru
```

## Main routes

- `/` - landing and search form
- `/report?q=XTA210740Y1234567`
- `/report?q=A123BC77`
- `/api/check?q=XTA210740Y1234567`
- `/health`

## Next steps

Reasonable next product steps after the cutover:

1. move persistent storage to SQLite or PostgreSQL
2. add caching for repeated VIN and plate lookups
3. split the current free provider into source adapters
4. move GIBDD-heavy traffic to a RU-based worker if needed
5. let the Telegram bot send users to full site reports on `autodosie.ru`
