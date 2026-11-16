"""Проверка на стъпка 3: попълване на бланките + гаранция, че личните данни не се записват.
Пускане: python tests/test_pdf_forms.py   (за четене на PDF текста се ползва pdfplumber)"""
import io, logging, os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
os.environ["DOCS_DIR"] = os.path.join(tmp, "docs")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdfplumber
from app import create_app, db
from app.models import AdminUser, ParentAccount, Player, Team, ROLE_HEAD_COACH, ROLE_COACH, KIND_YOUTH, utcnow
from app.team_utils import get_season_end_year
from datetime import date

app = create_app()
logs = io.StringIO()
handler = logging.StreamHandler(logs); handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(handler); logging.getLogger().setLevel(logging.DEBUG); app.logger.addHandler(handler)
# pdfminer/pdfplumber се ползват САМО от теста за четене на готовия PDF (приложението ги няма) и на DEBUG
# печатат съдържанието на файла — не са част от проверяваното.
for noisy in ("pdfminer", "pdfplumber", "PIL"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

def filled(page):
    """Само попълнения текст (тъмносин), без оригиналния текст и точките на бланката."""
    return "".join(c["text"] for c in page.chars
                   if isinstance(c.get("non_stroking_color"), (tuple, list)) and len(c["non_stroking_color"]) == 3
                   and abs(c["non_stroking_color"][2] - 0.35) < 0.01)

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

def mk_egn(y, m, d, seq):
    """Тестово 10-цифрено ЕГН (системата проверява само формата: 10 цифри)."""
    return f"{y % 100:02d}{m + (40 if y >= 2000 else 0):02d}{d:02d}{seq:03d}7"

with app.app_context():
    season = get_season_end_year()
    h = AdminUser(username="head", display_name="Главен", role=ROLE_HEAD_COACH); h.set_password("password123"); db.session.add(h)
    parent = ParentAccount(email="mama@example.com", display_name="Мария Георгиева Петрова", phone="0888", password_hash="")
    parent.set_password("novaparola1"); parent.consent_at = utcnow(); db.session.add(parent); db.session.flush()
    for y in (season - 9, season - 15, season - 19):
        db.session.add(Team(slug=str(y), kind=KIND_YOUTH, birth_year_from=y, description=""))
    kid = Player(parent=parent, child_name="Петър Иванов Петров", birth_date=date(season - 9, 5, 4))
    teen = Player(parent=parent, child_name="Георги Иванов Петров", birth_date=date(season - 15, 9, 10))
    db.session.add_all([kid, teen]); db.session.commit()
    kid_id, teen_id = kid.id, teen.id

p = app.test_client()
r = p.post("/api/parent/login", json={"email": "mama@example.com", "password": "novaparola1"})
P = {"X-CSRF-Token": r.get_json()["csrf"]}

# --- форма
r = p.get(f"/api/parent/children/{kid_id}/forms/spec"); s = r.get_json()
keys = [f["key"] for g in s["groups"] for f in g["fields"]]
ok(r.status_code == 200 and "birth_cert_no" in keys and "id_no" not in keys and s["prefill"]["p1_name"] == "Мария Георгиева Петрова", "форма до 14 г.: акт за раждане, предварително попълнен родител")
ok(s["club_name"] == "ФУТБОЛЕН КЛУБ ФУТБОЛНА АКАДЕМИЯ ГЕРМАН" and s["season"] == f"{season - 1}/{season}", "име на клуба и сезон")
s2 = p.get(f"/api/parent/children/{teen_id}/forms/spec").get_json()
keys2 = [f["key"] for g in s2["groups"] for f in g["fields"]]
ok("id_no" in keys2 and "p1_name" in keys2 and "birth_cert_no" not in keys2, "форма 14–18: лична карта и родители")

SECRET_EGN, SECRET_P2, SECRET_CHILD = mk_egn(1975, 3, 12, 321), mk_egn(1973, 8, 1, 123), mk_egn(season - 9, 5, 4, 234)
SECRET_NAME, SECRET_ACT = "Тайнолюб Скритов Невиждов", "АКТ98765"
values = {"p1_name": SECRET_NAME, "p1_egn": SECRET_EGN, "p2_name": "Иван Петров Петров", "p2_egn": SECRET_P2,
          "child_bg": "Петър Иванов Петров", "child_lat": "Petar Ivanov Petrov", "child_egn": SECRET_CHILD,
          "birth_cert_no": SECRET_ACT, "city": "София", "date": "2026-11-12"}

r = p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": values}, headers=P)
ok(r.status_code == 200 and r.mimetype == "application/pdf" and r.headers["Cache-Control"] == "private, no-store", "генериране на PDF (без кеш)")
pdf_bytes = r.data
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    ok(len(pdf.pages) == 3, "3 страници: заявление, декларация, медицинско")
    f1, f2, f3 = (filled(pg) for pg in pdf.pages)
    t1, t2, t3 = (pg.extract_text() for pg in pdf.pages)
ok("ФУТБОЛЕН КЛУБ ФУТБОЛНА АКАДЕМИЯ ГЕРМАН" in f1 and f"{season - 1}/{season}" in f1, "заявление: клуб и сезон")
ok(SECRET_NAME in f1 and SECRET_EGN in f1 and SECRET_CHILD in f1 and SECRET_ACT in f1, "заявление: родители, ЕГН, акт за раждане")
ok(SECRET_NAME in f2 and SECRET_CHILD in f2 and "12.11.2026" in f2, "декларация: данните и датата")
ok("Петър Иванов Петров" in f3 and "Футбол" in f3, "медицинско: име на детето и „Футбол“")
ok("ЗАЯВЛЕНИЕ" in t1 and "ДЕКЛАРАЦИЯ" in t2 and "Приложение № 4" in t3, "оригиналният текст на бланките е запазен")

# --- ЕГН: само 10 цифри, без друга проверка
anything = dict(values, child_egn="1234567890", p1_egn="0000000000")
r = p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": anything}, headers=P)
ok(r.status_code == 200 and "X-Form-Warnings" not in r.headers, "ЕГН: произволни 10 цифри се приемат (без контролна цифра и без сравнение с датата)")
for bad_egn in ("123", "12345678901", "12345abcde", "123456789 "):
    r = p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": dict(values, p1_egn=bad_egn)}, headers=P)
    j = r.get_json()
    ok((r.status_code == 200) if bad_egn == "123456789 " and False else r.status_code == 400 and "p1_egn" in j["errors"] and bad_egn.strip() not in r.get_data(as_text=True), f"ЕГН „{bad_egn.strip()}“ не е 10 цифри: 400, без връщане на стойността")
r = p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": dict(values, p2_egn="")}, headers=P)
ok(r.status_code == 400 and "p2_egn" in r.get_json()["errors"], "родител 2: името без ЕГН се отказва")
r = p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": dict(values, p2_name="", p2_egn="")}, headers=P)
ok(r.status_code == 200, "родител 2 е по желание")
r = p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": dict(values, child_bg="А" * 100)}, headers=P)
ok(r.status_code == 400 and "child_bg" in r.get_json()["errors"], "твърде дълго име не излиза от реда")
ok(p.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": values}, headers={"X-CSRF-Token": "x"}).status_code == 403, "без CSRF — отказ")
ok(app.test_client().post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": values}).status_code == 401, "без вход — отказ")
other = app.test_client()
with app.app_context():
    q = ParentAccount(email="druga@example.com", display_name="Друга", phone="1", password_hash=""); q.set_password("novaparola2"); q.consent_at = utcnow(); db.session.add(q); db.session.commit()
rr = other.post("/api/parent/login", json={"email": "druga@example.com", "password": "novaparola2"})
ok(other.post(f"/api/parent/children/{kid_id}/forms/generate", json={"values": values}, headers={"X-CSRF-Token": rr.get_json()["csrf"]}).status_code == 404, "чуждо дете — 404")

# --- категории 14–18 и 18+
v2 = {"player_bg": "Георги Иванов Петров", "player_lat": "Georgi Ivanov Petrov", "player_egn": mk_egn(season - 15, 9, 10, 345),
      "id_no": "643214567", "id_date": "2022-05-04", "id_issuer": "София", "p1_name": "Мария Петрова", "p1_egn": SECRET_EGN, "city": "София", "date": "2026-11-12"}
r = p.post(f"/api/parent/children/{teen_id}/forms/generate", json={"values": v2}, headers=P)
ok(r.status_code == 200, "генериране за 14–18 г.")
with pdfplumber.open(io.BytesIO(r.data)) as pdf:
    t = filled(pdf.pages[0])
ok("643214567" in t and "04.05.2022" in t and "Georgi Ivanov Petrov" in t, "14–18: лична карта и латиница в заявлението")

# --- настройка: име на клуба
head = app.test_client(); hr = head.post("/api/auth/login", json={"username": "head", "password": "password123"}); H = {"X-CSRF-Token": hr.get_json()["csrf"]}
ok(head.put("/api/admin/settings/club-name", json={"club_name": "ФК Тест"}, headers=H).status_code == 200, "главен треньор сменя името на клуба")
ok(p.get(f"/api/parent/children/{kid_id}/forms/spec").get_json()["club_name"] == "ФК Тест", "новото име се ползва във формата")
head.put("/api/admin/settings/club-name", json={"club_name": ""}, headers=H)
ok(p.get(f"/api/parent/children/{kid_id}/forms/spec").get_json()["club_name"].startswith("ФУТБОЛЕН КЛУБ"), "празно име връща стандартното")

# --- ЛИЧНИ ДАННИ: нищо не е запазено
secrets_ = [SECRET_NAME, SECRET_EGN, SECRET_P2, SECRET_CHILD, SECRET_ACT, "643214567"]
def blob_of(path):
    return open(path, "rb").read()
found = []
for root, _dirs, files in os.walk(tmp):
    for f in files:
        data = blob_of(os.path.join(root, f))
        for sec in secrets_:
            if sec.encode() in data: found.append((f, sec))
ok(not found, f"ЕГН/имена/лична карта не са в базата и файловете на диска: {found}")
leaks = [line[:160] for line in logs.getvalue().splitlines() if any(sec in line for sec in secrets_)]
ok(not leaks, f"нищо от въведеното не е в логовете: {leaks}")
with p.session_transaction() as sess:
    ok(set(sess.keys()) <= {"pid", "ptv", "pcsrf", "_permanent"}, f"сесията не съдържа данни от формата: {sorted(sess.keys())}")
with app.app_context():
    from sqlalchemy import text
    tables = [r[0] for r in db.session.execute(text("select name from sqlite_master where type='table'"))]
    dump = ""
    for tname in tables:
        dump += str(db.session.execute(text(f"select * from {tname}")).fetchall())
    ok(not any(sec in dump for sec in secrets_), "нищо от въведеното не е в нито една таблица")
print("ВСИЧКО МИНА")
