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
| GET   | /api/registration      | Списък с всички заявки (временно, без auth)|

### POST /api/registration — очаквани полета

Съвпадат с имената на input полетата в `registrationForm` от index.html:
`child`, `age`, `parent`, `phone`, `email`, `message`.

Приема `application/json` или стандартен form submit
(`application/x-www-form-urlencoded`).

## Следва

- Свързване на frontend формата с този endpoint (fetch вместо demo JS)
- Email известие при нова регистрация
- Прост admin изглед/endpoint за новините вместо хардкоднати карти
- Когато е готово за deploy: конфигуриране на cPanel Python Selector
  (WSGI) за superhosting.bg
