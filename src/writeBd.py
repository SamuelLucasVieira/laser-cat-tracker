import os
import json
import time
from pathlib import Path

import psycopg2
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# === Carrega o .env (no mesmo diretório deste script) ===
dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path)

# === Leitura da URL do banco na nuvem (Railway, Heroku) ===
database_url = os.getenv("DATABASE_URL")
if not database_url:
    # Fallback para credenciais individuais
    database_url = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@"
        f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )

# === Parâmetros MQTT ===
MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC  = os.getenv("MQTT_TOPIC", "laser/position")

# === Conecta no Postgres (nuvem) ===
try:
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("[DB] Conectado ao banco com sucesso.")
except Exception as e:
    print(f"[DB] Erro ao conectar no banco: {e}")
    exit(1)

# === Garante que a tabela exista ===
cur.execute("""
    CREATE TABLE IF NOT EXISTS movimentos_laser (
        id SERIAL PRIMARY KEY,
        movimento_num INTEGER NOT NULL,
        x_pos INTEGER NOT NULL,
        y_pos INTEGER NOT NULL,
        ts TIMESTAMP
    )
""")
conn.commit()

# === Fila local para mensagens pendentes ===
pending = []

def flush_pending():
    """Tenta gravar todos os payloads enfileirados."""
    global pending
    while pending:
        p = pending[0]
        try:
            cur.execute(
                "INSERT INTO movimentos_laser (movimento_num, x_pos, y_pos, ts) "
                "VALUES (%s, %s, %s, to_timestamp(%s))",
                (p["movimento_num"], p["x_pos"], p["y_pos"], p["ts"])
            )
            conn.commit()
            pending.pop(0)
        except Exception as e:
            print(f"[DB] Falha ao inserir: {e}. Tentarei novamente mais tarde.")
            break

def on_message(client, userdata, msg):
    """Callback: recebe o JSON via MQTT e grava (ou enfileira em caso de falha)."""
    try:
        payload = json.loads(msg.payload)
    except json.JSONDecodeError:
        print(f"[MQTT] Payload inválido: {msg.payload}")
        return

    # Tenta inserir imediatamente
    try:
        cur.execute(
            "INSERT INTO movimentos_laser (movimento_num, x_pos, y_pos, ts) "
            "VALUES (%s, %s, %s, to_timestamp(%s))",
            (payload["movimento_num"],
             payload["x_pos"],
             payload["y_pos"],
             payload["ts"])
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Erro no insert: {e}. Enfileirando payload.")
        pending.append(payload)

# === Setup MQTT ===
client = mqtt.Client()
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.subscribe(MQTT_TOPIC)
client.loop_start()

print(f"[INFO] Inscrito em '{MQTT_TOPIC}'. Gravando no banco…")
try:
    while True:
        time.sleep(1)
        flush_pending()
except KeyboardInterrupt:
    print("Encerrando...")
finally:
    client.loop_stop()
    cur.close()
    conn.close()
