
export interface MapNode {
  id: string;
  x: number;   
  y: number;
}

export interface MapEdge {
  from: string;
  to: string;
  distance: number;
}

export interface MapData {
  nodes: Record<string, [number, number]>;
  edges: MapEdge[];
}

export type RobotStatus =
  | "idle"
  | "waiting"
  | "navigating"
  | "turning"
  | "arrived"
  | "error";

export interface SystemState {
  route: string[];
  current_node: string;
  target_node: string | null;
  remaining: string[];
  status: RobotStatus;
  message: string;
  total_distance: number;
  timestamp: number;
}

export interface SendRouteResponse {
  ok: boolean;
  route: string[];
  distance: number;
  hops: number;
  error?: string;
}

export interface RoutePayload {
  start: string;
  destination: string;
}
