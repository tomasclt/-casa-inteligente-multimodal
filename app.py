import streamlit as st
import numpy as np
from PIL import Image
import json
import time

# --------- DEPENDENCIAS OPCIONALES ---------
# OPCIÓN A: Sin TensorFlow (desactiva gestos, MQTT funciona perfectamente)
TF_AVAILABLE = False
TM_AVAILABLE = False

# OPCIÓN B: Descomenta esto si quieres usar gestos (requiere tensorflow-cpu en requirements)
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
MQTT_BROKER = "broker.emqx.io"  # MISMO QUE ARDUINO
MQTT_PORT = 1883
MQTT_TOPIC = "tomasclt"         # MISMO QUE ARDUINO

# Estado de conexión
mqtt_status = {"connected": False, "last_error": "", "last_message": ""}


def on_connect(client, userdata, flags, rc):
    """Callback cuando se conecta al broker."""
    if rc == 0:
        mqtt_status["connected"] = True
        mqtt_status["last_error"] = ""
    else:
        mqtt_status["connected"] = False
        mqtt_status["last_error"] = f"Error código {rc}"


def on_disconnect(client, userdata, rc):
    """Callback cuando se desconecta."""
    mqtt_status["connected"] = False
    if rc != 0:
        mqtt_status["last_error"] = "Desconexión inesperada"


def on_publish(client, userdata, mid):
    """Callback cuando se publica un mensaje."""
    mqtt_status["last_message"] = f"Mensaje {mid} enviado"


@st.cache_resource
def get_mqtt_client():
    """Crea y mantiene un cliente MQTT conectado."""
    if not MQTT_AVAILABLE:
        mqtt_status["last_error"] = "paho-mqtt no instalado"
        return None

    try:
        # Cliente único por sesión
        client = mqtt.Client(client_id=f"StreamlitCasa-{int(time.time() * 1000)}")
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_publish = on_publish

        # Conectar al broker
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()

        # Dar tiempo para conectar
        for _ in range(20):  # Esperar máximo 2 segundos
            if mqtt_status["connected"]:
                break
            time.sleep(0.1)

        return client
    except Exception as e:
        mqtt_status["last_error"] = str(e)
        return None


def publish_casa_json():
    """
    Envía JSON al ESP32 vía MQTT.

    Formato:
    {
      "Act1": "ON"/"OFF",   -> Luz sala (LED D2 rojo)
      "Act2": "ON"/"OFF",   -> Luz habitación (LED D4 amarillo)
      "Vent": 0-3,          -> Ventilador (LED D5 verde)
      "Analog": 0-100       -> Puerta (Servo D13)
    }
    """
    if not MQTT_AVAILABLE:
        st.sidebar.warning("⚠️ Instala paho-mqtt: `pip install paho-mqtt`")
        return False

    client = get_mqtt_client()
    if client is None:
        st.sidebar.error("❌ Cliente MQTT no disponible")
        return False

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

        # Esperar confirmación
        result.wait_for_publish(timeout=2)

        if result.is_published():
            st.sidebar.success(f"✅ Enviado: `{json_str}`")
            return True
        else:
            st.sidebar.error("❌ Mensaje no confirmado")
            return False

    except Exception as e:
        st.sidebar.error(f"❌ Error: {str(e)[:50]}")
        return False


# --------- TEACHABLE MACHINE (SOLO SI TF_AVAILABLE=True) ---------
@st.cache_resource
def load_tm_model():
    """Carga modelo de gestos (requiere TensorFlow)."""
    if not TF_AVAILABLE:
        return None
    try:
        import tensorflow as tf
        model = tf.keras.models.load_model("gestos.h5", compile=False)
        return model
    except Exception:
        return None


tm_model = load_tm_model() if TF_AVAILABLE else None
TM_AVAILABLE = tm_model is not None
TM_CLASSES = ["luz_on", "luz_off", "puerta_abierta", "puerta_cerrada"]


def predict_gesto(image: Image.Image):
    """Clasifica gesto (requiere modelo cargado)."""
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
        st.error(f"Error: {e}")
        return None, 0.0


# --------- ESTADO INICIAL ---------
if "devices" not in st.session_state:
    st.session_state.devices = {
        "sala": {
            "luz": False,
            "brillo": 50,
            "ventilador": 0,
            "puerta_cerrada": True,
            "presencia": False,
        },
        "habitacion": {
            "luz": False,
            "brillo": 50,
            "ventilador": 0,
            "puerta_cerrada": True,
            "presencia": False,
        },
    }

devices = st.session_state.devices


# --------- COMANDOS DE TEXTO ---------
def ejecutar_comando(comando: str):
    """Procesa comandos de voz/texto."""
    comando = comando.lower().strip()

    # Detectar ambiente
    if "sala" in comando:
        room = "sala"
    elif any(x in comando for x in ["habitacion", "habitación", "cuarto", "dormitorio"]):
        room = "habitacion"
    else:
        st.warning("👉 Especifica 'sala' o 'habitación'")
        return

    dev = devices[room]
    cambio = False

    # Luz
    if any(x in comando for x in ["encender luz", "enciende luz", "luz on", "prende luz"]):
        dev["luz"] = True
        cambio = True
    if any(x in comando for x in ["apagar luz", "apaga luz", "luz off"]):
        dev["luz"] = False
        cambio = True

    # Ventilador
    if any(x in comando for x in ["subir ventilador", "sube ventilador", "aumenta ventilador"]):
        dev["ventilador"] = min(3, dev["ventilador"] + 1)
        cambio = True
    if any(x in comando for x in ["bajar ventilador", "baja ventilador", "reduce ventilador"]):
        dev["ventilador"] = max(0, dev["ventilador"] - 1)
        cambio = True
    if any(x in comando for x in ["apagar ventilador", "apaga ventilador"]):
        dev["ventilador"] = 0
        cambio = True
    if any(x in comando for x in ["encender ventilador", "enciende ventilador"]) and dev["ventilador"] == 0:
        dev["ventilador"] = 1
        cambio = True

    # Puerta (solo sala)
    if any(x in comando for x in ["abrir puerta", "abre puerta"]):
        devices["sala"]["puerta_cerrada"] = False
        cambio = True
    if any(x in comando for x in ["cerrar puerta", "cierra puerta"]):
        devices["sala"]["puerta_cerrada"] = True
        cambio = True

    if cambio:
        if publish_casa_json():
            st.success(f"✅ Comando ejecutado en {room.capitalize()}")
        else:
            st.error("❌ Error al comunicar con ESP32")
    else:
        st.info("ℹ️ No se detectó ningún comando válido")


# --------- SIDEBAR ---------
st.sidebar.title("🏠 Casa Inteligente IoT")

pagina = st.sidebar.radio(
    "📍 Navegación",
    ["🏠 Panel General", "🎛️ Control Detallado", "👋 Gestos (TM)"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")

# Comando de texto
with st.sidebar.expander("🎤 Comando de Texto", expanded=False):
    texto_cmd = st.text_input(
        "Escribe comando",
        placeholder="Ej: encender luz sala",
        label_visibility="collapsed"
    )
    if st.button("▶️ Ejecutar", use_container_width=True):
        if texto_cmd.strip():
            ejecutar_comando(texto_cmd)
        else:
            st.warning("⚠️ Escribe un comando")

st.sidebar.markdown("---")

# Estado del sistema
st.sidebar.markdown("### 📊 Estado del Sistema")

# MQTT
if MQTT_AVAILABLE:
    st.sidebar.success("✅ paho-mqtt instalado")

    client = get_mqtt_client()
    if client and mqtt_status["connected"]:
        st.sidebar.success("✅ MQTT conectado")
    else:
        st.sidebar.error("❌ MQTT desconectado")
        if mqtt_status["last_error"]:
            st.sidebar.caption(f"⚠️ {mqtt_status['last_error']}")
else:
    st.sidebar.error("❌ paho-mqtt no instalado")
    st.sidebar.code("pip install paho-mqtt", language="bash")

# TensorFlow
if TF_AVAILABLE:
    st.sidebar.success("✅ TensorFlow disponible")
else:
    st.sidebar.info("ℹ️ TensorFlow no disponible (gestos desactivados)")

# Modelo
if TM_AVAILABLE:
    st.sidebar.success("✅ Modelo gestos.h5 cargado")
else:
    st.sidebar.info("ℹ️ Modelo de gestos no disponible")

# Info de conexión
with st.sidebar.expander("🔧 Configuración MQTT"):
    st.code(f"""Broker: {MQTT_BROKER}
Puerto: {MQTT_PORT}
Topic:  {MQTT_TOPIC}""")

# Botón reconectar
if st.sidebar.button("🔄 Reconectar MQTT", use_container_width=True):
    st.cache_resource.clear()
    st.rerun()


# =================== PÁGINAS ===================

# --------- PÁGINA 1: PANEL GENERAL ---------
if pagina == "🏠 Panel General":
    st.title("🏠 Panel General - Control de Casa")

    # Indicador de conexión grande
    if mqtt_status["connected"]:
        st.success("🟢 **Sistema conectado al ESP32**")
    else:
        st.error("🔴 **Sistema desconectado** - Verifica ESP32 y WiFi")

    st.markdown("---")

    col1, col2 = st.columns(2)

    for room, col in zip(["sala", "habitacion"], [col1, col2]):
        dev = devices[room]
        with col:
            # Título del ambiente
            if room == "sala":
                st.subheader("📍 SALA")
            else:
                st.subheader("📍 HABITACIÓN")

            # Métricas
            luz_text = "Encendida" if dev["luz"] else "Apagada"
            vent_text = f"Vel. {dev['ventilador']}" if dev["ventilador"] > 0 else "Apagado"
            puerta_text = "Cerrada" if dev["puerta_cerrada"] else "Abierta"

            m1, m2 = st.columns(2)
            with m1:
                st.metric("💡 Luz", luz_text)
            with m2:
                st.metric("🌀 Ventilador", vent_text)

            m3, m4 = st.columns(2)
            with m3:
                st.metric("🚪 Puerta", puerta_text)
            with m4:
                pres_text = "Presente" if dev["presencia"] else "Ausente"
                st.metric("👤 Sensor", pres_text)

            st.markdown("")

            # Controles rápidos
            c1, c2, c3 = st.columns(3)

            # Luz
            with c1:
                if dev["luz"]:
                    if st.button("💡 Apagar", key=f"luz_{room}", use_container_width=True):
                        dev["luz"] = False
                        publish_casa_json()
                        st.rerun()
                else:
                    if st.button("💡 Encender", key=f"luz_{room}", use_container_width=True):
                        dev["luz"] = True
                        publish_casa_json()
                        st.rerun()

            # Ventilador
            with c2:
                if dev["ventilador"] > 0:
                    if st.button("🌀 Apagar", key=f"vent_{room}", use_container_width=True):
                        dev["ventilador"] = 0
                        publish_casa_json()
                        st.rerun()
                else:
                    if st.button("🌀 Encender", key=f"vent_{room}", use_container_width=True):
                        dev["ventilador"] = 1
                        publish_casa_json()
                        st.rerun()

            # Puerta
            with c3:
                if dev["puerta_cerrada"]:
                    if st.button("🔓 Abrir", key=f"puerta_{room}", use_container_width=True):
                        dev["puerta_cerrada"] = False
                        devices["sala"]["puerta_cerrada"] = False
                        publish_casa_json()
                        st.rerun()
                else:
                    if st.button("🔒 Cerrar", key=f"puerta_{room}", use_container_width=True):
                        dev["puerta_cerrada"] = True
                        devices["sala"]["puerta_cerrada"] = True
                        publish_casa_json()
                        st.rerun()

    st.markdown("---")

    with st.expander("🔌 Mapa de Hardware ESP32", expanded=False):
        st.code(
            """
╔═══════════════════════════════════════════╗
║        CONEXIONES FÍSICAS ESP32           ║
╠═══════════════════════════════════════════╣
║ 💡 Luz Sala       → LED Rojo D2  (Act1)   ║
║ 💡 Luz Habitación → LED Amarillo D4(Act2) ║
║ 🌀 Ventilador     → LED Verde D5  (Vent)  ║
║ 🚪 Puerta Servo   → Servo D13   (Analog)  ║
╠═══════════════════════════════════════════╣
║ 📡 MQTT: broker.emqx.io:1883              ║
║ 📨 Topic: tomasclt                        ║
╚═══════════════════════════════════════════╝
            """,
            language="text",
        )


# --------- PÁGINA 2: CONTROL DETALLADO ---------
elif pagina == "🎛️ Control Detallado":
    st.title("🎛️ Control Detallado por Ambiente")

    room = st.selectbox(
        "📍 Selecciona ambiente",
        ["sala", "habitacion"],
        format_func=lambda x: "SALA" if x == "sala" else "HABITACIÓN",
    )
    dev = devices[room]

    st.markdown("---")

    col1, col2 = st.columns(2)

    # Iluminación
    with col1:
        st.markdown("#### 💡 Iluminación")
        nueva_luz = st.toggle(
            "Luz encendida", value=dev["luz"], key=f"toggle_luz_{room}"
        )
        if nueva_luz != dev["luz"]:
            dev["luz"] = nueva_luz
            publish_casa_json()
            time.sleep(0.1)
            st.rerun()

        dev["brillo"] = st.slider(
            "Brillo (%)",
            0,
            100,
            dev["brillo"],
            key=f"brillo_{room}",
            help="Simulación visual (no envía al ESP32)",
        )

    # Ventilación
    with col2:
        st.markdown("#### 🌀 Ventilación")
        nuevo_vent = st.slider(
            "Velocidad",
            0,
            3,
            dev["ventilador"],
            key=f"slider_vent_{room}",
            help="0=Apagado, 1-3=Velocidad",
        )
        if nuevo_vent != dev["ventilador"]:
            dev["ventilador"] = nuevo_vent
            if room == "sala":
                devices["sala"]["ventilador"] = nuevo_vent
            publish_casa_json()
            time.sleep(0.1)
            st.rerun()

        # Botones rápidos
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            if st.button("❌ Apagar", key="vent_off"):
                dev["ventilador"] = 0
                publish_casa_json()
                st.rerun()
        with bc2:
            if st.button("➕ Subir", key="vent_up"):
                dev["ventilador"] = min(3, dev["ventilador"] + 1)
                publish_casa_json()
                st.rerun()
        with bc3:
            if st.button("➖ Bajar", key="vent_down"):
                dev["ventilador"] = max(0, dev["ventilador"] - 1)
                publish_casa_json()
                st.rerun()

    st.markdown("---")

    col3, col4 = st.columns(2)

    # Puerta
    with col3:
        st.markdown("#### 🚪 Puerta (Sala)")
        estado = "🔒 Cerrada" if devices["sala"]["puerta_cerrada"] else "🔓 Abierta"
        st.info(f"**Estado actual:** {estado}")

        pc1, pc2 = st.columns(2)
        with pc1:
            if st.button("🔓 Abrir", key="puerta_abrir", use_container_width=True):
                devices["sala"]["puerta_cerrada"] = False
                publish_casa_json()
                st.rerun()
        with pc2:
            if st.button("🔒 Cerrar", key="puerta_cerrar", use_container_width=True):
                devices["sala"]["puerta_cerrada"] = True
                publish_casa_json()
                st.rerun()

    # Sensor de presencia
    with col4:
        st.markdown("#### 🔍 Sensor de Presencia")
        nueva_pres = st.checkbox(
            "Persona presente",
            value=dev["presencia"],
            key=f"pres_{room}",
            help="Simulación de sensor PIR",
        )
        if nueva_pres != dev["presencia"]:
            dev["presencia"] = nueva_pres

    st.markdown("---")

    # JSON actual
    st.markdown("### 📨 Último JSON Enviado")
    payload = {
        "Act1": "ON" if devices["sala"]["luz"] else "OFF",
        "Act2": "ON" if devices["habitacion"]["luz"] else "OFF",
        "Vent": devices["sala"]["ventilador"],
        "Analog": 0 if devices["sala"]["puerta_cerrada"] else 100,
    }
    st.json(payload)


# --------- PÁGINA 3: GESTOS ---------
else:
    st.title("👋 Control por Gestos - Teachable Machine")

    if not TM_AVAILABLE:
        st.error("❌ Control por gestos NO disponible")

        st.markdown(
            """
        ### 📋 Para activar los gestos:

        1. **Entrena tu modelo** en [Teachable Machine](https://teachablemachine.withgoogle.com/)
        2. **Exporta como Keras** y descarga `gestos.h5`
        3. **Sube el archivo** a tu repositorio (raíz del proyecto)
        4. **Añade a `requirements.txt`:**
        ```
        tensorflow-cpu>=2.13.0
        ```
        5. **Descomenta** las líneas de import de TensorFlow
        6. **Redeploy** en Streamlit Cloud

        ⚠️ **Nota:** TensorFlow es pesado. Si no necesitas gestos, usa solo MQTT (más rápido).
        """
        )

    else:
        st.success("✅ Modelo de gestos cargado correctamente")

        st.markdown(
            """
        **Gestos disponibles para controlar LA SALA:**

        | Gesto | Acción | LED Afectado |
        |-------|--------|--------------|
        | ✊ Puño cerrado | `luz_on` | LED Rojo D2 ON |
        | ✋ Mano abierta | `luz_off` | LED Rojo D2 OFF |
        | 👍 Pulgar arriba | `puerta_abierta` | Servo D13 → 180° |
        | 👎 Pulgar abajo | `puerta_cerrada` | Servo D13 → 0° |
        """
        )

        foto = st.camera_input("📸 Captura tu gesto")

        if foto is not None:
            image = Image.open(foto)

            col1, col2 = st.columns([1, 2])

            with col1:
                st.image(image, caption="Gesto capturado", use_container_width=True)

            with col2:
                with st.spinner("🔍 Analizando gesto..."):
                    clase, prob = predict_gesto(image)

                if clase:
                    confianza_color = "🟢" if prob > 0.7 else "🟡" if prob > 0.5 else "🔴"
                    st.success(
                        f"{confianza_color} **Gesto:** `{clase}` | **Confianza:** {prob:.1%}"
                    )

                    dev_sala = devices["sala"]
                    cambio = False

                    if clase == "luz_on":
                        dev_sala["luz"] = True
                        cambio = True
                        st.info("💡 Luz sala: **ENCENDIDA**")
                    elif clase == "luz_off":
                        dev_sala["luz"] = False
                        cambio = True
                        st.info("💡 Luz sala: **APAGADA**")
                    elif clase == "puerta_abierta":
                        dev_sala["puerta_cerrada"] = False
                        cambio = True
                        st.info("🔓 Puerta: **ABIERTA**")
                    elif clase == "puerta_cerrada":
                        dev_sala["puerta_cerrada"] = True
                        cambio = True
                        st.info("🔒 Puerta: **CERRADA**")

                    if cambio:
                        if publish_casa_json():
                            st.markdown("---")
                            payload = {
                                "Act1": "ON" if dev_sala["luz"] else "OFF",
                                "Act2": "ON" if devices["habitacion"]["luz"] else "OFF",
                                "Vent": dev_sala["ventilador"],
                                "Analog": 0
                                if dev_sala["puerta_cerrada"]
                                else 100,
                            }

                            st.success("✅ **Comando enviado al ESP32**")
                            st.json(payload)
                        else:
                            st.error("❌ Error al comunicar con ESP32")
                else:
                    st.error("❌ No se pudo clasificar el gesto")
