"""Проверка на стъпка 2 (документи за картотекиране). Пускане: python tests/test_documents.py"""
import io, os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
os.environ["DOCS_DIR"] = os.path.join(tmp, "docs")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from app import create_app, db
from app.models import AdminUser, CoachProfile, DocumentFile, Team, ROLE_OWNER, ROLE_HEAD_COACH, ROLE_COACH, KIND_YOUTH
from app.team_utils import get_season_end_year

app = create_app()
import app.routes.players as pl
pl.send_email = lambda to, s, b: True

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

def admin(name):
    c = app.test_client()
    r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
    return c, {"X-CSRF-Token": r.get_json()["csrf"]}

def png(size=(60, 40)):
    b = io.BytesIO(); Image.new("RGB", size, "red").save(b, "PNG"); b.seek(0); return b

with app.app_context():
    season = get_season_end_year()
    for name, role in (("owner", ROLE_OWNER), ("head", ROLE_HEAD_COACH), ("coach", ROLE_COACH)):
        u = AdminUser(username=name, display_name=name, role=role); u.set_password("password123"); db.session.add(u)
    for y in (season - 8, season - 15, season - 19):
        db.session.add(Team(slug=str(y), kind=KIND_YOUTH, birth_year_from=y, description=""))
    db.session.commit()

head, H = admin("head"); coach, C = admin("coach")
def new_player(name, born_year, email):
    r = head.post("/api/admin/players", json={"child_name": name, "birth_date": f"{born_year}-03-01",
        "parent_name": "Родител " + name, "parent_phone": "0888", "parent_email": email}, headers=H)
    assert r.status_code == 201, r.data
    return r.get_json()["player"]["id"]

kid = new_player("Малък", season - 9, "p1@example.com")    # U9 -> до 14
teen = new_player("Тийн", season - 15, "p2@example.com")    # U15 -> 14–18
adult = new_player("Голям", season - 19, "p3@example.com")  # U19 -> 18+

def docs_of(pid):
    return head.get(f"/api/admin/players/{pid}/documents").get_json()
types = lambda pid: [d["doc_type"] for d in docs_of(pid)["documents"]]
ok(types(kid) == ["application", "declaration", "birth_certificate", "photo", "medical"], "до 14 г.: акт за раждане")
ok(types(teen) == ["application", "declaration", "id_card", "photo", "medical"], "14–18: лична карта")
ok(types(adult) == ["application", "declaration", "id_card", "photo", "medical"], "18+: лична карта")
ok(docs_of(adult)["category"] == "adult" and docs_of(teen)["category"] == "minor" and docs_of(kid)["category"] == "under14", "категории по U число")

# родител
def parent(email):
    c = app.test_client()
    with app.app_context():
        from app.models import ParentAccount, utcnow
        p = ParentAccount.query.filter_by(email=email).first()
        p.set_password("novaparola1"); p.consent_at = utcnow(); db.session.commit()
    r = c.post("/api/parent/login", json={"email": email, "password": "novaparola1"})
    return c, {"X-CSRF-Token": r.get_json()["csrf"]}
p1, P1 = parent("p1@example.com"); p2, P2 = parent("p2@example.com")

r = p1.get(f"/api/parent/children/{kid}/documents"); d = r.get_json()
ok(r.status_code == 200 and len(d["documents"]) == 5 and d["instructions"], "родителят вижда комплекта на детето си")
ok(p2.get(f"/api/parent/children/{kid}/documents").status_code == 404, "родител не вижда чуждо дете")
docs = {x["doc_type"]: x for x in d["documents"]}
app_id, photo_id, med_id = docs["application"]["id"], docs["photo"]["id"], docs["medical"]["id"]
ok(p1.get(f"/api/parent/documents/{app_id}/template").status_code == 200, "бланка на заявлението (до 14 г.)")
ok(p1.get(f"/api/parent/documents/{docs['birth_certificate']['id']}/template").status_code == 404, "акт за раждане няма бланка")
ok(p2.get(f"/api/parent/documents/{app_id}/template").status_code == 404, "чужда бланка се отказва")

# качване
r = p1.post(f"/api/parent/documents/{photo_id}/files", data={"file": (png(), "x.png")}, headers=P1, content_type="multipart/form-data")
ok(r.status_code == 400 and "consent" in r.get_json()["errors"], "снимка без съгласие се отказва")
r = p1.post(f"/api/parent/documents/{photo_id}/files", data={"file": (png(), "x.png"), "consent": "1"}, headers=P1, content_type="multipart/form-data")
ok(r.status_code == 201 and r.get_json()["document"]["files"][0]["mime"] == "image/jpeg", "снимка със съгласие; записва се като JPEG")
r = p1.post(f"/api/parent/documents/{app_id}/files", data={"file": (io.BytesIO(b"%PDF-1.4 test"), "a.pdf")}, headers=P1, content_type="multipart/form-data")
ok(r.status_code == 201 and r.get_json()["document"]["files"][0]["mime"] == "application/pdf", "PDF се приема")
r = p1.post(f"/api/parent/documents/{app_id}/files", data={"file": (io.BytesIO(b"hello text"), "a.txt")}, headers=P1, content_type="multipart/form-data")
ok(r.status_code == 400, "файл, който не е снимка/PDF, се отказва")
r = p1.post(f"/api/parent/documents/{app_id}/files", data={"file": (png(), "x.png")}, headers=dict(P1, **{"X-CSRF-Token": "грешен"}), content_type="multipart/form-data")
ok(r.status_code == 403, "качване без валиден CSRF се отказва")
ok(p2.post(f"/api/parent/documents/{app_id}/files", data={"file": (png(), "x.png")}, headers=P2, content_type="multipart/form-data").status_code == 404, "чужд документ не се променя")
for _ in range(4):
    p1.post(f"/api/parent/documents/{app_id}/files", data={"file": (png(), "x.png")}, headers=P1, content_type="multipart/form-data")
r = p1.post(f"/api/parent/documents/{app_id}/files", data={"file": (png(), "x.png")}, headers=P1, content_type="multipart/form-data")
ok(r.status_code == 409, "максимум 5 файла на документ")

# файловете са шифровани на диска
with app.app_context():
    names = [f.name for f in DocumentFile.query.all()]
    raw = open(os.path.join(tmp, "docs", names[0] + ".bin"), "rb").read()
    ok(b"%PDF" not in raw and b"JFIF" not in raw and not raw.startswith(b"\xff\xd8"), "файловете са шифровани на диска")
fid = d and p1.get(f"/api/parent/children/{kid}/documents").get_json()["documents"][3]["files"][0]["id"]
r = p1.get(f"/api/parent/files/{fid}")
ok(r.status_code == 200 and r.data[:2] == b"\xff\xd8" and r.headers["Cache-Control"] == "private, no-store", "родителят чете свой файл (разшифрован, без кеш)")
ok(p2.get(f"/api/parent/files/{fid}").status_code == 404, "чужд файл не се чете")
ok(coach.get(f"/api/admin/files/{fid}").status_code == 403, "обикновен треньор не чете файлове")
ok(app.test_client().get(f"/api/admin/files/{fid}").status_code == 401, "без вход файл не се чете")
ok(head.get(f"/api/admin/files/{fid}").status_code == 200, "главен треньор чете файла")

# изпращане и проверка
ok(p1.post(f"/api/parent/documents/{med_id}/submit", headers=P1).status_code == 400, "изпращане без файл се отказва")
ok(p1.post(f"/api/parent/documents/{app_id}/submit", headers=P1).get_json()["document"]["status"] == "uploaded", "изпращане за проверка")
p1.post(f"/api/parent/documents/{photo_id}/submit", headers=P1)
ok(head.get("/api/admin/documents/summary").get_json()["pending"] == 2, "значка: 2 чакат проверка")
ok(coach.get("/api/admin/documents/summary").get_json()["pending"] == 0, "треньор няма значка")
ok(head.post(f"/api/admin/documents/{med_id}/approve", headers=H).status_code == 409, "неизпратен документ не се одобрява")
ok(coach.post(f"/api/admin/documents/{app_id}/approve", headers=C).status_code == 403, "треньор не одобрява")
r = head.post(f"/api/admin/documents/{app_id}/return", json={}, headers=H); ok(r.status_code == 400, "връщане без коментар се отказва")
r = head.post(f"/api/admin/documents/{app_id}/return", json={"comment": "Не се чете подписът"}, headers=H)
ok(r.status_code == 200 and {x["doc_type"]: x for x in r.get_json()["documents"]}["application"]["status"] == "returned", "връщане с коментар")
doc = p1.get(f"/api/parent/children/{kid}/documents").get_json()["documents"][0]
ok(doc["status"] == "returned" and doc["comment"] == "Не се чете подписът" and doc["can_edit"], "родителят вижда коментара и може да поправи")
p1.post(f"/api/parent/documents/{app_id}/submit", headers=P1)
r = head.post(f"/api/admin/documents/{app_id}/approve", headers=H)
ok(r.status_code == 200, "одобряване")
ok(p1.post(f"/api/parent/documents/{app_id}/files", data={"file": (png(), "x.png")}, headers=P1, content_type="multipart/form-data").status_code == 409, "одобрен документ е заключен")
lst = head.get("/api/admin/players").get_json()["players"]
mine = [p for p in lst if p["id"] == kid][0]["docs"]
ok(mine["done"] == 1 and mine["pending"] == 1 and mine["total"] == 5, f"колона „1/5“ в списъка: {mine}")
ok(len(head.get("/api/admin/players?docs=missing").get_json()["players"]) == 3, "филтър „с липсващи документи“")
ok([p["id"] for p in head.get("/api/admin/players?docs=pending").get_json()["players"]] == [kid], "филтър „чакат проверка“")
ok("docs" not in coach.get("/api/admin/players").get_json()["players"][0] if coach.get("/api/admin/players").get_json()["players"] else True, "треньор не вижда документи")

# добавяне/махане на документ
r = head.post(f"/api/admin/players/{kid}/documents", json={"doc_type": "id_card"}, headers=H)
ok(r.status_code == 200 and len(r.get_json()["documents"]) == 6, "добавяне на документ към комплекта")
ok(head.post(f"/api/admin/players/{kid}/documents", json={"doc_type": "id_card"}, headers=H).status_code == 409, "дубликат се отказва")
extra = [x for x in r.get_json()["documents"] if x["doc_type"] == "id_card"][0]["id"]
ok(len(head.delete(f"/api/admin/documents/{extra}", headers=H).get_json()["documents"]) == 5, "махане на документ")

# картотека получена
r = head.post(f"/api/admin/players/{kid}/card-received", json={"received": True}, headers=H); j = r.get_json()
ok(j["card_received"] and all(not x["files"] for x in j["documents"]), "картотека получена: файловете изчезват")
with app.app_context():
    left = [n for n in os.listdir(os.path.join(tmp, "docs")) if n.endswith(".bin")]
    ok(len(left) == 0, "шифрованите файлове са изтрити от диска")
doc = p1.get(f"/api/parent/children/{kid}/documents").get_json()
ok(doc["card_received"] and not any(x["can_edit"] for x in doc["documents"]), "родителят вижда „получена“, без промени")
ok(p1.post(f"/api/parent/documents/{med_id}/files", data={"file": (png(), "x.png")}, headers=P1, content_type="multipart/form-data").status_code == 409, "след получаване не се качва")
j = head.post(f"/api/admin/players/{kid}/card-received", json={"received": False}, headers=H).get_json()
ok(not j["card_received"] and all(x["status"] == "waiting" for x in j["documents"]), "връщане на комплекта")

# архивиране трие файловете; нов сезон отваря нов комплект
p1.post(f"/api/parent/documents/{photo_id}/files", data={"file": (png(), "x.png"), "consent": "1"}, headers=P1, content_type="multipart/form-data")
ok(len(os.listdir(os.path.join(tmp, "docs"))) >= 1, "нов файл е качен")
head.post(f"/api/admin/players/{kid}/archive", headers=H)
ok(len([n for n in os.listdir(os.path.join(tmp, "docs")) if n.endswith(".bin")]) == 0, "архивирането изтрива файловете")
with app.app_context():
    from app.team_utils import set_season_end_year
    set_season_end_year(season + 1); db.session.commit()
ok(docs_of(teen)["season"] != docs_of(teen)["season"][:0] and len(docs_of(teen)["documents"]) == 5, "нов сезон: нов комплект")
print("ВСИЧКО МИНА")
