import sys, asyncio
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import math
import time
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import psycopg2
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from pathlib import Path

# === Carrega .env (mesmo diretório deste script) ===
dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path)

# === Configurações da página ===
st.set_page_config(page_title="Laser Tracker", layout="wide")

# === Auto-refresh a cada 2 segundos ===
st_autorefresh(interval=2000, limit=None, key="refresh")

# === Funções de banco de dados ===
def conectar():
    url = os.getenv("DATABASE_URL")
    if not url:
        st.error("DATABASE_URL não definida no .env")
        st.stop()
    try:
        return psycopg2.connect(url)
    except Exception as e:
        st.error(f"Falha ao conectar no banco: {e}")
        st.stop()

# === Função de cálculo de ângulo polar ===
def calcular_angulo(x, y):
    a = math.degrees(math.atan2(y, x))
    return a if a >= 0 else a + 360

# === Cabeçalho do dashboard ===
st.title("📡 Dashboard em Tempo Real - Laser Tracker")
st.caption("Atualiza automaticamente a cada 2 segundos.")

# === Botão para resetar dados ===
if st.button("🗑️ Apagar todos os movimentos e reiniciar ID"):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("TRUNCATE movimentos_laser RESTART IDENTITY")
    conn.commit()
    cur.close()
    conn.close()
    st.success("Dados apagados e contador reiniciado.")
    st.experimental_rerun()

# === Carrega dados do banco ===
conn = conectar()
df = pd.read_sql("SELECT id, x_pos, y_pos, ts FROM movimentos_laser ORDER BY id ASC", conn)
conn.close()

if df.empty:
    st.warning("Nenhum movimento registrado ainda.")
    st.stop()

# === Calcula ângulo ===
df["angulo"] = df.apply(lambda r: calcular_angulo(r["x_pos"], r["y_pos"]), axis=1)

# === Exibe últimos 10 movimentos ===
st.subheader("📋 Últimos Movimentos")
st.dataframe(df[["id","x_pos","y_pos","angulo"]].tail(10), use_container_width=True)

# === Gráfico de evolução dos ângulos ===
st.subheader("📈 Evolução dos Ângulos")
st.line_chart(df.set_index("id")["angulo"])

# === Gráfico de trajetória 2D ===
st.subheader("🧭 Trajetória 2D do Laser")
fig, ax = plt.subplots()
ax.plot(df["x_pos"], df["y_pos"], marker='o', linestyle='-')
ax.set_xlabel('Posição X')
ax.set_ylabel('Posição Y')
ax.set_title('Trajetória do Laser')
ax.grid(True)
ax.set_aspect('equal', adjustable='box')
st.pyplot(fig)
