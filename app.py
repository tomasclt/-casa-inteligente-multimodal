import streamlit as st
import numpy as np
from PIL import Image
import json

# Intentar cargar dependencias opcionales
try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False
    st.sidebar.warning("⚠️ TensorFlow no instalado. Control por gestos deshabilitado.")

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    st.sidebar.error("⚠️ paho-mqtt no instalado. Instala con: pip install paho-mqtt")

# ---------------- CONFIG STREAMLIT ----------------
st.set_page_config(page_title="Casa Inteligente Multimodal", layout="wide")

# ---------------- CONFIG MQTT ----------------
MQTT_BROKER = "157.230.214.127"  # El mismo que en el ESP32
MQTT_PORT = 1883
MQTT_TOPIC = "cmqtt_a"           # Topic al que está suscrito el ESP32


@st.cache_resource
def get_mqtt_client():
    """Crea y mantiene un cliente MQTT conectado."""
    if not MQTT_AVAILABLE:
        return None
    
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        return client
    except Exception as e:
        st.sidebar.error(f"❌ Error MQTT: {e}")
        return None


def publish_sala_json():
    """
    Envía el estado de la SALA en el formato que espera el ESP32:

    {
      "Act1": "ON"/"OFF",   -> luz sala (GPIO2)
      "Analog": 0-100       -> puerta sala (servo GPIO13)
    }
    """
    if not MQTT_AVAILABLE:
        st.sidebar.warning("⚠️ MQTT no disponible")
        return
    
    client = get_mqtt_client()
    if client is None:
        return
    
    sala = st.session_state.devices["sala"]

    act1 = "ON" if sala["luz"] else "OFF"
    analog = 0 if sala["puerta_cerrada"] else 100

    payload = {
        "Act1": act1,
        "Analog": analog,
    }

    try:
        result = client.publish(MQTT_TOPIC, json.dumps(payload))
        if result.rc == 0:
            st.sidebar.success(f"✅ Enviado: {payload}")
        else:
            st.sidebar.error(f"❌ Error enviando: rc={result.rc}")
    except Exception as e:
        st.sidebar.error(f"❌ Error: {e}")


# ---------------- CARGA MODELO TEACHABLE MACHINE ----------------
@st.cache_resource
def load_tm_model():
    """
    Carga el modelo 'gestos.h5' desde la raíz del repo.
    Si falla, devuelve None.
    """
    if not TF_AVAILABLE:
        return None
    
    try:
        model = tf.keras.models.load_model("gestos.h5", compile=False)
        return model
    except Exception as e:
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
        st.error(f"Error prediciendo: {e}")
        return None, 0.0


# ---------------- ESTADO INICIAL ----------------
if "devices" not in st.session_state:
    st.session_state.devices = {
        "sala": {
            "luz": False,
            "brillo": 50,
            "ventilador": 1,     # 0=apagado, 1-3 velocidad
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
        dev["puerta_cerrada"] = False
    if "cerrar puerta" in comando or "cierra puerta" in comando:
        dev["puerta_cerrada"] = True

    # Publicar cambios si es la sala
    if room == "sala":
        publish_sala_json()

    st.success(f"✅ Comando aplicado en {room.capitalize()}")


# ---------------- SIDEBAR ----------------
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
    st.sidebar.success("✅ MQTT disponible")
else:
    st.sidebar.error("❌ MQTT no instalado")

if TF_AVAILABLE:
    st.sidebar.success("✅ TensorFlow disponible")
else:
    st.sidebar.warning("⚠️ TensorFlow no instalado")

if TM_AVAILABLE:
    st.sidebar.success("✅ Modelo gestos cargado")
else:
    st.sidebar.warning("⚠️ Modelo gestos.h5 no encontrado")

st.sidebar.info(f"**Broker:** {MQTT_BROKER}\n**Topic:** {MQTT_TOPIC}")


# ---------------- PÁGINA 1: PANEL GENERAL ----------------
if pagina == "Panel general":
    st.title("🏠 Panel General - Casa Inteligente")
    st.markdown("Control centralizado de todos los ambientes")

    col1, col2 = st.columns(2)

    for room, col in zip(["sala", "habitacion"], [col1, col2]):
        dev = devices[room]
        with col:
            st.subheader(f"📍 {room.capitalize()}")
            
            # Métricas visuales
            luz_estado = "🟢 Encendida" if dev["luz"] else "🔴 Apagada"
            puerta_estado = "🔒 Cerrada" if dev["puerta_cerrada"] else "🔓 Abierta"
            vent_estado = "❌ Apagado" if dev["ventilador"] == 0 else f"🌀 Velocidad {dev['ventilador']}"
            presencia = "👤 Presente" if dev["presencia"] else "🚫 Ausente"

            st.metric("💡 Luz", luz_estado)
            st.metric("🌀 Ventilador", vent_estado)
            st.metric("🚪 Puerta", puerta_estado)
            st.metric("🔍 Sensor", presencia)

            st.markdown("---")
            
            # Controles rápidos
            c1, c2 = st.columns(2)
            
            # Luz
            with c1:
                luz_label = "💡 Apagar" if dev["luz"] else "💡 Encender"
                if st.button(luz_label, key=f"btn_luz_{room}"):
                    dev["luz"] = not dev["luz"]
                    if room == "sala":
                        publish_sala_json()
                    st.rerun()
            
            # Puerta
            with c2:
                puerta_label = "🔓 Abrir" if dev["puerta_cerrada"] else "🔒 Cerrar"
                if st.button(puerta_label, key=f"btn_puerta_{room}"):
                    dev["puerta_cerrada"] = not dev["puerta_cerrada"]
                    if room == "sala":
                        publish_sala_json()
                    st.rerun()

    st.markdown("---")
    st.subheader("🔌 Simulación Física (ESP32 + Wokwi + MQTT)")
    st.info(
        "**La SALA está conectada físicamente:**\n\n"
        "• 💡 **Luz sala** → LED GPIO2 del ESP32 (JSON: `Act1`)\n\n"
        "• 🚪 **Puerta sala** → Servo GPIO13 del ESP32 (JSON: `Analog`)\n\n"
        f"• 📡 **Comunicación:** Topic `{MQTT_TOPIC}` en `{MQTT_BROKER}`"
    )


# ---------------- PÁGINA 2: CONTROL POR AMBIENTE ----------------
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
            if room == "sala":
                publish_sala_json()
        
        dev["brillo"] = st.slider("Brillo (%)", 0, 100, dev["brillo"], key=f"brillo_{room}")
        
    with col2:
        st.markdown("#### 🌀 Ventilación")
        dev["ventilador"] = st.slider(
            "Velocidad (0=apagado)", 
            0, 3, dev["ventilador"], 
            key=f"vent_{room}"
        )
    
    st.markdown("---")
    
    col3, col4 = st.columns(2)
    
    with col3:
        st.markdown("#### 🚪 Puerta")
        puerta_label = "🔒 Cerrada" if dev["puerta_cerrada"] else "🔓 Abierta"
        if st.button(f"Cambiar estado: {puerta_label}", key=f"btn_puerta_det_{room}"):
            dev["puerta_cerrada"] = not dev["puerta_cerrada"]
            if room == "sala":
                publish_sala_json()
            st.rerun()
    
    with col4:
        st.markdown("#### 🔍 Sensor de Presencia")
        dev["presencia"] = st.checkbox(
            "Simular persona presente", 
            value=dev["presencia"],
            key=f"presencia_{room}"
        )

    if room == "sala":
        if st.button("📤 Enviar estado al ESP32"):
            publish_sala_json()

    st.markdown("---")
    st.markdown("### 📊 Estado Actual")
    st.write(
        f"💡 **Luz:** {'🟢 Encendida' if dev['luz'] else '🔴 Apagada'} (Brillo: {dev['brillo']}%) | "
        f"🌀 **Ventilador:** {'❌ Apagado' if dev['ventilador'] == 0 else f'Velocidad {dev[\"ventilador\"]}'} | "
        f"🚪 **Puerta:** {'🔒 Cerrada' if dev['puerta_cerrada'] else '🔓 Abierta'} | "
        f"🔍 **Presencia:** {'👤 Sí' if dev['presencia'] else '🚫 No'}"
    )


# ---------------- PÁGINA 3: CONTROL POR GESTOS ----------------
else:
    st.title("👋 Control por Gestos - Teachable Machine")

    if not TM_AVAILABLE:
        st.error("❌ El control por gestos no está disponible.")
        st.info(
            "**Requisitos faltantes:**\n\n"
            "1. Instala TensorFlow: `pip install tensorflow`\n\n"
            "2. Coloca el archivo `gestos.h5` en la raíz del proyecto\n\n"
            "3. Reinicia la aplicación"
        )
    else:
        st.markdown(
            "Usa gestos frente a la cámara para controlar **la sala** (físicamente en Wokwi):\n\n"
            "• 💡 **luz_on** → ✊ Puño cerrado → Enciende la luz (LED GPIO2)\n\n"
            "• 💡 **luz_off** → ✋ Mano abierta → Apaga la luz (LED GPIO2)\n\n"
            "• 🚪 **puerta_abierta** → 👍 Pulgar arriba → Abre la puerta (Servo 180°)\n\n"
            "• 🚪 **puerta_cerrada** → 👎 Pulgar abajo → Cierra la puerta (Servo 0°)\n\n"
            "**Los cambios se envían automáticamente al ESP32 en Wokwi vía MQTT.**"
        )

        foto = st.camera_input("📸 Haz tu gesto y toma la foto")

        if foto is not None:
            image = Image.open(foto)
            st.image(image, caption="Imagen capturada", width=300)
            
            with st.spinner("🔍 Analizando gesto..."):
                clase, prob = predict_gesto(image)

            if clase:
                st.success(f"🎯 **Gesto detectado:** `{clase}` (Confianza: {prob:.2%})")

                dev = devices["sala"]

                if clase == "luz_on":
                    dev["luz"] = True
                    st.info("💡 **Acción:** Luz de la sala ENCENDIDA → LED GPIO2 en Wokwi")
                elif clase == "luz_off":
                    dev["luz"] = False
                    st.info("💡 **Acción:** Luz de la sala APAGADA → LED GPIO2 en Wokwi")
                elif clase == "puerta_abierta":
                    dev["puerta_cerrada"] = False
                    st.info("🚪 **Acción:** Puerta ABIERTA → Servo a 180° en GPIO13 Wokwi")
                elif clase == "puerta_cerrada":
                    dev["puerta_cerrada"] = True
                    st.info("🚪 **Acción:** Puerta CERRADA → Servo a 0° en GPIO13 Wokwi")

                publish_sala_json()

                st.markdown("---")
                st.markdown("### 📊 Estado Actual de la Sala (Físico en Wokwi)")
                
                # Mostrar JSON enviado
                payload_enviado = {
                    "Act1": "ON" if dev['luz'] else "OFF",
                    "Analog": 0 if dev['puerta_cerrada'] else 100
                }
                st.code(json.dumps(payload_enviado, indent=2), language="json")
                
                st.write(
                    f"💡 **Luz (LED GPIO2):** {'🟢 ON' if dev['luz'] else '🔴 OFF'} | "
                    f"🚪 **Puerta (Servo GPIO13):** {'🔒 Cerrada (0°)' if dev['puerta_cerrada'] else '🔓 Abierta (180°)'}"
                )
