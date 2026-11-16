"""Проверка на стъпка 4а (такси). Пускане: python tests/test_fees.py"""
import os, sys, tempfile
from datetime import date
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
os.environ["DOCS_DIR"] = os.path.join(tmp, "docs")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import AdminUser, CoachProfile, ParentAccount, Player, Team, ROLE_OWNER, ROLE_HEAD_COACH, ROLE_COACH, KIND_YOUTH, utcnow
from app.team_utils import get_season_end_year
import app.fee_utils as fu

TODAY = {"d": date(2026, 11, 13)}
fu.today_sofia = lambda: TODAY["d"]  # „днес“ за тестовете

app = create_app()

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

def admin(name):
    c = app.test_client()
    r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
    return c, {"X-CSRF-Token": r.get_json()["csrf"]}

with app.app_context():
    s = get_season_end_year()
    for name, role in (("owner", ROLE_OWNER), ("head", ROLE_HEAD_COACH), ("coach", ROLE_COACH)):
        u = AdminUser(username=name, display_name=name, role=role); u.set_password("password123"); db.session.add(u)
    t1 = Team(slug="a", kind=KIND_YOUTH, birth_year_from=s - 9, description="")
    t2 = Team(slug="b", kind=KIND_YOUTH, birth_year_from=s - 12, description="")
    db.session.add_all([t1, t2]); db.session.flush()
    def parent(email, name):
        p = ParentAccount(email=email, display_name=name, phone="0888", password_hash="")
        p.set_password("novaparola1"); p.consent_at = utcnow(); db.session.add(p); db.session.flush(); return p
    pa, pb = parent("a@example.com", "Мама А"), parent("b@example.com", "Мама Б")
    kids = [Player(parent=pa, child_name="Иван А", birth_date=date(s - 9, 3, 1)),
            Player(parent=pa, child_name="Мария А", birth_date=date(s - 9, 6, 1)),
            Player(parent=pb, child_name="Петър Б", birth_date=date(s - 12, 2, 2))]
    db.session.add_all(kids); db.session.commit()
    ivan, maria, petar = (k.id for k in kids)
    team_a = t1.id

head, H = admin("head"); owner, O = admin("owner"); coach, C = admin("coach")

# --- видове такси
r = head.post("/api/admin/fee-types", json={"name": "Месечна такса", "kind": "monthly", "default_amount": "30"}, headers=H)
ok(r.status_code == 201 and r.get_json()["type"]["default_amount_text"] == "30 €", "вид такса: месечна, 30 €")
monthly = r.get_json()["type"]["id"]
r = head.post("/api/admin/fee-types", json={"name": "Екип", "kind": "one_time", "default_amount": "45,50"}, headers=H)
kit = r.get_json()["type"]["id"]; ok(r.get_json()["type"]["default_amount_text"] == "45,50 €", "еднократна такса: 45,50 €")
ok(head.post("/api/admin/fee-types", json={"name": "месечна такса", "kind": "monthly", "default_amount": 1}, headers=H).status_code == 400, "дублирано име се отказва")
ok(head.post("/api/admin/fee-types", json={"name": "X", "kind": "monthly", "default_amount": "abc"}, headers=H).status_code == 400, "невалидна сума се отказва")

# --- права
ok(coach.get("/api/admin/fee-types").status_code == 403, "обикновен треньор няма достъп до такси")
ok(app.test_client().get("/api/admin/fee-types").status_code == 401, "без вход няма достъп")
ok(owner.get("/api/admin/fee-types").status_code == 200, "главен админ има достъп")

# --- масово присвояване на отбор, начален месец август 2026
r = head.post("/api/admin/fees/assign", json={"fee_type_id": monthly, "team_id": team_a, "start_month": "2026-08"}, headers=H)
ok(r.status_code == 201 and r.get_json()["created"] == 2, "масово присвояване на отбор (2 играчи)")
r = head.post("/api/admin/fees/assign", json={"fee_type_id": monthly, "team_id": team_a, "start_month": "2026-08"}, headers=H)
ok(r.get_json()["created"] == 0 and len(r.get_json()["skipped"]) == 2, "повторно присвояване пропуска вече присвоените")

# --- редове: август..ноември (текущ) = 4 месеца
f = head.get(f"/api/admin/players/{ivan}/fees").get_json()
ok(len(f["charges"]) == 4 and {c["month"] for c in f["charges"]} == {"2026-08", "2026-09", "2026-10", "2026-11"}, "месеци от началния до текущия")
ok(all(c["amount_cents"] == 3000 and c["status"] == "unpaid" for c in f["charges"]), "сума 30 € във всеки месец, всичките неплатени")
ok(f["summary"]["paid_until"] is None and f["summary"]["unpaid_count"] == 4 and f["summary"]["unpaid_total_text"] == "120 €", "обобщение: нищо не е платено")

# --- отбелязване на плащане
cid = {c["month"]: c["id"] for c in f["charges"]}
for m in ("2026-08", "2026-09"):
    r = head.patch(f"/api/admin/fee-charges/{cid[m]}", json={"status": "paid"}, headers=H); ok(r.get_json()["charge"]["status"] == "paid", f"{m}: платено")
f = head.get(f"/api/admin/players/{ivan}/fees").get_json()
ok(f["summary"]["paid_until"] == "2026-09" and f["summary"]["unpaid_months"] == ["октомври 2026", "ноември 2026"], "„платено до септември“, неплатени октомври и ноември")
ok(f["history"] and f["history"][0]["by"] == "head" and "Платено" in f["history"][0]["detail"], "историята пази кой и какво е променил")
ok(coach.patch(f"/api/admin/fee-charges/{cid['2026-10']}", json={"status": "paid"}, headers=C).status_code == 403, "треньор не отбелязва плащане")
r = head.patch(f"/api/admin/fee-charges/{cid['2026-10']}", json={"amount": "20", "note": "скъсен месец"}, headers=H)
ok(r.get_json()["charge"]["amount_cents"] == 2000 and "скъсен" in r.get_json()["charge"]["note"], "собствена сума и бележка на месец")
r = owner.patch(f"/api/admin/fee-charges/{cid['2026-10']}", json={"status": "paid"}, headers=O)
ok(r.status_code == 200 and head.get(f"/api/admin/players/{ivan}/fees").get_json()["history"][0]["by"] == "owner", "главният админ също отбелязва (записва се кой)")

# --- промяна на присвояването: сумата важи за следващите месеци
aid = head.get(f"/api/admin/players/{ivan}/fees").get_json()["assignments"][0]["id"]
head.patch(f"/api/admin/fee-assignments/{aid}", json={"amount": "25"}, headers=H)
f = head.get(f"/api/admin/players/{ivan}/fees").get_json()
ok(all(c["amount_cents"] in (3000, 2000) for c in f["charges"]), "съществуващите месеци не променят сумата")
TODAY["d"] = date(2026, 12, 2)
f = head.get(f"/api/admin/players/{ivan}/fees").get_json()
dec = [c for c in f["charges"] if c["month"] == "2026-12"][0]
ok(dec["amount_cents"] == 2500, "новият месец (декември) е с новата сума 25 €")
TODAY["d"] = date(2026, 11, 13)

# --- скъсен първи месец и отстъпка (собствена сума)
r = head.post("/api/admin/fees/assign", json={"fee_type_id": monthly, "player_ids": [petar], "start_month": "2026-10",
                                              "amount": "20", "first_month_amount": "10", "note": "отстъпка"}, headers=H)
ok(r.get_json()["created"] == 1, "присвояване на отделен играч със собствена сума")
f = head.get(f"/api/admin/players/{petar}/fees").get_json()
amounts = {c["month"]: c["amount_cents"] for c in f["charges"]}
ok(amounts == {"2026-10": 1000, "2026-11": 2000}, f"скъсен първи месец 10 €, после 20 €: {amounts}")

# --- еднократна такса (екип) за октомври
r = head.post("/api/admin/fees/assign", json={"fee_type_id": kit, "player_ids": [maria], "start_month": "2026-10"}, headers=H)
f = head.get(f"/api/admin/players/{maria}/fees").get_json()
one = [c for c in f["charges"] if c["kind"] == "one_time"]
ok(len(one) == 1 and one[0]["amount_cents"] == 4550 and one[0]["month"] == "2026-10", "еднократна такса: един ред, 45,50 €")

# --- екран „месец + отбор“
r = head.get("/api/admin/fees/month?month=2026-11").get_json()
ok(len(r["rows"]) == 3 and r["is_current"], "месец ноември: 3 реда (Иван, Мария, Петър)")
r2 = head.get(f"/api/admin/fees/month?month=2026-11&team={team_a}").get_json()
ok({x["child_name"] for x in r2["rows"]} == {"Иван А", "Мария А"}, "филтър по отбор")
ok(head.get("/api/admin/fees/month?month=грешка").status_code == 400, "невалиден месец се отказва")

# --- масово „всички платени“ и „освободи лятото“
r = head.post("/api/admin/fees/bulk", json={"months": ["2026-11"], "team_id": team_a, "status": "paid"}, headers=H)
ok(r.get_json()["changed"] == 2, "масово платено за отбора (2 реда)")
r = head.post("/api/admin/fees/bulk", json={"months": ["2027-07", "2027-08"], "team_id": team_a, "status": "waived"}, headers=H)
ok(r.get_json()["changed"] == 4, "освобождаване на юли и август наперед за отбора (2 играчи × 2 месеца)")
f = head.get(f"/api/admin/players/{ivan}/fees").get_json()
ok({c["month"]: c["status"] for c in f["charges"]}["2027-07"] == "waived", "юли 2027 е освободен")
ok(head.post("/api/admin/fees/bulk", json={"months": ["2031-01"], "status": "waived"}, headers=H).status_code == 400, "твърде далечен месец се отказва")
ok(head.post("/api/admin/fees/bulk", json={"months": ["2026-11"], "status": "unpaid"}, headers=H).status_code == 400, "масово може само платено/освободено")

# --- пауза: нови месеци не се създават; старите се запазват
head.patch(f"/api/admin/players/{petar}", json={"status": "paused"}, headers=H)
TODAY["d"] = date(2027, 2, 3)
f = head.get(f"/api/admin/players/{petar}/fees").get_json()
ok({c["month"] for c in f["charges"]} == {"2026-10", "2026-11"}, "паузиран играч: без нови месеци, старите остават")
TODAY["d"] = date(2026, 11, 13)

# --- родител: напомняне
pa_c = app.test_client(); r = pa_c.post("/api/parent/login", json={"email": "a@example.com", "password": "novaparola1"})
PA = {"X-CSRF-Token": r.get_json()["csrf"]}
head.put("/api/admin/fees/pay-info", json={"text": "В брой на тренировка или по банков път: BG00 TEST 0000 0000"}, headers=H)
m = pa_c.get("/api/parent/messages").get_json()
fees = [x for x in m["reminders"] if x["type"] == "fees"]
ok(len(fees) == 1 and fees[0]["child_name"] == "Мария А", "напомняне само за детето с дължими такси (Иван е платил всичко до сега)")
mr = fees[0]
labels = [i["label"] for i in mr["items"]]
ok(len(labels) == 4 and any("август" in l for l in labels) and any(l == "Екип" for l in labels), f"позиции: 3 неплатени месеца + екип: {labels}")
ok(mr["total_text"] == "135,50 €", f"обща сума 3 × 30 € + 45,50 €: {mr['total_text']}")
ok("Ако вече сте платили" in mr["text"] and "просроч" not in mr["text"].lower(), "спокоен тон, без просрочие")
ok(m["pay_info"].startswith("В брой"), "показва се „Как се плаща“")
mb = app.test_client(); rb = mb.post("/api/parent/login", json={"email": "b@example.com", "password": "novaparola1"})
mm = mb.get("/api/parent/messages").get_json()
ok(all(x["child_name"] == "Петър Б" for x in mm["reminders"]), "родител вижда само своите деца")
# платено -> напомнянето изчезва
for c in head.get(f"/api/admin/players/{maria}/fees").get_json()["charges"]:
    head.patch(f"/api/admin/fee-charges/{c['id']}", json={"status": "paid"}, headers=H)
m2 = pa_c.get("/api/parent/messages").get_json()
ok(all(x["child_name"] != "Мария А" for x in m2["reminders"] if x["type"] == "fees"), "напомнянето изчезва, когато всичко е платено")
ok(app.test_client().get("/api/parent/messages").status_code == 401, "без вход няма съобщения")
ok(pa_c.get("/api/admin/fee-types").status_code == 401, "родител няма достъп до админ такси")

# --- списък „Футболисти“: обобщение за управителите, не за треньор
lst = head.get("/api/admin/players").get_json()["players"]
ok(all("fees" in p for p in lst) and [p for p in lst if p["id"] == ivan][0]["fees"]["has_fees"], "в списъка има „такси“ за управителите")
with app.app_context():
    prof = CoachProfile(user=AdminUser.query.filter_by(username="coach").first()); prof.teams = [db.session.get(Team, team_a)]; db.session.add(prof); db.session.commit()
cl = coach.get("/api/admin/players").get_json()["players"]
ok(cl and all("fees" not in p and "docs" not in p for p in cl), "треньорът не вижда такси в списъка")

# --- отчет и CSV
rep = head.get("/api/admin/fees/report?month=2026-10").get_json()
ok(rep["totals"]["count"] >= 1 and all(x["status"] == "unpaid" for x in rep["rows"]), "отчет: само неплатените за месеца")
csv_r = head.get("/api/admin/fees/report.csv?month=2026-10&status=all")
ok(csv_r.status_code == 200 and csv_r.data.startswith("\ufeff".encode()) and "Месец;Дете" in csv_r.get_data(as_text=True), "CSV за Excel (UTF-8 с BOM)")
ok(coach.get("/api/admin/fees/report.csv").status_code == 403, "треньор няма достъп до отчета")

# --- изтриване на присвояване
aid2 = head.get(f"/api/admin/players/{petar}/fees").get_json()["assignments"][0]["id"]
ok(head.delete(f"/api/admin/fee-assignments/{aid2}", headers=H).status_code == 200, "присвояване без платени месеци се изтрива")
ok(head.delete(f"/api/admin/fee-assignments/{aid}", headers=H).status_code == 409, "присвояване с платени месеци не се изтрива")

# --- пълно изтриване на играч чисти таксите
head.post(f"/api/admin/players/{maria}/archive", headers=H)
ok(owner.delete(f"/api/admin/players/{maria}?forever=1", headers=O).status_code == 200, "пълно изтриване на играч с такси")
with app.app_context():
    from app.models import FeeCharge, FeeHistory
    ok(FeeCharge.query.filter_by(player_id=maria).count() == 0 and FeeHistory.query.filter_by(player_id=maria).count() == 0, "таксите и историята му са изчистени")
print("ВСИЧКО МИНА")
