"""Изтриване на записи за пробна тренировка и поръчки. Пускане: python tests/test_deletes.py"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = tmp
os.environ["DOCS_DIR"] = os.path.join(tmp, "docs")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import AdminUser, Order, OrderItem, Player, ParentAccount, Registration, ROLE_COACH, ROLE_HEAD_COACH, ROLE_OWNER
from app.shop_orders import create_order

app = create_app()

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

def login(username, role):
    with app.app_context():
        u = AdminUser(username=username, display_name=username, role=role); u.set_password("password123")
        db.session.add(u); db.session.commit()
    c = app.test_client()
    csrf = c.post("/api/auth/login", json={"username": username, "password": "password123"}).get_json()["csrf"]
    return c, {"X-CSRF-Token": csrf}

owner, O = login("owner", ROLE_OWNER)
head, H = login("head", ROLE_HEAD_COACH)
coach, C = login("coach", ROLE_COACH)

def new_reg(name="Дете"):
    with app.app_context():
        r = Registration(child_name=name, child_age=9, parent_name="Родител", phone="1", email="a@b.bg")
        db.session.add(r); db.session.commit(); return r.id

# --- записи за пробна тренировка
rid = new_reg()
ok(coach.delete(f"/api/registration/{rid}", headers=C).status_code == 403, "треньор не изтрива запис")
ok(app.test_client().delete(f"/api/registration/{rid}").status_code == 401, "без вход — 401")
ok(head.delete(f"/api/registration/{rid}", headers=H).status_code == 200, "главен треньор изтрива запис")
ok(head.delete(f"/api/registration/{rid}", headers=H).status_code == 404, "вече изтритият — 404")
rid2 = new_reg("Друго")
ok(owner.delete(f"/api/registration/{rid2}", headers=O).status_code == 200, "главен админ изтрива запис")

with app.app_context():
    parent = ParentAccount(email="p@e.com", display_name="П", phone="1", password_hash=""); parent.set_password("novaparola1")
    from app.models import utcnow
    from datetime import date
    parent.consent_at = utcnow(); db.session.add(parent); db.session.flush()
    pl = Player(parent=parent, child_name="С профил", birth_date=date(2017, 3, 1)); db.session.add(pl); db.session.flush()
    r = Registration(child_name="С профил", child_age=9, parent_name="П", phone="1", email="p@e.com", player_id=pl.id)
    db.session.add(r); db.session.commit(); rid3 = r.id
ok(head.delete(f"/api/registration/{rid3}", headers=H).status_code == 409, "запис със създаден профил не се трие (409)")

# --- поръчки
with app.app_context():
    from app.models import Product
    def mk():
        o = create_order({"name": "К", "email": "k@e.bg", "phone": "1", "delivery": "pickup", "address": ""},
                         [{"product": type("P", (), {"id": None, "name": "Тениска"})(), "size": "M", "group": "", "unit": 3900,
                           "qty": 1, "pname": "", "pnumber": "", "fee": 0}])
        return o.id, o.number
    (a, na), (b, nb), (c3, nc) = mk(), mk(), mk()
ok(len({na, nb, nc}) == 3, "три различни номера")
ok(coach.delete(f"/api/admin/shop/orders/{a}", headers=C).status_code == 403, "треньор не изтрива поръчка")
ok(head.delete(f"/api/admin/shop/orders/{a}", headers=H).status_code == 200, "главен треньор изтрива поръчка")
ok(owner.delete(f"/api/admin/shop/orders/{b}", headers=O).status_code == 200, "главен админ изтрива поръчка")
with app.app_context():
    n_new = mk()[1]
ok(n_new not in {nc}, f"нов номер след изтриване не повтаря съществуващ ({n_new})")
with app.app_context():
    ok(Order.query.count() == 2 and OrderItem.query.count() == 2, "редовете на изтритите поръчки са изтрити")
print("OK")
