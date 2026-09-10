"""
Проверка подтверждения личности через Google (ТЗ п.45, постоянная
идентификация гостя). Тот же приём, что уже принят в проекте для
VirtualDJ (см. VDJ_ADAPTER в config.py и vdj/adapters/mock.py) — режим
"mock" даёт полностью рабочую имитацию, пока реальный Google OAuth
Client ID не заведён владельцем проекта, чтобы можно было написать,
протестировать и живо прогнать ВЕСЬ остальной код (постоянный профиль,
перенос данных, гейт на заказ/заявку VIP), не выдумывая ничего в самом
протоколе Google — когда ключ появится, включается режим "real", и
ничего в вызывающем коде (services/guest_account_service.py,
routes/guest.py) менять не нужно.

Реальный режим проверяет id_token, который в норме присылает кнопка
Google Identity Services на фронтенде — подпись и издатель проверяются
библиотекой google-auth, aud сверяется с нашим GOOGLE_CLIENT_ID.
"""


class GoogleAuthError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def verify_google_credential(mode: str, client_id, credential) -> dict:
    """
    Возвращает {"sub": ..., "email": ...} по подтверждённому Google-credential
    или бросает GoogleAuthError.

    mode="mock": credential — это НЕ настоящий Google id_token, а простой
    JSON-объект {"sub": "...", "email": "..."} — сам гость его не видит и
    не вводит, его формирует фронтенд Guest App в режиме разработки, пока
    настоящей кнопки Google ещё нет за неимением реального Client ID (см.
    docstring выше и config.py::GOOGLE_AUTH_MODE). sub обязателен —
    именно он идентифицирует Google-аккаунт постоянно.

    mode="real": credential — настоящий id_token от Google Identity
    Services, проверяется подпись/издатель/aud через google-auth.
    """
    if not isinstance(credential, dict):
        raise GoogleAuthError("credential обязателен")

    if mode == "mock":
        sub = credential.get("sub")
        if not sub or not isinstance(sub, str):
            raise GoogleAuthError("mock-credential должен содержать sub")
        email = credential.get("email")
        return {"sub": sub, "email": email}

    if mode == "real":
        id_token_str = credential.get("id_token")
        if not id_token_str or not isinstance(id_token_str, str):
            raise GoogleAuthError("credential.id_token обязателен")
        if not client_id:
            raise GoogleAuthError("GOOGLE_CLIENT_ID не настроен на сервере")
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
        except ImportError as exc:  # pragma: no cover - зависимость всегда должна стоять
            raise GoogleAuthError("библиотека google-auth не установлена") from exc

        try:
            claims = google_id_token.verify_oauth2_token(
                id_token_str, google_requests.Request(), client_id,
            )
        except Exception as exc:
            raise GoogleAuthError(f"Не удалось подтвердить Google-токен: {exc}") from exc

        sub = claims.get("sub")
        if not sub:
            raise GoogleAuthError("Google-токен без sub")
        return {"sub": sub, "email": claims.get("email")}

    raise GoogleAuthError(f"Неизвестный GOOGLE_AUTH_MODE: {mode}")
