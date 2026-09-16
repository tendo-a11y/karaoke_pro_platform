"""
Тесты живого статуса моста VirtualDJ (запрос пользователя 2026-09:
"переключатель" для контроля из KJ Panel) — vdj/bridge_status.py,
sockets.py::handle_bridge_connect/handle_bridge_disconnect и
GET /api/kj/bridge/status/<club_id>.

Подключение самого моста эмулируется через flask_socketio.test_client на
namespace "/bridge" — тот же протокол, что использует настоящая программа
vdj_bridge/vdj_bridge_app.py (auth={"club_id":..., "bridge_token":...}).
"""
from extensions import socketio


def _kj_headers(kj):
    return {"Authorization": f"Bearer {kj['token']}"}


def _connect_bridge(app, client, club_id, token):
    return socketio.test_client(app, namespace="/bridge", flask_test_client=client, auth={
        "club_id": club_id, "bridge_token": token,
    })


def test_status_false_when_no_bridge_connected(client, db, club, kj):
    resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["connected"] is False
    assert data["connected_since"] is None


def test_status_requires_auth(client, db, club):
    resp = client.get(f"/api/kj/bridge/status/{club.club_id}")
    assert resp.status_code == 401


def test_status_cannot_read_other_clubs_bridge(client, db, club, other_club, kj):
    resp = client.get(f"/api/kj/bridge/status/{other_club.club_id}", headers=_kj_headers(kj))
    assert resp.status_code == 403


def test_bridge_connect_marks_status_true(app, client, db, club, kj):
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-token")
    try:
        assert bridge.is_connected(namespace="/bridge")
        resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        data = resp.get_json()["data"]
        assert data["connected"] is True
        assert data["connected_since"] is not None
    finally:
        bridge.disconnect(namespace="/bridge")


def test_bridge_disconnect_marks_status_false(app, client, db, club, kj):
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-token")
    bridge.disconnect(namespace="/bridge")

    resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
    assert resp.get_json()["data"]["connected"] is False


def test_bridge_connect_rejected_with_wrong_token_does_not_mark_connected(app, client, db, club, kj):
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "wrong-token")
    try:
        assert not bridge.is_connected(namespace="/bridge")
        resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        assert resp.get_json()["data"]["connected"] is False
    finally:
        if bridge.is_connected(namespace="/bridge"):
            bridge.disconnect(namespace="/bridge")


def test_bridge_status_isolated_per_club(app, client, db, club, other_club, kj):
    """Мост клуба A подключился — у клуба B статус не должен подмениться."""
    club.bridge_token = "secret-a"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-a")
    try:
        resp_a = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        assert resp_a.get_json()["data"]["connected"] is True

        # other_kj не заведён в этом тесте — читаем напрямую через сервис,
        # чтобы не плодить лишнюю фикстуру ради одной проверки изоляции.
        from vdj import bridge_status
        assert bridge_status.is_connected(other_club.club_id) is False
    finally:
        bridge.disconnect(namespace="/bridge")
