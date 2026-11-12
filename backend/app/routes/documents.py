"""Документи за картотекиране: родителско качване + проверка от главния треньор.

Родител (/api/parent/...):
  GET    /parent/children/<id>/documents          комплектът на детето за сезона
  POST   /parent/documents/<id>/files             качва ЕДИН файл (multipart "file"; за снимката и consent=1)
  DELETE /parent/documents/<id>/files/<file_id>   маха файл
  POST   /parent/documents/<id>/submit            „Изпрати за проверка“
  GET    /parent/files/<file_id>                  вижда свой файл
  GET    /parent/documents/<id>/template          празна бланка на БФС

Админ (/api/admin/..., само главен админ и главен треньор):
  GET    /admin/players/<id>/documents            комплектът + налични видове за добавяне
  POST   /admin/players/<id>/documents            добавя документ към комплекта
  DELETE /admin/documents/<id>                    маха документ от комплекта
  POST   /admin/documents/<id>/approve | return   одобрява / връща с коментар
  GET    /admin/files/<file_id>                   вижда файл
  POST   /admin/players/<id>/card-received        „картотеката е получена“ -> файловете се изтриват
  GET    /admin/documents/summary                 колко документа чакат проверка (за значката в менюто)"""
from flask import Blueprint, jsonify, request, send_file

from app import db
from app.auth import check_admin, current_user
from app.doc_storage import MAX_FILES_PER_DOC, StorageError, delete_files, file_response, save_upload
from app.documents_catalog import (
    CATEGORY_LABELS, DOC_PHOTO, DOC_TYPES, INSTRUCTIONS, category_for, ensure_set, hint_for, purge_files, summary,
    template_path,
)
from app.models import (
    DOC_APPROVED, DOC_RETURNED, DOC_UPLOADED, DOC_WAITING, CardSeason, DocumentFile, Player,
    PlayerDocument, utcnow,
)
from app.parent_auth import current_parent, parent_required
from app.routes.players import _manager_only, _who
from app.team_utils import get_season_end_year, season_text

parent_docs_bp = Blueprint("parent_docs", __name__)
admin_docs_bp = Blueprint("admin_docs", __name__)
admin_docs_bp.before_request(check_admin)

STATUS_LABELS = {DOC_WAITING: "Чака", DOC_UPLOADED: "Качен", DOC_APPROVED: "Одобрен", DOC_RETURNED: "Върнат за поправка"}
MAX_COMMENT = 500


def _error(message, status=400, errors=None):
    body = {"ok": False, "error": message}
    if errors:
        body["errors"] = errors
    return jsonify(body), status


def _iso(value):
    return value.isoformat() if value else None


# ----------------------------------------------------------------- речници ---
def doc_dict(doc, url_prefix, category, can_edit=False, admin=False):
    meta = DOC_TYPES.get(doc.doc_type, {"title": doc.doc_type, "hint": ""})
    data = {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "title": meta["title"],
        "hint": hint_for(doc.doc_type, category),
        "status": doc.status,
        "status_label": STATUS_LABELS.get(doc.status, doc.status),
        "comment": doc.comment or "",
        "submitted_at": _iso(doc.submitted_at),
        "has_template": template_path(doc.doc_type, category) is not None,
        "needs_consent": doc.doc_type == DOC_PHOTO,
        "consent_given": doc.consent_at is not None,
        "can_edit": can_edit and not doc.archived and doc.status != DOC_APPROVED,
        "max_files": MAX_FILES_PER_DOC,
        "files": [{"id": f.id, "mime": f.mime, "size": f.size, "url": f"{url_prefix}/files/{f.id}"} for f in doc.files],
    }
    if admin:
        data.update({"reviewed_at": _iso(doc.reviewed_at), "reviewed_by": doc.reviewed_by})
    return data


def _set_payload(player, season_end, url_prefix, can_edit, admin=False):
    card, docs = ensure_set(player, season_end)
    category = category_for(player, season_end)
    return card, {
        "ok": True,
        "season": season_text(season_end),
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "card_received": card.card_received_at is not None,
        "card_received_at": _iso(card.card_received_at),
        "child_name": player.child_name,
        "summary": summary(card, docs),
        "documents": [doc_dict(d, url_prefix, category, can_edit=can_edit and card.card_received_at is None, admin=admin)
                      for d in docs],
    }


# --------------------------------------------------------------- родител ---
def _parent_player(player_id):
    parent = current_parent()
    player = db.session.get(Player, player_id)
    if player is None or player.parent_id != parent.id or player.archived:
        return None
    return player


def _parent_doc(doc_id):
    doc = db.session.get(PlayerDocument, doc_id)
    if doc is None or _parent_player(doc.player_id) is None:
        return None
    return doc


def _editable_or_error(doc):
    """None, ако родителят може да променя документа; иначе (отговор, код)."""
    card = CardSeason.query.filter_by(player_id=doc.player_id, season_end=doc.season_end).first()
    if doc.archived or (card and card.card_received_at):
        return _error("Картотеката вече е получена — документите не се променят.", 409)
    if doc.status == DOC_APPROVED:
        return _error("Документът е одобрен и не може да се променя.", 409)
    return None


@parent_docs_bp.get("/parent/children/<int:player_id>/documents")
@parent_required
def parent_documents(player_id):
    player = _parent_player(player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    card, payload = _set_payload(player, get_season_end_year(), "/api/parent", can_edit=True)
    db.session.commit()
    payload["instructions"] = INSTRUCTIONS
    return jsonify(payload)


@parent_docs_bp.post("/parent/documents/<int:doc_id>/files")
@parent_required
def parent_add_file(doc_id):
    doc = _parent_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    denied = _editable_or_error(doc)
    if denied:
        return denied
    if len(doc.files) >= MAX_FILES_PER_DOC:
        return _error(f"Към документа могат да се добавят най-много {MAX_FILES_PER_DOC} файла.", 409)

    if doc.doc_type == DOC_PHOTO and doc.consent_at is None:
        if request.form.get("consent") not in ("1", "true", "on"):
            return _error("За снимката е нужно съгласие.", 400,
                          {"consent": "Потвърдете, че сте съгласни снимката на детето да се използва за картотекирането."})
        doc.consent_at = utcnow()

    try:
        name, mime, size = save_upload(request.files.get("file"))
    except StorageError as err:
        db.session.rollback()
        return _error(str(err))
    parent = current_parent()
    db.session.add(DocumentFile(document_id=doc.id, name=name, mime=mime, size=size,
                                position=len(doc.files), uploaded_by=parent.display_name[:80]))
    if doc.status in (DOC_UPLOADED,):
        doc.status = DOC_WAITING  # променен след изпращането — трябва да се изпрати отново
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        delete_files([name])
        return _error("Файлът не можа да се запази. Опитайте пак.", 500)
    return jsonify({"ok": True, "document": doc_dict(doc, "/api/parent", _doc_category(doc), can_edit=True)}), 201


def _doc_category(doc):
    return category_for(doc.player, doc.season_end)


@parent_docs_bp.delete("/parent/documents/<int:doc_id>/files/<int:file_id>")
@parent_required
def parent_delete_file(doc_id, file_id):
    doc = _parent_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    denied = _editable_or_error(doc)
    if denied:
        return denied
    file = next((f for f in doc.files if f.id == file_id), None)
    if file is None:
        return _error("Файлът не е намерен.", 404)
    name = file.name
    db.session.delete(file)
    db.session.flush()
    db.session.refresh(doc)
    if doc.status == DOC_UPLOADED:
        doc.status = DOC_WAITING
    db.session.commit()
    delete_files([name])
    return jsonify({"ok": True, "document": doc_dict(doc, "/api/parent", _doc_category(doc), can_edit=True)})


@parent_docs_bp.post("/parent/documents/<int:doc_id>/submit")
@parent_required
def parent_submit(doc_id):
    doc = _parent_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    denied = _editable_or_error(doc)
    if denied:
        return denied
    if not doc.files:
        return _error("Първо качете поне един файл.", 400)
    if doc.doc_type == DOC_PHOTO and doc.consent_at is None:
        return _error("За снимката е нужно съгласие.", 400)
    doc.status = DOC_UPLOADED
    doc.comment = ""
    doc.submitted_at = utcnow()
    db.session.commit()
    return jsonify({"ok": True, "document": doc_dict(doc, "/api/parent", _doc_category(doc), can_edit=True)})


@parent_docs_bp.get("/parent/files/<int:file_id>")
@parent_required
def parent_file(file_id):
    file = db.session.get(DocumentFile, file_id)
    if file is None or _parent_doc(file.document_id) is None:
        return _error("Файлът не е намерен.", 404)
    try:
        return file_response(file.name, file.mime)
    except StorageError as err:
        return _error(str(err), 500)


@parent_docs_bp.get("/parent/documents/<int:doc_id>/template")
@parent_required
def parent_template(doc_id):
    doc = _parent_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    path = template_path(doc.doc_type, _doc_category(doc))
    if path is None:
        return _error("За този документ няма бланка.", 404)
    return send_file(path, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{doc.doc_type}.pdf")


# ------------------------------------------------------------------ админ ---
def _player_or_404(player_id):
    player = db.session.get(Player, player_id)
    return player


@admin_docs_bp.get("/admin/players/<int:player_id>/documents")
def admin_documents(player_id):
    denied = _manager_only()
    if denied:
        return denied
    player = _player_or_404(player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    season_end = get_season_end_year()
    card, payload = _set_payload(player, season_end, "/api/admin", can_edit=False, admin=True)
    db.session.commit()
    present = {d["doc_type"] for d in payload["documents"]}
    payload["available_types"] = [{"code": c, "title": m["title"]} for c, m in DOC_TYPES.items() if c not in present]
    payload["player"] = {"id": player.id, "child_name": player.child_name, "archived": bool(player.archived)}
    return jsonify(payload)


@admin_docs_bp.post("/admin/players/<int:player_id>/documents")
def admin_add_document(player_id):
    denied = _manager_only()
    if denied:
        return denied
    player = _player_or_404(player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    data = request.get_json(silent=True) or {}
    doc_type = data.get("doc_type")
    if doc_type not in DOC_TYPES:
        return _error("Невалиден вид документ.")
    season_end = get_season_end_year()
    card, docs = ensure_set(player, season_end)
    if card.card_received_at:
        return _error("Картотеката е получена. Първо върнете комплекта.", 409)
    if any(d.doc_type == doc_type for d in docs):
        return _error("Този документ вече е в комплекта.", 409)
    db.session.add(PlayerDocument(player_id=player.id, season_end=season_end, doc_type=doc_type))
    db.session.commit()
    return admin_documents(player_id)


def _admin_doc(doc_id):
    return db.session.get(PlayerDocument, doc_id)


@admin_docs_bp.delete("/admin/documents/<int:doc_id>")
def admin_remove_document(doc_id):
    denied = _manager_only()
    if denied:
        return denied
    doc = _admin_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    names = [f.name for f in doc.files]
    player_id = doc.player_id
    db.session.delete(doc)
    db.session.commit()
    delete_files(names)
    return admin_documents(player_id)


@admin_docs_bp.post("/admin/documents/<int:doc_id>/approve")
def admin_approve(doc_id):
    denied = _manager_only()
    if denied:
        return denied
    doc = _admin_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    if doc.status != DOC_UPLOADED:
        return _error("Одобрява се само документ, изпратен за проверка.", 409)
    doc.status = DOC_APPROVED
    doc.comment = ""
    doc.reviewed_at = utcnow()
    doc.reviewed_by = _who()
    db.session.commit()
    return admin_documents(doc.player_id)


@admin_docs_bp.post("/admin/documents/<int:doc_id>/return")
def admin_return(doc_id):
    denied = _manager_only()
    if denied:
        return denied
    doc = _admin_doc(doc_id)
    if doc is None:
        return _error("Документът не е намерен.", 404)
    if doc.status not in (DOC_UPLOADED, DOC_APPROVED):
        return _error("Връща се само изпратен или одобрен документ.", 409)
    comment = (request.get_json(silent=True) or {}).get("comment")
    comment = " ".join(comment.split()) if isinstance(comment, str) else ""
    if not comment:
        return _error("Напишете какво трябва да се поправи.", 400, {"comment": "Напишете какво трябва да се поправи."})
    if len(comment) > MAX_COMMENT:
        return _error(f"Коментарът е до {MAX_COMMENT} символа.", 400, {"comment": f"Най-много {MAX_COMMENT} символа."})
    doc.status = DOC_RETURNED
    doc.comment = comment
    doc.reviewed_at = utcnow()
    doc.reviewed_by = _who()
    db.session.commit()
    return admin_documents(doc.player_id)


@admin_docs_bp.get("/admin/files/<int:file_id>")
def admin_file(file_id):
    denied = _manager_only()
    if denied:
        return denied
    file = db.session.get(DocumentFile, file_id)
    if file is None:
        return _error("Файлът не е намерен.", 404)
    try:
        return file_response(file.name, file.mime)
    except StorageError as err:
        return _error(str(err), 500)


@admin_docs_bp.post("/admin/players/<int:player_id>/card-received")
def admin_card_received(player_id):
    """received=true: картотеката е получена -> файловете се изтриват, документите се архивират.
    received=false: връща комплекта (файловете не се възстановяват; документите пак чакат)."""
    denied = _manager_only()
    if denied:
        return denied
    player = _player_or_404(player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("received"), bool):
        return _error("Невалидна заявка.")
    season_end = get_season_end_year()
    card, docs = ensure_set(player, season_end)
    names = []
    if data["received"]:
        names = purge_files(docs)
        for doc in docs:
            doc.archived = True
        card.card_received_at = utcnow()
        card.card_received_by = _who()
    else:
        for doc in docs:
            doc.archived = False
            doc.status = DOC_WAITING
            doc.comment = ""
        card.card_received_at = None
        card.card_received_by = ""
    db.session.commit()
    delete_files(names)
    return admin_documents(player_id)


@admin_docs_bp.get("/admin/documents/summary")
def admin_documents_summary():
    user = current_user()
    if not (user.is_owner or user.is_head_coach):
        return jsonify({"ok": True, "pending": 0})
    season_end = get_season_end_year()
    pending = (PlayerDocument.query.join(Player, PlayerDocument.player_id == Player.id)
               .filter(PlayerDocument.season_end == season_end, PlayerDocument.status == DOC_UPLOADED,
                       PlayerDocument.archived.is_(False), Player.archived.is_(False)).count())
    return jsonify({"ok": True, "pending": pending})
