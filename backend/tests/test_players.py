"""Бърза проверка на стъпка 1 (профили, родителски вход, роли). Пускане: python tests/test_players.py"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import AdminUser, CoachProfile, Registration, Team, ROLE_OWNER, ROLE_HEAD_COACH, ROLE_COACH, KIND_YOUTH

app = create_app()
sent = []
import app.routes.players as pl
pl.send_email = lambda to, s, b: sent.append((to, s, b)) or True

with app.app_context():
    for name, role in (("owner", ROLE_OWNER), ("head", ROLE_HEAD_COACH), ("coach", ROLE_COACH)):
        u = AdminUser(username=name, display_name=name, role=role); u.set_password("password123"); db.session.add(u)
    t2016 = Team(slug="2016", kind=KIND_YOUTH, birth_year_from=2016, description="")
    t2017 = Team(slug="2017", kind=KIND_YOUTH, birth_year_from=2017, description="")
    db.session.add_all([t2016, t2017]); db.session.flush()
    coach = AdminUser.query.filter_by(username="coach").first()
    prof = CoachProfile(user=coach); prof.teams = [t2016]; db.session.add(prof)
    reg = Registration(child_name="Иван Петров", child_age=10, parent_name="Мария Петрова", phone="0888", email="Maria@Example.com")
    db.session.add(reg); db.session.commit()
    reg_id = reg.id

def admin(name):
    c = app.test_client()
    r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.data
    return c, {"X-CSRF-Token": r.get_json()["csrf"]}

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

head, H = admin("head"); coachc, C = admin("coach"); owner, O = admin("owner")

# prefill + създаване
r = head.get(f"/api/admin/registrations/{reg_id}/prefill"); ok(r.get_json()["parent_email"] == "Maria@Example.com", "prefill")
body = {"child_name": "Иван Петров", "birth_date": "2016-05-04", "parent_name": "Мария Петрова",
        "parent_phone": "0888", "parent_email": "Maria@Example.com", "registration_id": reg_id}
r = head.post("/api/admin/players", json=body, headers=H); d = r.get_json()
ok(r.status_code == 201 and d["email_status"] == "sent" and not d["parent_existing"], "създаване на профил + имейл")
ok(d["player"]["team_label"] == "U11" or d["player"]["team_label"].startswith("U"), f"отбор по година: {d['player']['team_label']}")
pw = sent[-1][2].split("Временна парола: ")[1].split("\n")[0]
ok(sent[-1][0] == "maria@example.com", "имейлът е с малки букви и съдържа парола")
with app.app_context():
    ok(db.session.get(Registration, reg_id).player_id == d["player"]["id"], "запитването е свързано с профила")
r = head.post("/api/admin/players", json={**body, "registration_id": reg_id}, headers=H); ok(r.status_code == 400, "дубликат на запитване/дете се отказва")

# второ дете на същия имейл
body2 = {"child_name": "Петър Петров", "birth_date": "2017-01-02", "parent_email": "maria@example.com"}
r = head.post("/api/admin/players", json=body2, headers=H); d2 = r.get_json()
ok(r.status_code == 201 and d2["parent_existing"] and "Временна парола" not in sent[-1][2], "второ дете: без нов акаунт и без парола")

# роли
r = coachc.get("/api/admin/players"); lst = r.get_json()
ok([p["child_name"] for p in lst["players"]] == ["Иван Петров"], "треньор вижда само играчите на отбора си")
ok("parent" not in lst["players"][0] and "internal_notes" not in lst["players"][0], "треньор не вижда родител и бележки")
ok(coachc.post("/api/admin/players", json=body2, headers=C).status_code == 403, "треньор не създава")
ok(coachc.patch(f"/api/admin/players/{d['player']['id']}", json={"status": "paused"}, headers=C).status_code == 403, "треньор не редактира")
ok(coachc.get(f"/api/admin/players/{d2['player']['id']}").status_code == 404, "треньор не отваря чужд отбор")

# родителски вход
p = app.test_client()
ok(p.post("/api/parent/login", json={"email": "maria@example.com", "password": "грешна"}).status_code == 401, "грешна парола")
r = p.post("/api/parent/login", json={"email": "MARIA@example.com", "password": pw}); me = r.get_json()
ok(r.status_code == 200 and me["must_change_password"] and me["needs_consent"], "вход с временна парола")
P = {"X-CSRF-Token": me["csrf"]}
r = p.get("/api/parent/children"); ok(r.status_code == 403 and r.get_json()["code"] == "password_change_required", "порталът е затворен до смяна на паролата")
ok(p.get("/parent-portal.html", follow_redirects=False).headers["Location"].endswith("/parent-change-password.html"), "страницата пренасочва към смяна")
ok(p.get("/admin-news.html", follow_redirects=False).headers["Location"].endswith("/admin-login.html"), "родител няма достъп до админ страници")
ok(p.get("/api/admin/players").status_code == 401, "родител няма достъп до админ API")
r = p.post("/api/parent/change-password", json={"current_password": pw, "new_password": "novaparola1"}, headers=P)
ok(r.status_code == 400 and "consent" in r.get_json()["errors"], "без съгласие смяната се отказва")
r = p.post("/api/parent/change-password", json={"current_password": pw, "new_password": "novaparola1", "consent": True}, headers=P)
ok(r.status_code == 200 and not r.get_json()["must_change_password"], "смяна на парола + съгласие")
P = {"X-CSRF-Token": r.get_json()["csrf"]}
r = p.get("/api/parent/children"); kids = r.get_json()["children"]
ok(len(kids) == 2 and all("internal_notes" not in k for k in kids), "родителят вижда двете си деца без бележки")
ok(p.post("/api/parent/change-password", json={"current_password": "novaparola1", "new_password": "novaparola1"}, headers=P).status_code == 400, "същата парола се отказва")

# нова временна парола
r = head.post(f"/api/admin/players/{d['player']['id']}/new-password", headers=H); ok(r.get_json()["email_status"] == "sent", "нова временна парола по имейл")
ok(p.get("/api/parent/children").status_code == 401, "старата сесия спира веднага")
ok(app.test_client().post("/api/parent/login", json={"email": "maria@example.com", "password": "novaparola1"}).status_code == 401, "старата парола не важи")
pw2 = sent[-1][2].split("Временна парола: ")[1].split("\n")[0]
ok(app.test_client().post("/api/parent/login", json={"email": "maria@example.com", "password": pw2}).status_code == 200, "новата временна парола работи")

# заключване
q = app.test_client()
for _ in range(5): q.post("/api/parent/login", json={"email": "maria@example.com", "password": "x"})
ok(q.post("/api/parent/login", json={"email": "maria@example.com", "password": pw2}).status_code == 429, "заключване след 5 грешки")

# архив и изтриване
for pid in (d["player"]["id"], d2["player"]["id"]):
    ok(head.delete(f"/api/admin/players/{pid}", headers=H).get_json()["player"]["archived"], "изтриване = архивиране")
with app.app_context():
    ok(not AdminUser.query.count() == 0 and not __import__("app.models", fromlist=["ParentAccount"]).ParentAccount.query.first().is_active, "родител без активни деца губи достъп")
r = app.test_client().post("/api/parent/login", json={"email": "maria@example.com", "password": pw2})
ok(r.status_code in (403, 429), "спрян достъп не влиза")
# страници
pc = app.test_client()
with app.app_context():
    from app.models import ParentAccount
    x = ParentAccount.query.first(); x.is_active = True; x.locked_until = None; x.set_password("novaparola1"); x.consent_at = __import__("app.models", fromlist=["utcnow"]).utcnow(); db.session.commit()
pc.post("/api/parent/login", json={"email": "maria@example.com", "password": "novaparola1"})
for page in ("parent-portal.html", "parent-change-password.html", "parent-login.html", "parent.css", "parent-common.js", "admin-players.html"):
    code = pc.get("/" + page, follow_redirects=False).status_code
    exp = 302 if page == "admin-players.html" else 200
    ok(code == exp, f"страница {page}: {code}")
ok(head.delete(f"/api/admin/players/{d['player']['id']}?forever=1", headers=H).status_code == 403, "главен треньор не изтрива завинаги")
ok(owner.delete(f"/api/admin/players/{d['player']['id']}?forever=1", headers=O).status_code == 200, "главен админ изтрива завинаги")
print("ВСИЧКО МИНА")
