import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime
import json
from PIL import Image
import os
import time
from google import genai
import requests
import warnings

# Suprimir avisos de Pandas en el log del servidor
warnings.filterwarnings('ignore', category=UserWarning)

# ------------------------------------------
# CONFIGURACIÓN GLOBAL
# ------------------------------------------
st.set_page_config(page_title="Calculadora de Ahorro", layout="wide")
api_key = st.secrets.get("GEMINI_API_KEY", "")

# ------------------------------------------
# SISTEMA DE SEGURIDAD (LOGIN)
# ------------------------------------------
def check_password():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False

    if st.session_state["autenticado"]:
        return True

    st.title("🔒 Acceso Restringido")
    st.write("Por favor, introduce la contraseña para acceder a la despensa.")
    
    contrasena = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary", width="stretch"):
        if contrasena == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    return False

if not check_password():
    st.stop()

# ==========================================
# CÓDIGO PRINCIPAL (Optimizado para la Nube)
# ==========================================
LISTA_SUPERS = ["Mercadona", "Carrefour", "Lidl", "Aldi", "Dia", "Alcampo", "Eroski", "Consum", "Otro"]

def get_db_conexion():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

# 🚀 OPTIMIZACIÓN 1: El Escudo Anti-Reinicio
@st.cache_resource
def init_db():
    conexion = get_db_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS despensa (
            id SERIAL PRIMARY KEY,
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
    return True # Necesario para que st.cache_resource sepa que terminó correctamente

init_db() # Ahora esta llamada es casi instantánea tras el primer arranque

def limpiar_temporales():
    for f in os.listdir("."):
        if f.startswith("temp_") and f.endswith(".png"):
            try:
                os.remove(f)
            except:
                pass

st.title("🛒 Mi Despensa Inteligente")

# ------------------------------------------
# PESTAÑAS PRINCIPALES DE NAVEGACIÓN
# ------------------------------------------
tab_gestion, tab_lista = st.tabs(["⚙️ Gestión de Despensa", "📝 Lista de la Compra"])

# ==========================================
# PESTAÑA 1: GESTIÓN DE DESPENSA
# ==========================================
with tab_gestion:
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
                conexion = get_db_conexion()
                cursor = conexion.cursor()
                fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                
                for prod in productos_a_guardar:
                    peso_total_lote = prod["unidades"] * prod["peso"]
                    precio_ref = (prod["precio"] / peso_total_lote) if peso_total_lote > 0 else prod["precio"]
                    
                    cursor.execute("""
                        INSERT INTO despensa 
                        (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s)
                    """, (supermercado_detectado, prod["nombre"].lower(), prod["marca"].title(), prod["peso"], prod["unidades"], prod["precio"], precio_ref, fecha_hoy))
                    
                conexion.commit()
                conexion.close()
                del st.session_state['resultado_json_ticket']
                st.success("✅ ¡Todos los productos del ticket guardados en la Nube con éxito!")
                st.rerun()

    st.divider()

    st.header("➕ 2. Añadir Producto Individual")
    subtab_manual, subtab_barras = st.tabs(["📝 Ingreso Manual", "📸 Escáner Multifoto"])

    with subtab_manual:
        # Añadimos una 'key' única para el formulario
        with st.form("form_manual", clear_on_submit=True): 
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
                
                conexion = get_db_conexion()
                cursor = conexion.cursor()
                cursor.execute("""
                    INSERT INTO despensa 
                    (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s)
                """, (supermercado, producto.lower(), marca.title(), peso, unidades, precio, precio_ref, datetime.now().strftime("%Y-%m-%d")))
                
                conexion.commit()
                conexion.close()
                st.success("✅ Producto guardado en la Nube con éxito.")
                # Al tener clear_on_submit=True, Streamlit ya limpia los campos automáticamente aquí

    with subtab_barras:
        st.write("Sube o haz varias fotos. La IA cruzará todas para extraer la información.")
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
                        prompt_1 = "Analiza estas fotos. Busca un código de barras. Si lo encuentras, devuelve ÚNICAMENTE los números. Si no ves ningún código, responde exactamente 'NO_ENCONTRADO'."
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
                        usar_analisis_visual = True
                    else:
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
                                    prompt_2 = f"Datos brutos: {json.dumps(info_para_ia)}. Devuelve JSON con: 'producto_generico', 'marca', 'peso_total' (en kg/L), 'unidades_pack'. Solo JSON puro."
                                    
                                    for intento_2 in range(max_reintentos):
                                        try:
                                            res_2 = client.models.generate_content(model='gemini-2.5-flash', contents=[prompt_2])
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
                                usar_analisis_visual = True
                                
                    if usar_analisis_visual:
                        with st.spinner("Extrayendo datos visualmente..."):
                            prompt_visual = "Analiza estas fotos. Devuelve estrictamente un JSON con: 'producto_generico' (nombre en minúsculas), 'marca' (si no hay pon 'Blanca'), 'peso_total' (en kg o L, ej: 0.4), y 'unidades_pack' (número). Solo JSON puro."
                            
                            for intento_v in range(max_reintentos):
                                try:
                                    res_v = client.models.generate_content(model='gemini-2.5-flash', contents=archivos_gemini + [prompt_visual])
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
                    
                    conexion = get_db_conexion()
                    cursor = conexion.cursor()
                    cursor.execute("""
                        INSERT INTO despensa 
                        (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s)
                    """, (super_ia, nombre_ia.lower(), marca_ia.title(), peso_ia, unids_ia, precio_ia, precio_ref_ia, datetime.now().strftime("%Y-%m-%d")))
                    
                    conexion.commit()
                    conexion.close()
                    
                    st.session_state.pop('ia_temp_nombre', None)
                    st.session_state.pop('ia_temp_marca', None)
                    st.session_state.pop('ia_temp_peso', None)
                    st.session_state.pop('ia_temp_unidades', None)
                    
                    st.success(f"✅ ¡{nombre_ia.title()} guardado correctamente!")
                    st.rerun()

    st.divider()

    st.header("📊 3. Mi Despensa (Editar y Borrar)")
    conexion = get_db_conexion()
    df_despensa = pd.read_sql_query("SELECT * FROM despensa WHERE activo = 1 ORDER BY fecha_compra DESC", conexion)
    conexion.close()

    if not df_despensa.empty:
        df_mostrar = df_despensa[['id', 'producto_generico', 'marca', 'supermercado', 'precio_total', 'precio_referencia', 'fecha_compra']].copy()
        df_mostrar.columns = ['ID', 'Producto', 'Marca', 'Supermercado', 'Precio Pack (€)', 'Precio Ref (€/kg)', 'Fecha']
        
        st.write("Puedes modificar directamente en la tabla los datos o marcar la casilla para borrar.")
        df_mostrar['Borrar'] = False
        
        df_editado = st.data_editor(
            df_mostrar,
            hide_index=True,
            width="stretch", 
            disabled=["ID", "Precio Pack (€)", "Precio Ref (€/kg)", "Fecha"]
        )
        
        if st.button("Aplicar Cambios a la Despensa", width="stretch"):
            conexion = get_db_conexion()
            cursor = conexion.cursor()
            
            ids_borrar = df_editado[df_editado['Borrar'] == True]['ID'].tolist()
            if ids_borrar:
                cursor.execute(f"UPDATE despensa SET activo = 0 WHERE id IN ({','.join(map(str, ids_borrar))})")
                
            for index, row in df_editado.iterrows():
                if not row['Borrar']:
                    cursor.execute("""
                        UPDATE despensa 
                        SET producto_generico = %s, marca = %s, supermercado = %s
                        WHERE id = %s
                    """, (row['Producto'].lower(), row['Marca'].title(), row['Supermercado'], row['ID']))
                    
            conexion.commit()
            conexion.close()
            st.success("✅ Cambios aplicados con éxito.")
            st.rerun()
    else:
        st.info("Tu despensa está vacía. ¡Empieza a añadir productos o subir tickets!")

# ==========================================
# PESTAÑA 2: LISTA DE LA COMPRA (RUTAS)
# ==========================================
with tab_lista:
    st.header("📝 Planificador de Rutas")
    st.write("Escribe los productos que necesitas comprar separados por comas y buscaré las 3 mejores opciones basándome en los tickets y escaneos de tu despensa.")
    
    lista_input = st.text_area("¿Qué falta en casa?", placeholder="Ej: leche, tomate frito, huevos, pan de molde")
    
    if st.button("🗺️ Calcular Rutas de Ahorro", type="primary", width="stretch"):
        items_buscados = [item.strip().lower() for item in lista_input.split(",") if item.strip()]
        
        if items_buscados:
            conexion = get_db_conexion()
            df_historico = pd.read_sql_query("SELECT * FROM despensa WHERE activo = 1", conexion)
            conexion.close()
            
            if df_historico.empty:
                st.warning("No hay datos en tu despensa para comparar. Sube algún ticket primero.")
            else:
                productos_encontrados = []
                
                for item in items_buscados:
                    coincidencias = df_historico[df_historico['producto_generico'].str.contains(item, case=False, na=False)]
                    if not coincidencias.empty:
                        for _, row in coincidencias.iterrows():
                            productos_encontrados.append({
                                'Producto Buscado': item.title(),
                                'Producto Real': row['producto_generico'].title(),
                                'Marca': row['marca'],
                                'Supermercado': row['supermercado'],
                                'Precio_Pack': row['precio_total'],
                                'Precio_Ref': row['precio_referencia']
                            })
                
                if productos_encontrados:
                    df_matches = pd.DataFrame(productos_encontrados)
                    st.divider()
                    
                    st.subheader("🟢 RUTA 1: El Mayor Ahorro (Varios Supermercados)")
                    st.write("Comprando cada producto individualmente donde está más barato.")
                    
                    idx_min = df_matches.groupby('Producto Buscado')['Precio_Ref'].idxmin()
                    df_mix = df_matches.loc[idx_min]
                    total_mix = df_mix['Precio_Pack'].sum()
                    
                    st.metric("Gasto Total Estimado", f"{total_mix:.2f} €")
                    st.dataframe(df_mix[['Producto Buscado', 'Producto Real', 'Marca', 'Supermercado', 'Precio_Pack']], width="stretch", hide_index=True)
                    
                    idx_min_super = df_matches.groupby(['Supermercado', 'Producto Buscado'])['Precio_Ref'].idxmin()
                    df_super = df_matches.loc[idx_min_super]
                    
                    agg_super = df_super.groupby('Supermercado').agg(
                        Items_Encontrados=('Producto Buscado', 'nunique'),
                        Costo_Total=('Precio_Pack', 'sum')
                    ).reset_index()
                    
                    agg_super = agg_super.sort_values(by=['Items_Encontrados', 'Costo_Total'], ascending=[False, True])
                    
                    top_supers = agg_super.head(2)
                    
                    for i, row in top_supers.iterrows():
                        super_name = row['Supermercado']
                        st.divider()
                        st.subheader(f"🔵 RUTA {i+2}: Compra Cómoda en {super_name}")
                        st.write(f"Prioriza hacer toda la compra en un solo viaje. Tienen {row['Items_Encontrados']} de los {len(items_buscados)} productos que buscas.")
                        
                        st.metric("Gasto Total Estimado", f"{row['Costo_Total']:.2f} €")
                        
                        df_this_super = df_super[df_super['Supermercado'] == super_name]
                        st.dataframe(df_this_super[['Producto Buscado', 'Producto Real', 'Marca', 'Precio_Pack']], width="stretch", hide_index=True)
                else:
                    st.warning("No he encontrado esos productos en tu historial. ¡Revisa cómo los escribiste o sube tickets donde aparezcan!")
