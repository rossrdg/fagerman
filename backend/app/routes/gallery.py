"""Галерия на отбор: албуми със снимки + YouTube клипове.

Публично:  GET /teams/<slug>/albums/<id>        страница на албум (без индексиране)
Админ:     GET    /api/admin/teams/<id>/gallery            албуми + клипове на отбора
           POST   /api/admin/teams/<id>/albums             нов албум
           GET    /api/admin/albums/<id>                   албум със снимките му
           PATCH  /api/admin/albums/<id>                   заглавие, дата, скрит, корица
           DELETE /api/admin/albums/<id>                   изтрива албума и файловете
           POST   /api/admin/albums/<id>/photos            качва ЕДНА снимка (multipart "image")
           DELETE /api/admin/photos/<id>                   изтрива снимка и файловете й
           POST   /api/admin/teams/<id>/videos             добавя YouTube линк
           DELETE /api/admin/videos/<id>
"""
import os
import uuid
from datetime import date

from flask import Blueprint, current_app, jsonify, render_template, request
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.auth import check_admin, current_user
from app.gallery_utils import album_cover, bg_date, new_code, parse_youtube, photo_urls, remove_files
from app.models import TEAM_ACTIVE, Album, Photo, Team, Video
# Същата обработка като при снимките на новините (завъртане, JPEG, 1600px + 800px).
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app.routes.uploads import (
    MAIN_SIZE, MAX_PIXELS, READABLE_FORMATS, THUMB_SIZE, UNSUPPORTED_MESSAGE, _save_jpeg, _to_rgb,
)
from app.team_utils import get_season_end_year, u_label

page_bp = Blueprint("gallery_page", __name__)
admin_gallery_bp = Blueprint("admin_gallery", __name__)
admin_gallery_bp.before_request(check_admin)  # собственик или треньор

MAX_TITLE = 80
MAX_PHOTOS_PER_ALBUM = 28
MIN_YEAR = 2020


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _who():
    user = current_user()
    return (user.display_name or user.username)[:80] if user else ""


def _parse_date(value):
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.year >= MIN_YEAR else None


def photo_dict(photo, album):
    main, thumb = photo_urls(photo)
    return {
        "id": photo.id, "code": photo.code, "url": main, "thumb": thumb,
        "uploaded_by": photo.uploaded_by,
        "uploaded_at": photo.created_at.isoformat() if photo.created_at else None,
        "is_cover": album_cover(album) is not None and album_cover(album).id == photo.id,
    }


def album_dict(album, with_photos=False):
    cover = album_cover(album)
    data = {
        "id": album.id, "team_id": album.team_id, "title": album.title,
        "event_date": album.event_date.isoformat(), "date_text": bg_date(album.event_date),
        "is_hidden": album.is_hidden, "photo_count": len(album.photos), "max_photos": MAX_PHOTOS_PER_ALBUM,
        "cover_thumb": photo_urls(cover)[1] if cover else None,
    }
    if with_photos:
        data["photos"] = [photo_dict(p, album) for p in album.photos]
    return data


def video_dict(video):
    return {
        "id": video.id, "youtube_id": video.youtube_id, "title": video.title,
        "url": f"https://www.youtube.com/watch?v={video.youtube_id}",
        "added_by": video.added_by,
    }


# ----------------------------------------------------------- public page ---
@page_bp.get("/teams/<slug>/albums/<int:album_id>")
def album_page(slug, album_id):
    team = Team.query.filter_by(slug=slug, status=TEAM_ACTIVE).first()
    album = db.session.get(Album, album_id) if team else None
    if team is None or album is None or album.team_id != team.id or album.is_hidden or not album.photos:
        return render_template("album_page.html", album=None), 404

    season_end = get_season_end_year()
    label = u_label(team, season_end)
    photos = [{"url": photo_urls(p)[0], "thumb": photo_urls(p)[1], "code": p.code} for p in album.photos]
    return render_template(
        "album_page.html",
        album={"title": album.title, "date_text": bg_date(album.event_date), "photos": photos},
        team={"slug": team.slug, "u_label": label},
        page_url=_absolute(f"/teams/{team.slug}/albums/{album.id}"),
        image_url=_absolute(DEFAULT_SHARE_IMAGE),
    )


# ----------------------------------------------------------------- admin ---
@admin_gallery_bp.get("/admin/teams/<int:team_id>/gallery")
def admin_gallery(team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        return _error("Отборът не е намерен.", 404)
    albums = (Album.query.filter_by(team_id=team.id).order_by(Album.event_date.desc(), Album.id.desc()).all())
    videos = Video.query.filter_by(team_id=team.id).order_by(Video.id.desc()).all()
    return jsonify({"ok": True, "albums": [album_dict(a) for a in albums], "videos": [video_dict(v) for v in videos]})


@admin_gallery_bp.post("/admin/teams/<int:team_id>/albums")
def admin_create_album(team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        return _error("Отборът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    title = data.get("title")
    title = title.strip() if isinstance(title, str) else ""
    errors = {}
    if not title:
        errors["title"] = "Въведете заглавие на албума."
    elif len(title) > MAX_TITLE:
        errors["title"] = f"Максимум {MAX_TITLE} символа."
    event_date = _parse_date(data.get("event_date")) if data.get("event_date") else date.today()
    if event_date is None:
        errors["event_date"] = "Невалидна дата."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    album = Album(team_id=team.id, title=title, event_date=event_date)
    db.session.add(album)
    db.session.commit()
    return jsonify({"ok": True, "album": album_dict(album, with_photos=True)}), 201


@admin_gallery_bp.get("/admin/albums/<int:album_id>")
def admin_get_album(album_id):
    album = db.session.get(Album, album_id)
    if album is None:
        return _error("Албумът не е намерен.", 404)
    return jsonify({"ok": True, "album": album_dict(album, with_photos=True)})


@admin_gallery_bp.patch("/admin/albums/<int:album_id>")
def admin_update_album(album_id):
    album = db.session.get(Album, album_id)
    if album is None:
        return _error("Албумът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    errors = {}
    if "title" in data:
        title = data["title"].strip() if isinstance(data["title"], str) else ""
        if not title:
            errors["title"] = "Въведете заглавие на албума."
        elif len(title) > MAX_TITLE:
            errors["title"] = f"Максимум {MAX_TITLE} символа."
        else:
            album.title = title
    if "event_date" in data:
        parsed = _parse_date(data["event_date"])
        if parsed is None:
            errors["event_date"] = "Невалидна дата."
        else:
            album.event_date = parsed
    if "is_hidden" in data:
        if not isinstance(data["is_hidden"], bool):
            errors["is_hidden"] = "Невалидна стойност."
        else:
            album.is_hidden = data["is_hidden"]
    if "cover_photo_id" in data:
        wanted = data["cover_photo_id"]
        if wanted is None:
            album.cover_photo_id = None
        elif isinstance(wanted, int) and any(p.id == wanted for p in album.photos):
            album.cover_photo_id = wanted
        else:
            errors["cover_photo_id"] = "Снимката не е от този албум."
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    db.session.commit()
    return jsonify({"ok": True, "album": album_dict(album, with_photos=True)})


@admin_gallery_bp.delete("/admin/albums/<int:album_id>")
def admin_delete_album(album_id):
    album = db.session.get(Album, album_id)
    if album is None:
        return _error("Албумът не е намерен.", 404)
    names = [p.name for p in album.photos]
    db.session.delete(album)
    db.session.commit()
    remove_files(names)  # файловете се трият чак след успешния запис в базата
    return jsonify({"ok": True})


@admin_gallery_bp.post("/admin/albums/<int:album_id>/photos")
def admin_add_photo(album_id):
    album = db.session.get(Album, album_id)
    if album is None:
        return _error("Албумът не е намерен.", 404)
    if len(album.photos) >= MAX_PHOTOS_PER_ALBUM:
        return _error(f"Албумът е пълен — максимум {MAX_PHOTOS_PER_ALBUM} снимки. Създайте нов албум.", 409)
    file = request.files.get("image")
    if file is None or not file.filename:
        return _error("Не е избран файл.")

    try:
        img = Image.open(file.stream, formats=READABLE_FORMATS)
        if img.width * img.height > MAX_PIXELS:
            return _error("Снимката е с твърде голяма резолюция.")
        img.load()
        rgb = _to_rgb(img)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return _error(UNSUPPORTED_MESSAGE)

    code = new_code()
    if code is None:
        return _error("Дневният лимит от 1000 снимки е достигнат. Опитайте утре.", 429)

    folder = current_app.config["UPLOAD_DIR"]
    os.makedirs(folder, exist_ok=True)
    name = uuid.uuid4().hex[:20]
    _save_jpeg(rgb, os.path.join(folder, f"{name}.jpg"), MAIN_SIZE)
    _save_jpeg(rgb, os.path.join(folder, f"{name}-800.jpg"), THUMB_SIZE)

    photo = Photo(album_id=album.id, name=name, code=code, uploaded_by=_who())
    db.session.add(photo)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        remove_files([name])
        return _error("Снимката не можа да се запази. Опитайте пак.", 500)
    return jsonify({"ok": True, "photo": photo_dict(photo, album)}), 201


@admin_gallery_bp.delete("/admin/photos/<int:photo_id>")
def admin_delete_photo(photo_id):
    photo = db.session.get(Photo, photo_id)
    if photo is None:
        return _error("Снимката не е намерена.", 404)
    album, name = photo.album, photo.name
    if album.cover_photo_id == photo.id:
        album.cover_photo_id = None
    db.session.delete(photo)
    db.session.commit()
    remove_files([name])
    return jsonify({"ok": True})


@admin_gallery_bp.post("/admin/teams/<int:team_id>/videos")
def admin_add_video(team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        return _error("Отборът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    youtube_id = parse_youtube(data.get("url"))
    title = data.get("title", "")
    title = title.strip() if isinstance(title, str) else ""
    errors = {}
    if youtube_id is None:
        errors["url"] = "Невалиден YouTube линк. Пример: https://www.youtube.com/watch?v=…"
    if len(title) > MAX_TITLE:
        errors["title"] = f"Максимум {MAX_TITLE} символа."
    if not errors and Video.query.filter_by(team_id=team.id, youtube_id=youtube_id).first():
        errors["url"] = "Този клип вече е добавен."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    video = Video(team_id=team.id, youtube_id=youtube_id, title=title, added_by=_who())
    db.session.add(video)
    db.session.commit()
    return jsonify({"ok": True, "video": video_dict(video)}), 201


@admin_gallery_bp.delete("/admin/videos/<int:video_id>")
def admin_delete_video(video_id):
    video = db.session.get(Video, video_id)
    if video is None:
        return _error("Клипът не е намерен.", 404)
    db.session.delete(video)
    db.session.commit()
    return jsonify({"ok": True})


# --------------------------------------------------- общата галерия (/gallery) ---
ALBUMS_PER_PAGE = 24


@page_bp.get("/gallery")
@page_bp.get("/gallery/")
def gallery_index():
    """Всички видими албуми на всички активни отбори — най-новите събития първи."""
    season_end = get_season_end_year()
    query = (
        Album.query.join(Team, Album.team_id == Team.id)
        .filter(Team.status == TEAM_ACTIVE, Album.is_hidden.is_(False), Album.photos.any())
        .order_by(Album.event_date.desc(), Album.id.desc())
    )
    total = query.count()
    pages = max(1, -(-total // ALBUMS_PER_PAGE))
    page = min(max(request.args.get("page", 1, type=int), 1), pages)
    albums = (
        query.options(selectinload(Album.photos), joinedload(Album.team))
        .offset((page - 1) * ALBUMS_PER_PAGE).limit(ALBUMS_PER_PAGE).all()
    )

    cards = []
    for album in albums:
        cover = album_cover(album)
        cards.append({
            "title": album.title,
            "team_label": u_label(album.team, season_end),
            "date_text": bg_date(album.event_date),
            "count": len(album.photos),
            "cover": photo_urls(cover)[1],
            "url": f"/teams/{album.team.slug}/albums/{album.id}",
        })
    return render_template(
        "gallery_page.html",
        albums=cards, page=page, pages=pages,
        page_url=_absolute("/gallery" if page == 1 else f"/gallery?page={page}"),
        image_url=_absolute(DEFAULT_SHARE_IMAGE),
    )
