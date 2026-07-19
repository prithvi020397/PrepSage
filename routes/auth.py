# Phase 5 refactor — routes (verbatim from app.py).
from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

bp = Blueprint('auth', __name__)

@bp.route("/api/signup", methods=["POST"])
def api_signup():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if not SUPABASE_ENABLED or sb is None:
        data = request.json or {}
        return jsonify({
            "ok": True,
            "user": "legacy-user",
            "access_token": LEGACY_FAKE_TOKEN,
        })
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    c = sb.get_client()
    if not c:
        return jsonify({"error": "supabase client unavailable"}), 500
    try:
        res = c.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        log.exception("api_signup: unhandled exception")
        return jsonify({"error": f"signup failed: {e}"}), 500
    if getattr(res, "error", None):
        return jsonify({"error": str(res.error)}), 400
    # Create profile row directly (GoTrue triggers on auth.users are unreliable).
    # Set the user's session so RLS sees auth.uid() = user id.
    user_id = res.user.id if res.user else None
    session = res.session
    if user_id and session:
        try:
            c.auth.set_session(session.access_token, session.refresh_token)
            display_name = email.split("@")[0]
            c.table("profiles").upsert({
                "id": user_id,
                "email": email,
                "display_name": display_name,
            }).execute()
        except Exception:
            pass
    return jsonify({
        "ok": True,
        "user": user_id,
        "access_token": session.access_token if session else None,
    })



@bp.route("/api/login", methods=["POST"])
def api_login():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if not SUPABASE_ENABLED or sb is None:
        data = request.json or {}
        return jsonify({
            "access_token": LEGACY_FAKE_TOKEN,
            "refresh_token": LEGACY_FAKE_TOKEN,
            "user_id": "legacy-user",
        })
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    c = sb.get_client()
    if not c:
        return jsonify({"error": "supabase client unavailable"}), 500
    try:
        res = c.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        log.exception("api_login: unhandled exception")
        return jsonify({"error": f"login failed: {e}"}), 500
    if getattr(res, "error", None):
        return jsonify({"error": str(res.error)}), 401
    session = res.session
    return jsonify({
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": res.user.id if res.user else None,
    })



@bp.route("/api/test-login", methods=["POST"])
def api_test_login():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Login or signup a test user. If ?fresh=1, wipe progress first."""
    if not SUPABASE_ENABLED or sb is None:
        fresh = request.args.get("fresh") == "1"
        if fresh:
            PROGRESS.clear()
            save_progress()
        return jsonify({
            "access_token": LEGACY_FAKE_TOKEN,
            "refresh_token": LEGACY_FAKE_TOKEN,
            "user_id": "legacy-user",
            "fresh": fresh,
        })
    c = sb.get_client()
    if not c:
        return jsonify({"error": "supabase client unavailable"}), 500
    fresh = request.args.get("fresh") == "1"
    if fresh:
        PROGRESS.clear()
        save_progress()
    # try login first
    session = None
    user_id = None
    try:
        res = c.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
        if getattr(res, "error", None):
            raise Exception(str(res.error))
        session = res.session
        user_id = res.user.id if res.user else None
    except Exception:
        # user doesn't exist — sign up
        try:
            res2 = c.auth.sign_up({"email": TEST_EMAIL, "password": TEST_PASSWORD})
            if getattr(res2, "error", None):
                return jsonify({"error": str(res2.error)}), 400
            session = res2.session
            user_id = res2.user.id if res2.user else None
            if user_id and session:
                try:
                    c.auth.set_session(session.access_token, session.refresh_token)
                    c.table("profiles").upsert({
                        "id": user_id, "email": TEST_EMAIL, "display_name": "Test User",
                    }).execute()
                except Exception:
                    pass
        except Exception as e:
            log.exception("api_test_login: unhandled exception")
            return jsonify({"error": f"test signup failed: {e}"}), 500
    if not session:
        return jsonify({"error": "could not authenticate"}), 500
    return jsonify({
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": user_id,
        "fresh": fresh,
    })



@bp.route("/api/me", methods=["GET"])
def api_me():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if not SUPABASE_ENABLED or sb is None:
        return jsonify({"user_id": None, "mode": "legacy"})
    uid = current_user_id()
    if not uid:
        return jsonify({"user_id": None, "mode": "anonymous"}), 401
    return jsonify({"user_id": uid, "mode": "supabase"})


# ponytail: reset wipes the *working state* of a question (saved code, trace, pattern,
# skeleton, concept map) but preserves the earned credit (solved_at / due_at / fails) so a
# redo doesn't also erase spaced-repetition progress. This is the "clean slate to retry the
# code" action, not an "I never solved this" action.

@bp.route("/api/reset-question/<qid>", methods=["POST"])
def reset_question(qid):
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if qid not in QUESTIONS:
        return jsonify({"error": "not found"}), 404
    _reset_entry(qid)
    save_progress()
    return jsonify({"ok": True})



@bp.route("/api/reset-category/<lang>", methods=["POST"])
def reset_category(lang):
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if lang not in ("sql", "python", "design", "tradeoff"):
        return jsonify({"error": "unknown lang"}), 404
    for qid, q in QUESTIONS.items():
        if q["lang"] == lang:
            _reset_entry(qid)
    save_progress()
    return jsonify({"ok": True, "lang": lang})



@bp.route("/api/start-over", methods=["POST"])
def start_over():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    # ponytail: full clean slate — wipes every persistence file so the dashboard reads 0/N
    # with no streaks, due reviews, saved code, chat history, or replay comments. Distinct
    # from /api/reset-category which only clears working state and keeps solved credit.
    import glob
    for f in (PROGRESS_FILE, HISTORY_FILE, CHATS_FILE, REPLAY_COMMENTS_FILE, JUDGES_FILE):
        if os.path.exists(f):
            os.remove(f)
    return jsonify({"ok": True})




