// api/client.ts
// Toate apelurile HTTP catre backend

import axios from "axios";
import type {
  MapData,
  SystemState,
  SendRouteResponse,
  RoutePayload,
} from "../types/types_index";

let BASE_URL = "http://localhost:5000";

export const setBaseUrl = (url: string) => {
  BASE_URL = url.replace(/\/$/, "");
};

export const getBaseUrl = () => BASE_URL;

const timeout = 3000;


export const fetchMap = async (): Promise<MapData> => {
  const { data } = await axios.get<MapData>(`${BASE_URL}/map`, { timeout });
  return data;
};


export const fetchStatus = async (): Promise<SystemState> => {
  const { data } = await axios.get<SystemState>(`${BASE_URL}/status`, {
    timeout,
  });
  return data;
};



export const sendRoute = async (
  payload: RoutePayload
): Promise<SendRouteResponse> => {
  const { data } = await axios.post<SendRouteResponse>(
    `${BASE_URL}/send_route`,
    payload,
    { timeout }
  );
  return data;
};


export const sendControl = async (
  command: string,
  extra?: Record<string, string>
): Promise<{ ok: boolean }> => {
  const { data } = await axios.post(
    `${BASE_URL}/control`,
    { command, ...extra },
    { timeout }
  );
  return data;
};
