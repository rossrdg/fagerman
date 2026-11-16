"""Проверка на стъпка 4б (известия). Пускане: python tests/test_announcements.py"""
import os, sys, tempfile
from datetime import date, timedelta
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
os.environ["DOCS_DIR"] = os.path.join(tmp, "docs")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import AdminUser, ParentAccount, Player, Team, ROLE_OWNER, ROLE_HEAD_COACH, ROLE_COACH, KIND_YOUTH, utcnow
from app.team_utils import get_season_end_year
import app.announcement_utils as au

TODAY = {"d": date(2026, 11, 13)}
au.today_sofia = lambda: TODAY["d"]
app = create_app()

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

def admin(name):
    c = app.test_client(); r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
    return c, {"X-CSRF-Token": r.get_json()["csrf"]}

with app.app_context():
    s = get_season_end_year()
    for name, role in (("owner", ROLE_OWNER), ("head", ROLE_HEAD_COACH), ("coach", ROLE_COACH)):
        u = AdminUser(username=name, display_name=name, role=role); u.set_password("password123"); db.session.add(u)
    ta = Team(slug="a", kind=KIND_YOUTH, birth_year_from=s - 9, description="")
    tb = Team(slug="b", kind=KIND_YOUTH, birth_year_from=s - 12, description="")
    db.session.add_all([ta, tb]); db.session.flush()
    def parent(email, name):
        p = ParentAccount(email=email, display_name=name, phone="1", password_hash="")
        p.set_password("novaparola1"); p.consent_at = utcnow(); db.session.add(p); db.session.flush(); return p
    pa, pb, pc = parent("a@example.com", "А"), parent("b@example.com", "Б"), parent("c@example.com", "В")
    kids = [Player(parent=pa, child_name="Иван", birth_date=date(s - 9, 3, 1)),     # отбор A
            Player(parent=pa, child_name="Мария", birth_date=date(s - 12, 6, 1)),   # отбор B
            Player(parent=pb, child_name="Петър", birth_date=date(s - 12, 2, 2)),   # отбор B
            Player(parent=pc, child_name="Стоян", birth_date=date(s - 9, 5, 5))]    # отбор A, архивиран
    kids[3].archived = True
    db.session.add_all(kids); db.session.commit()
    ivan, maria, petar, stoyan = (k.id for k in kids); team_a, team_b = ta.id, tb.id

head, H = admin("head"); owner, O = admin("owner"); coach, C = admin("coach")
def login(email):
    c = app.test_client(); c.post("/api/parent/login", json={"email": email, "password": "novaparola1"}); return c
A, B = login("a@example.com"), login("b@example.com")
def titles(c): return [a["title"] for a in c.get("/api/parent/messages").get_json()["announcements"]]

# --- права и валидация
ok(coach.get("/api/admin/announcements").status_code == 403, "обикновен треньор няма достъп")
ok(app.test_client().get("/api/admin/announcements").status_code == 401, "без вход няма достъп")
ok(A.get("/api/admin/announcements").status_code == 401, "родител няма достъп до админ известия")
ok(head.post("/api/admin/announcements", json={"title": "", "body": "x"}, headers=H).status_code == 400, "без заглавие — отказ")
ok(head.post("/api/admin/announcements", json={"title": "Т", "body": ""}, headers=H).status_code == 400, "без текст — отказ")
r = head.post("/api/admin/announcements", json={"title": "Т", "body": "т", "audience": "team", "team_id": 999}, headers=H)
ok(r.status_code == 400 and "team_id" in r.get_json()["errors"], "несъществуващ отбор — отказ")
r = head.post("/api/admin/announcements", json={"title": "Т", "body": "т", "publish_date": "2026-11-20", "expires_date": "2026-11-10"}, headers=H)
ok(r.status_code == 400 and "expires_date" in r.get_json()["errors"], "край преди началото — отказ")
r = head.post("/api/admin/announcements", json={"title": "Т", "body": "т", "audience": "player", "player_id": stoyan}, headers=H)
ok(r.status_code == 400 and "player_id" in r.get_json()["errors"], "архивирано дете — отказ")

# --- за всички
r = head.post("/api/admin/announcements", json={"title": "Събрание на родителите", "body": "В събота в 10:00.\n\nМоля, елате!"}, headers=H)
ok(r.status_code == 201 and r.get_json()["announcement"]["state"] == "active", "известие за всички — показва се от днес")
all_id = r.get_json()["announcement"]["id"]
ok(r.get_json()["announcement"]["recipients"] == 2, "получатели: 2 родители с активни деца (архивираното дете не се брои)")
ok(titles(A) == ["Събрание на родителите"] and titles(B) == ["Събрание на родителите"], "и двамата родители го виждат")
m = A.get("/api/parent/messages").get_json()["announcements"][0]
ok(m["body"] == "В събота в 10:00.\n\nМоля, елате!" and m["for_children"] == [], "текстът и абзаците се запазват; за всички няма „за кое дете“")

# --- за отбор
r = head.post("/api/admin/announcements", json={"title": "Тренировка в сряда се отменя", "body": "Отбор B.", "audience": "team", "team_id": team_b}, headers=H)
ok(r.get_json()["announcement"]["recipients"] == 2 and r.get_json()["announcement"]["audience_text"].startswith("Отбор "), "известие за отбор B: 2 родители")
ok("Тренировка в сряда се отменя" in titles(A) and "Тренировка в сряда се отменя" in titles(B), "родителите на деца от отбор B го виждат")
m = [x for x in A.get("/api/parent/messages").get_json()["announcements"] if x["title"].startswith("Тренировка")][0]
ok(m["for_children"] == ["Мария"], "родител с две деца вижда за кое дете е известието (само Мария е в отбор B)")

# --- за дете
r = head.post("/api/admin/announcements", json={"title": "За Иван", "body": "Лично.", "audience": "player", "player_id": ivan}, headers=H)
ok(r.get_json()["announcement"]["recipients"] == 1, "известие за дете: 1 родител")
ok("За Иван" in titles(A) and "За Иван" not in titles(B), "само родителят на детето го вижда")

# --- насрочено и изтичане
tomorrow = (TODAY["d"] + timedelta(days=1)).isoformat()
r = head.post("/api/admin/announcements", json={"title": "Утре", "body": "т", "publish_date": tomorrow}, headers=H)
ok(r.get_json()["announcement"]["state"] == "scheduled" and "Утре" not in titles(A), "насроченото не се показва преди датата")
TODAY["d"] += timedelta(days=1)
ok("Утре" in titles(A), "показва се от датата на публикуване")
r = head.post("/api/admin/announcements", json={"title": "До днес", "body": "т", "publish_date": TODAY["d"].isoformat(), "expires_date": TODAY["d"].isoformat()}, headers=H)
ok("До днес" in titles(A), "показва се и в последния ден")
TODAY["d"] += timedelta(days=1)
ok("До днес" not in titles(A), "след края не се показва")
lst = {a["title"]: a for a in head.get("/api/admin/announcements").get_json()["announcements"]}
ok(lst["До днес"]["state"] == "expired" and lst["Утре"]["state"] == "active", "състояния в списъка: изтекло / показва се")
TODAY["d"] = date(2026, 11, 13)

# --- скриване, промяна, изтриване
r = head.patch(f"/api/admin/announcements/{all_id}", json={"is_hidden": True}, headers=H)
ok(r.get_json()["announcement"]["state"] == "hidden" and "Събрание на родителите" not in titles(A), "скритото изчезва от портала")
r = head.patch(f"/api/admin/announcements/{all_id}", json={"is_hidden": False, "title": "Събрание (нов час)", "body": "В 11:00."}, headers=H)
ok(r.status_code == 200 and "Събрание (нов час)" in titles(A) and r.get_json()["announcement"]["updated_by"] == "head", "промяна на заглавие/текст; записва се кой")
r = head.patch(f"/api/admin/announcements/{all_id}", json={"audience": "team", "team_id": team_a}, headers=H)
ok(r.get_json()["announcement"]["recipients"] == 1 and "Събрание (нов час)" in titles(A) and "Събрание (нов час)" not in titles(B), "смяна на аудиторията: вече само отбор A")
ok(owner.delete(f"/api/admin/announcements/{all_id}", headers=O).status_code == 200 and "Събрание (нов час)" not in titles(A), "изтриване")
ok(head.delete("/api/admin/announcements/999", headers=H).status_code == 404, "несъществуващо — 404")

# --- HTML не се интерпретира (приема се като текст)
r = head.post("/api/admin/announcements", json={"title": "<b>Х</b>", "body": "<script>alert(1)</script>"}, headers=H)
ok(r.status_code == 201 and "<script>" in A.get("/api/parent/messages").get_json()["announcements"][0]["body"], "HTML се пази като обикновен текст (порталът го показва с textContent)")

# --- изпращане по имейл
import app.routes.announcements as ar
from app.mailer import MailError
outbox, mode = [], {"fail": set(), "dry": False}
def fake_send(to, subject, body):
    if to in mode["fail"]:
        raise MailError("smtp down")
    outbox.append((to, subject, body))
    return not mode["dry"]
ar.send_email = fake_send

rm = head.post("/api/admin/announcements", json={"title": "Нов график", "body": "От понеделник тренираме в 18:00.", "audience": "team", "team_id": team_b}, headers=H).get_json()["announcement"]
ok(rm["can_email"] and rm["emailed_at"] is None and rm["emailed_count"] == 0, "ново известие: може да се изпраща, още не е изпращано")
r = head.post(f"/api/admin/announcements/{rm['id']}/send-email", headers=H); j = r.get_json()
ok(r.status_code == 200 and j["total"] == 2 and j["sent"] == 2 and j["failed"] == 0, "изпращане до 2 родители (отбор B)")
ok({o[0] for o in outbox} == {"a@example.com", "b@example.com"} and all(o[1] == "Нов график" for o in outbox), "получатели и тема")
body_a = [o[2] for o in outbox if o[0] == "a@example.com"][0]
ok("Здравейте А" in body_a and "От понеделник тренираме в 18:00." in body_a and "Касае: Мария" in body_a and "parent-login.html" in body_a, "тяло: поздрав, текст, „Касае: Мария“ и линк към портала")
ok(j["announcement"]["emailed_at"] and j["announcement"]["emailed_count"] == 2, "записва се кога и до колко е изпратено")

outbox.clear()
rall = head.post("/api/admin/announcements", json={"title": "За всички", "body": "Общо."}, headers=H).get_json()["announcement"]
head.post(f"/api/admin/announcements/{rall['id']}/send-email", headers=H)
ok(all("Касае:" not in o[2] for o in outbox), "известие към всички: без „Касае“")

# грешка при един получател не спира останалите
outbox.clear(); mode["fail"] = {"b@example.com"}
j = head.post(f"/api/admin/announcements/{rm['id']}/send-email", headers=H).get_json()
ok(j["sent"] == 1 and j["failed"] == 1 and j["failed_emails"] == ["b@example.com"], "един неуспешен имейл не спира останалите")
mode["fail"] = set()

# тестов режим (без MAIL_SERVER): не се брои за изпратено
outbox.clear(); mode["dry"] = True
rd = head.post("/api/admin/announcements", json={"title": "Тест", "body": "т"}, headers=H).get_json()["announcement"]
j = head.post(f"/api/admin/announcements/{rd['id']}/send-email", headers=H).get_json()
ok(j["sent"] == 0 and j["dry_run"] == 2 and j["announcement"]["emailed_at"] is None, "тестов режим: имейлите не се броят за изпратени")
mode["dry"] = False

# състояния и права
future = head.post("/api/admin/announcements", json={"title": "Насрочено", "body": "т", "publish_date": "2026-12-01"}, headers=H).get_json()["announcement"]
ok(head.post(f"/api/admin/announcements/{future['id']}/send-email", headers=H).status_code == 409, "насрочено известие не се изпраща по имейл")
head.patch(f"/api/admin/announcements/{rd['id']}", json={"is_hidden": True}, headers=H)
ok(head.post(f"/api/admin/announcements/{rd['id']}/send-email", headers=H).status_code == 409, "скрито известие не се изпраща по имейл")
ok(coach.post(f"/api/admin/announcements/{rm['id']}/send-email", headers=C).status_code == 403, "обикновен треньор не изпраща")
ok(A.post(f"/api/admin/announcements/{rm['id']}/send-email").status_code == 401, "родител не изпраща")
ok(head.post("/api/admin/announcements/999/send-email", headers=H).status_code == 404, "несъществуващо — 404")
ok("mail_configured" in head.get("/api/admin/announcements").get_json(), "списъкът казва дали има настроен MAIL_SERVER")

# --- изтриване на играч чисти известията му
head.post(f"/api/admin/players/{ivan}/archive", headers=H)
ok(owner.delete(f"/api/admin/players/{ivan}?forever=1", headers=O).status_code == 200, "пълно изтриване на дете с известие")
with app.app_context():
    from app.models import Announcement
    ok(Announcement.query.filter_by(player_id=ivan).count() == 0, "известията за изтритото дете са изчистени")
print("ВСИЧКО МИНА")
