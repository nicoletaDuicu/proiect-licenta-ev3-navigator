#!/usr/bin/env python3

import time
import math

from ev3dev2.motor  import LargeMotor, OUTPUT_A, OUTPUT_C, SpeedPercent
from ev3dev2.sensor import INPUT_2, INPUT_3
from ev3dev2.sensor.lego import ColorSensor
from ev3dev2.button import Button

from urllib.request import urlopen, Request
import json as _json
import csv


def http_get(url):
    r = urlopen(url, timeout=3)
    return _json.loads(r.read().decode())

def http_post(url, data):
    body = _json.dumps(data).encode()
    req  = Request(url, data=body,
                   headers={"Content-Type": "application/json"})
    r = urlopen(req, timeout=3)
    return _json.loads(r.read().decode())


BACKEND_URL = "http://172.20.10.8:5000"

BASE_SPEED  = 10
MAX_SPEED   = 20
MIN_SPEED   = 5
TURN_SPEED  = 6

WHITE_VALUE = 66
BLACK_VALUE = 6
THRESHOLD   = 50

SEGMENT_TIMEOUT = 40.0

TURN_ANGLE_TIMEOUT = 6.0
TURN_SEARCH_TIMEOUT = 3.0

SETTLE_TIME = 0.5

WHEEL_DIAMETER_CM   = 5.6
WHEEL_CIRCUMFERENCE = math.pi * WHEEL_DIAMETER_CM
AXLE_TRACK_CM       = 11.0

LOOP_DT       = 0.02
POLL_INTERVAL = 1.0
CAMERA_POLL_DT = 0.1

LOG_FILE = "/home/robot/fuzzy_log.csv"
log_data = []



robot_state = {
    "current_node": "N1",
    "running":      False,
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))

def normalize_sensor(raw):
    norm = (raw - BLACK_VALUE) / float(WHITE_VALUE - BLACK_VALUE)
    return clamp(norm * 2.0 - 1.0, -1.0, 1.0)

def trimf(x, a, b, c):
    if x <= a or x >= c: return 0.0
    if x <= b: return (x-a)/(b-a) if b != a else 1.0
    return (c-x)/(c-b) if c != b else 1.0

def trapmf(x, a, b, c, d):
    if x < a or x > d: return 0.0
    if b <= x <= c:    return 1.0
    if x < b: return (x-a)/(b-a) if b != a else 1.0
    return (d-x)/(d-c) if d != c else 1.0

def fuzzify_line(norm_l, norm_r):
   
    l_negru = trapmf(norm_l, -1.0, -1.0, -0.4, 0.0)
    l_alb   = trapmf(norm_l,  0.0,  0.4,  1.0, 1.0)
    r_negru = trapmf(norm_r, -1.0, -1.0, -0.4, 0.0)
    r_alb   = trapmf(norm_r,  0.0,  0.4,  1.0, 1.0)

    rules = [
        (min(l_negru, r_alb),             +1.0),
        (min(l_alb,   r_negru),           -1.0),
        (min(l_alb,   r_alb),              0.0),
        (min(l_negru, r_negru),            0.0),
        (min(l_negru * 0.6, r_alb * 0.4), +0.4),
        (min(l_alb * 0.4, r_negru * 0.6), -0.4),
    ]

    num = sum(deg * val for deg, val in rules)
    den = sum(deg         for deg, _   in rules)
    if den < 1e-6:
        return 0.0
    return clamp(num / den, -1.0, 1.0)

def correction_to_speeds(correction, base_speed):
    amount = abs(correction) * base_speed * 0.8
    if correction > 0:
        sl = base_speed + amount * 0.5
        sr = base_speed - amount
    elif correction < 0:
        sl = base_speed - amount
        sr = base_speed + amount * 0.5
    else:
        sl = sr = float(base_speed)
    return clamp(sl, MIN_SPEED, MAX_SPEED), clamp(sr, MIN_SPEED, MAX_SPEED)


class Hardware(object):
    def __init__(self):
        self.sensor_l = ColorSensor(INPUT_2)
        self.sensor_r = ColorSensor(INPUT_3)
        self.motor_l  = LargeMotor(OUTPUT_C)
        self.motor_r  = LargeMotor(OUTPUT_A)
        self.btn      = Button()
        self.sensor_l.mode = "COL-REFLECT"
        self.sensor_r.mode = "COL-REFLECT"

    def read_sensors(self):
        return (self.sensor_l.reflected_light_intensity,
                self.sensor_r.reflected_light_intensity)

    def set_motors(self, sl, sr):
        self.motor_l.on(SpeedPercent(sl))
        self.motor_r.on(SpeedPercent(sr))

    def stop(self):
        self.motor_l.off()
        self.motor_r.off()

    def reset_encoder(self):
        self.motor_l.position = 0
        self.motor_r.position = 0

    def get_encoder(self):
        return (abs(self.motor_l.position) + abs(self.motor_r.position)) / 2.0

    def button_pressed(self):
        return self.btn.enter

hw = Hardware()



def post_status(node, status, message="", ack_node=False, ack_command=False):
    try:
        http_post(BACKEND_URL + "/update_status", {
            "current_node":     node,
            "status":           status,
            "message":          message,
            "ack_node_reached": ack_node,
            "ack_command":      ack_command,
        })
    except Exception as e:
        print("[NET] post_status:", e)

def get_route_from_backend():
    try:
        return http_get(BACKEND_URL + "/route")
    except Exception as e:
        print("[NET] get_route:", e)
        return None

def check_node_reached():
    try:
        data = http_get(BACKEND_URL + "/route")
        if data.get("node_reached"):
            return True, data.get("node_reached_id")
    except Exception:
        pass
    return False, None

def get_turn_angle():
    try:
        data = http_get(BACKEND_URL + "/turn_angle")
        if data.get("available"):
            return data.get("angle_deg")
    except Exception:
        pass
    return None

def ack_turn_angle():
    try:
        http_post(BACKEND_URL + "/ack_turn_angle", {})
    except Exception:
        pass


def degrees_to_cm(degrees):
    return (degrees / 360.0) * WHEEL_CIRCUMFERENCE

def turn_by_angle(diff_deg):
    

    if abs(diff_deg) < 5:
        print("[TURN] Unghi mic ({:.1f}), fara viraj.".format(diff_deg))
        return True

    print("[TURN] Viraj {:+.1f} grade".format(diff_deg))

    arc_cm = (abs(diff_deg) / 360.0) * math.pi * AXLE_TRACK_CM
    hw.reset_encoder()

    if diff_deg > 0: 
        hw.set_motors(+TURN_SPEED, -TURN_SPEED)
    else:         
        hw.set_motors(-TURN_SPEED, +TURN_SPEED)

    while degrees_to_cm(hw.get_encoder()) < arc_cm * 0.90:
        time.sleep(0.01)

    hw.stop()
    time.sleep(0.15)

    
    print("[TURN] Caut linia in sens opus virajului...")
    slow = TURN_SPEED - 2

    if diff_deg > 0:   
        hw.set_motors(+slow, -slow)
    else:            
        hw.set_motors(-slow, +slow)

    while True:
        raw_l, raw_r = hw.read_sensors()

        if raw_l < THRESHOLD or raw_r < THRESHOLD:
            hw.stop()
            print("[TURN] Linie gasita! L={} R={}".format(raw_l, raw_r))
            break

        time.sleep(0.01)

    time.sleep(0.2)
    return True

def turn_using_camera(node_to):
    print("[TURN] Astept unghi de la camera pentru {}...".format(node_to))

    timeout = time.time() + TURN_ANGLE_TIMEOUT
    while time.time() < timeout:
        angle = get_turn_angle()
        if angle is not None:
            print("[TURN] Unghi primit: {:+.1f} grade".format(angle))
            ack_turn_angle()
            return turn_by_angle(float(angle))
        time.sleep(0.2)

    print("[TURN] Timeout - camera nu a raspuns!")
    return False


def drive_segment(node_label):
   
    print("[DRIVE] Mers spre {}".format(node_label))

    hw.set_motors(BASE_SPEED, BASE_SPEED)
    timeout        = time.time() + SEGMENT_TIMEOUT
    last_cam_check = time.time()
    iteration      = 0

    while True:
       
        if time.time() > timeout:
            hw.stop()
            print("[DRIVE] Timeout {}s!".format(SEGMENT_TIMEOUT))
            return False

        if time.time() - last_cam_check > CAMERA_POLL_DT:
            reached, node_id = check_node_reached()
            last_cam_check   = time.time()
            if reached and node_id == node_label:
                hw.stop()
                print("[DRIVE] Camera confirma: robot la {}!".format(node_id))
                time.sleep(SETTLE_TIME)
                post_status(node_id, "navigating",
                           "Ajuns la {}".format(node_id),
                           ack_node=True)
                return True

        
        raw_l, raw_r = hw.read_sensors()
        norm_l       = normalize_sensor(raw_l)
        norm_r       = normalize_sensor(raw_r)
        correction   = fuzzify_line(norm_l, norm_r)
        sl, sr       = correction_to_speeds(correction, BASE_SPEED)
        hw.set_motors(sl, sr)

        
        log_data.append([
            time.time(), raw_l, raw_r,
            norm_l, norm_r, correction, sl, sr
        ])

        if iteration % 25 == 0:
            d = "<-" if correction < -0.05 else "->" if correction > 0.05 else "^"
            print("  L={} R={} cor={:.2f} {}".format(
                raw_l, raw_r, correction, d), flush=True)

        iteration += 1
        time.sleep(LOOP_DT)


def execute_route(route):
    print("\n[ROBOT] Traseu: {}".format(" -> ".join(route)))
    robot_state["running"] = True

    for i in range(len(route) - 1):
        node_from = route[i]
        node_to   = route[i + 1]

        print("\n[ROBOT] {} -> {}".format(node_from, node_to))

        post_status(node_from, "turning",
                    "Calculez viraj spre {}".format(node_to))

        turn_ok = turn_using_camera(node_to)
        if not turn_ok:
            print("[ROBOT] Viraj nereusit, incerc sa merg pe linie.")

        post_status(node_from, "navigating",
                    "Mers spre {}".format(node_to))

        drive_ok = drive_segment(node_to)

        if not drive_ok:
            hw.stop()
            post_status(node_from, "error",
                        "Nu am ajuns la {}".format(node_to))
            robot_state["running"] = False
            return

       
        robot_state["current_node"] = node_to
        print("[ROBOT] Ajuns la {}".format(node_to))

        data = get_route_from_backend()
        if data and data.get("pending_command") == "stop":
            hw.stop()
            post_status(node_to, "idle", "Oprit", ack_command=True)
            robot_state["running"] = False
            return

    hw.stop()
    robot_state["running"] = False
    post_status(robot_state["current_node"], "arrived",
                "Destinatie atinsa: {}".format(robot_state["current_node"]))
    print("\n[ROBOT] Destinatie atinsa!")

def main():
    print("=" * 50)
    print("  EV3 Navigator")
    print("=" * 50)
    print("  Backend:    {}".format(BACKEND_URL))
    print("  Nod start:  {}".format(robot_state["current_node"]))
    print("  Oprire:     senzori + camera")
    print("  Viraje:     camera")
    print("=" * 50)
    print("  Astept traseu... Buton CENTRAL = oprire.\n")

    last_route = []

    while True:
        if hw.button_pressed():
            hw.stop()
            post_status(robot_state["current_node"], "idle", "Oprit manual")
            print("[ROBOT] Oprit manual.")
            break

        if robot_state["running"]:
            time.sleep(POLL_INTERVAL)
            continue

        data = get_route_from_backend()
        if not data:
            time.sleep(POLL_INTERVAL)
            continue

        route   = data.get("route",   [])
        status  = data.get("status",  "idle")
        command = data.get("pending_command")

        if command == "stop":
            hw.stop()
            robot_state["running"] = False
            post_status(robot_state["current_node"], "idle",
                       "Oprit", ack_command=True)
            time.sleep(POLL_INTERVAL)
            continue

        if (route and
                route != last_route and
                status in ("waiting", "navigating") and
                len(route) > 1):

            last_route = route[:]
            if route[0] != robot_state["current_node"]:
                robot_state["current_node"] = route[0]

            execute_route(route)

        time.sleep(POLL_INTERVAL)

def save_log():
    try:
        if log_data and len(log_data) > 0:
            with open(LOG_FILE, "w") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "raw_l", "raw_r",
                               "norm_l", "norm_r", "correction",
                               "speed_l", "speed_r"])
                writer.writerows(log_data)
            print("[LOG] Salvat {} inregistrari in {}".format(
                len(log_data), LOG_FILE))
        else:
            print("[LOG] Nicio inregistrare de salvat.")
    except Exception as e:
        print("[LOG] Eroare la salvare: {}".format(e))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        hw.stop()
        print("\n[ROBOT] Oprit.")
    finally:
        save_log()