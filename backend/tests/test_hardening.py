"""Проверка на защитите: повторение при състезание, debug режим. Пускане: python tests/test_hardening.py"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
os.environ["DOCS_DIR"] = os.path.join(tmp, "docs")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from sqlalchemy.exc import IntegrityError
from app import create_app, db
from app.models import AdminUser, ParentAccount, Player, ROLE_HEAD_COACH, utcnow
from datetime import date

app = create_app()
calls = {"once": 0, "always": 0}

@app.get("/__race_once")
def race_once():
    calls["once"] += 1
    if calls["once"] == 1:
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
    return {"ok": True, "attempt": calls["once"]}

@app.get("/__race_always")
def race_always():
    calls["always"] += 1
    raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

c = app.test_client()
r = c.get("/__race_once")
ok(r.status_code == 200 and r.get_json()["attempt"] == 2 and calls["once"] == 2, "състезание: заявката се повтаря веднъж и минава")
r = c.get("/__race_always")
ok(r.status_code == 409 and calls["always"] == 2, "постоянен конфликт: 409 след едно повторение (не е безкраен цикъл)")

# повторението запазва вход и работи с реални маршрути
with app.app_context():
    u = AdminUser(username="head", display_name="Главен", role=ROLE_HEAD_COACH); u.set_password("password123"); db.session.add(u); db.session.commit()
head = app.test_client(); head.post("/api/auth/login", json={"username": "head", "password": "password123"})
ok(head.get("/api/admin/players").status_code == 200, "обикновена заявка след повторение пак работи")

# --- истинско състезание: много заявки едновременно върху НОВ профил (комплектът му още не съществува)
import threading
from app.models import ParentAccount, Player, utcnow
from app.team_utils import get_season_end_year
with app.app_context():
    season = get_season_end_year()
    parent = ParentAccount(email="a@e.com", display_name="А", phone="1", password_hash="")
    parent.set_password("novaparola1"); parent.consent_at = utcnow(); db.session.add(parent); db.session.flush()
    kids = [Player(parent=parent, child_name=f"Дете {i}", birth_date=date(season - 9, 3, 1)) for i in range(6)]
    db.session.add_all(kids); db.session.commit(); kid_ids = [k.id for k in kids]

def concurrent(n, make_call):
    codes, lock, barrier = [], threading.Lock(), threading.Barrier(n)
    def worker(i):
        call = make_call(); barrier.wait(); status = call().status_code
        with lock: codes.append(status)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in threads]; [t.join() for t in threads]
    return codes

def parent_call():
    cl = app.test_client(); cl.post("/api/parent/login", json={"email": "a@e.com", "password": "novaparola1"})
    return lambda: cl.get(f"/api/parent/children/{kid_ids[0]}/documents")
def admin_call():
    cl = app.test_client(); cl.post("/api/auth/login", json={"username": "head", "password": "password123"})
    return lambda: cl.get("/api/admin/players")

codes = concurrent(8, parent_call)
ok(codes.count(200) == 8, f"8 едновременни родителски заявки за нов комплект документи: всички 200 ({codes.count(500)} × 500)")
codes = concurrent(6, admin_call)
ok(codes.count(200) == 6, f"6 едновременни списъка „Футболисти“, създаващи комплекти: всички 200 ({codes.count(500)} × 500)")

# debug: изключен по подразбиране и в production
import run
ok(run.debug_enabled(False, {}) is False and run.debug_enabled(False, {"FLASK_DEBUG": ""}) is False, "debug е изключен по подразбиране")
ok(run.debug_enabled(False, {"FLASK_DEBUG": "1"}) is True, "debug се включва само с FLASK_DEBUG=1 (локално)")
ok(run.debug_enabled(True, {"FLASK_DEBUG": "1"}) is False, "в production (SESSION_COOKIE_SECURE=1) debug никога не се включва")
print("ВСИЧКО МИНА")
