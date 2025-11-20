import streamlit as st
import numpy as np
from PIL import Image
import json
import time

# --------- DEPENDENCIAS OPCIONALES ---------
try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# --------- CONFIG STREAMLIT ---------
st.set_page_config(page_title="Casa Inteligente Multimodal", layout="wide")

# --------- CONFIG MQTT (SINCRONIZADO CON ESP32) ---------
MQTT_BROKER = "broker.emqx.io"  # MISMO QUE EN ARDUINO
MQTT_PORT = 1883
MQTT_TOPIC = "tomasclt"         # MISMO QUE EN ARDUINO

# Variable global para estado de conexión
mqtt_status = {"connected": False, "last_error": ""}


def on_connect(client, userdata, flags, rc):
    """Callback cuando se conecta al broker."""
    if rc == 0:
        mqtt_status["connected"] = True
        mqtt_status["last_error"] = ""
        print(f"✅ Conectado a MQTT broker: {MQTT_BROKER}")
    else:
        mqtt_status["connected"] = False
        mqtt_status["last_error"] = f"Error de conexión: código {rc}"
        print(f"❌ Error MQTT: código {rc}")


def on_disconnect(client, userdata, rc):
    """Callback cuando se desconecta del broker."""
    mqtt_status["connected"] = False
    if rc != 0:
        mqtt_status["last_error"] = "Desconexión inesperada"
        print("⚠️ Desconectado inesperadamente del broker")


@st.cache_resource
def get_mqtt_client():
    """Crea y mantiene un cliente MQTT conectado con callbacks."""
    if not MQTT_AVAILABLE:
        mqtt_status["last_error"] = "paho-mqtt no instalado"
        return None
    
    try:
        client = mqtt.Client(client_id=f"StreamlitCasa-{int(time.time())}")
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        
        print(f"🔄 Conectando a {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        
        # Esperar un momento para la conexión inicial
        time.sleep(1)
        
        return client
    except Exception as e:
        mqtt_status["last_error"] = str(e)
        print(f"❌ Error creando cliente MQTT: {e}")
        return None


def publish_casa_json():
    """
    Envía el estado COMPLETO de la casa al ESP32.
    
    Formato JSON:
    {
      "Act1": "ON"/"OFF",   -> luz sala (LED D2)
      "Act2": "ON"/"OFF",   -> luz habitación (LED D4)
      "Vent": 0-3,          -> ventilador (LED D5)
      "Analog": 0-100       -> puerta servo (D13)
    }
    """
    if not MQTT_AVAILABLE:
        st.sidebar.warning("⚠️ MQTT no disponible (instala: pip install paho-mqtt)")
        return False

    client = get_mqtt_client()
    if client is None:
        st.sidebar.error(f"❌ Cliente MQTT no disponible: {mqtt_status['last_error']}")
        return False

    if not mqtt_status["connected"]:
        st.sidebar.warning("⚠️ MQTT desconectado, reintentando...")
        try:
            client.reconnect()
            time.sleep(0.5)
        except:
            pass

    sala = st.session_state.devices["sala"]
    hab = st.session_state.devices["habitacion"]

    payload = {
        "Act1": "ON" if sala["luz"] else "OFF",
        "Act2": "ON" if hab["luz"] else "OFF",
        "Vent": sala["ventilador"],
        "Analog": 0 if sala["puerta_cerrada"] else 100,
    }

    try:
        json_str = json.dumps(payload)
        result = client.publish(MQTT_TOPIC, json_str, qos=1)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            st.sidebar.success(f"✅ Enviado: {json_str}")
            return True
        else:
            st.sidebar.error(f"❌ Error publicando: código {result.rc}")
            return False
            
    except Exception as e:
        st.sidebar.error(f"❌ Error MQTT: {e}")
        mqtt_status["last_error"] = str(e)
        return False


# --------- TEACHABLE MACHINE (GESTOS) ---------
@st.cache_resource
def load_tm_model():
    """Carga el modelo 'gestos.h5' desde la raíz del proyecto."""
    if not TF_AVAILABLE:
        return None
    try:
        model = tf.keras.models.load_model("gestos.h5", compile=False)
        return model
    except FileNotFoundError:
        st.sidebar.warning("⚠️ Archivo gestos.h5 no encontrado.")
        return None
    except Exception as e:
        st.sidebar.error(f"❌ Error cargando modelo: {e}")
        return None


tm_model = load_tm_model()
TM_AVAILABLE = tm_model is not None and TF_AVAILABLE
TM_CLASSES = ["luz_on", "luz_off", "puerta_abierta", "puerta_cerrada"]


def predict_gesto(image: Image.Image):
    """Clasifica un gesto usando el modelo de TM."""
    if not TM_AVAILABLE:
        return None, 0.0
    try:
        image = image.convert("RGB")
        img = image.resize((224, 224))
        arr = np.array(img) / 255.0
        arr = np.expand_dims(arr, axis=0)
        preds = tm_model.predict(arr)[0]
        idx = int(np.argmax(preds))
        return TM_CLASSES[idx], float(preds[idx])
    except Exception as e:
        st.error(f"Error prediciendo gesto: {e}")
        return None, 0.0


# --------- ESTADO INICIAL ---------
if "devices" not in st.session_state:
    st.session_state.devices = {
        "sala": {
            "luz": False,
            "brillo": 50,
            "ventilador": 1,
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


# --------- COMANDOS DE TEXTO ---------
def ejecutar_comando(comando: str):
    """Procesa comandos de texto y actualiza dispositivos."""
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
    if "encender luz" in comando or "enciende luz" in comando or "luz on" in comando:
        dev["luz"] = True
    if "apagar luz" in comando or "apaga luz" in comando or "luz off" in comando:
        dev["luz"] = False

    # Ventilador
    if "subir ventilador" in comando or "sube ventilador" in comando:
        dev["ventilador"] = min(3, dev["ventilador"] + 1)
    if "bajar ventilador" in comando or "baja ventilador" in comando:
        dev["ventilador"] = max(0, dev["ventilador"] - 1)
    if "apagar ventilador" in comando or "apaga ventilador" in comando:
        dev["ventilador"] = 0
    if ("encender ventilador" in comando or "enciende ventilador" in comando) and dev["ventilador"] == 0:
        dev["ventilador"] = 1

    # Puerta
    if "abrir puerta" in comando or "abre puerta" in comando:
        devices["sala"]["puerta_cerrada"] = False
    if "cerrar puerta" in comando or "cierra puerta" in comando:
        devices["sala"]["puerta_cerrada"] = True

    if publish_casa_json():
        st.success(f"✅ Comando ejecutado en {room.capitalize()}")
    else:
        st.error("❌ Error al enviar comando al ESP32")


# --------- SIDEBAR ---------
st.sidebar.title("🏠 Casa Inteligente")

pagina = st.sidebar.radio(
    "📍 Navegación",
    ["Panel general", "Control por ambiente", "Control por gestos (TM)"],
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎤 Comando de texto")
texto_cmd = st.sidebar.text_input(
    "Escribe tu comando",
    placeholder="Ej: encender luz sala"
)
if st.sidebar.button("▶️ Ejecutar comando"):
    if texto_cmd.strip():
        ejecutar_comando(texto_cmd)
    else:
        st.sidebar.warning("⚠️ Escribe un comando primero.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📡 Estado del Sistema")

if MQTT_AVAILABLE:
    st.sidebar.success("✅ paho-mqtt instalado")
    
    client = get_mqtt_client()
    if client and mqtt_status["connected"]:
        st.sidebar.success("✅ MQTT conectado")
    else:
        st.sidebar.error(f"❌ MQTT desconectado")
        if mqtt_status["last_error"]:
            st.sidebar.caption(f"Error: {mqtt_status['last_error']}")
else:
    st.sidebar.error("❌ Instala: pip install paho-mqtt")

if TF_AVAILABLE:
    st.sidebar.success("✅ TensorFlow disponible")
else:
    st.sidebar.warning("⚠️ TensorFlow no disponible")

if TM_AVAILABLE:
    st.sidebar.success("✅ Modelo gestos.h5 cargado")
else:
    st.sidebar.warning("⚠️ Modelo gestos.h5 no disponible")

st.sidebar.info(f"**Broker:** {MQTT_BROKER}:{MQTT_PORT}\n**Topic:** {MQTT_TOPIC}")

if st.sidebar.button("🔄 Reconectar MQTT"):
    st.cache_resource.clear()
    st.rerun()


# --------- PÁGINA 1: PANEL GENERAL ---------
if pagina == "Panel general":
    st.title("🏠 Panel General - Casa Inteligente")
    st.markdown("Control centralizado de todos los ambientes")

    col1, col2 = st.columns(2)

    for room, col in zip(["sala", "habitacion"], [col1, col2]):
        dev = devices[room]
        with col:
            st.subheader(f"📍 {room.capitalize()}")

            luz_estado = "🟢 Encendida" if dev["luz"] else "🔴 Apagada"
            puerta_estado = "🔒 Cerrada" if dev["puerta_cerrada"] else "🔓 Abierta"
            vent_estado = "❌ Apagado" if dev["ventilador"] == 0 else f"🌀 Velocidad {dev['ventilador']}"
            presencia_estado = "👤 Presente" if dev["presencia"] else "🚫 Ausente"

            st.metric("💡 Luz", luz_estado)
            st.metric("🌀 Ventilador", vent_estado)
            st.metric("🚪 Puerta", puerta_estado)
            st.metric("🔍 Sensor", presencia_estado)

            st.markdown("---")

            c1, c2 = st.columns(2)

            with c1:
                luz_label = "💡 Apagar" if dev["luz"] else "💡 Encender"
                if st.button(luz_label, key=f"btn_luz_{room}"):
                    dev["luz"] = not dev["luz"]
                    publish_casa_json()
                    st.rerun()

            with c2:
                puerta_label = "🔓 Abrir" if dev["puerta_cerrada"] else "🔒 Cerrar"
                if st.button(puerta_label, key=f"btn_puerta_{room}"):
                    dev["puerta_cerrada"] = not dev["puerta_cerrada"]
                    devices["sala"]["puerta_cerrada"] = dev["puerta_cerrada"]
                    publish_casa_json()
                    st.rerun()

    st.markdown("---")
    st.subheader("🔌 Mapa de Hardware ESP32")
    st.info(
        "**Conexiones físicas:**\n\n"
        "• 💡 **Luz sala** → LED rojo D2 (Act1)\n"
        "• 💡 **Luz habitación** → LED amarillo D4 (Act2)\n"
        "• 🌀 **Ventilador** → LED verde D5 (Vent > 0)\n"
        "• 🚪 **Puerta** → Servo D13 (Analog: 0=cerrada, 100=abierta)\n\n"
        f"• 📡 **MQTT:** `{MQTT_BROKER}:{MQTT_PORT}` → Topic: `{MQTT_TOPIC}`"
    )


# --------- PÁGINA 2: CONTROL POR AMBIENTE ---------
elif pagina == "Control por ambiente":
    st.title("🎛️ Control Detallado por Ambiente")

    room = st.selectbox("📍 Selecciona el ambiente", ["sala", "habitacion"],
                        format_func=lambda x: x.capitalize())
    dev = devices[room]

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 💡 Iluminación")
        nueva_luz = st.toggle("Luz encendida", value=dev["luz"], key=f"toggle_luz_{room}")
        if nueva_luz != dev["luz"]:
            dev["luz"] = nueva_luz
            publish_casa_json()

        dev["brillo"] = st.slider("Brillo (%)", 0, 100, dev["brillo"], key=f"brillo_{room}")

    with col2:
        st.markdown("#### 🌀 Ventilación")
        nuevo_vent = st.slider(
            "Velocidad (0=apagado)",
            0, 3, dev["ventilador"],
            key=f"vent_{room}"
        )
        if nuevo_vent != dev["ventilador"]:
            dev["ventilador"] = nuevo_vent
            if room == "sala":
                devices["sala"]["ventilador"] = nuevo_vent
            publish_casa_json()

    st.markdown("---")

    col3, col4 = st.columns(2)

    with col3:
        st.markdown("#### 🚪 Puerta (Sala)")
        puerta_label = "🔒 Cerrada" if devices["sala"]["puerta_cerrada"] else "🔓 Abierta"
        if st.button(f"Cambiar estado: {puerta_label}", key="btn_puerta_det"):
            devices["sala"]["puerta_cerrada"] = not devices["sala"]["puerta_cerrada"]
            publish_casa_json()
            st.rerun()

    with col4:
        st.markdown("#### 🔍 Sensor de Presencia")
        dev["presencia"] = st.checkbox(
            "Simular persona presente",
            value=dev["presencia"],
            key=f"presencia_{room}"
        )

    st.markdown("---")
    st.markdown("### 📊 Estado Actual")

    payload_actual = {
        "Act1": "ON" if devices["sala"]["luz"] else "OFF",
        "Act2": "ON" if devices["habitacion"]["luz"] else "OFF",
        "Vent": devices["sala"]["ventilador"],
        "Analog": 0 if devices["sala"]["puerta_cerrada"] else 100,
    }
    
    st.code(json.dumps(payload_actual, indent=2), language="json")


# --------- PÁGINA 3: CONTROL POR GESTOS ---------
else:
    st.title("👋 Control por Gestos - Teachable Machine")

    if not TM_AVAILABLE:
        st.error("❌ El control por gestos no está disponible.")
        st.info(
            "**Requisitos:**\n\n"
            "1. `pip install tensorflow`\n"
            "2. Coloca `gestos.h5` en la raíz del proyecto\n"
            "3. Reinicia la aplicación"
        )
    else:
        st.markdown(
            "**Gestos disponibles para controlar LA SALA:**\n\n"
            "• 💡 `luz_on` → ✊ Puño cerrado → Enciende luz\n"
            "• 💡 `luz_off` → ✋ Mano abierta → Apaga luz\n"
            "• 🚪 `puerta_abierta` → 👍 Pulgar arriba → Abre puerta\n"
            "• 🚪 `puerta_cerrada` → 👎 Pulgar abajo → Cierra puerta"
        )

        foto = st.camera_input("📸 Captura tu gesto")

        if foto is not None:
            image = Image.open(foto)
            st.image(image, caption="Imagen capturada", width=300)

            with st.spinner("🔍 Analizando gesto..."):
                clase, prob = predict_gesto(image)

            if clase:
                st.success(f"**Gesto:** `{clase}` | **Confianza:** {prob:.1%}")

                dev_sala = devices["sala"]

                if clase == "luz_on":
                    dev_sala["luz"] = True
                elif clase == "luz_off":
                    dev_sala["luz"] = False
                elif clase == "puerta_abierta":
                    dev_sala["puerta_cerrada"] = False
                elif clase == "puerta_cerrada":
                    dev_sala["puerta_cerrada"] = True

                if publish_casa_json():
                    st.markdown("---")
                    st.markdown("### ✅ JSON enviado al ESP32")
                    payload = {
                        "Act1": "ON" if dev_sala["luz"] else "OFF",
                        "Act2": "ON" if devices["habitacion"]["luz"] else "OFF",
                        "Vent": dev_sala["ventilador"],
                        "Analog": 0 if dev_sala["puerta_cerrada"] else 100,
                    }
                    st.code(json.dumps(payload, indent=2), language="json")

st.markdown("---")
st.markdown("### 📦 Último JSON enviado al ESP32")
if st.session_state.last_payload is not None:
    st.code(json.dumps(st.session_state.last_payload, indent=2), language="json")
else:
    st.write("Aún no se ha enviado ningún payload.")
