from flask import current_app

from vdj.mock_client import MockVirtualDJClient

_mock_singleton = MockVirtualDJClient()


def get_vdj_client(club_id: int | None = None):
    """
    Фабрика адаптера VirtualDJ.

    - mock — общий процессный синглтон (чтобы очередь была видна между
      запросами и тестами в рамках одного процесса), для разработки/тестов.
    - http — прямой HTTP-вызов из Backend в VirtualDJ; подходит только если
      Backend физически стоит рядом с VirtualDJ (в одной сети/на одной машине).
    - bridge — реальный сценарий "Backend в облаке, VirtualDJ у KJ": команда
      уходит через WebSocket локальному мосту на компьютере KJ и Backend ждёт
      ответа (см. vdj/bridge_client.py). Требует club_id — команду нужно
      адресовать мосту конкретного клуба.
    """
    adapter = current_app.config.get("VDJ_ADAPTER", "mock")
    if adapter == "mock":
        return _mock_singleton
    if adapter == "http":
        from vdj.http_client import HttpVirtualDJClient

        return HttpVirtualDJClient(
            base_url=current_app.config.get("VDJ_API_URL"),
            api_token=current_app.config.get("VDJ_API_TOKEN"),
        )
    if adapter == "bridge":
        if club_id is None:
            raise RuntimeError("VDJ_ADAPTER=bridge требует club_id — команду некому адресовать")
        from vdj.bridge_client import BridgeVirtualDJClient

        return BridgeVirtualDJClient(club_id=club_id)
    raise RuntimeError(f"Неизвестный VDJ_ADAPTER: {adapter}")
