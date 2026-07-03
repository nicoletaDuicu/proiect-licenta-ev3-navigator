#!/usr/bin/env python3

import cv2
import math
import time
import numpy as np
import requests
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("ATENTIE: ultralytics nu este instalat.")


BACKEND_URL   = "http://localhost:5000"
CAMERA_INDEX  = 0
SHOW_WINDOW   = True
FRAME_WIDTH   = 640
FRAME_HEIGHT  = 480

NODE_PROXIMITY_CM     = 6
SEND_INTERVAL         = 0.5
BACKEND_POLL_INTERVAL = 1.0
CONFIRM_FRAMES        = 2
ARUCO_EVERY_N_FRAMES  = 2
ROBOT_FORWARD_OFFSET_DEG = 90
LOCK_REQUIRED_NODES   = 6

YOLO_MODEL_PATH  = "yolov8n.pt"
YOLO_CONFIDENCE  = 0.20
YOLO_IMGSZ       = 640
YOLO_IGNORED_CLASSES = {
    "floor","ceiling","wall","table","desk","carpet",
    "background","window","door","curtain","person"
}


YOLO_ROTATIONS = [0, 90, 180, 270]

OBSTACLE_EDGE_MARGIN_CM = 8
EDGE_SCORE_THRESHOLD    = 0.35
CONFIRM_NEEDED = 5  
MAP_MARGIN_PX  = 80


NODE_MARKER_IDS = {1:"N1",2:"N2",3:"N3",4:"N4",5:"N5",6:"N6"}
ROBOT_MARKER_ID = 10

NODE_POSITIONS_CM = {
    "N1":(0,0),"N2":(0,40),"N3":(0,80),
    "N4":(84,0),"N5":(84,40),"N6":(84,80),
}
NODE_OFFSETS_CM = {
    "N1":(10,0),"N2":(10,0),"N3":(10,0),
    "N4":(-10,0),"N5":(-10,0),"N6":(-10,0),
}
EDGES_UNIQUE = [
    ("N1","N2"),("N2","N3"),
    ("N4","N5"),("N5","N6"),
    ("N1","N4"),("N2","N5"),("N3","N6"),
]
MAP_EDGES = []
for _a,_b in EDGES_UNIQUE:
    MAP_EDGES += [(_a,_b),(_b,_a)]


STREAM_PORT = 5001
_current_frame = None
_frame_lock = threading.Lock()
map_min_x=0; map_max_x=640; map_min_y=0; map_max_y=480

def update_stream_frame(frame):
    global _current_frame
    ok,jpeg=cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,80])
    if not ok: return
    with _frame_lock: _current_frame=jpeg.tobytes()

class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path!="/video":
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type","multipart/x-mixed-replace; boundary=frame")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        while True:
            with _frame_lock: fd=_current_frame
            if fd:
                try:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(fd); self.wfile.write(b"\r\n")
                except: break
            time.sleep(0.05)

def start_stream_server():
    HTTPServer(("0.0.0.0",STREAM_PORT),StreamHandler).serve_forever()

def post_json(url,data):
    try: requests.post(url,json=data,timeout=0.1)
    except: pass

def get_json(url):
    try: return requests.get(url,timeout=0.1).json()
    except: return {}


def normalize_angle(a):
    while a>180: a-=360
    while a<-180: a+=360
    return a

def pixel_distance(p1,p2):
    return math.sqrt((p1[0]-p2[0])**2+(p1[1]-p2[1])**2)

def point_to_segment(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay; sq=dx*dx+dy*dy
    if sq<1e-6: return pixel_distance((px,py),(ax,ay)),0.0
    t=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/sq))
    return pixel_distance((px,py),(ax+t*dx,ay+t*dy)),t


def rotate_frame(frame, angle):
    """Roteste frame-ul cu angle grade clockwise. Returneaza (frame_rotit, W_nou, H_nou)."""
    h, w = frame.shape[:2]
    if angle == 0:
        return frame.copy(), w, h
    elif angle == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE), h, w
    elif angle == 180:
        return cv2.rotate(frame, cv2.ROTATE_180), w, h
    elif angle == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE), h, w
    return frame.copy(), w, h


def map_bbox_to_original(x1, y1, x2, y2, angle, orig_w, orig_h):
    
    if angle == 0:
        return x1, y1, x2, y2
    corners = [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]
    mapped = []
    for (xr, yr) in corners:
        if angle == 90:
            nx = yr
            ny = orig_h - 1 - xr
        elif angle == 180:
            nx = orig_w - 1 - xr
            ny = orig_h - 1 - yr
        elif angle == 270:
            nx = orig_w - 1 - yr
            ny = xr
        else:
            nx, ny = xr, yr
        mapped.append((nx, ny))
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return min(xs), min(ys), max(xs), max(ys)



def setup_aruco():
    d=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    p=cv2.aruco.DetectorParameters()
    p.adaptiveThreshWinSizeMin=3; p.adaptiveThreshWinSizeMax=23
    p.adaptiveThreshWinSizeStep=10; p.minMarkerPerimeterRate=0.005
    p.maxMarkerPerimeterRate=4.0; p.polygonalApproxAccuracyRate=0.05
    p.minCornerDistanceRate=0.01; p.minDistanceToBorder=3
    p.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_NONE
    return cv2.aruco.ArucoDetector(d,p)

def get_marker_center(c):
    pts=c[0]; return int(np.mean(pts[:,0])),int(np.mean(pts[:,1]))

def get_robot_heading_deg(c):
    pts=c[0]; top=(pts[0]+pts[1])/2.0; cen=np.mean(pts,axis=0)
    dx=top[0]-cen[0]; dy=-(top[1]-cen[1])
    return normalize_angle(math.degrees(math.atan2(dy,dx))+ROBOT_FORWARD_OFFSET_DEG)


def get_px_per_cm(npp):
    nodes=list(npp.items())
    for i in range(len(nodes)):
        for j in range(i+1,len(nodes)):
            n1,p1=nodes[i]; n2,p2=nodes[j]
            if n1 not in NODE_POSITIONS_CM or n2 not in NODE_POSITIONS_CM: continue
            dpx=pixel_distance(p1,p2)
            dcm=pixel_distance(NODE_POSITIONS_CM[n1],NODE_POSITIONS_CM[n2])
            if dpx>20 and dcm>0: return dpx/dcm
    return None

def get_real_px(nid,npp):
    mp=npp[nid]; s=get_px_per_cm(npp)
    if s is None: return mp
    ox,oy=NODE_OFFSETS_CM.get(nid,(0,0))
    return int(mp[0]+ox*s),int(mp[1]-oy*s)

def find_nearest_node(px,py,npp):
    best,bd=None,float("inf")
    for nid in npp:
        d=pixel_distance((px,py),get_real_px(nid,npp))
        if d<bd: bd=d; best=nid
    return best,bd

def px_to_cm(dpx,npp):
    s=get_px_per_cm(npp)
    return dpx/(s if s else 10.0)

def pixels_to_cm(px,py,npp,nn):
    if nn not in npp: return 0.0,0.0
    rx,ry=get_real_px(nn,npp); refx,refy=NODE_POSITIONS_CM[nn]
    s=get_px_per_cm(npp)
    if s is None: return refx,refy
    return refx+(px-rx)/s,refy-(py-ry)/s

def calculate_turn_angle(rpx,rpy,tpx,tpy,hdeg):
    dx=tpx-rpx; dy=-(tpy-rpy)
    th=math.degrees(math.atan2(dy,dx))
    diff=normalize_angle(th-hdeg)
    print("[DEBUG] dx={:.0f} dy={:.0f} target={:.1f} heading={:.1f} diff={:.1f}".format(
        dx,dy,th,hdeg,diff))
    return diff

def score_object_on_edge(cx,cy,bbox_w,bbox_h,ax,ay,bx,by,scale):
    margin_px=OBSTACLE_EDGE_MARGIN_CM*scale
    edge_len=pixel_distance((ax,ay),(bx,by))
    if edge_len<1: return 0.0

    dist_perp,t_clamped=point_to_segment(cx,cy,ax,ay,bx,by)
    dx,dy=bx-ax,by-ay; sq=dx*dx+dy*dy
    t_raw=((cx-ax)*dx+(cy-ay)*dy)/sq if sq>1e-6 else 0.0

    if t_raw<-0.15 or t_raw>1.15: return 0.0
    if dist_perp>margin_px*2.0: return 0.0

    dist_factor=max(0.0,1.0-dist_perp/margin_px)
    t_center=abs(t_clamped-0.5)*2.0
    position_factor=max(0.0,1.0-t_center*0.5)

    edge_dir_x=(bx-ax)/edge_len; edge_dir_y=(by-ay)/edge_len
    bbox_proj=abs(bbox_w*edge_dir_x)+abs(bbox_h*edge_dir_y)
    coverage=min(1.0,bbox_proj/edge_len)

    return dist_factor*0.60+position_factor*0.25+coverage*0.15


def find_best_edge(x1,y1,x2,y2,node_positions_px,source="",debug_frame=None):
    scale=get_px_per_cm(node_positions_px)
    if scale is None or scale<=0: return []

    cx=(x1+x2)/2.0; cy=(y1+y2)/2.0
    bbox_w=x2-x1; bbox_h=y2-y1
    scores={}

    for n1,n2 in EDGES_UNIQUE:
        if n1 not in node_positions_px or n2 not in node_positions_px: continue
        ax,ay=get_real_px(n1,node_positions_px)
        bx,by=get_real_px(n2,node_positions_px)
        s=score_object_on_edge(cx,cy,bbox_w,bbox_h,ax,ay,bx,by,scale)
        scores[(n1,n2)]=s
        dist_perp,t=point_to_segment(cx,cy,ax,ay,bx,by)
        print("[{} SCORE] {}-{} | dist={:.1f}cm | t={:.2f} | score={:.3f}".format(
            source,n1,n2,dist_perp/scale,t,s))
        if debug_frame is not None:
            proj_x=int(ax+t*(bx-ax)); proj_y=int(ay+t*(by-ay))
            col=(100,100,100)
            cv2.line(debug_frame,(int(cx),int(cy)),(proj_x,proj_y),col,1)
            cv2.putText(debug_frame,"{:.0f}cm".format(dist_perp/scale),
                        (int((cx+proj_x)/2),int((cy+proj_y)/2)),
                        cv2.FONT_HERSHEY_SIMPLEX,0.28,col,1)

    if not scores: return []
    best_edge,best_score=max(scores.items(),key=lambda x:x[1])
    print("[{} SCORE] >>> Best: {}-{} score={:.3f} (threshold={:.2f})".format(
        source,best_edge[0],best_edge[1],best_score,EDGE_SCORE_THRESHOLD))

    if best_score<EDGE_SCORE_THRESHOLD:
        return []

    n1,n2=best_edge
    if debug_frame is not None:
        ax,ay=get_real_px(n1,node_positions_px)
        bx,by=get_real_px(n2,node_positions_px)
        cv2.line(debug_frame,(ax,ay),(bx,by),(0,0,255),3)
        cv2.putText(debug_frame,"{}-{} {:.2f}".format(n1,n2,best_score),
                    (int((ax+bx)/2)-30,int((ay+by)/2)-10),
                    cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,0,255),1)
    return [(n1,n2),(n2,n1)]


def yolo_detect_multi_rotation(frame, yolo_model, node_positions_px,
                                draw_debug=False):
   
    orig_h, orig_w = frame.shape[:2]
    out = frame.copy() if draw_debug else None

    for angle in YOLO_ROTATIONS:
        rotated, rot_w, rot_h = rotate_frame(frame, angle)

        try:
            results = yolo_model(rotated, imgsz=YOLO_IMGSZ,
                                 conf=YOLO_CONFIDENCE, verbose=False)[0]
        except Exception as e:
            print("[YOLO] Eroare rotatie {}:".format(angle), e)
            continue

        if len(results.boxes) == 0:
            print("[YOLO] Rotatie {}°: niciun obiect".format(angle))
            continue

        
        relevant = []
        for box in results.boxes:
            rx1,ry1,rx2,ry2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            cls  = int(box.cls[0])
            label = results.names[cls]

            if label.lower() in YOLO_IGNORED_CLASSES:
                continue

            
            ox1,oy1,ox2,oy2 = map_bbox_to_original(
                rx1,ry1,rx2,ry2, angle, orig_w, orig_h)

            
            cx = int((ox1+ox2)/2)
            cy = int((oy1+oy2)/2)

            if not (map_min_x<=cx<=map_max_x and map_min_y<=cy<=map_max_y):
                print("[YOLO] Rotatie {}° - {} ignorat (afara hartii)".format(angle,label))
                continue

            
            bbox_area = (ox2-ox1) * (oy2-oy1)
            map_area  = (map_max_x-map_min_x) * (map_max_y-map_min_y)
            area_ratio = bbox_area / map_area if map_area > 0 else 1.0

           
            bbox_w_ratio = (ox2-ox1) / (map_max_x-map_min_x) if (map_max_x-map_min_x)>0 else 1.0
            bbox_h_ratio = (oy2-oy1) / (map_max_y-map_min_y) if (map_max_y-map_min_y)>0 else 1.0

            if area_ratio > 0.25 or bbox_w_ratio > 0.60 or bbox_h_ratio > 0.60:
                print("[YOLO] Rotatie {}° - {} ignorat (bbox prea mare: aria={:.0f}% w={:.0f}% h={:.0f}%)".format(
                    angle, label, area_ratio*100, bbox_w_ratio*100, bbox_h_ratio*100))
                continue

            relevant.append((ox1,oy1,ox2,oy2,conf,label))
            print("[YOLO] Rotatie {}° - {} ({:.0f}%) centru_orig=({},{}) aria={:.0f}%".format(
                angle,label,conf*100,cx,cy,area_ratio*100))

        if not relevant:
            print("[YOLO] Rotatie {}°: obiecte gasite dar toate ignorate".format(angle))
            continue

       
        print("[YOLO] *** Detectie reusita la rotatie {}° ***".format(angle))
        blocked = []
        for (ox1,oy1,ox2,oy2,conf,label) in relevant:
            if draw_debug and out is not None:
                cv2.rectangle(out,(int(ox1),int(oy1)),(int(ox2),int(oy2)),(0,255,255),2)
                cv2.putText(out,"{} {:.0f}% r{}".format(label,conf*100,angle),
                            (int(ox1),int(oy1)-5),
                            cv2.FONT_HERSHEY_SIMPLEX,0.42,(0,255,255),1)
            bl = find_best_edge(ox1,oy1,ox2,oy2,node_positions_px,
                                "YOLO_R{}".format(angle),
                                debug_frame=out if draw_debug else None)
            blocked.extend(bl)

        unique=[]
        for e in blocked:
            if e not in unique: unique.append(e)
        return True, unique, out, angle

    print("[YOLO] Nicio rotatie nu a detectat obiecte relevante")
    return False, [], out, None


_confirm_streak = defaultdict(int)  
_confirmed_edges = set()             


def reset_confirm_state():
    global _confirm_streak, _confirmed_edges
    _confirm_streak = defaultdict(int)
    _confirmed_edges = set()


def process_detection_frame(frame, yolo_model, node_positions_px, draw_debug=False):
    """
    Ruleaza YOLO pe un frame si actualizeaza streak-ul de confirmari.
    O muchie e confirmata definitiv dupa CONFIRM_NEEDED frame-uri consecutive.
    Returneaza (newly_confirmed_edges, debug_frame).
    newly_confirmed_edges: muchii confirmate in acest frame (pot fi goale).
    """
    global _confirm_streak, _confirmed_edges

    found, blocked, dbg, rot = yolo_detect_multi_rotation(
        frame, yolo_model, node_positions_px, draw_debug=draw_debug)

    
    detected_keys = set()
    for e in blocked:
        ek = tuple(sorted(e))
        detected_keys.add(ek)

    newly_confirmed = []

    for ek in list(EDGES_UNIQUE):
        n1, n2 = ek
        if ek not in node_positions_px and (n1 not in node_positions_px or n2 not in node_positions_px):
            continue
        if ek in _confirmed_edges:
            continue  
        if ek in detected_keys:
            _confirm_streak[ek] += 1
            print("[CONFIRM] {}-{}: {}/{}".format(
                ek[0], ek[1], _confirm_streak[ek], CONFIRM_NEEDED))
            if _confirm_streak[ek] >= CONFIRM_NEEDED:
                _confirmed_edges.add(ek)
                newly_confirmed.append(ek)
                print("[CONFIRM] *** CONFIRMATA definitiv: {}-{} ***".format(ek[0], ek[1]))
        else:
            if _confirm_streak[ek] > 0:
                print("[CONFIRM] {}-{}: streak resetat ({} -> 0)".format(
                    ek[0], ek[1], _confirm_streak[ek]))
            _confirm_streak[ek] = 0

    return newly_confirmed, dbg


def send_position(nid,x,y,d):
    post_json(BACKEND_URL+"/update_position",
              {"detected_node":nid,"x_cm":round(float(x),1),
               "y_cm":round(float(y),1),"dist_to_node":round(float(d),1),"source":"aruco"})

def set_robot_position(nid):
    post_json(BACKEND_URL+"/control",{"command":"set_position","node":nid})
    print("[CAM] Pozitie initiala:",nid)

def send_camera_status(active):
    post_json(BACKEND_URL+"/camera_status",{"active":active})

def send_turn_angle(a):
    post_json(BACKEND_URL+"/update_turn_angle",{"angle_deg":round(float(a),1)})
    print("[CAM] Unghi viraj: {:+.1f}".format(a))

def send_blocked_edges(bl):
    post_json(BACKEND_URL+"/update_obstacles",{"blocked_edges":bl})
    print("[DETECT] Muchii trimise:",bl)


def open_camera():
    cap=cv2.VideoCapture(CAMERA_INDEX,cv2.CAP_DSHOW)
    if not cap.isOpened(): cap=cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened(): return None
    cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc("M","J","P","G"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS,30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
    return cap


def main():
    global map_min_x,map_max_x,map_min_y,map_max_y
    global OBSTACLE_EDGE_MARGIN_CM,EDGE_SCORE_THRESHOLD

    print("="*55)
    print("EV3 VISION - YOLO multi-rotatie (0/90/180/270)")
    print("  conf:{:.0f}%  margin:{}cm  threshold:{}".format(
        YOLO_CONFIDENCE*100,OBSTACLE_EDGE_MARGIN_CM,EDGE_SCORE_THRESHOLD))
    print("="*55)

    threading.Thread(target=start_stream_server,daemon=True).start()
    print("Stream: http://localhost:{}/video".format(STREAM_PORT))

    detector=setup_aruco()
    yolo_model=None
    if YOLO_AVAILABLE:
        try:
            yolo_model=YOLO(YOLO_MODEL_PATH)
            print("[YOLO] Model incarcat:",YOLO_MODEL_PATH)
        except Exception as e:
            print("[YOLO] Nu s-a incarcat:",e)

    cap=open_camera()
    if cap is None: print("EROARE: camera"); return

    send_camera_status(True)

    backend_data={}; last_backend_poll=0.0; last_send_time=0.0
    initial_pos_set=False; confirm_counter=0; confirm_candidate=None; turn_sent_for=None
    frame_count=0; last_corners=None; last_ids=None
    fixed_node_positions_px={}; nodes_locked=False
    detect_done=False; blocked_static=[]
    debug_frame_saved=None; debug_until=0.0; show_debug=True
    fps_count=0; fps_time=time.time(); fps_real=0.0

    print("Comenzi: [c] recalibrare | [r] rerulare | [d] toggle debug")
    print("         [+/-] margin cm | [e/w] edge threshold | [q] oprire")

    while True:
        ret,frame=cap.read()
        if not ret or frame is None: time.sleep(0.02); continue

        now=time.time(); frame_count+=1

        if now-last_backend_poll>=BACKEND_POLL_INTERVAL:
            backend_data=get_json(BACKEND_URL+"/route"); last_backend_poll=now

        backend_status=backend_data.get("status","idle")
        remaining=backend_data.get("remaining",[])
        expected_node=remaining[0] if remaining else None
        if backend_status!="turning": turn_sent_for=None

        if frame_count%ARUCO_EVERY_N_FRAMES==0:
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            last_corners,last_ids,_=detector.detectMarkers(gray)

        robot_px=None; robot_py=None; robot_heading_deg=None
        if last_ids is not None and last_corners is not None:
            for i,mid in enumerate(last_ids.flatten()):
                cx,cy=get_marker_center(last_corners[i])
                if mid in NODE_MARKER_IDS:
                    if not nodes_locked: fixed_node_positions_px[NODE_MARKER_IDS[mid]]=(cx,cy)
                elif mid==ROBOT_MARKER_ID:
                    robot_px,robot_py=cx,cy
                    robot_heading_deg=get_robot_heading_deg(last_corners[i])

        if not nodes_locked and len(fixed_node_positions_px)>=LOCK_REQUIRED_NODES:
            nodes_locked=True
            print("[VISION] Noduri blocate:",fixed_node_positions_px)
            all_r=[get_real_px(n,fixed_node_positions_px) for n in fixed_node_positions_px]
            map_min_x=min(p[0] for p in all_r)-MAP_MARGIN_PX
            map_max_x=max(p[0] for p in all_r)+MAP_MARGIN_PX
            map_min_y=min(p[1] for p in all_r)-MAP_MARGIN_PX
            map_max_y=max(p[1] for p in all_r)+MAP_MARGIN_PX
            print("[VISION] Zona harta: x=[{},{}] y=[{},{}]".format(
                map_min_x,map_max_x,map_min_y,map_max_y))
            reset_confirm_state()
            print("[DETECT] Incep confirmare ({} frame-uri consecutive)...".format(CONFIRM_NEEDED))

        node_positions_px=fixed_node_positions_px.copy()

        if not detect_done and nodes_locked:
            if yolo_model is None:
                send_blocked_edges([]); detect_done=True
            else:
                if frame_count % 2 == 0:
                    newly, dbg = process_detection_frame(
                        frame, yolo_model, node_positions_px, draw_debug=True)
                    if dbg is not None:
                        debug_frame_saved = dbg
                        debug_until = now + 3.0
                    if newly:
                        for (n1, n2) in newly:
                            if (n1,n2) not in blocked_static:
                                blocked_static.append((n1,n2))
                            if (n2,n1) not in blocked_static:
                                blocked_static.append((n2,n1))
                        send_blocked_edges([[a,b] for a,b in blocked_static])
                        detect_done = True
                        print("[DETECT] Confirmat. Muchii blocate:", blocked_static)

        if robot_px is not None and node_positions_px:
            nn,dpx=find_nearest_node(robot_px,robot_py,node_positions_px)
            dcm=px_to_cm(dpx,node_positions_px)
            xcm,ycm=pixels_to_cm(robot_px,robot_py,node_positions_px,nn)

            if not initial_pos_set and dcm<NODE_PROXIMITY_CM:
                set_robot_position(nn); initial_pos_set=True

            if dcm<NODE_PROXIMITY_CM:
                if nn==confirm_candidate: confirm_counter+=1
                else: confirm_candidate=nn; confirm_counter=1
            else: confirm_counter=0; confirm_candidate=None

            if now-last_send_time>=SEND_INTERVAL and confirm_counter>=CONFIRM_FRAMES:
                send_position(nn,xcm,ycm,dcm); last_send_time=now

            if (backend_status=="turning" and expected_node
                    and expected_node in node_positions_px
                    and robot_heading_deg is not None
                    and turn_sent_for!=expected_node):
                tpx,tpy=get_real_px(expected_node,node_positions_px)
                diff=calculate_turn_angle(robot_px,robot_py,tpx,tpy,robot_heading_deg)
                if abs(diff)<20: diff=0
                if abs(abs(diff)-180)<15: diff=180
                send_turn_angle(diff); turn_sent_for=expected_node
                if SHOW_WINDOW:
                    cv2.line(frame,(robot_px,robot_py),(tpx,tpy),(0,0,255),2)
                    cv2.putText(frame,"Viraj: {:+.1f}".format(diff),
                                (10,150),cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,0,255),2)
        else:
            initial_pos_set=False

        if SHOW_WINDOW:
            if show_debug and debug_frame_saved is not None and now<debug_until:
                df=debug_frame_saved.copy()
                cv2.putText(df,"DEBUG (d=toggle, r=rerun)",
                            (10,FRAME_HEIGHT-10),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,255,255),1)
            else:
                df=frame.copy()

            for n1,n2 in EDGES_UNIQUE:
                if n1 in node_positions_px and n2 in node_positions_px:
                    ax,ay=get_real_px(n1,node_positions_px)
                    bx,by=get_real_px(n2,node_positions_px)
                    ib=(n1,n2) in blocked_static or (n2,n1) in blocked_static
                    cv2.line(df,(ax,ay),(bx,by),(0,0,255) if ib else (180,180,180),3 if ib else 2)
                    if ib:
                        cv2.putText(df,"BLOCAT",
                                    (int((ax+bx)/2)-20,int((ay+by)/2)-8),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,0,255),1)

            for nid,(mx,my) in node_positions_px.items():
                rx,ry=get_real_px(nid,node_positions_px)
                cv2.circle(df,(mx,my),7,(255,255,0),-1)
                cv2.putText(df,nid,(mx+10,my-10),cv2.FONT_HERSHEY_SIMPLEX,0.55,(255,255,0),2)
                cv2.circle(df,(rx,ry),7,(0,0,255),2)

            if robot_px is not None:
                cv2.circle(df,(robot_px,robot_py),10,(0,255,0),2)
                cv2.putText(df,"ROBOT",(robot_px+12,robot_py),
                            cv2.FONT_HERSHEY_SIMPLEX,0.55,(0,255,0),2)
                if robot_heading_deg is not None:
                    hx=int(robot_px+35*math.cos(math.radians(robot_heading_deg)))
                    hy=int(robot_py-35*math.sin(math.radians(robot_heading_deg)))
                    cv2.arrowedLine(df,(robot_px,robot_py),(hx,hy),(0,255,0),2)
                nn2,dpx2=find_nearest_node(robot_px,robot_py,node_positions_px)
                dcm2=px_to_cm(dpx2,node_positions_px)
                npx,npy=get_real_px(nn2,node_positions_px)
                col=(0,255,0) if dcm2<NODE_PROXIMITY_CM else (0,165,255)
                cv2.line(df,(robot_px,robot_py),(npx,npy),col,1)
                cv2.putText(df,"{} {:.1f}cm".format(nn2,dcm2),
                            (robot_px+12,robot_py+22),cv2.FONT_HERSHEY_SIMPLEX,0.55,col,2)
            else:
                cv2.putText(df,"Robot nedetectat",(10,90),
                            cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2)

            fps_count+=1; el=now-fps_time
            if el>=1.0: fps_real=fps_count/el; fps_count=0; fps_time=now

            if detect_done: st="DONE"
            elif nodes_locked:
                confirmed_count = len(_confirmed_edges)
                max_streak = max((_confirm_streak[tuple(sorted(e))] for e in EDGES_UNIQUE
                                  if e[0] in node_positions_px and e[1] in node_positions_px),
                                 default=0)
                st="LIVE streak:{}/{}".format(max_streak, CONFIRM_NEEDED)
            else: st="WAIT"

            cv2.putText(df,"FPS:{:.1f} | Lock:{} | Astept:{}".format(
                fps_real,"DA" if nodes_locked else "NU",expected_node),
                (10,25),cv2.FONT_HERSHEY_SIMPLEX,0.6,(255,255,255),2)
            cv2.putText(df,"YOLO:{} | margin:{}cm thr:{:.2f} | Blocat:{}".format(
                st,OBSTACLE_EDGE_MARGIN_CM,EDGE_SCORE_THRESHOLD,
                ["{}-{}".format(a,b) for a,b in blocked_static if a<b] or "nimic"),
                (10,50),cv2.FONT_HERSHEY_SIMPLEX,0.4,(255,255,255),1)
            if robot_heading_deg is not None:
                cv2.putText(df,"Heading:{:.1f}".format(robot_heading_deg),
                            (10,75),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)

            cv2.imshow("EV3 Vision",df)

        update_stream_frame(frame)
        key=cv2.waitKey(1)&0xFF

        if key==ord("c"):
            fixed_node_positions_px={}; nodes_locked=False
            detect_done=False; blocked_static=[]
            debug_frame_saved=None; reset_confirm_state()
            print("[VISION] Recalibrare...")
        if key==ord("r"):
            detect_done=False; blocked_static=[]
            debug_frame_saved=None; reset_confirm_state()
            print("[DETECT] Rerulare...")
        if key==ord("d"):
            show_debug=not show_debug; debug_until=now+10.0
        if key==ord("+") or key==ord("="):
            OBSTACLE_EDGE_MARGIN_CM=min(20,OBSTACLE_EDGE_MARGIN_CM+1)
            print("[PARAM] margin:",OBSTACLE_EDGE_MARGIN_CM,"cm")
        if key==ord("-"):
            OBSTACLE_EDGE_MARGIN_CM=max(2,OBSTACLE_EDGE_MARGIN_CM-1)
            print("[PARAM] margin:",OBSTACLE_EDGE_MARGIN_CM,"cm")
        if key==ord("e"):
            EDGE_SCORE_THRESHOLD=min(0.9,round(EDGE_SCORE_THRESHOLD+0.05,2))
            print("[PARAM] threshold:",EDGE_SCORE_THRESHOLD)
        if key==ord("w"):
            EDGE_SCORE_THRESHOLD=max(0.05,round(EDGE_SCORE_THRESHOLD-0.05,2))
            print("[PARAM] threshold:",EDGE_SCORE_THRESHOLD)
        if key==ord("q"): break

    send_camera_status(False)
    cap.release(); cv2.destroyAllWindows()
    print("Vision oprit.")

if __name__=="__main__":
    main()