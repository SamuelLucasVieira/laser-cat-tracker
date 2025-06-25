import os
import json
import time
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# === Carrega .env (no mesmo diretório) ===
load_dotenv()

BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
PORT   = int(os.getenv("MQTT_PORT", "1883"))
TOPIC  = os.getenv("MQTT_TOPIC", "laser/position")

# === Callbacks ===
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Conectado com sucesso ao broker {BROKER}:{PORT}")
        client.subscribe(TOPIC)
        print(f"[MQTT] Inscrito em '{TOPIC}'")
    else:
        print(f"[MQTT] Falha na conexão, código de erro: {rc}")

def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    print(f"\n[{msg.topic}] {payload}")
    try:
        data = json.loads(payload)
        print("→ JSON decodificado:", data)
    except json.JSONDecodeError:
        print("→ NÃO é um JSON válido")

# === Setup cliente MQTT ===
client = mqtt.Client()
client.on_connect  = on_connect
client.on_message  = on_message

print(f"[MQTT] Conectando a {BROKER}:{PORT}...")
client.connect(BROKER, PORT, keepalive=60)
client.loop_start()

# Mantém vivo para exibir mensagens
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[MQTT] Encerrando teste.")
finally:
    client.loop_stop()
    client.disconnect()
