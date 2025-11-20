import streamlit as st
import json

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# --------- CONFIG STREAMLIT ---------
st.set_page_config(page_title="Casa Inteligente MQTT", layout="wide")
st.title("🏠 Casa Inteligente - Control desde Streamlit")

# --------- CONFIG MQTT ---------
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "cmqtt_a"

st.sidebar.markdown("### 🛰️ Config MQTT")
st.sidebar.write(f"**Broker:** `{MQTT_BROKER}`")
st.sidebar.write(f"**Puerto:** `{MQTT_PORT}`")
st.sidebar.write(f"**Topic:** `{MQTT_TOPIC}`")

if not MQTT_AVAILABLE:
    st.sidebar.error("❌ Falta instalar paho-mqtt\n\nAgrega `paho-mqtt` a `requirements.txt`.")
    st.stop()


@st.cache_resource
def get_mqtt_client():
    """Crea y mantiene un cliente MQTT conectado."""
    try:
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        return client
    except Exception as e:
        st.sidebar.error(f"❌ Error MQTT al conectar: {e}")
        return None


client = get_mqtt_client()
if client is None:
    st.stop()

st.sidebar.success("✅ Cliente MQTT inicializado (lado Python)")

# ---- TEST RÁPIDO MQTT ----
if st.sidebar.button("🔍 Probar envío de prueba"):
    test_payload = {"Act1": "ON", "Act2": "OFF", "Vent": 0, "Analog": 0}
    try:
        client.publish(MQTT_TOPIC, json.dumps(test_payload))
        st.sidebar.success(f"📤 Test enviado: {test_payload}")
    except Exception as e:
        st.sidebar.error(f"❌ Error enviando test MQTT: {e}")

# --------- ESTADO INICIAL ---------
if "devices" not in st.session_state:
    st.session_state.devices = {
        "sala": {
            "luz": False,
            "ventilador": 0,
            "puerta_cerrada": True,
        },
        "habitacion": {
            "luz": False,
        },
    }
if "last_payload" not in st.session_state:
    st.session_state.last_payload = None

devices = st.session_state.devices


def publish_state():
    """Publica el estado completo de la casa en el formato JSON que espera el ESP32."""
    sala = devices["sala"]
    hab = devices["habitacion"]

    payload = {
        "Act1": "ON" if sala["luz"] else "OFF",
        "Act2": "ON" if hab["luz"] else "OFF",
        "Vent": sala["ventilador"],  # 0–3
        "Analog": 0 if sala["puerta_cerrada"] else 100,
    }

    try:
        client.publish(MQTT_TOPIC, json.dumps(payload))
        st.session_state.last_payload = payload
        st.sidebar.success(f"📤 Enviado: {payload}")
        return payload
    except Exception as e:
        st.sidebar.error(f"❌ Error enviando MQTT: {e}")
        return None


# --------- UI PRINCIPAL ---------
col1, col2 = st.columns(2)

# ----- SALA -----
with col1:
    st.subheader("📍 Sala")

    luz_sala = st.toggle("💡 Luz sala encendida", value=devices["sala"]["luz"])
    devices["sala"]["luz"] = luz_sala

    vent = st.slider(
        "🌀 Velocidad ventilador (0=apagado, 1–3)",
        min_value=0,
        max_value=3,
        value=devices["sala"]["ventilador"],
    )
    devices["sala"]["ventilador"] = vent

    puerta_cerrada = st.checkbox(
        "🚪 Puerta cerrada",
        value=devices["sala"]["puerta_cerrada"],
    )
    devices["sala"]["puerta_cerrada"] = puerta_cerrada

    if st.button("📤 Enviar estado SALA al ESP32"):
        payload = publish_state()
        if payload:
            st.code(json.dumps(payload, indent=2), language="json")

# ----- HABITACIÓN -----
with col2:
    st.subheader("📍 Habitación")

    luz_hab = st.toggle(
        "💡 Luz habitación encendida",
        value=devices["habitacion"]["luz"]
    )
    devices["habitacion"]["luz"] = luz_hab

    st.info("La habitación solo controla la luz (LED D4).")

    if st.button("📤 Enviar estado HABITACIÓN al ESP32"):
        payload = publish_state()
        if payload:
            st.code(json.dumps(payload, indent=2), language="json")

st.markdown("---")
st.markdown("### 🔎 Estado actual de la casa")

sala = devices["sala"]
hab = devices["habitacion"]

st.write(
    f"**Sala:** Luz: {'ON' if sala['luz'] else 'OFF'} | "
    f"Ventilador: {sala['ventilador']} | "
    f"Puerta: {'CERRADA' if sala['puerta_cerrada'] else 'ABIERTA'}"
)
st.write(
    f"**Habitación:** Luz: {'ON' if hab['luz'] else 'OFF'}"
)

st.markdown("---")
st.markdown("### 📦 Último JSON enviado al ESP32")
if st.session_state.last_payload is not None:
    st.code(json.dumps(st.session_state.last_payload, indent=2), language="json")
else:
    st.write("Aún no se ha enviado ningún payload.")
