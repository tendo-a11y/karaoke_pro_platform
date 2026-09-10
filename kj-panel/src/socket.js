import { io } from "socket.io-client";
import { BACKEND_URL } from "./api";

export function connectSocket(token) {
  return io(BACKEND_URL, {
    auth: { token },
    transports: ["websocket", "polling"],
  });
}
