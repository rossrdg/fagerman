from datetime import datetime, timezone

from urllib.parse import quote

from flask import Blueprint, current_app, jsonify, render_template, request

from app import db
from app.models import Post
from app.news_utils import extract_youtube_id, make_excerpt, sanitize_html, slugify

# Public: only published articles. Used by the homepage "Новини" section.
news_bp = Blueprint("news", __name__)
# Admin: drafts included, create / edit / delete. Everything lives under
# /api/admin/ so a single login check can protect it later (no auth yet,
# same as the registrations admin — must be added before production).
admin_news_bp = Blueprint("admin_news", __name__)

# Public HTML page of one article (not under /api): /news/<slug>
page_bp = Blueprint("news_page", __name__)

STATUSES = ("draft", "published")
MONTHS_BG = ["януари", "февруари", "март", "април", "май", "юни", "юли",
             "август", "септември", "октомври", "ноември", "декември"]
DEFAULT_SHARE_IMAGE = "/assets/fa-german-fb-cover.jpg"
MAX_BODY = 100_000


# ---------------------------------------------------------------- public ---
@news_bp.get("/news")
def list_news():
    try:
        limit = max(1, min(int(request.args.get("limit", 12)), 50))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"ok": False, "error": "Невалидни параметри."}), 400

    posts = (
        Post.query.filter_by(status="published")
        .order_by(Post.published_at.desc(), Post.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return jsonify({"ok": True, "posts": [p.to_dict() for p in posts]})


@news_bp.get("/news/<slug>")
def get_news(slug):
    post = Post.query.filter_by(slug=slug, status="published").first()
    if post is None:
        return jsonify({"ok": False, "error": "Статията не е намерена."}), 404
    return jsonify({"ok": True, "post": post.to_dict(full=True)})


# ------------------------------------------------------------ HTML page ---
def _absolute(path):
    """Facebook needs absolute URLs. SITE_URL (e.g. https://fa-german.eu) is
    set in production; locally the current host is used."""
    base = (current_app.config.get("SITE_URL") or request.url_root).rstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return base + path


@page_bp.get("/news/<slug>")
def news_page(slug):
    post = Post.query.filter_by(slug=slug, status="published").first()
    if post is None:
        return render_template("news_post.html", post=None), 404

    page_url = _absolute(f"/news/{post.slug}")
    date_bg = None
    if post.published_at:
        d = post.published_at
        date_bg = f"{d.day} {MONTHS_BG[d.month - 1]} {d.year} г."

    return render_template(
        "news_post.html",
        post=post,
        page_url=page_url,
        share_url="https://www.facebook.com/sharer/sharer.php?u=" + quote(page_url, safe=""),
        image_url=_absolute(post.cover_image or DEFAULT_SHARE_IMAGE),
        description=post.excerpt or make_excerpt(post.body),
        date_bg=date_bg,
    )


# ----------------------------------------------------------------- admin ---
def _unique_slug(title):
    base = slugify(title) or "novina"
    slug, n = base, 2
    while Post.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _apply(post, data, creating):
    """Validates the JSON payload and copies it onto the post.
    Returns a dict with field errors (empty = ok)."""
    errors = {}

    def text(field, max_len, required=False, label=""):
        if field not in data:
            if creating and required:
                errors[field] = f"Моля, въведете {label}."
            return None
        value = data[field]
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors[field] = "Невалидна стойност."
            return None
        value = value.strip()
        if required and not value:
            errors[field] = f"Моля, въведете {label}."
        elif len(value) > max_len:
            errors[field] = f"Максимум {max_len} символа."
        return value

    title = text("title", 200, required=True, label="заглавие")
    excerpt = text("excerpt", 300)
    category = text("category", 40)
    cover = text("cover_image", 255)

    if title is not None and "title" not in errors:
        post.title = title
    if excerpt is not None and "excerpt" not in errors:
        post.excerpt = excerpt
    if category is not None and "category" not in errors:
        post.category = category or None

    if cover is not None and "cover_image" not in errors:
        if cover and not (cover.startswith("/uploads/") or cover.startswith("https://")):
            errors["cover_image"] = "Невалиден адрес на снимката."
        else:
            post.cover_image = cover or None

    if "body" in data:
        body = data["body"]
        if body is not None and not isinstance(body, str):
            errors["body"] = "Невалидна стойност."
        elif body and len(body) > MAX_BODY:
            errors["body"] = "Текстът е твърде дълъг."
        else:
            post.body = sanitize_html(body)
    elif creating:
        post.body = ""

    if "youtube_url" in data:
        url = data["youtube_url"]
        if url in (None, ""):
            post.youtube_id = None
        elif not isinstance(url, str) or not (yt := extract_youtube_id(url)):
            errors["youtube_url"] = "Невалиден YouTube линк."
        else:
            post.youtube_id = yt

    if "status" in data:
        if data["status"] not in STATUSES:
            errors["status"] = "Невалиден статус."
        else:
            post.status = data["status"]
    elif creating:
        post.status = "draft"

    if post.status == "published":
        if not (post.title or "").strip():
            errors["title"] = "Моля, въведете заглавие."
        if post.published_at is None:
            post.published_at = datetime.now(timezone.utc)

    return errors


@admin_news_bp.get("/admin/news")
def admin_list():
    posts = Post.query.order_by(Post.created_at.desc(), Post.id.desc()).all()
    return jsonify({"ok": True, "posts": [p.to_dict(admin=True) for p in posts]})


@admin_news_bp.get("/admin/news/<int:post_id>")
def admin_get(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({"ok": False, "error": "Статията не е намерена."}), 404
    return jsonify({"ok": True, "post": post.to_dict(admin=True)})


@admin_news_bp.post("/admin/news")
def admin_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Невалидна заявка."}), 400

    post = Post()
    errors = _apply(post, data, creating=True)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    post.slug = _unique_slug(post.title)
    db.session.add(post)
    db.session.commit()
    return jsonify({"ok": True, "post": post.to_dict(admin=True)}), 201


@admin_news_bp.patch("/admin/news/<int:post_id>")
def admin_update(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({"ok": False, "error": "Статията не е намерена."}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Невалидна заявка."}), 400

    errors = _apply(post, data, creating=False)
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400

    db.session.commit()
    return jsonify({"ok": True, "post": post.to_dict(admin=True)})


@admin_news_bp.delete("/admin/news/<int:post_id>")
def admin_delete(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({"ok": False, "error": "Статията не е намерена."}), 404
    db.session.delete(post)
    db.session.commit()
    return jsonify({"ok": True})
