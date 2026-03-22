# autodosie_bot

Каркас Telegram-бота для поэтапной проверки автомобиля по VIN и госномеру.

Сейчас в репозитории уже есть:
- бот на `aiogram 3` c long polling;
- команды `/start`, `/help`, `/check`, `/checkvin`;
- валидация VIN и российского госномера;
- прием VIN или госномера прямо сообщением;
- базовая расшифровка VIN через `NHTSA vPIC`;
- абстракция провайдера данных, чтобы потом подключить `gibdd`;
- деплой на VPS через GitHub Actions + `systemd`.

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install --no-build-isolation -e .
cp .env.example .env
```

Заполни `BOT_TOKEN`, затем:

```bash
autodosie-bot
```

## Деплой через GitHub Actions

Схема такая:
- ты пушишь в `main`;
- GitHub Actions подключается по SSH к VPS;
- код синхронизируется на сервер;
- сервер обновляет venv и Python-пакеты;
- `systemd` перезапускает бота.

### 1. Один раз подготовить SSH-ключ для GitHub Actions

На локальной машине сгенерируй отдельный deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/autodosie_github_actions -C "autodosie github actions"
```

Понадобятся оба файла:
- приватный ключ `~/.ssh/autodosie_github_actions`;
- публичный ключ `~/.ssh/autodosie_github_actions.pub`.

### 2. Один раз загрузить deploy-файлы на сервер

С локальной машины:

```bash
scp -r deploy root@SERVER_IP:/root/autodosie_deploy
```

### 3. Один раз выполнить bootstrap на сервере

На сервере под `root`:

```bash
cd /root/autodosie_deploy
chmod +x bootstrap-server.sh
./bootstrap-server.sh
```

Скрипт:
- создаст рабочую директорию `/home/autobot/apps/autodosie_bot`;
- создаст `/home/autobot/.ssh/authorized_keys`;
- установит `systemd` unit;
- добавит `sudoers` правило для перезапуска сервиса из deploy-скрипта;
- создаст env-файл `/home/autobot/apps/shared/autodosie_bot.env`.

### 4. Добавить публичный ключ на сервер

На сервере под `root`:

```bash
nano /home/autobot/.ssh/authorized_keys
```

Вставь содержимое файла `~/.ssh/autodosie_github_actions.pub`, затем проверь права:

```bash
chown -R autobot:autobot /home/autobot/.ssh
chmod 700 /home/autobot/.ssh
chmod 600 /home/autobot/.ssh/authorized_keys
```

### 5. Заполнить env на сервере

На сервере:

```bash
nano /home/autobot/apps/shared/autodosie_bot.env
```

Минимум нужно заполнить:

```env
BOT_TOKEN=...
LOG_LEVEL=INFO
VEHICLE_DATA_PROVIDER=nhtsa
REQUEST_TIMEOUT_SECONDS=20
```

### 6. Добавить GitHub secrets

В GitHub repository -> `Settings` -> `Secrets and variables` -> `Actions` создай secrets:

- `DEPLOY_HOST` = IP сервера
- `DEPLOY_USER` = `autobot`
- `DEPLOY_SSH_KEY` = содержимое файла `~/.ssh/autodosie_github_actions`

Опционально:
- `DEPLOY_PORT` = SSH port, если он не `22`

### 7. Первый деплой

```bash
git add .
git commit -m "Enable GitHub Actions deploy"
git push origin main
```

После пуша workflow из [.github/workflows/deploy.yml](.github/workflows/deploy.yml) сам:
- зальет код на VPS через `rsync`;
- выполнит серверный deploy-скрипт [deploy/remote-deploy.sh](deploy/remote-deploy.sh);
- обновит зависимости;
- перезапустит `autodosie-bot.service`.

### 8. Проверка статуса на сервере

```bash
systemctl status autodosie-bot.service --no-pager
journalctl -u autodosie-bot.service -n 100 --no-pager
```

## Что делать дальше

Следующий этап после первого запуска:
1. добавить SQLite;
2. сохранять пользователей и историю запросов;
3. отдельно спроектировать поток работы с капчей ГИБДД;
4. добавить объединение данных из нескольких источников.
