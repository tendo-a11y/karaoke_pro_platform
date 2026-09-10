from flask import jsonify


def api_error(status_code: int, error_code: str, message: str):
    """
    Единый формат ошибки согласно ТЗ п.34:
    {"success": false, "error": "...", "message": "..."}
    """
    response = jsonify({"success": False, "error": error_code, "message": message})
    response.status_code = status_code
    return response


def api_ok(data=None, status_code: int = 200):
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    response = jsonify(payload)
    response.status_code = status_code
    return response
