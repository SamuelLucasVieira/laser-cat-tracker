import os
import time
import random
import re
import serial
import cv2
import json
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# === CARREGA CONFIGURAÇÕES ===
load_dotenv()
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM12")

# MQTT Broker público
MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC  = os.getenv("MQTT_TOPIC", "laser/position")

# Setup MQTT
mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
mqtt_client.loop_start()

# === SERIAL / ARDUINO ===
def init_serial(port=SERIAL_PORT, baud=115200, timeout=1):
    try:
        ar = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2)
        print("[INFO] Arduino conectado.")
        return ar
    except Exception as e:
        print(f"[SerialError] {e}")
        return None

def robust_serial_write(conn, cmd):
    if conn is None or not conn.is_open:
        print("[WARN] Serial caiu. Reconectando...")
        conn = init_serial()
        if conn is None:
            return None, False
    try:
        conn.write((cmd + '\n').encode())
        conn.flush()
        return conn, True
    except:
        conn.close()
        return init_serial(), False

def read_distance(conn):
    try:
        while conn.in_waiting:
            line = conn.readline().decode(errors='ignore').strip()
            if line.startswith("DISTANCIA:"):
                return float(line.split(":")[1].rstrip(";"))
    except:
        pass
    return None

# === CONSTANTES ===
FRAME_W, FRAME_H   = 1280, 720
SERVO_MIN_X, SERVO_MAX_X = 0, 180
SERVO_MIN_Y, SERVO_MAX_Y = 60, 180
CENTER_X = (SERVO_MIN_X + SERVO_MAX_X)//2
CENTER_Y = (SERVO_MIN_Y + SERVO_MAX_Y)//2
SERVO_DELAY = 0.05

def random_target(avoid, ox, oy, min_y):
    for _ in range(100):
        tx = random.randint(SERVO_MIN_X, SERVO_MAX_X)
        ty = random.randint(90, SERVO_MAX_Y)
        px = int(tx/180*FRAME_W) + ox*2
        py = int(ty/180*FRAME_H) + oy*2
        if not any(x1<=px<=x2 and y1<=py<=y2 for x1,y1,x2,y2 in avoid):
            return tx, ty, px, py
    return CENTER_X, CENTER_Y, FRAME_W//2, FRAME_H//2

def smooth_move(last, target, alpha=0.2):
    return int(last + alpha*(target-last))

# === INICIALIZAÇÃO ===
arduino     = init_serial()
last_sx     = CENTER_X
last_sy     = CENTER_Y
_last_time  = time.time()
mov_counter = 0
last_px, last_py = FRAME_W//2, FRAME_H//2

# Carrega DNN
net = cv2.dnn.readNetFromCaffe("deploy.prototxt", "mobilenet_iter_73000.caffemodel")
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
CLASSES = ["background","cat","person"]
bg_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=16, detectShadows=True)

# Configura câmera
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

# Calibração
print("CALIBRAÇÃO: W/A/S/D para ajustar; ENTER para confirmar")
ox = oy = 0
while True:
    ret, frame = cap.read()
    if not ret: continue
    frame = cv2.flip(frame,1)
    cf = frame.copy()
    cv2.drawMarker(cf,(FRAME_W//2,FRAME_H//2),(0,255,255),cv2.MARKER_CROSS,40,2)
    cv2.putText(cf,f"Ox={ox} Oy={oy}",(10,30),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2)
    cv2.imshow("Calibracao",cf)
    k = cv2.waitKey(1)&0xFF
    if   k==ord('w'): arduino,_=robust_serial_write(arduino,"SUBIR"); oy-=1
    elif k==ord('s'): arduino,_=robust_serial_write(arduino,"DESCER"); oy+=1
    elif k==ord('a'): arduino,_=robust_serial_write(arduino,"DIREITA"); ox+=1
    elif k==ord('d'): arduino,_=robust_serial_write(arduino,"ESQUERDA"); ox-=1
    elif k==13: break

cv2.destroyWindow("Calibracao")
arduino,_ = robust_serial_write(arduino, f"POSICAO:{CENTER_X}:{CENTER_Y}")
time.sleep(1)
print(f"[OK] Calibrado Ox={ox}, Oy={oy}")
print("MODO BRINCADEIRA: ESC para sair.")

# Loop principal
try:
    while True:
        dist = read_distance(arduino)
        ret, frame = cap.read()
        if not ret: break
        frame = cv2.flip(frame,1)

        # detecção + máscara
        blob = cv2.dnn.blobFromImage(cv2.resize(frame,(300,300)),0.007843,(300,300),127.5)
        net.setInput(blob)
        dets = net.forward()
        h,w = frame.shape[:2]
        fg = bg_sub.apply(frame)
        avoid=[]
        for i in range(dets.shape[2]):
            conf=float(dets[0,0,i,2])
            cls =int(dets[0,0,i,1])
            label=CLASSES[cls] if 0<=cls<len(CLASSES) else None
            if conf>0.4 and label in ("person","cat"):
                x1,y1,x2,y2 = (dets[0,0,i,3:7]*[w,h,w,h]).astype(int)
                roi = fg[y1:y2, x1:x2]
                if roi.size and cv2.countNonZero(roi)/roi.size>0.2:
                    avoid.append((x1,y1,x2,y2))
                    cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,0),2)

        # cálculo e publicação MQTT
        tx,ty,px,py = random_target(avoid,ox,oy,last_sy)
        now = time.time()
        if now - _last_time >= SERVO_DELAY:
            sx = smooth_move(last_sx,tx)
            sy = smooth_move(last_sy,ty)
            arduino, ok = robust_serial_write(arduino,f"POSICAO:{sx}:{sy}")
            if ok:
                mov_counter += 1
                payload = {"movimento_num":mov_counter, "x_pos":sx, "y_pos":sy, "ts":time.time()}
                mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
                last_sx, last_sy = sx, sy
            _last_time = now

        # interface visual (suavizada)
        last_px = smooth_move(last_px, px, alpha=0.05)
        last_py = smooth_move(last_py, py, alpha=0.05)
        cv2.circle(frame,(last_px,last_py),8,(0,0,255),-1)
        if dist is not None:
            cv2.putText(frame,f"Dist: {dist:.1f}cm",(10,30),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2)

        cv2.imshow("Laser Brincalhao", frame)
        if cv2.waitKey(1)&0xFF == 27: break

finally:
    cap.release()
    cv2.destroyAllWindows()
    if arduino and arduino.is_open:
        robust_serial_write(arduino,f"POSICAO:{CENTER_X}:{CENTER_Y}")
        time.sleep(0.5)
        arduino.close()
