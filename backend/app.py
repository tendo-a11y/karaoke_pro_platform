import logging
import os
import secrets

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import Config
from extensions import db, migrate, socketio


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    # models импортируется до migrate.init_app, иначе Alembic не увидит
    # таблицы при автогенерации новых миграций (flask db migrate).
    import models  # noqa: F401
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins=app.config.get("CORS_ORIGINS", "*"))
    # expose_headers: Content-Disposition нужен фронтенду admin-app, чтобы
    # прочитать имя файла через fetch() при скачивании бэкапа БД (Block #4,
    # GET /api/admin/system/backup) — без этого браузер по умолчанию не
    # отдаёт JS доступ к этому заголовку даже при успешном CORS-запросе,
    # и фронтенду не из чего взять реальное имя файла с таймстампом.
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}},
        expose_headers=["Content-Disposition"],
    )

    # sockets.py регистрирует @socketio.on(...) обработчики через side-effect импорта
    import sockets  # noqa: F401

    from routes.admin import bp as admin_bp
    from routes.client import bp as client_bp
    from routes.guest import bp as guest_bp
    from routes.kj import bp as kj_bp
    from routes.vdj import bp as vdj_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(guest_bp)
    app.register_blueprint(kj_bp)
    app.register_blueprint(vdj_bp)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Разовый служебный адрес для подключения настоящего VirtualDJ через
    # мост (vdj_bridge/agent.py, см. её докстринг и backend/manage.py::
    # cmd_set_bridge_token) — обычно этот код выдаёт `manage.py
    # set-bridge-token`, но прямого доступа к консоли Backend в проде нет,
    # поэтому здесь то же самое действие доступно по HTTP, под отдельным
    # секретом BRIDGE_SETUP_TOKEN (переменная окружения, задаётся только в
    # Railway, никогда не в коде). Секрет передаётся заголовком, а не
    # параметром адреса — секреты в URL (query string) остаются в логах
    # прокси/браузера, заголовок — нет. Без верного заголовка X-Setup-Token
    # ничего не отдаёт и не создаёт. Можно оставить в проекте — без заданной
    # переменной окружения BRIDGE_SETUP_TOKEN маршрут всегда отвечает 403.
    @app.post("/internal/bridge-setup")
    def bridge_setup():
        from models import Club

        setup_token = os.environ.get("BRIDGE_SETUP_TOKEN")
        if not setup_token or request.headers.get("X-Setup-Token") != setup_token:
            return jsonify({"error": "forbidden"}), 403

        payload = request.get_json(silent=True) or {}
        club_id = payload.get("club_id")
        if not isinstance(club_id, int):
            return jsonify({"error": "club_id обязателен"}), 400

        club = db.session.get(Club, club_id)
        if club is None:
            return jsonify({"error": "club не найден"}), 404

        if not club.bridge_token:
            club.bridge_token = secrets.token_urlsafe(32)
            db.session.commit()

        return jsonify({"club_id": club.club_id, "bridge_token": club.bridge_token})

    return app
