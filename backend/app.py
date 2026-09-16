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

    # 2026-09-16 (найденная причина "мост не подключается" / KJ Panel
    # принимала подключения без проверки токена — см. новые
    # backend/tests/test_kj_websocket_auth.py::test_connect_rejected_without_token
    # и test_bridge_status.py::test_bridge_connect_marks_status_true, которые
    # падали на этом самом коде): sockets.py сам по себе больше не
    # регистрирует обработчики через side-effect импорта — все @socketio.on(...)
    # переехали внутрь sockets.register_handlers() (см. её докстринг про то,
    # почему — баг с повторными create_app() в тестах), но эта явная функция
    # никогда не была здесь вызвана. В проде это означало: "/bridge" namespace
    # вообще не существовал для python-socketio (мост получал "One or more
    # namespaces failed to connect"), а дефолтный namespace KJ Panel принимал
    # вообще любое подключение без проверки JWT, потому что handle_connect,
    # который мог бы отклонить его, тоже никогда не регистрировался.
    import sockets
    sockets.register_handlers()

    # 2026-09-16 (вторая, независимая причина обрывов у моста и KJ Panel —
    # видна в логах Railway отдельно от бага выше, повторяется каждые
    # ~80-140с: "Error handling request /socket.io/?...&sid=..." +
    # "KeyError: 'Session is disconnected'"): python-engineio 4.14.0 (см.
    # engineio/base_server.py::_get_socket и engineio/server.py::
    # handle_request) кидает необработанный KeyError('Session is
    # disconnected'), когда POST-запрос приходит на сессию, которая уже
    # помечена закрытой (socket.closed=True), но ещё не удалена из
    # self.sockets — обычная гонка потоков под gunicorn --worker-class
    # gthread с несколькими потоками на воркер. У GET-пути в той же функции
    # есть "except KeyError as e: ... r = self._bad_request", а у POST-пути
    # — нет: там "socket = self._get_socket(sid)" вызывается ДО try/except,
    # поэтому исключение улетает наверх необработанным, gunicorn ловит его
    # сам и отвечает клиенту голым 500. Для python-socketio.Client (мост на
    # компьютере KJ) такой 500 внутри активного long-polling цикла
    # выглядит как обрыв связи. Это баг самой библиотеки (асимметрия
    # GET/POST в handle_request), а не нашего кода — чинить его здесь, на
    # уровне WSGI, проще и безопаснее, чем патчить сторонний пакет:
    # превращаем тот же случай в тот же чистый "400", что GET-путь и так
    # уже делает для идентичной ситуации. Проверено локально (см. описание
    # в PR/сопроводительном сообщении): без этой обёртки повторение гонки
    # (сокет в self.sockets, но closed=True) роняет запрос необработанным
    # KeyError; с обёрткой — чистый 400, обычное подключение и разговор
    # моста по-прежнему проходят без изменений.
    _socketio_wsgi_app = app.wsgi_app

    def _session_race_guard(environ, start_response):
        try:
            return _socketio_wsgi_app(environ, start_response)
        except KeyError as exc:
            if str(exc) != "'Session is disconnected'":
                raise
            logging.getLogger(__name__).info(
                "Engine.IO: POST на уже закрытую сессию (гонка потоков) — "
                "отвечаю 400 вместо необработанного 500 (%s)",
                environ.get("QUERY_STRING", ""),
            )
            body = b"Session is disconnected"
            start_response(
                "400 BAD REQUEST",
                [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))],
            )
            return [body]

    app.wsgi_app = _session_race_guard

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
