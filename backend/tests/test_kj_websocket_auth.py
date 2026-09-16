"""
Тест живого Socket.IO-подключения KJ Panel (sockets.py::handle_connect,
дефолтный namespace — не путать с /bridge, см. test_bridge_status.py).

Найдено пользователем вживую: после входа через Google KJ Panel навсегда
показывала "○ переподключение…" — REST-запросы (require_kj) работали
нормально, а вот здесь identity="google" не проверялся вовсе, sub всегда
трактовался как telegram_user_id, и int(google_sub) падал на нечисловой
строке. Раз баг был замечен только на живом сокете, а не в тестах —
здесь он теперь закрыт явной проверкой.
"""
from auth import issue_kj_google_token
from extensions import socketio


def _connect(app, client, token):
    return socketio.test_client(app, flask_test_client=client, auth={"token": token})


def test_connect_accepted_for_telegram_token(app, client, db, kj):
    ws = _connect(app, client, kj["token"])
    try:
        assert ws.is_connected()
    finally:
        ws.disconnect()


def test_connect_accepted_for_google_token(app, client, db, club, kj):
    """Именно этот сценарий был сломан до фикса — google_sub как sub."""
    kj["operator"].google_sub = "google-sub-live-bridge"
    db.session.commit()
    token = issue_kj_google_token(
        "google-sub-live-bridge", app.config["KJ_JWT_SECRET"], 3600,
    )

    ws = _connect(app, client, token)
    try:
        assert ws.is_connected()
    finally:
        ws.disconnect()


def test_connect_rejected_without_token(app, client, db):
    ws = socketio.test_client(app, flask_test_client=client, auth={})
    assert not ws.is_connected()


def test_connect_rejected_for_unknown_google_sub(app, client, db):
    token = issue_kj_google_token("nobody-sub", app.config["KJ_JWT_SECRET"], 3600)
    ws = _connect(app, client, token)
    assert not ws.is_connected()


def test_connect_rejected_for_inactive_kj(app, client, db, kj):
    kj["operator"].is_active = False
    db.session.commit()

    ws = _connect(app, client, kj["token"])
    assert not ws.is_connected()
