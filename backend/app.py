import logging

from flask import Flask
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

    return app
