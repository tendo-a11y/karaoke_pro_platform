import { io } from "socket.io-client";
import { BACKEND_URL } from "./api";

export function connectSocket(token) {
  // 2026-09 (жалоба пользователя: "долго подключает kj панель"): раньше
  // здесь стояло transports: ["websocket", "polling"] — с websocket первым
  // в списке socket.io-client v4 пытается открыть именно его для самого
  // первого рукопожатия, а не сразу использует polling. Backend же
  // запущен под gunicorn с --worker-class gthread и Flask-SocketIO в
  // async_mode="threading" (см. extensions.py) — это самый обычный
  // многопоточный WSGI-сервер, который физически не умеет держать
  // настоящий websocket (нет перехвата сырого сокета из WSGI-протокола),
  // поэтому первая попытка гарантированно проваливалась, и только ПОСЛЕ
  // этого клиент откатывался на polling и только тогда подключался по-настоящему
  // — то есть каждое открытие KJ Panel ждало один заведомо бесполезный
  // провал перед реальным подключением. Раз реального websocket всё равно
  // никогда не будет (пока backend не переведут на eventlet/gevent — это
  // отдельная, более рискованная задача), самый быстрый и безопасный путь —
  // сразу подключаться через polling, без обречённой попытки.
  return io(BACKEND_URL, {
    auth: { token },
    transports: ["polling"],
  });
}
