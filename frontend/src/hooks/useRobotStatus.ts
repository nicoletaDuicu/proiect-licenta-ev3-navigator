
import { useState, useEffect, useRef } from "react";
import { io, Socket } from "socket.io-client";
import type { SystemState } from "../types/types_index";

interface UseRobotStatusReturn {
  state: SystemState | null;
  error: string | null;
  connected: boolean;
}

export const useRobotStatus = (
  active: boolean,
  baseUrl: string
): UseRobotStatusReturn => {
  const [state, setState]       = useState<SystemState | null>(null);
  const [error, setError]       = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    if (!active || !baseUrl) return;

    // Conectare WebSocket
    const socket = io(baseUrl, {
      transports: ["websocket"],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    socketRef.current = socket;

    socket.on("connect", () => {
      setConnected(true);
      setError(null);
      console.log("[WS] Conectat la", baseUrl);
    });

    socket.on("disconnect", () => {
      setConnected(false);
      console.log("[WS] Deconectat");
    });

    socket.on("connect_error", (err) => {
      setError("Eroare WebSocket: " + err.message);
      setConnected(false);
    });

    socket.on("status_update", (data: SystemState) => {
      setState(data);
      setError(null);
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [active, baseUrl]);

  return { state, error, connected };
};