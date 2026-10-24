# FA German — Backend (Flask)

Минимален Flask API, който ще расте стъпка по стъпка. Използва app factory
pattern, за да е лесно добавянето на нови blueprint-и (новини, отбори,
админ и т.н.) без да се пипа съществуващият код.

## Локално стартиране

```bash
cd backend
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

API-то тръгва на `http://127.0.0.1:5000`. При първото стартиране се
създава `fagerman.db` (SQLite) автоматично.

## Налични endpoint-и

| Метод | Път                  | Описание                                   |
|-------|----------------------|---------------------------------------------|
| GET   | /api/health           | Проверка дали API-то работи                |
| POST  | /api/registration      | Записва заявка от регистрационната форма   |
| GET   | /api/registration      | Списък с всички заявки (изисква вход)      |
| GET   | /api/news              | Публикувани статии (`?limit=`, `?offset=`) |
| GET   | /api/news/<slug>       | Една публикувана статия с пълен текст      |
| GET/POST | /api/admin/news     | Всички статии (с чернови) / нова статия    |
| GET/PATCH/DELETE | /api/admin/news/<id> | Четене / редакция / изтриване     |
| GET   | /news, /news?page=2    | Страница „Всички новини“ (12 на страница)  |
| GET   | /news/<slug>           | Страница на статията (с Open Graph тагове) |
| POST  | /api/admin/uploads     | Качване на снимка (`image`): смалява се до 1600 px + 800 px версия, записва се като JPEG |
| GET   | /uploads/<файл>        | Качените снимки (дълъг кеш)                |

Снимките се пазят в `UPLOAD_DIR` (по подразбиране `backend/uploads/`, извън git).
Тази папка трябва да влиза в бекъпа и да не се трие при deploy.

Новините: `title`, `excerpt`, `body` (HTML от редактора, чисти се на сървъра),
`category`, `cover_image`, `youtube_url` (само YouTube линк), `status`
(`draft` / `published`). Адресът (`slug`) се създава от заглавието при
създаване и не се променя, за да не се чупят вече споделени линкове.

### POST /api/registration — очаквани полета

Съвпадат с имената на input полетата в `registrationForm` от index.html:
`child`, `age`, `parent`, `phone`, `email`, `message`.

Приема `application/json` или стандартен form submit
(`application/x-www-form-urlencoded`).

## Вход и акаунти (админ панел)

Роли: **owner** (главен администратор) и **coach** (треньор). Треньорите
работят само с инструментите (записвания, новини); само главният
администратор вижда страница „Потребители“ и създава/изключва/трие акаунти
и задава пароли (няма възстановяване по имейл).

Първи старт (или нов сървър) — създаване на главния администратор:

```bash
cd backend
flask --app run create-owner rosen --name "Росен"   # пита за парола
flask --app run reset-password rosen                 # забравена парола
flask --app run list-users
```

| Метод | Път | Кой |
|-------|-----|-----|
| POST | /api/auth/login, /api/auth/logout | всеки / логнат |
| GET | /api/auth/me | логнат |
| GET/POST | /api/admin/users | само owner |
| PATCH/DELETE | /api/admin/users/<id> | само owner (само треньори) |

Защитено с вход: `/api/registration` (GET/PATCH/notify), `/api/admin/*`,
`/api/admin/uploads` и всички `admin*.html` страници (без `admin-login.html`).
Публични остават `POST /api/registration`, новините и `/uploads/`.

Сигурност: хеширани пароли, сесийна cookie (HttpOnly, SameSite=Lax), CSRF
токен за всяка променяща заявка, заключване на акаунт за 15 мин. след 5
грешни паролата, спиране/смяна на парола прекратява отворените сесии.
**Production (.env):** `SECRET_KEY=<дълъг случаен низ>` и
`SESSION_COOKIE_SECURE=1` (само https; без SECRET_KEY приложението не стартира).

## Следва

- Свързване на frontend формата с този endpoint (fetch вместо demo JS)
- Email известие при нова регистрация
- Прост admin изглед/endpoint за новините вместо хардкоднати карти
- Когато е готово за deploy: конфигуриране на cPanel Python Selector
  (WSGI) за superhosting.bg

## Имейл уведомления към родителите

Настройките са в environment променливи (или в `backend/.env`, копирай от `.env.example`):
`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_SSL`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`.
Ако `MAIL_SERVER` е празен, имейлът само се записва в лога (тестов режим) и не се изпраща.
Шаблонът на текста е във `app/mailer.py` (`build_trial_training_email`).
