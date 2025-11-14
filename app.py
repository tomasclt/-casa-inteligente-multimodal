import streamlit as st
import numpy as np
from PIL import Image
import tensorflow as tf
import paho.mqtt.client as mqtt
import json

# ---------------- CONFIGURACIÓN STREAMLIT ----------------
st.set_page_config(page_title="Casa Inteligente Multimodal", layout="wide")

# ---------------- CONFIGURACIÓN MQTT ----------------
MQTT_BROKER = "broker.hivemq.com"   # Debe ser el mismo en el ESP32
MQTT_PORT = 1883
MQTT_TOPIC = "cmqtt_a"              # Topic que escucha tu ESP32 (cmqtt_a)


@st.cache_resource
def get_mqtt_client():
    """
    Crea y mantiene un cliente MQTT conectado.
    Se ejecuta una sola vez gracias a cache_resource.
    """
    client = mqtt.Client()
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    return client


def publish_sala_json():
    """
    Envía por MQTT el estado de la SALA en formato JSON:
    {
      "Act1": "ON"/"OFF",   -> Luz sala
      "Analog": 0-100       -> Puerta sala (0 cerrada, 100 abierta)
    }
    Este formato es el que espera tu código de ESP32 en Wokwi.
    """
    client = get_mqtt_client()
    sala = st.session_state.devices["sala"]

    act1 = "ON" if sala["luz"] else "OFF"
    analog = 0 if sala["puerta_cerrada"] else 100

    payload = {
        "Act1": act1,
        "Analog": analog,
    }

    client.publish(MQTT_TOPIC, json.dumps(payload))


# ---------------- CARGA DEL MODELO TM ----------------
@st.cache_resource
def load_tm_model():
    """
    Carga el modelo de Teachable Machine desde gestos.h5 en la raíz del repo.
    Si falla, devolvemos None y la app sigue funcionando sin la parte de gestos.
    """
    try:
        model = tf.keras.models.load_model("gestos.h5", compile=False)
        return model
    except Exception as e:
        st.sidebar.error(f"No se pudo cargar gestos.h5: {e}")
        return None


tm_model = load_tm_model()
TM_AVAILABLE = tm_model is not None

TM_CLASSES = ["luz_on", "luz_off", "ventilador_on", "ventilador_off"]


def predict_gesto(image: Image.Image):
    """
    Pasa una imagen por el modelo de TM y devuelve (clase, probabilidad).
    """
    image = image.convert("RGB")
    img = image.resize((224, 224))
    arr = np.array(img) / 255.0
    arr = np.expand_dims(arr, axis=0)

    preds = tm_model.predict(arr)[0]
    idx = int(np.argmax(preds))
    return TM_CLASSES[idx], float(preds[idx])


# ---------------- ESTADO INICIAL DE DISPOSITIVOS ----------------
if "devices" not in st.session_state:
    st.session_state.devices = {
        "sala": {
            "luz": False,
            "brillo": 50,
            "ventilador": 1,    # 0=apagado, 1-3 velocidad
            "puerta_cerrada": True,
            "presencia": False,
        },
        "habitacion": {
            "luz": False,
            "brillo": 50,
            "ventilador": 1,
            "puerta_cerrada": True,
            "presencia": False,
        },
    }

devices = st.session_state.devices


# ---------------- COMANDOS DE TEXTO ----------------
def ejecutar_comando(comando: str):
    comando = comando.lower().strip()

    if "sala" in comando:
        room = "sala"
    elif "habitacion" in comando or "habitación" in comando or "cuarto" in comando:
        room = "habitacion"
    else:
        st.warning("👉 Especifica 'sala' u 'habitación' en el comando.")
        return

    dev = devices[room]

    # Luz
    if "encender luz" in comando:
        dev["luz"] = True
    if "apagar luz" in comando:
        dev["luz"] = False

    # Ventilador
    if "subir ventilador" in comando:
        dev["ventilador"] = min(3, dev["ventilador"] + 1)
    if "bajar ventilador" in comando:
        dev["ventilador"] = max(0, dev["ventilador"] - 1)
    if "apagar ventilador" in comando:
        dev["ventilador"] = 0
    if "encender ventilador" in comando and dev["ventilador"] == 0:
        dev["ventilador"] = 1

    # Puerta
    if "abrir puerta" in comando and room == "sala":
        dev["puerta_cerrada"] = False
    if "cerrar puerta" in comando and room == "sala":
        dev["puerta_cerrada"] = True

    # Solo publicamos MQTT para la sala (la que está conectada al ESP32)
    if room == "sala":
        publish_sala_json()

    st.success(f"✅ Comando aplicado en {room.capitalize()}")


# ---------------- SIDEBAR ----------------
st.sidebar.title("Casa Inteligente")

pagina = st.sidebar.radio(
    "Navegación",
    ["Panel general", "Control por ambiente", "Control por gestos (TM)"],
)

st.sidebar.markdown("### Comando de texto")
texto_cmd = st.sidebar.text_input(
    "Ejemplo: 'encender luz sala', 'cerrar puerta habitación'"
)
if st.sidebar.button("Ejecutar comando"):
    if texto_cmd.strip():
        ejecutar_comando(texto_cmd)
    else:
        st.sidebar.warning("Escribe un comando primero.")


# ---------------- PÁGINA 1: PANEL GENERAL ----------------
if pagina == "Panel general":
    st.title("Panel general de la casa inteligente")

    col1, col2 = st.columns(2)

    for room, col in zip(["sala", "habitacion"], [col1, col2]):
        dev = devices[room]
        with col:
            st.subheader(room.capitalize())
            luz_estado = "Encendida 💡" if dev["luz"] else "Apagada 💡"
            puerta_estado = "Cerrada 🔒" if dev["puerta_cerrada"] else "Abierta 🔓"
            vent_estado = "Apagado 🌀" if dev["ventilador"] == 0 else f"Velocidad {dev['ventilador']} 🌀"
            presencia = "Persona detectada 🧍" if dev["presencia"] else "Sin presencia"

            st.metric("Luz", luz_estado)
            st.metric("Ventilador", vent_estado)
            st.metric("Puerta", puerta_estado)
            st.metric("Sensor", presencia)

            c1, c2 = st.columns(2)
            # Botón sala/habitación
            with c1:
                if st.button(f"Luz ON/OFF {room}", key=f"btn_luz_{room}"):
                    dev["luz"] = not dev["luz"]
                    if room == "sala":
                        publish_sala_json()
            with c2:
                if st.button(f"Abrir/Cerrar puerta {room}", key=f"btn_puerta_{room}"):
                    dev["puerta_cerrada"] = not dev["puerta_cerrada"]
                    if room == "sala":
                        publish_sala_json()

    st.markdown("---")
    st.subheader("Simulación física (WOKWI + MQTT)")
    st.write(
        "La SALA está conectada a un ESP32 en Wokwi mediante MQTT.\n\n"
        "- Luz sala → LED en el pin 2 del ESP32\n"
        "- Puerta sala → Servo en el pin 13 del ESP32\n"
        "La app envía mensajes JSON al topic `cmqtt_a` del broker "
        f"`{MQTT_BROKER}` para actualizar el hardware simulado."
    )


# ---------------- PÁGINA 2: CONTROL POR AMBIENTE ----------------
elif pagina == "Control por ambiente":
    st.title("Control detallado por ambiente")

    room = st.selectbox("Selecciona el ambiente", ["sala", "habitacion"])
    dev = devices[room]

    st.subheader(f"Configuración de {room.capitalize()}")

    dev["luz"] = st.toggle("Luz encendida", value=dev["luz"])
    dev["brillo"] = st.slider("Brillo de la luz", 0, 100, dev["brillo"])
    dev["ventilador"] = st.slider(
        "Velocidad ventilador (0 = apagado)", 0, 3, dev["ventilador"]
    )

    puerta_label = "Puerta cerrada" if dev["puerta_cerrada"] else "Puerta abierta"
    if st.button(puerta_label, key=f"btn_puerta_detalle_{room}"):
        dev["puerta_cerrada"] = not dev["puerta_cerrada"]

    dev["presencia"] = st.checkbox(
        "Simular persona presente", value=dev["presencia"]
    )

    # Publicar MQTT solo si es la sala
    if room == "sala":
        publish_sala_json()

    st.markdown("### Vista visual")
    st.write(
        f"💡 Luz: {'Encendida' if dev['luz'] else 'Apagada'} | "
        f"🔒 Puerta: {'Cerrada' if dev['puerta_cerrada'] else 'Abierta'} | "
        f"🌀 Ventilador: {dev['ventilador']} | "
        f"🧍 Presencia: {'Sí' if dev['presencia'] else 'No'}"
    )


# ---------------- PÁGINA 3: CONTROL POR GESTOS (TM) ----------------
else:
    st.title("Control por gestos con Teachable Machine")

    if not TM_AVAILABLE:
        st.error("No se pudo cargar el modelo de Teachable Machine (gestos.h5).")
    else:
        st.markdown(
            "Usa gestos frente a la cámara para controlar **la sala**:\n"
            "- `luz_on` / `luz_off`\n"
            "- `ventilador_on` / `ventilador_off` (solo se refleja en la app)\n"
            "La luz y la puerta pueden enviarse al ESP32 a través de MQTT."
        )

        foto = st.camera_input("Haz tu gesto y toma la foto")

        if foto is not None:
            image = Image.open(foto)
            clase, prob = predict_gesto(image)

            st.write(f"🔍 Modelo detectó: **{clase}** (confianza: {prob:.2f})")

            dev = devices["sala"]

            if clase == "luz_on":
                dev["luz"] = True
            elif clase == "luz_off":
                dev["luz"] = False
            elif clase == "ventilador_on":
                dev["ventilador"] = max(dev["ventilador"], 1)
            elif clase == "ventilador_off":
                dev["ventilador"] = 0

            # Enviamos estado de la sala al ESP32 (luz y puerta)
            publish_sala_json()

            st.success("Estado de la sala actualizado y enviado por MQTT.")
            st.write(
                f"💡 Luz sala: {'Encendida' if dev['luz'] else 'Apagada'} | "
                f"🌀 Ventilador sala: {dev['ventilador']} | "
                f"🚪 Puerta sala: {'Cerrada' if dev['puerta_cerrada'] else 'Abierta'}"
            )

        st.markdown("---")
        st.caption(
            "Este módulo demuestra control multimodal: interfaz gráfica, comandos de texto "
            "y reconocimiento de gestos usando Teachable Machine."
        )
