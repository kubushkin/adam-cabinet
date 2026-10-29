# Личный кабинет Adam University

Кабинет студента и преподавателя: вход через Keycloak, данные — из Гауди (профиль, карта, оценки), расписания
и библиотеки. Сам кабинет почти ничего не хранит: в своей базе PostgreSQL — только сессии входа
(в сессии — копия профиля и оценок из Гауди на 5 минут: Гауди отвечает около секунды, без копии тормозят вкладки).

Стек: Django 5.2, Authlib (OpenID Connect), PostgreSQL 17, gunicorn, whitenoise. Языки: русский, кыргызский, английский.

Сейчас готово: вход и выход через Keycloak, переключатель языка, профиль из Гауди, «Сегодня», «Расписание», «Учёба».
Разделы «Библиотека», «Карта», «Контракт» — следующими шагами.

## Как устроен вход

- Логин в Keycloak — ID человека в Гауди (`preferred_username` в токене). Логин не из цифр — вход отклоняется.
- Студенты и преподаватели — разные realm (ID студентов и сотрудников в Гауди пересекаются). Если
  `OIDC_STAFF_ISSUER` пустой, кнопки «Я преподаватель» нет.
- Подпись токена, `state` и `nonce` проверяет Authlib. После входа сессия выдаётся заново.
- Выход — через Keycloak (`end_session_endpoint`), чтобы закрылась и сессия Keycloak.

## Клиент в Keycloak (для каждого realm)

auth.adam.edu.kg → realm `student` → **Clients → Create client**:

| Поле | Значение |
|---|---|
| Client type | OpenID Connect |
| Client ID | `cabinet` |
| Client authentication | **On** (закрытый клиент с секретом) |
| Authentication flow | только **Standard flow** (Direct access grants и Implicit — выключить) |
| Root URL / Home URL | `https://cabinet.adam.edu.kg` |
| Valid redirect URIs | `https://cabinet.adam.edu.kg/auth/student/callback/` |
| Valid post logout redirect URIs | `https://cabinet.adam.edu.kg/login/` |
| Web origins | `https://cabinet.adam.edu.kg` |

Затем вкладка **Credentials** → Client secret → в `.env` как `OIDC_STUDENT_CLIENT_SECRET`.
Для realm преподавателей — то же, но redirect URI `https://cabinet.adam.edu.kg/auth/staff/callback/`
и секрет в `OIDC_STAFF_CLIENT_SECRET`, адрес realm — в `OIDC_STAFF_ISSUER`.

## Установка на docker-01

Ключ на чтение репозитория (deploy key у каждого репозитория свой):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/adam_cabinet -N "" -C "cabinet-vm"
cat ~/.ssh/adam_cabinet.pub        # GitHub → adam-cabinet → Settings → Deploy keys → Add, без «Allow write access»
cat >> ~/.ssh/config <<'CFG'
Host github-cabinet
  HostName github.com
  User git
  IdentityFile ~/.ssh/adam_cabinet
  IdentitiesOnly yes
CFG
```

Код, настройки, запуск:

```bash
D=/opt/stacks/adam-cabinet
sudo mkdir -p $D && sudo chown $USER: $D
git clone github-cabinet:kubushkin/adam-cabinet.git $D && cd $D
cp .env.example .env && chmod 600 .env
sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$(openssl rand -hex 32)|; s|^DB_PASSWORD=.*|DB_PASSWORD=$(openssl rand -hex 16)|" .env
read -rsp "Ключ cabinet из Гауди: " K; echo; sed -i "s|^GAUDI_API_KEY=.*|GAUDI_API_KEY=$K|" .env; unset K
read -rsp "Client secret из Keycloak: " K; echo; sed -i "s|^OIDC_STUDENT_CLIENT_SECRET=.*|OIDC_STUDENT_CLIENT_SECRET=$K|" .env; unset K
docker compose up -d --build
docker compose ps                  # db (healthy), web — Up
```

Публикация — как у библиотеки: DNS-запись `cabinet` в BIND на pfSense, в HAProxy backend `192.168.100.2:8102`
и правило «Host matches `cabinet.adam.edu.kg`» во фронтенде 443 (там же `X-Forwarded-Proto: https`).

Обновление: `cd /opt/stacks/adam-cabinet && git pull && docker compose up -d --build`.

## Разработка

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export DJANGO_SECRET_KEY=dev DJANGO_DEBUG=1 DB_HOST=127.0.0.1 DB_NAME=cabinet DB_USER=cabinet DB_PASSWORD=cabinet
python manage.py test
```

Переводы: `python manage.py makemessages -l ky -l en`, правка `locale/*/LC_MESSAGES/django.po`,
затем `python manage.py compilemessages` (нужен gettext). Файлы `.mo` лежат в репозитории.
Кыргызский перевод стоит проверить носителю языка.

## Устройство

```
config/          настройки (всё из переменных окружения), адреса
cabinet/oidc.py  вход через Keycloak (два realm)
cabinet/gaudi.py запросы к API Гауди (/api/cabinet/…, ключ «cabinet»)
cabinet/views.py вход, выход, главная
templates/       страницы (без JavaScript)
locale/          переводы ky, en
docker/          entrypoint: миграции и gunicorn
```
