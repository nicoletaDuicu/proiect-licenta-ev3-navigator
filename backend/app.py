#!/usr/bin/env python3
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import heapq
import threading
import time

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

MAP_NODES = {
    "N1": (0, 0),
    "N2": (0, 40),
    "N3": (0, 80),
    "N4": (84, 0),
    "N5": (84, 40),
    "N6": (84, 80),
}

MAP_EDGES = [
    ("N1", "N4", 84),
    ("N2", "N5", 84),
    ("N3", "N6", 84),
    ("N1", "N2", 40),
    ("N2", "N3", 40),
    ("N4", "N5", 40),
    ("N5", "N6", 40),
]

NODE_REACH_DISTANCE_CM = 15.0

state_lock = threading.Lock()

state = {
    "route": [],
    "current_node": "N1",
    "target_node": None,
    "remaining": [],
    "status": "idle",
    "message": "Sistem pornit.",
    "total_distance": 0,
    "pending_command": None,
    "timestamp": time.time(),

    "camera_active": False,
    "camera_x_cm": None,
    "camera_y_cm": None,

    "node_reached": False,
    "node_reached_id": None,

    "turn_angle_deg": None,
    "turn_angle_available": False,

    "blocked_edges": [],
}


def normalize_edge(a, b):
    return tuple(sorted((a, b)))


def get_blocked_set():
    blocked = set()
    for edge in state["blocked_edges"]:
        if len(edge) == 2:
            blocked.add(normalize_edge(edge[0], edge[1]))
    return blocked


def build_graph_without_blocked(blocked_edges=None):
    if blocked_edges is None:
        blocked_edges = []

    blocked_set = set()
    for edge in blocked_edges:
        if len(edge) == 2:
            blocked_set.add(normalize_edge(edge[0], edge[1]))

    graph = {node: {} for node in MAP_NODES}

    for a, b, dist in MAP_EDGES:
        if normalize_edge(a, b) in blocked_set:
            continue
        graph[a][b] = dist
        graph[b][a] = dist

    return graph


def dijkstra(graph, start, goal):
    heap = [(0, start, [start])]
    visited = set()

    while heap:
        cost, node, path = heapq.heappop(heap)

        if node in visited:
            continue

        visited.add(node)

        if node == goal:
            return path, cost

        for neighbor, weight in graph[node].items():
            if neighbor not in visited:
                heapq.heappush(heap, (cost + weight, neighbor, path + [neighbor]))

    return None, float("inf")


def public_state():
    return {
        "route": state["route"],
        "current_node": state["current_node"],
        "target_node": state["target_node"],
        "remaining": state["remaining"],
        "status": state["status"],
        "message": state["message"],
        "total_distance": state["total_distance"],
        "timestamp": state["timestamp"],
        "camera_active": state["camera_active"],
        "camera_x_cm": state["camera_x_cm"],
        "camera_y_cm": state["camera_y_cm"],
        "node_reached": state["node_reached"],
        "node_reached_id": state["node_reached_id"],
        "blocked_edges": state["blocked_edges"],
    }


def broadcast_state():
    with state_lock:
        data = public_state()
    socketio.emit("status_update", data)


@socketio.on("connect")
def on_connect():
    with state_lock:
        data = public_state()
    emit("status_update", data)
    print("[WS] Client conectat")


@socketio.on("disconnect")
def on_disconnect():
    print("[WS] Client deconectat")


@app.route("/map", methods=["GET"])
def get_map():
    return jsonify({
        "nodes": MAP_NODES,
        "edges": [
            {"from": a, "to": b, "distance": d}
            for a, b, d in MAP_EDGES
        ]
    })


@app.route("/send_route", methods=["POST"])
def send_route():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    start = data.get("start")
    goal = data.get("destination")

    if not start or not goal:
        return jsonify({"error": "start si destination obligatorii"}), 400
    if start not in MAP_NODES:
        return jsonify({"error": "Nod start invalid"}), 400
    if goal not in MAP_NODES:
        return jsonify({"error": "Nod destinatie invalid"}), 400
    if start == goal:
        return jsonify({"error": "Start si destinatie identice"}), 400

    with state_lock:
        if state["status"] in ("navigating", "turning"):
            return jsonify({"error": "Robotul este in miscare"}), 409

        graph_for_route = build_graph_without_blocked(state["blocked_edges"])

    route, total_dist = dijkstra(graph_for_route, start, goal)

    if route is None:
        return jsonify({
            "error": "Nu exista traseu disponibil. Exista muchii blocate.",
            "blocked_edges": state["blocked_edges"],
        }), 404

    with state_lock:
        state["route"] = route
        state["current_node"] = start
        state["target_node"] = goal
        state["remaining"] = route[1:]
        state["status"] = "waiting"
        state["message"] = "Traseu: {} ({} cm)".format(" -> ".join(route), total_dist)
        state["total_distance"] = total_dist
        state["pending_command"] = None
        state["node_reached"] = False
        state["node_reached_id"] = None
        state["turn_angle_deg"] = None
        state["turn_angle_available"] = False
        state["timestamp"] = time.time()

    print("[BACKEND] Traseu: {}".format(" -> ".join(route)))
    print("[BACKEND] Muchii blocate active:", state["blocked_edges"])

    broadcast_state()

    return jsonify({
        "ok": True,
        "route": route,
        "distance": total_dist,
        "hops": len(route) - 1,
        "blocked_edges": state["blocked_edges"],
    })


@app.route("/route", methods=["GET"])
def get_route():
    with state_lock:
        return jsonify({
            "route": state["route"],
            "current_node": state["current_node"],
            "target_node": state["target_node"],
            "remaining": state["remaining"],
            "status": state["status"],
            "pending_command": state["pending_command"],
            "node_reached": state["node_reached"],
            "node_reached_id": state["node_reached_id"],
            "blocked_edges": state["blocked_edges"],
        })


@app.route("/status", methods=["GET"])
def get_status():
    with state_lock:
        return jsonify(public_state())


@app.route("/update_status", methods=["POST"])
def update_status():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    node = data.get("current_node")
    status = data.get("status", "navigating")
    msg = data.get("message", "")

    if node and node not in MAP_NODES:
        return jsonify({"error": "Nod invalid"}), 400

    with state_lock:
        state["status"] = status
        state["message"] = msg or "Status: {}".format(status)
        state["timestamp"] = time.time()

        if data.get("ack_command"):
            state["pending_command"] = None

        if data.get("ack_node_reached"):
            reached_node = node or state["node_reached_id"]

            if reached_node and reached_node in state["route"]:
                idx = state["route"].index(reached_node)
                state["current_node"] = reached_node
                state["remaining"] = state["route"][idx + 1:]

                print("[BACKEND] Nod confirmat:", reached_node)
                print("[BACKEND] Ramas:", state["remaining"])

            state["node_reached"] = False
            state["node_reached_id"] = None

    broadcast_state()
    return jsonify({"ok": True})


@app.route("/update_position", methods=["POST"])
def update_position():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    detected_node = data.get("detected_node")
    x_cm = data.get("x_cm", 0)
    y_cm = data.get("y_cm", 0)
    dist_to_node = float(data.get("dist_to_node", 999))

    node_reached = False

    with state_lock:
        state["camera_active"] = True
        state["camera_x_cm"] = x_cm
        state["camera_y_cm"] = y_cm

        expected_node = state["remaining"][0] if state["remaining"] else None

        if (
            detected_node
            and expected_node
            and detected_node == expected_node
            and dist_to_node <= NODE_REACH_DISTANCE_CM
            and not state["node_reached"]
        ):
            state["node_reached"] = True
            state["node_reached_id"] = detected_node
            state["message"] = "Camera: robot la {}".format(detected_node)
            state["timestamp"] = time.time()
            node_reached = True

            print("[CAMERA] Robot la {} | dist={:.1f}cm".format(
                detected_node, dist_to_node
            ))

    if node_reached:
        broadcast_state()

    return jsonify({
        "ok": True,
        "detected_node": detected_node,
        "expected_node": expected_node,
        "node_reached": node_reached,
    })


@app.route("/camera_status", methods=["POST"])
def camera_status():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    with state_lock:
        state["camera_active"] = data.get("active", False)
        state["message"] = "Camera {}".format(
            "activa" if state["camera_active"] else "oprita"
        )
        state["timestamp"] = time.time()

    broadcast_state()
    return jsonify({"ok": True})


@app.route("/turn_angle", methods=["GET"])
def get_turn_angle():
    with state_lock:
        return jsonify({
            "available": state["turn_angle_available"],
            "angle_deg": state["turn_angle_deg"],
        })


@app.route("/update_turn_angle", methods=["POST"])
def update_turn_angle():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    angle = data.get("angle_deg")
    if angle is None:
        return jsonify({"error": "angle_deg lipsa"}), 400

    with state_lock:
        state["turn_angle_deg"] = angle
        state["turn_angle_available"] = True
        state["timestamp"] = time.time()

    print("[BACKEND] Unghi viraj: {:.1f}".format(angle))
    return jsonify({"ok": True})


@app.route("/ack_turn_angle", methods=["POST"])
def ack_turn_angle():
    with state_lock:
        state["turn_angle_available"] = False
        state["turn_angle_deg"] = None
        state["timestamp"] = time.time()

    return jsonify({"ok": True})


@app.route("/update_obstacles", methods=["POST"])
def update_obstacles():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    blocked_edges = data.get("blocked_edges", [])

    new_blocked_set = set()
    for edge in blocked_edges:
        if len(edge) == 2:
            a, b = edge[0], edge[1]
            if a in MAP_NODES and b in MAP_NODES:
                new_blocked_set.add(normalize_edge(a, b))

    recalculated = False
    new_route = None
    new_dist = None

    with state_lock:
        old_blocked_set = get_blocked_set()

        if new_blocked_set == old_blocked_set:
            return jsonify({
                "ok": True,
                "blocked_edges": state["blocked_edges"],
                "recalculated": False,
                "message": "Obstacole neschimbate",
            })

        state["blocked_edges"] = [[a, b] for a, b in sorted(new_blocked_set)]

        print("[BACKEND] Obstacole schimbate:", state["blocked_edges"])

        graph_temp = build_graph_without_blocked(state["blocked_edges"])

        start = state["current_node"]
        goal = state["target_node"]

        if (
            start
            and goal
            and state["status"] in ("waiting", "navigating", "turning")
        ):
            new_route, new_dist = dijkstra(graph_temp, start, goal)

            if new_route:
                state["route"] = new_route
                state["remaining"] = new_route[1:]
                state["total_distance"] = new_dist
                state["message"] = "Traseu recalculat: {}".format(
                    " -> ".join(new_route)
                )
                state["timestamp"] = time.time()
                recalculated = True

                print("[BACKEND] Traseu nou:", " -> ".join(new_route))
            else:
                state["route"] = []
                state["remaining"] = []
                state["status"] = "idle"
                state["message"] = "Niciun traseu disponibil!"
                state["pending_command"] = "stop"
                state["timestamp"] = time.time()

                print("[BACKEND] Niciun traseu disponibil!")

    broadcast_state()

    return jsonify({
        "ok": True,
        "blocked_edges": state["blocked_edges"],
        "recalculated": recalculated,
        "new_route": new_route,
        "new_distance": new_dist,
    })


@app.route("/control", methods=["POST"])
def control():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Date lipsa"}), 400

    command = data.get("command")

    if command == "stop":
        with state_lock:
            state["pending_command"] = "stop"
            state["status"] = "idle"
            state["message"] = "Oprire manuala"
            state["remaining"] = []
            state["node_reached"] = False
            state["node_reached_id"] = None
            state["turn_angle_deg"] = None
            state["turn_angle_available"] = False
            state["timestamp"] = time.time()

        broadcast_state()
        return jsonify({"ok": True})

    if command == "reset":
        with state_lock:
            state["route"] = []
            state["remaining"] = []
            state["target_node"] = None
            state["status"] = "idle"
            state["message"] = "Sistem resetat"
            state["pending_command"] = "stop"
            state["node_reached"] = False
            state["node_reached_id"] = None
            state["turn_angle_deg"] = None
            state["turn_angle_available"] = False
            state["blocked_edges"] = []
            state["timestamp"] = time.time()

        broadcast_state()
        return jsonify({"ok": True})

    if command == "set_position":
        node = data.get("node")
        if not node or node not in MAP_NODES:
            return jsonify({"error": "Nod invalid"}), 400

        with state_lock:
            state["current_node"] = node
            state["message"] = "Pozitie setata: {}".format(node)
            state["timestamp"] = time.time()

        broadcast_state()
        return jsonify({"ok": True})

    return jsonify({"error": "Comanda necunoscuta"}), 400


if __name__ == "__main__":
    import socket

    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "localhost"

    print("=" * 55)
    print("  EV3 Navigator Backend")
    print("=" * 55)
    print("  URL:         http://{}:5000".format(ip))
    print("  Noduri:      {}".format(list(MAP_NODES.keys())))
    print("  Prag oprire: {} cm".format(NODE_REACH_DISTANCE_CM))
    print("=" * 55)

    socketio.run(app, host="0.0.0.0", port=5000, debug=False)