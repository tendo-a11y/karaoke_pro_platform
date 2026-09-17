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
    assert data["vdj_reachable"] is None


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
        # Мост только что подключился — ещё не успел ни разу отчитаться о
        # VirtualDJ (см. mark_connected в vdj/bridge_status.py).
        assert data["vdj_reachable"] is None
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


# --- Третий индикатор панели обзора KJ: "Мост↔VirtualDJ" (запрос
# пользователя 2026-09-17) — мост сам отчитывается событием
# "bridge_vdj_status", видит ли он сейчас VirtualDJ на своём компьютере.

def test_bridge_vdj_status_true_after_report(app, client, db, club, kj):
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-token")
    try:
        bridge.emit("bridge_vdj_status", {"reachable": True}, namespace="/bridge")
        resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        assert resp.get_json()["data"]["vdj_reachable"] is True
    finally:
        bridge.disconnect(namespace="/bridge")


def test_bridge_vdj_status_false_after_report(app, client, db, club, kj):
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-token")
    try:
        bridge.emit("bridge_vdj_status", {"reachable": False}, namespace="/bridge")
        resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        assert resp.get_json()["data"]["vdj_reachable"] is False
    finally:
        bridge.disconnect(namespace="/bridge")


def test_bridge_reconnect_resets_vdj_reachable_to_none(app, client, db, club, kj):
    """Новое подключение моста (например, после перезапуска программы) не
    должно унаследовать старый статус VirtualDJ — пока новый мост ещё сам
    не проверил, мы не знаем, жива ли VirtualDJ прямо сейчас."""
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-token")
    bridge.emit("bridge_vdj_status", {"reachable": True}, namespace="/bridge")
    bridge.disconnect(namespace="/bridge")

    bridge2 = _connect_bridge(app, client, club.club_id, "secret-token")
    try:
        resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        assert resp.get_json()["data"]["vdj_reachable"] is None
    finally:
        bridge2.disconnect(namespace="/bridge")


def test_bridge_vdj_status_ignored_with_malformed_payload(app, client, db, club, kj):
    """Мусорный payload (не bool/не dict) не должен падать и не должен
    менять уже известный статус."""
    club.bridge_token = "secret-token"
    db.session.commit()

    bridge = _connect_bridge(app, client, club.club_id, "secret-token")
    try:
        bridge.emit("bridge_vdj_status", {"reachable": True}, namespace="/bridge")
        bridge.emit("bridge_vdj_status", {"reachable": "yes"}, namespace="/bridge")
        bridge.emit("bridge_vdj_status", "not-a-dict", namespace="/bridge")

        resp = client.get(f"/api/kj/bridge/status/{club.club_id}", headers=_kj_headers(kj))
        assert resp.get_json()["data"]["vdj_reachable"] is True
    finally:
        bridge.disconnect(namespace="/bridge")
