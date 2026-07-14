import streamlit as st
import sqlite3
import pandas as pd
import google.generativeai as genai
from PIL import Image
import json
import os
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y BASE DE DATOS
# ==========================================
st.set_page_config(page_title="Copiloto Finanzas Hogar", page_icon="🛒", layout="wide")

DB_PATH = "supermercado.db"
LISTA_SUPERS = ["Mercadona", "Dia", "Carrefour", "Aldi", "Lidl", "Family Cash", "Otros"]

def init_db():
    """Crea la tabla única si no existe al arrancar la app."""
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS despensa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supermercado TEXT,
            producto_generico TEXT,
            marca TEXT,
            peso_unitario REAL,
            unidades_pack INTEGER,
            precio_total REAL,
            precio_referencia REAL,
            activo INTEGER DEFAULT 1,
            fecha_compra TEXT
        )
    ''')
    conexion.commit()
    conexion.close()

# Inicializamos la base de datos automáticamente
init_db()

# ==========================================
# MENÚ DE NAVEGACIÓN (SIDEBAR)
# ==========================================
with st.sidebar:
    st.title("🛒 Menú Principal")
    opcion_menu = st.radio("Navegación:", [
        "🗺️ Planificador de Rutas", 
        "📷 Lector de Tickets IA", 
        "✍️ Ingreso Manual / Barras", 
        "📦 Mi Despensa (Configuración)"
    ])
    st.divider()
    st.markdown("### Filtros de la compra de hoy")
    supers_activos = st.multiselect("¿A qué súper puedes ir hoy?", LISTA_SUPERS, default=LISTA_SUPERS)
    ahorro_minimo = st.slider("Ahorro mínimo para dividir compra (€)", 0.0, 5.0, 1.5, 0.1)

# ==========================================
# SECCIÓN 1: LECTOR DE TICKETS IA
# ==========================================
if opcion_menu == "📷 Lector de Tickets IA":
    st.title("📷 Escáner de Tickets Inteligente")
    
    # Intenta obtener la API Key (Asegúrate de tener un archivo .streamlit/secrets.toml)
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    
    if not api_key: 
        st.warning("⚠️ Configura GEMINI_API_KEY en los Secrets de Streamlit.")
    else:
        archivo_ticket = st.file_uploader("Sube la foto del ticket:", type=["jpg", "jpeg", "png"])
        if archivo_ticket:
            imagen = Image.open(archivo_ticket)
            st.image(imagen, width=250)
            
            if st.button("🚀 Analizar Ticket"):
                with st.spinner("Procesando con IA..."):
                    try:
                        client = genai.Client(api_key=api_key)
                        imagen.save("temp_ticket.png")
                        
                        # Prompt ajustado a la nueva estructura de base de datos
                        prompt = "Analiza este ticket y devuelve estrictamente un objeto JSON con las claves: supermercado, articulos_despensa (lista de objetos con: producto, marca, unidades_pack, peso_unitario_kg, precio_total). Si no pone la marca, pon 'Blanca'. Sin explicaciones, solo el JSON."
                        
                        uploaded_file = client.files.upload(file="temp_ticket.png")
                        response = client.models.generate_content(model='gemini-2.5-flash', contents=[uploaded_file, prompt])
                        raw_text = response.text.strip()
                        
                        json_marker = chr(96) * 3 + "json"
                        end_marker = chr(96) * 3
                        
                        if json_marker in raw_text:
                            raw_text = raw_text.split(json_marker)[1]
                        if end_marker in raw_text:
                            raw_text = raw_text.rsplit(end_marker, 1)[0]
                            
                        st.session_state['resultado_json_ticket'] = json.loads(raw_text.strip())
                        
                        if os.path.exists("temp_ticket.png"): 
                            os.remove("temp_ticket.png")
                        st.success("¡Análisis completado!")
                    except Exception as e: 
                        st.error(f"Error procesando ticket: {e}")
            
        # Si hay datos de la IA, los mostramos para edición manual
        if 'resultado_json_ticket' in st.session_state:
            datos = st.session_state['resultado_json_ticket']
            
            st.write("### 🛠️ Revisa y corrige antes de guardar:")
            super_det = st.selectbox("Supermercado detectado:", LISTA_SUPERS, index=LISTA_SUPERS.index(datos.get('supermercado', 'Otros')) if datos.get('supermercado', 'Otros') in LISTA_SUPERS else 0)
            
            df_desp = pd.DataFrame(datos.get('articulos_despensa', []))
            
            if not df_desp.empty: 
                # st.data_editor te permite hacer doble clic y cambiar un número si la IA se equivocó
                df_editado = st.data_editor(df_desp, num_rows="dynamic", use_container_width=True)
            
            if st.button("🔨 Inyectar a Base de Datos Local"):
                conexion = sqlite3.connect(DB_PATH, timeout=10)
                cursor = conexion.cursor()
                fecha_actual = datetime.now().strftime("%Y-%m-%d")
                
                # Iteramos sobre la tabla que acabas de corregir en pantalla
                for index, row in df_editado.iterrows():
                    producto = str(row.get('producto', 'Desconocido')).lower().strip()
                    marca = str(row.get('marca', 'Blanca')).title().strip()
                    unidades = int(row.get('unidades_pack', 1))
                    peso = float(row.get('peso_unitario_kg', 1.0))
                    precio = float(row.get('precio_total', 0.0))
                    
                    # MATEMÁTICAS LOCALES: Cálculo del precio de referencia
                    peso_total_lote = unidades * peso
                    precio_ref = (precio / peso_total_lote) if peso_total_lote > 0 else precio
                    
                    cursor.execute("""
                        INSERT INTO despensa 
                        (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """, (super_det, producto, marca, peso, unidades, precio, precio_ref, fecha_actual))
                
                conexion.commit()
                conexion.close()
                
                # Limpiamos la pantalla
                del st.session_state['resultado_json_ticket']
                st.success("¡Todos los productos han sido guardados y calculados con éxito!")
                st.rerun()

# ==========================================
# SECCIÓN 2: PLANIFICADOR (Placeholder)
# ==========================================
elif opcion_menu == "🗺️ Planificador de Rutas":
    st.title("🗺️ Planificador de Compra")
    st.info("Pestaña reservada para el buscador de rutas.")

# ==========================================
# SECCIÓN 3: MANUAL / BARRAS (Placeholder)
# ==========================================
elif opcion_menu == "✍️ Ingreso Manual / Barras":
    st.title("✍️ Añadir Producto Individual")
    st.info("Pestaña reservada para el formulario simplificado y Open Food Facts.")

# ==========================================
# SECCIÓN 4: MI DESPENSA (Placeholder)
# ==========================================
elif opcion_menu == "📦 Mi Despensa (Configuración)":
    st.title("📦 Base de Datos Local")
    st.info("Pestaña reservada para ver la tabla completa, descartar y borrar productos.")
