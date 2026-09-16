"""
2026-09-16: регрессия на баг из логов Railway ("мост не подключается",
повторяется каждые ~80-140с): "Error handling request /socket.io/?...&sid=..."
+ "KeyError: 'Session is disconnected'".

python-engineio 4.14.0 (see engineio/base_server.py::_get_socket) raises this
KeyError, unguarded, from the POST branch of engineio/server.py::handle_request
when a session exists in self.sockets but is already marked closed — a normal
thread race under gunicorn --worker-class gthread. The GET branch in the same
function already catches this KeyError and answers 400; the POST branch does
not, so the exception used to reach gunicorn unhandled and come back to the
client (the KJ's bridge program) as a bare 500, which python-socketio.Client
treats as a connection failure.

app.py wraps app.wsgi_app (see its docstring) to catch exactly this KeyError
and answer 400, matching what the GET path already does. These tests exercise
the real, wrapped app.wsgi_app (not a mock of the guard).
"""
import io

from extensions import socketio


class _FakeClosedSocket:
    """Stand-in for engineio.socket.Socket with .closed=True — same shape
    _get_socket() checks in the real library."""
    closed = True
    upgraded = False


def _wsgi_get(app, path):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
    }
    body = app.wsgi_app(environ, start_response)
    return captured["status"], b"".join(body)


def test_post_to_already_closed_session_returns_400_instead_of_crashing(app):
    eio = socketio.server.eio
    fake_sid = "FAKESIDFORRACETEST00"
    eio.sockets[fake_sid] = _FakeClosedSocket()
    try:
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/socket.io/",
            "QUERY_STRING": f"EIO=4&transport=polling&sid={fake_sid}",
            "wsgi.input": io.BytesIO(b""),
            "CONTENT_LENGTH": "0",
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "80",
            "wsgi.url_scheme": "http",
        }

        body = app.wsgi_app(environ, start_response)

        assert captured["status"] == "400 BAD REQUEST"
        assert b"".join(body) == b"Session is disconnected"
    finally:
        eio.sockets.pop(fake_sid, None)


def test_ordinary_requests_still_work_through_the_guard(app):
    """The guard wraps every request (not just /socket.io/) — a plain route
    must still work normally, proving the try/except doesn't swallow or
    otherwise interfere with the regular request path."""
    status, body = _wsgi_get(app, "/health")
    assert status.startswith("200")
    assert b'"status": "ok"' in body or b'"status":"ok"' in body
