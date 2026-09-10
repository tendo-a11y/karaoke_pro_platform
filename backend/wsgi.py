from app import create_app
from extensions import socketio

app = create_app()

if __name__ == "__main__":
    # Дев-сервер с поддержкой WebSocket. В проде — тот же app под gunicorn
    # (worker class eventlet/gevent) или любой ASGI-совместимый способ.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
