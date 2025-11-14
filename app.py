import json
import paho.mqtt.client as mqtt

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "cmqtt_a"

# ---------------- MQTT CLIENT ----------------
@st.cache_resource
def get_mqtt_client():
    client = mqtt.Client()
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    return client


def publish_to_wokwi():
    """Envía el estado actual de la casa hacia el ESP32 vía MQTT."""
    sala = st.session_state.devices["sala"]
    hab = st.session_state.devices["habitacion"]

    payload = {
        "Act1": "ON" if sala["luz"] else "OFF",
        "Act2": "ON" if hab["luz"] else "OFF",
        "Act3": "ON" if sala["ventilador"] > 0 else "OFF",
        "Analog": 0 if sala["puerta_cerrada"] else 100
    }

    client = get_mqtt_client()
    client.publish(MQTT_TOPIC, json.dumps(payload))
    st.success("Datos enviados al ESP32 vía MQTT")
