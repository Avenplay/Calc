import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import json
from PIL import Image
import os
import time
from google import genai
import requests

# ------------------------------------------
# CONFIGURACIÓN GLOBAL
# ------------------------------------------
st.set_page_config(page_title="Calculadora de Ahorro", layout="wide")
api_key = st.secrets.get("GEMINI_API_KEY", "")

DB_PATH = "despensa.db"
LISTA_SUPERS = ["Mercadona", "Carrefour", "Lidl", "Aldi", "Dia", "Alcampo", "Eroski", "Consum", "Otro"]

def init_db():
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute("""
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
    """)
    conexion.commit()
    conexion.close()

init_db()

# Función para limpiar archivos temporales y no saturar Streamlit Cloud
def limpiar_temporales():
    for f in os.listdir("."):
        if f.startswith("temp_") and f.endswith(".png"):
            try:
                os.remove(f)
            except:
                pass

st.title("🛒 Mi Despensa Inteligente")
st.divider()

# ------------------------------------------
# SECCIÓN 1: LECTOR DE TICKETS
# ------------------------------------------
st.header("🧾 1. Subir Ticket de Compra")
foto_ticket = st.file_uploader("Sube la foto de tu ticket", type=["png", "jpg", "jpeg"])

if foto_ticket:
    if st.button("Analizar Ticket con IA", width="stretch"):
        with st.spinner("Procesando ticket (puede tardar unos segundos)..."):
            try:
                client = genai.Client(api_key=api_key)
                imagen = Image.open(foto_ticket)
                imagen.save("temp_ticket.png")
                
                prompt = "Analiza este ticket y devuelve estrictamente un objeto JSON con las claves: supermercado, articulos_despensa (lista de objetos con: producto, marca, unidades_pack, peso_unitario_kg, precio_total). Si no pone la marca, pon 'Blanca'. Sin explicaciones, solo el JSON."
                
                uploaded_file = client.files.upload(file="temp_ticket.png")
                
                # Bucle anti-503 implementado también aquí
                max_reintentos = 3
                for intento in range(max_reintentos):
                    try:
                        response = client.models.generate_content(
                            model='gemini-2.5-flash', 
                            contents=[uploaded_file, prompt]
                        )
                        break
                    except Exception as api_error:
                        if "503" in str(api_error) and intento < max_reintentos - 1:
                            time.sleep(2)
                            continue
                        else:
                            raise api_error
                
                raw_text = response.text.strip()
                json_marker = chr(96) * 3 + "json"
                end_marker = chr(96) * 3
                
                if json_marker in raw_text:
                    raw_text = raw_text.split(json_marker)[1]
                if end_marker in raw_text:
                    raw_text = raw_text.rsplit(end_marker, 1)[0]
                    
                st.session_state['resultado_json_ticket'] = json.loads(raw_text.strip())
                limpiar_temporales()
                st.success("¡Análisis completado!")
            except Exception as e: 
                limpiar_temporales()
                st.error(f"Error procesando ticket: {e}")

if 'resultado_json_ticket' in st.session_state:
    datos = st.session_state['resultado_json_ticket']
    supermercado_detectado = datos.get("supermercado", "Mercadona").title()
    
    # Asegurarnos de que el supermercado detectado está en la lista o asignarle "Otro"
    if supermercado_detectado not in LISTA_SUPERS:
        supermercado_detectado = "Otro"
        
    st.write(f"**Supermercado detectado:** {supermercado_detectado}")
    
    with st.form("form_ticket"):
        st.write("Revisa los productos extraídos:")
        productos_a_guardar = []
        for i, art in enumerate(datos.get("articulos_despensa", [])):
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1: p_nombre = st.text_input(f"Producto {i}", value=art.get("producto", ""), key=f"t_nom_{i}")
            with col2: p_marca = st.text_input(f"Marca {i}", value=art.get("marca", "Blanca"), key=f"t_mar_{i}")
            with col3: p_uni = st.number_input(f"Unidades {i}", value=int(art.get("unidades_pack", 1)), min_value=1, key=f"t_uni_{i}")
            with col4: p_peso = st.number_input(f"Peso 1ud(kg/L) {i}", value=float(art.get("peso_unitario_kg", 1.0)), min_value=0.01, key=f"t_peso_{i}")
            with col5: p_precio = st.number_input(f"Precio Total {i}", value=float(art.get("precio_total", 0.0)), min_value=0.0, step=0.10, key=f"t_prec_{i}")
            
            productos_a_guardar.append({
                "nombre": p_nombre, "marca": p_marca, "unidades": p_uni, 
                "peso": p_peso, "precio": p_precio
            })
            
        if st.form_submit_button("💾 Guardar Ticket en Base de Datos", width="stretch"):
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            
            for prod in productos_a_guardar:
                peso_total_lote = prod["unidades"] * prod["peso"]
                precio_ref = (prod["precio"] / peso_total_lote) if peso_total_lote > 0 else prod["precio"]
                
                cursor.execute("""
                    INSERT INTO despensa 
                    (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (supermercado_detectado, prod["nombre"].lower(), prod["marca"].title(), prod["peso"], prod["unidades"], prod["precio"], precio_ref, fecha_hoy))
                
            conexion.commit()
            conexion.close()
            del st.session_state['resultado_json_ticket']
            st.success("✅ ¡Todos los productos del ticket guardados con éxito!")
            st.rerun()

st.divider()

# ------------------------------------------
# SECCIÓN 2: INGRESO MANUAL O ESCÁNER
# ------------------------------------------
st.header("➕ 2. Añadir Producto Individual")
tab_manual, tab_barras = st.tabs(["📝 Ingreso Manual", "📸 Escáner Híbrido (Multifoto)"])

with tab_manual:
    with st.form("form_manual"):
        c1, c2 = st.columns(2)
        with c1:
            supermercado = st.selectbox("Supermercado", LISTA_SUPERS)
            producto = st.text_input("Producto Genérico (ej: tomate frito)")
            marca = st.text_input("Marca (ej: Orlando)")
        with c2:
            unidades = st.number_input("Unidades del pack", min_value=1, step=1, value=1)
            peso = st.number_input("Peso de 1 unidad (kg o Litros)", min_value=0.01, step=0.10, value=1.0)
            precio = st.number_input("Precio Total del lote (€)", min_value=0.0, step=0.10)
            
        if st.form_submit_button("💾 Guardar Producto", width="stretch"):
            peso_total = unidades * peso
            precio_ref = (precio / peso_total) if peso_total > 0 else precio
            
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            cursor.execute("""
                INSERT INTO despensa 
                (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (supermercado, producto.lower(), marca.title(), peso, unidades, precio, precio_ref, datetime.now().strftime("%Y-%m-%d")))
            
            conexion.commit()
            conexion.close()
            st.success("✅ Producto guardado con éxito.")
            st.rerun()

with tab_barras:
    st.write("Sube o haz varias fotos (código de barras, etiqueta frontal, peso...). La IA las cruzará todas para extraer la información.")
    fotos_subidas = st.file_uploader("Añadir fotos", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    
    if fotos_subidas:
        if st.button("🚀 Procesar Todas las Fotos", width="stretch"):
            try:
                client = genai.Client(api_key=api_key)
                archivos_gemini = []
                
                for i, foto in enumerate(fotos_subidas):
                    ruta_temp = f"temp_foto_{i}.png"
                    img = Image.open(foto)
                    img.save(ruta_temp)
                    uploaded_file = client.files.upload(file=ruta_temp)
                    archivos_gemini.append(uploaded_file)
                    
                with st.spinner("Fase 1: Buscando código de barras..."):
                    prompt_1 = "Analiza estas fotos. Busca un código de barras. Si lo encuentras, devuelve ÚNICAMENTE los números (suele tener 13 dígitos). Si no ves ningún código de barras claro, responde exactamente 'NO_ENCONTRADO'."
                    max_reintentos = 3
                    
                    for intento in range(max_reintentos):
                        try:
                            res_1 = client.models.generate_content(
                                model='gemini-2.5-flash', 
                                contents=archivos_gemini + [prompt_1]
                            )
                            break
                        except Exception as api_error:
                            if "503" in str(api_error) and intento < max_reintentos - 1:
                                time.sleep(2)
                                continue
                            else:
                                raise api_error
                                
                    codigo_ean = res_1.text.strip().replace(" ", "")
                    
                datos_ia = {}
                usar_analisis_visual = False
                
                if codigo_ean == "NO_ENCONTRADO" or not codigo_ean.isdigit():
                    st.warning("⚠️ Sin código claro. Pasando a Modo Visión Profunda...")
                    usar_analisis_visual = True
                else:
                    st.success(f"✅ Código EAN detectado: {codigo_ean}")
                    with st.spinner("Fase 2: Conectando con Open Food Facts..."):
                        url = f"https://world.openfoodfacts.org/api/v2/product/{codigo_ean}.json"
                        res_api = requests.get(url)
                        
                        if res_api.status_code == 200 and res_api.json().get('status') == 1:
                            datos_crudos = res_api.json().get('product', {})
                            info_para_ia = {
                                "nombre": datos_crudos.get("product_name", ""),
                                "marca": datos_crudos.get("brands", ""),
                                "cantidad": datos_crudos.get("quantity", "")
                            }
                            
                            with st.spinner("Fase 3: Normalizando datos..."):
                                prompt_2 = f"Datos brutos: {json.dumps(info_para_ia)}. Devuelve JSON con: 'producto_generico', 'marca', 'peso_total' (en kg/L, ej: 0.4), 'unidades_pack' (si no indica, pon 1). Solo JSON puro."
                                
                                for intento_2 in range(max_reintentos):
                                    try:
                                        res_2 = client.models.generate_content(
                                            model='gemini-2.5-flash', 
                                            contents=[prompt_2]
                                        )
                                        break
                                    except Exception as api_error_2:
                                        if "503" in str(api_error_2) and intento_2 < max_reintentos - 1:
                                            time.sleep(2)
                                            continue
                                        else:
                                            raise api_error_2
                                            
                                raw_text = res_2.text.strip()
                                json_marker = chr(96) * 3 + "json"
                                end_marker = chr(96) * 3
                                if json_marker in raw_text: raw_text = raw_text.split(json_marker)[1]
                                if end_marker in raw_text: raw_text = raw_text.rsplit(end_marker, 1)[0]
                                datos_ia = json.loads(raw_text.strip())
                        else:
                            st.warning("⚠️ Código no registrado. Activando Modo Visión Profunda...")
                            usar_analisis_visual = True
                            
                if usar_analisis_visual:
                    with st.spinner("Extrayendo datos visualmente..."):
                        prompt_visual = "Analiza estas fotos. Devuelve estrictamente un JSON con: 'producto_generico' (nombre en minúsculas), 'marca' (si no hay pon 'Blanca'), 'peso_total' (en kg o L, ej: 0.4), y 'unidades_pack' (número). Solo JSON puro."
                        
                        for intento_v in range(max_reintentos):
                            try:
                                res_v = client.models.generate_content(
                                    model='gemini-2.5-flash', 
                                    contents=archivos_gemini + [prompt_visual]
                                )
                                break
                            except Exception as api_error_v:
                                if "503" in str(api_error_v) and intento_v < max_reintentos - 1:
                                    time.sleep(2)
                                    continue
                                else:
                                    raise api_error_v
                                    
                        raw_text = res_v.text.strip()
                        json_marker = chr(96) * 3 + "json"
                        end_marker = chr(96) * 3
                        if json_marker in raw_text: raw_text = raw_text.split(json_marker)[1]
                        if end_marker in raw_text: raw_text = raw_text.rsplit(end_marker, 1)[0]
                        datos_ia = json.loads(raw_text.strip())
                        
                limpiar_temporales()
                
                st.session_state['ia_temp_nombre'] = datos_ia.get('producto_generico', '').lower()
                st.session_state['ia_temp_marca'] = datos_ia.get('marca', 'Blanca').title()
                st.session_state['ia_temp_peso'] = float(datos_ia.get('peso_total', 1.0))
                st.session_state['ia_temp_unidades'] = int(datos_ia.get('unidades_pack', 1))
                
                st.rerun()
                
            except Exception as e: 
                limpiar_temporales()
                st.error(f"Error procesando fotos: {e}")

    if 'ia_temp_nombre' in st.session_state:
        st.divider()
        st.write("🛠️ **Datos extraídos. Añade el precio, revisa unidades y guarda:**")
        
        c_ia1, c_ia2 = st.columns(2)
        with c_ia1:
            nombre_ia = st.text_input("Producto", value=st.session_state.get('ia_temp_nombre', ''), key="nom_ia")
            marca_ia = st.text_input("Marca", value=st.session_state.get('ia_temp_marca', 'Blanca'), key="mar_ia")
            super_ia = st.selectbox("Comprado en:", LISTA_SUPERS, key="sup_ia")
        with c_ia2:
            unids_ia = st.number_input("Unidades del pack", value=int(st.session_state.get('ia_temp_unidades', 1)), min_value=1, step=1, key="uni_ia")
            peso_ia = st.number_input("Peso 1 unidad (kg/L)", value=float(st.session_state.get('ia_temp_peso', 1.0)), min_value=0.01, step=0.10, key="pes_ia")
            precio_ia = st.number_input("Precio Total en caja (€)", min_value=0.0, step=0.10, key="prec_ia")
            
        if st.button("💾 Guardar Producto", type="primary", width="stretch"):
            if precio_ia <= 0:
                st.warning("⚠️ Recuerda introducir el precio del producto antes de guardar.")
            else:
                peso_total_lote = unids_ia * peso_ia
                precio_ref_ia = (precio_ia / peso_total_lote) if peso_total_lote > 0 else precio_ia
                
                conexion = sqlite3.connect(DB_PATH)
                cursor = conexion.cursor()
                cursor.execute("""
                    INSERT INTO despensa 
                    (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (super_ia, nombre_ia.lower(), marca_ia.title(), peso_ia, unids_ia, precio_ia, precio_ref_ia, datetime.now().strftime("%Y-%m-%d")))
                
                conexion.commit()
                conexion.close()
                
                st.session_state.pop('ia_temp_nombre', None)
                st.session_state.pop('ia_temp_marca', None)
                st.session_state.pop('ia_temp_peso', None)
                st.session_state.pop('ia_temp_unidades', None)
                
                st.success(f"✅ ¡{nombre_ia.title()} guardado correctamente a {precio_ref_ia:.2f} €/kg!")
                st.rerun()

st.divider()

# ------------------------------------------
# SECCIÓN 3: MI DESPENSA (VISUALIZACIÓN)
# ------------------------------------------
st.header("📊 3. Mi Despensa (Editar y Borrar)")

conexion = sqlite3.connect(DB_PATH)
df_despensa = pd.read_sql_query("SELECT * FROM despensa WHERE activo = 1 ORDER BY fecha_compra DESC", conexion)
conexion.close()

if not df_despensa.empty:
    df_mostrar = df_despensa[['id', 'producto_generico', 'marca', 'supermercado', 'precio_referencia', 'fecha_compra']].copy()
    df_mostrar.columns = ['ID', 'Producto', 'Marca', 'Supermercado', 'Precio Ref (€/kg)', 'Fecha']
    
    st.write("Puedes modificar directamente en la tabla los datos o marcar la casilla para borrar.")
    
    df_mostrar['Borrar'] = False
    
    df_editado = st.data_editor(
        df_mostrar,
        hide_index=True,
        use_container_width=False, # Sobrescrito abajo con la nueva sintaxis
        width="stretch",
        disabled=["ID", "Precio Ref (€/kg)", "Fecha"]
    )
    
    if st.button("Aplicar Cambios a la Despensa", width="stretch"):
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        
        # Eliminar los marcados
        ids_borrar = df_editado[df_editado['Borrar'] == True]['ID'].tolist()
        if ids_borrar:
            cursor.execute(f"UPDATE despensa SET activo = 0 WHERE id IN ({','.join(map(str, ids_borrar))})")
            
        # Actualizar modificaciones manuales
        for index, row in df_editado.iterrows():
            if not row['Borrar']:
                cursor.execute("""
                    UPDATE despensa 
                    SET producto_generico = ?, marca = ?, supermercado = ?
                    WHERE id = ?
                """, (row['Producto'].lower(), row['Marca'].title(), row['Supermercado'], row['ID']))
                
        conexion.commit()
        conexion.close()
        st.success("✅ Cambios aplicados con éxito.")
        st.rerun()
else:
    st.info("Tu despensa está vacía. ¡Empieza a añadir productos o subir tickets!")
