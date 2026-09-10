from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()

# async_mode="threading" — не требует eventlet/gevent monkey-patch, безопаснее
# сочетается с обычным Flask dev/prod сервером (gunicorn -k gthread).
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
