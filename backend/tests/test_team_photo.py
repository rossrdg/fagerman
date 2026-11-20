"""Проверка: снимка на отбор. Пускане: python tests/test_team_photo.py"""
import io, os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from app import create_app, db
from app.models import AdminUser, Team, ROLE_COACH, ROLE_OWNER, KIND_YOUTH
from app.team_utils import get_season_end_year

app = create_app()

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

def png(size=(1200, 800), color="blue"):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); b.seek(0); return b

with app.app_context():
    s = get_season_end_year()
    for name, role in (("owner", ROLE_OWNER), ("coach", ROLE_COACH)):
        u = AdminUser(username=name, display_name=name, role=role); u.set_password("password123"); db.session.add(u)
    team = Team(slug="2018", kind=KIND_YOUTH, birth_year_from=s - 9, description="Техника, игра и увереност.")
    db.session.add(team); db.session.commit(); tid = team.id

def login(name):
    c = app.test_client(); r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
    return c, {"X-CSRF-Token": r.get_json()["csrf"]}
owner, O = login("owner"); coach, C = login("coach"); anon = app.test_client()

page = anon.get("/teams/2018").get_data(as_text=True)
ok("team-photo" not in page, "без снимка страницата няма блок за снимка")
ok(owner.get(f"/api/admin/teams/{tid}").get_json()["team"]["photo"] is None, "админ: още няма снимка")

ok(anon.post(f"/api/admin/teams/{tid}/photo", data={"image": (png(), "t.png")}).status_code == 401, "без вход качването се отказва")
r = owner.post(f"/api/admin/teams/{tid}/photo", data={"image": (io.BytesIO(b"not an image"), "x.png")}, headers=O, content_type="multipart/form-data")
ok(r.status_code == 400, "файл, който не е снимка, се отказва")
r = owner.post(f"/api/admin/teams/{tid}/photo", data={"image": (png((3000, 2000)), "team.png")}, headers=O, content_type="multipart/form-data")
j = r.get_json()["team"]
ok(r.status_code == 200 and j["photo"].endswith(".jpg") and j["photo_thumb"].endswith("-800.jpg"), "качване: записва се като JPEG (основна и умалена версия)")
main = os.path.join(tmp, os.path.basename(j["photo"])); thumb = os.path.join(tmp, os.path.basename(j["photo_thumb"]))
with Image.open(main) as im: w1 = im.width
with Image.open(thumb) as im: w2 = im.width
ok(os.path.exists(main) and os.path.exists(thumb) and w1 == 1600 and w2 == 800, f"размери: основна {w1} px, умалена {w2} px (оригиналът не се пази)")

page = anon.get("/teams/2018").get_data(as_text=True)
i_desc, i_photo, i_btn = page.find("Техника, игра и увереност."), page.find('class="team-photo"'), page.find("Запиши се за тренировка")
ok(0 < i_desc < i_photo < i_btn, "публично: снимката е под описанието и преди бутона „Запиши се“")
ok(j["photo"] in page and 'srcset="' + j["photo_thumb"] in page and 'alt="Отбор' in page, "публично: основна и умалена версия (srcset) и описание на снимката")
ok(f'og:image" content="http://localhost{j["photo"]}' in page or j["photo"] in page.split('og:image')[1][:200], "снимката е и за споделяне (og:image)")
ok(anon.get(j["photo"]).status_code == 200, "снимката се сервира публично")

# смяна: старата се изтрива
r = coach.post(f"/api/admin/teams/{tid}/photo", data={"image": (png(color="green"), "n.png")}, headers=C, content_type="multipart/form-data")
j2 = r.get_json()["team"]
ok(r.status_code == 200 and j2["photo"] != j["photo"] and not os.path.exists(main) and not os.path.exists(thumb), "смяна на снимката: старата се изтрива от диска (и треньор може да качва)")

# премахване
new_main = os.path.join(tmp, os.path.basename(j2["photo"]))
r = owner.delete(f"/api/admin/teams/{tid}/photo", headers=O)
ok(r.get_json()["team"]["photo"] is None and not os.path.exists(new_main), "премахване: и от базата, и от диска")
ok("team-photo" not in anon.get("/teams/2018").get_data(as_text=True), "след премахване блокът изчезва")

# изтриване на отбор завинаги чисти снимката
owner.post(f"/api/admin/teams/{tid}/photo", data={"image": (png(), "t.png")}, headers=O, content_type="multipart/form-data")
pn = os.path.join(tmp, os.path.basename(owner.get(f"/api/admin/teams/{tid}").get_json()["team"]["photo"]))
owner.patch(f"/api/admin/teams/{tid}", json={"status": "archived"}, headers=O)
ok(owner.delete(f"/api/admin/teams/{tid}", headers=O).status_code == 200 and not os.path.exists(pn), "изтриване на отбор завинаги трие и снимката му")
ok(owner.post("/api/admin/teams/999/photo", data={"image": (png(), "t.png")}, headers=O, content_type="multipart/form-data").status_code == 404, "несъществуващ отбор — 404")
print("ВСИЧКО МИНА")
