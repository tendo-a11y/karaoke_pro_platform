"""
Мост между централизованным Backend (обычно в облаке/на своём сервере) и
VirtualDJ, который физически стоит на компьютере KJ в клубе.

Зачем этот файл вообще нужен — см. подробное объяснение в
backend/vdj/bridge_client.py: Backend не может сам "достучаться" в
локальную сеть клуба (нет статического IP, NAT/файрвол), поэтому эта
маленькая программа запускается на том же компьютере, что и VirtualDJ, и
САМА открывает соединение НАРУЖУ, к Backend. Портов открывать/пробрасывать
на роутере клуба не требуется — исходящие соединения почти всегда
разрешены.

Запуск:
    export BRIDGE_BACKEND_URL=https://your-backend.example.com
    export BRIDGE_CLUB_ID=1
    export BRIDGE_TOKEN=<значение из `python3 manage.py set-bridge-token --club-id 1`>
    python3 agent.py

Про VirtualDJ: по умолчанию используется MockVDJDriver (driver.py) — он
держит очередь только в памяти самого моста и не трогает реальный
VirtualDJ. Это осознанно: реальный протокол управления VirtualDJ —
отдельный открытый вопрос ТЗ п.16, для ответа на который нужен доступ к
реально установленной программе на месте. Когда протокол определён —
меняется только driver.py и переменная DRIVER ниже, остальной код этого
файла (подключение, реестр команд, обработка ошибок) менять не нужно.
"""
import logging
import os
import sys

import socketio

from driver import MockVDJDriver, NetworkControlVDJDriver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [vdj_bridge] %(levelname)s %(message)s")
logger = logging.getLogger("vdj_bridge")

BACKEND_URL = os.environ.get("BRIDGE_BACKEND_URL", "http://localhost:5000")
CLUB_ID = os.environ.get("BRIDGE_CLUB_ID")
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN")

# Точка расширения: протокол VirtualDJ Network Control Plugin проверен на
# практике этапом 6 (см. PHASE6_VDJ_NETWORK_CONTROL.md), но не полностью —
# reorder/remove/полный листинг очереди ещё не подтверждены, поэтому
# NetworkControlVDJDriver НЕ включён по умолчанию. Явно включается через
# BRIDGE_VDJ_DRIVER=network_control на компьютере KJ, где реально стоит
# VirtualDJ; VIRTUALDJ_NETWORK_CONTROL_URL меняет адрес плагина, если он не
# на стандартных 127.0.0.1:80.
_driver_choice = os.environ.get("BRIDGE_VDJ_DRIVER", "mock")
if _driver_choice == "network_control":
    DRIVER = NetworkControlVDJDriver(
        base_url=os.environ.get("VIRTUALDJ_NETWORK_CONTROL_URL", "http://127.0.0.1:80")
    )
    logger.info("Драйвер VirtualDJ: NetworkControlVDJDriver (%s)", DRIVER.base_url)
elif _driver_choice == "mock":
    DRIVER = MockVDJDriver()
    logger.info("Драйвер VirtualDJ: MockVDJDriver (очередь только в памяти моста)")
else:
    logger.error("Неизвестный BRIDGE_VDJ_DRIVER=%s (допустимо: mock, network_control)", _driver_choice)
    sys.exit(1)

sio = socketio.Client(reconnection=True, reconnection_delay=1, reconnection_delay_max=10)


@sio.event(namespace="/bridge")
def connect():
    logger.info("Подключено к Backend %s (клуб %s)", BACKEND_URL, CLUB_ID)


@sio.event(namespace="/bridge")
def connect_error(data):
    logger.error("Backend отклонил подключение моста: %s", data)


@sio.event(namespace="/bridge")
def disconnect():
    logger.warning("Отключено от Backend — socketio сам попробует переподключиться")


@sio.on("vdj_command", namespace="/bridge")
def handle_vdj_command(data):
    request_id = data.get("request_id") if isinstance(data, dict) else None
    command = data.get("command") if isinstance(data, dict) else None
    logger.info("Команда от Backend: %s (request_id=%s)", command, request_id)

    try:
        result = _dispatch(command, data)
    except Exception as exc:  # noqa: BLE001 — ошибка драйвера должна уйти
        # обратно в Backend как error, а не уронить мост (иначе клуб
        # останется без связи из-за одной неудачной команды).
        logger.exception("Ошибка выполнения команды %s", command)
        result = {"error": str(exc)}

    if not request_id:
        logger.warning("vdj_command без request_id — отвечать некому, игнорирую")
        return

    sio.emit("vdj_result", {"request_id": request_id, "result": result}, namespace="/bridge")


def _dispatch(command, data):
    if command == "add_to_queue":
        item_id = DRIVER.add_to_queue(data.get("song_title"), data.get("artist"), data.get("table_no"))
        return {"vdj_item_id": item_id}
    if command == "remove_from_queue":
        DRIVER.remove_from_queue(data.get("vdj_item_id"))
        return {}
    if command == "get_queue":
        return {"items": DRIVER.get_queue()}
    if command == "get_current_song":
        return {"item": DRIVER.get_current_song()}
    return {"error": f"Неизвестная команда: {command}"}


def main():
    if not CLUB_ID or not BRIDGE_TOKEN:
        logger.error(
            "Обязательны переменные окружения BRIDGE_CLUB_ID и BRIDGE_TOKEN "
            "(см. `python3 manage.py set-bridge-token --club-id <id>` в backend/)"
        )
        sys.exit(1)

    try:
        sio.connect(
            BACKEND_URL,
            namespaces=["/bridge"],
            auth={"club_id": int(CLUB_ID), "bridge_token": BRIDGE_TOKEN},
        )
    except socketio.exceptions.ConnectionError:
        # connect_error() выше уже залогировал причину (например неверный
        # bridge_token); здесь просто выходим с понятным кодом, без трейсбека.
        logger.error("Не удалось подключиться к Backend — проверь BRIDGE_BACKEND_URL/BRIDGE_TOKEN")
        sys.exit(1)

    sio.wait()


if __name__ == "__main__":
    main()
