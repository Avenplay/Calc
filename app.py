import streamlit as st
import sqlite3
import pandas as pd
from google import genai
from PIL import Image
import json
import os
from datetime import datetime
import time

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
# Cargamos la clave API de forma global
api_key = st.secrets.get("GEMINI_API_KEY", "")

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
                        # Sintaxis oficial 2026
                        client = genai.Client(api_key=api_key)
                        imagen.save("temp_ticket.png")
                        
                        prompt = "Analiza este ticket y devuelve estrictamente un objeto JSON con las claves: supermercado, articulos_despensa (lista de objetos con: producto, marca, unidades_pack, peso_unitario_kg, precio_total). Si no pone la marca, pon 'Blanca'. Sin explicaciones, solo el JSON."
                        
                        uploaded_file = client.files.upload(file="temp_ticket.png")
                        response = client.models.generate_content(
                            model='gemini-2.5-flash', 
                            contents=[uploaded_file, prompt]
                        )
                        
                        raw_text = response.text.strip()
                        
                        # Limpiamos las comillas del JSON
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
# SECCIÓN 2: PLANIFICADOR DE RUTAS
# ==========================================
elif opcion_menu == "🗺️ Planificador de Rutas":
    st.title("🗺️ Planificador de Compra")
    st.markdown("Escribe lo que necesitas comprar separado por comas (ej: *leche, tomate frito, atún*).")
    
    lista_input = st.text_area("Lista de la compra:", height=100)
    
    if st.button("🔍 Calcular Mejor Ruta"):
        if not lista_input.strip():
            st.warning("⚠️ Escribe al menos un producto para buscar.")
        else:
            # 1. Limpiar lista ingresada por el usuario
            articulos = [x.strip().lower() for x in lista_input.split(",") if x.strip()]
            
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            
            resultados_por_articulo = {}
            
            # 2. Búsqueda local en SQLite (Filtrando inactivos)
            for art in articulos:
                query = """
                    SELECT supermercado, marca, peso_unitario, unidades_pack, precio_total, precio_referencia
                    FROM despensa
                    WHERE producto_generico LIKE ? AND activo = 1
                    ORDER BY precio_referencia ASC
                """
                cursor.execute(query, (f"%{art}%",))
                filas = cursor.fetchall()
                
                # Filtrar resultados aplicando el selector del menú lateral
                filas_filtradas = [f for f in filas if f[0] in supers_activos]
                
                if filas_filtradas:
                    resultados_por_articulo[art] = filas_filtradas
                else:
                    st.error(f"❌ No se encontraron precios activos para: **{art}** en los supermercados que has seleccionado hoy.")
            
            conexion.close()
            
            # 3. El Motor de Matemáticas (Calcular rutas)
            if len(resultados_por_articulo) == len(articulos): # Solo si encontró todos los productos
                
                # Diccionarios para guardar los totales y el carrito de cada opción
                totales_monosuper = {superm: 0.0 for superm in supers_activos}
                carrito_monosuper = {superm: [] for superm in supers_activos}
                
                costo_hibrido = 0.0
                carrito_hibrido = []
                
                for art, opciones in resultados_por_articulo.items():
                    # --- Ruta Híbrida (La mejor opción global absoluta) ---
                    mejor_opcion = opciones[0]
                    super_hibrido, marca_h, peso_h, uni_h, precio_h, ref_h = mejor_opcion
                    costo_hibrido += precio_h
                    carrito_hibrido.append((art, super_hibrido, marca_h, precio_h))
                    
                    # --- Rutas Monosúper (La mejor opción por cada tienda) ---
                    for superm in supers_activos:
                        opciones_super = [opt for opt in opciones if opt[0] == superm]
                        if opciones_super:
                            mejor_super = opciones_super[0]
                            totales_monosuper[superm] += mejor_super[4]
                            carrito_monosuper[superm].append((art, mejor_super[1], mejor_super[4]))
                        else:
                            # Si en un súper falta un producto, esa ruta se descarta (precio infinito)
                            totales_monosuper[superm] = float('inf')
                
                # 4. Renderizado Visual (Las Tarjetas)
                st.divider()
                st.subheader("📊 Tus Opciones de Compra")
                
                monosupers_validos = {k: v for k, v in totales_monosuper.items() if v != float('inf')}
                
                if not monosupers_validos:
                    st.warning("⚠️ Ningún supermercado individual tiene TODOS los productos de tu lista. Tendrás que hacer ruta híbrida obligatoriamente.")
                else:
                    # Ordenamos para saber cuál es el súper único más barato
                    monosupers_ordenados = sorted(monosupers_validos.items(), key=lambda x: x[1])
                    mejor_monosuper = monosupers_ordenados[0]
                    ahorro_combinado = mejor_monosuper[1] - costo_hibrido
                    
                    col1, col2, col3 = st.columns(3)
                    
                    # Tarjeta 1: La mejor opción de un solo sitio
                    with col1:
                        st.info(f"🥇 Todo en **{mejor_monosuper[0]}**")
                        st.metric("Costo Total", f"{mejor_monosuper[1]:.2f} €")
                        with st.expander("Ver lista de compra"):
                            for item in carrito_monosuper[mejor_monosuper[0]]:
                                st.write(f"• {item[0].title()} ({item[1]}): {item[2]:.2f} €")
                                
                    # Tarjeta 2: La alternativa de un solo sitio
                    with col2:
                        if len(monosupers_ordenados) > 1:
                            alt_mono = monosupers_ordenados[1]
                            st.warning(f"🥈 Todo en **{alt_mono[0]}**")
                            # Muestra cuánto más caro es respecto al primero
                            st.metric("Costo Total", f"{alt_mono[1]:.2f} €", delta=f"+{(alt_mono[1]-mejor_monosuper[1]):.2f} €", delta_color="inverse")
                            with st.expander("Ver lista de compra"):
                                for item in carrito_monosuper[alt_mono[0]]:
                                    st.write(f"• {item[0].title()} ({item[1]}): {item[2]:.2f} €")
                        else:
                            st.write("No hay alternativas para comprar todo de golpe.")
                            
                    # Tarjeta 3: La Ruta Híbrida (Optimizada)
                    with col3:
                        if ahorro_combinado >= ahorro_minimo:
                            st.success("🗺️ Ruta Híbrida Inteligente")
                            st.metric("Costo Total", f"{costo_hibrido:.2f} €", delta=f"-{ahorro_combinado:.2f} € vs {mejor_monosuper[0]}")
                            with st.expander("Ver paradas de la ruta"):
                                # Agrupamos el carrito híbrido por supermercados para hacerlo más visual
                                rutas = {}
                                for item in carrito_hibrido:
                                    s = item[1]
                                    if s not in rutas:
                                        rutas[s] = []
                                    rutas[s].append((item[0], item[2], item[3]))
                                    
                                for s, items in rutas.items():
                                    st.markdown(f"📍 **Parada en {s}:**")
                                    for i in items:
                                        st.write(f"• {i[0].title()} ({i[1]}): {i[2]:.2f} €")
                        else:
                            # Penalización visual si no compensa la gasolina/tiempo
                            st.error("🗺️ Ruta Híbrida Descartada")
                            st.metric("Costo Total", f"{costo_hibrido:.2f} €")
                            st.write(f"Dar vueltas solo te ahorra **{ahorro_combinado:.2f} €**. ¡No supera tu margen mínimo de {ahorro_minimo:.2f} €! Compra todo en {mejor_monosuper[0]}.")

# ==========================================
# SECCIÓN 3: INGRESO MANUAL / BARRAS
# ==========================================
elif opcion_menu == "✍️ Ingreso Manual / Barras":
    st.title("✍️ Añadir Producto")
    st.write("Registra productos individuales rápidamente sin necesidad de ticket.")
    
    # Dividimos la pantalla en dos pestañas muy limpias
    tab_manual, tab_barras = st.tabs(["📝 Ingreso Manual", "🏷️ Escáner Código de Barras"])
    
    # ------------------------------------------
    # PESTAÑA 1: INGRESO MANUAL
    # ------------------------------------------
    with tab_manual:
        st.subheader("Datos del Producto")
        c1, c2 = st.columns(2)
        with c1: 
            super_m = st.selectbox("Supermercado", LISTA_SUPERS, key="sup_man")
            prod_m = st.text_input("Producto Genérico (ej. tomate frito)").lower().strip()
            marca_m = st.text_input("Marca (ej. Orlando o Blanca)").title().strip()
        with c2: 
            precio_m = st.number_input("Precio Total en caja (€)", min_value=0.0, step=0.10, key="prec_man")
            # El interruptor mágico para los formatos
            es_pack = st.toggle("📦 ¿Es un pack multicantidad?")
            
            if es_pack:
                cc1, cc2 = st.columns(2)
                with cc1: unids_m = st.number_input("Unidades", min_value=2, step=1)
                with cc2: peso_m = st.number_input("Peso de 1 unidad (kg/L)", min_value=0.01, step=0.10)
            else:
                unids_m = 1
                peso_m = st.number_input("Peso/Volumen total (kg/L)", min_value=0.01, step=0.10)
                
        if st.button("💾 Guardar Producto Manual", use_container_width=True):
            if not prod_m:
                st.error("⚠️ El nombre del producto no puede estar vacío.")
            else:
                # Matemáticas locales para el precio de referencia
                peso_total_lote = unids_m * peso_m
                precio_ref = (precio_m / peso_total_lote) if peso_total_lote > 0 else precio_m
                
                conexion = sqlite3.connect(DB_PATH)
                cursor = conexion.cursor()
                fecha_actual = datetime.now().strftime("%Y-%m-%d")
                
                cursor.execute("""
                    INSERT INTO despensa 
                    (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (super_m, prod_m, marca_m, peso_m, unids_m, precio_m, precio_ref, fecha_actual))
                
                conexion.commit()
                conexion.close()
                st.success(f"✅ ¡{prod_m.title()} ({marca_m}) guardado a {precio_ref:.2f} €/kg!")

  # ------------------------------------------
    # PESTAÑA 2: ESCÁNER HÍBRIDO (IA + API + IA)
    # ------------------------------------------
    with tab_barras:
        import requests
        import time
        
        st.subheader("🔍 Escáner Híbrido: Código de Barras")
        st.write("Hazle una foto a los números del código de barras. La IA extraerá el código, consultará la base mundial y estructurará los datos.")
        
        foto_barras = st.camera_input("📸 Capturar Código de Barras")
        
        if foto_barras:
            if st.button("🚀 Iniciar Escaneo Híbrido", use_container_width=True):
                
                try:
                    client = genai.Client(api_key=api_key)
                    img = Image.open(foto_barras)
                    img.save("temp_barras.png")
                    
                    # FASE 1: IA lee la imagen (Con sistema anti-colapso 503)
                    with st.spinner("Fase 1: IA leyendo el código numérico..."):
                        prompt_1 = "Lee el código de barras de esta imagen. Devuelve ÚNICAMENTE los números (suele tener 13 dígitos). Nada de texto adicional ni símbolos, solo el número."
                        uploaded_file = client.files.upload(file="temp_barras.png")
                        
                        max_reintentos = 3
                        for intento in range(max_reintentos):
                            try:
                                res_1 = client.models.generate_content(
                                    model='gemini-2.5-flash', 
                                    contents=[uploaded_file, prompt_1]
                                )
                                break # Si funciona, sale del bucle de reintentos
                            except Exception as api_error:
                                if "503" in str(api_error) and intento < max_reintentos - 1:
                                    time.sleep(2) # Espera 2 segundos y vuelve a intentar
                                    continue
                                else:
                                    raise api_error # Si falla 3 veces, muestra el error
                        
                        codigo_ean = res_1.text.strip().replace(" ", "")
                        
                        if os.path.exists("temp_barras.png"): 
                            os.remove("temp_barras.png")
                            
                    # Comprobamos que lo que ha devuelto la IA son números
                    if not codigo_ean.isdigit():
                        st.error(f"❌ La IA no pudo leer un número claro. Intentó leer: {codigo_ean}. Prueba a acercar más la cámara a los números.")
                    else:
                        st.success(f"✅ Código EAN detectado: {codigo_ean}")
                        
                        # FASE 2: Python consulta la API Open Food Facts
                        with st.spinner("Fase 2: Conectando con Open Food Facts..."):
                            url = f"https://world.openfoodfacts.org/api/v2/product/{codigo_ean}.json"
                            res_api = requests.get(url)
                            
                            if res_api.status_code == 200 and res_api.json().get('status') == 1:
                                datos_crudos = res_api.json().get('product', {})
                                
                                # Extraemos lo esencial para no saturar a la IA
                                info_para_ia = {
                                    "nombre": datos_crudos.get("product_name", "Desconocido"),
                                    "marca": datos_crudos.get("brands", ""),
                                    "cantidad": datos_crudos.get("quantity", "")
                                }
                                
                                # FASE 3: IA limpia y estructura el JSON (También con escudo 503)
                                with st.spinner("Fase 3: IA normalizando los datos brutos..."):
                                    prompt_2 = f"Aquí tienes los datos brutos de un producto sacados de una API: {json.dumps(info_para_ia)}. Actúa como un estructurador de datos y devuelve estrictamente un objeto JSON con 3 claves: 'producto_generico' (el nombre limpio y en minúsculas), 'marca' (la marca principal, si está vacía pon 'Blanca'), y 'peso_total' (convierte la cantidad a un número en kilogramos o litros, ej: si pone 400g o 400ml pon 0.4. Si no hay cantidad, pon 1.0). Sin explicaciones, solo el JSON puro."
                                    
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
                                    if json_marker in raw_text:
                                        raw_text = raw_text.split(json_marker)[1]
                                    if end_marker in raw_text:
                                        raw_text = raw_text.rsplit(end_marker, 1)[0]
                                        
                                    datos_ia = json.loads(raw_text.strip())
                                    
                                    # Guardamos en memoria para el formulario
                                    st.session_state['ia_temp_nombre'] = datos_ia.get('producto_generico', '').lower()
                                    st.session_state['ia_temp_marca'] = datos_ia.get('marca', 'Blanca').title()
                                    st.session_state['ia_temp_peso'] = float(datos_ia.get('peso_total', 1.0))
                                    
                                    st.rerun()
                            else:
                                st.error("❌ El código se leyó bien, pero el producto no existe en la base de datos de Open Food Facts.")
                                
                except Exception as e: 
                    st.error(f"Error en el proceso híbrido: {e}")
                    
        # Formulario final donde apruebas lo que ha hecho el puente híbrido
        if 'ia_temp_nombre' in st.session_state:
            st.divider()
            st.write("🛠️ **Datos estructurados. Añade el precio y guarda:**")
            
            c_ia1, c_ia2 = st.columns(2)
            with c_ia1:
                nombre_ia = st.text_input("Producto", value=st.session_state.get('ia_temp_nombre', ''), key="nom_ia")
                marca_ia = st.text_input("Marca", value=st.session_state.get('ia_temp_marca', 'Blanca'), key="mar_ia")
                super_ia = st.selectbox("Comprado en:", LISTA_SUPERS, key="sup_ia")
            with c_ia2:
                peso_ia = st.number_input("Peso Neto (kg/L)", value=float(st.session_state.get('ia_temp_peso', 1.0)), min_value=0.01, step=0.10, key="pes_ia")
                precio_ia = st.number_input("Precio en estantería (€)", min_value=0.0, step=0.10, key="prec_ia")
                
            if st.button("💾 Guardar Producto", type="primary", use_container_width=True):
                if precio_ia <= 0:
                    st.warning("⚠️ Recuerda introducir el precio del producto antes de guardar.")
                else:
                    precio_ref_ia = precio_ia / peso_ia
                    
                    conexion = sqlite3.connect(DB_PATH)
                    cursor = conexion.cursor()
                    cursor.execute("""
                        INSERT INTO despensa 
                        (supermercado, producto_generico, marca, peso_unitario, unidades_pack, precio_total, precio_referencia, activo, fecha_compra) 
                        VALUES (?, ?, ?, ?, 1, ?, ?, 1, ?)
                    """, (super_ia, nombre_ia.lower(), marca_ia.title(), peso_ia, precio_ia, precio_ref_ia, datetime.now().strftime("%Y-%m-%d")))
                    
                    conexion.commit()
                    conexion.close()
                    
                    st.session_state.pop('ia_temp_nombre', None)
                    st.session_state.pop('ia_temp_marca', None)
                    st.session_state.pop('ia_temp_peso', None)
                    
                    st.success(f"✅ ¡{nombre_ia.title()} guardado correctamente!")
                    st.rerun()

# ==========================================
# SECCIÓN 4: MI DESPENSA (CONFIGURACIÓN)
# ==========================================
elif opcion_menu == "📦 Mi Despensa (Configuración)":
    st.title("📦 Mi Despensa y Precios")
    st.markdown("Consulta tu histórico, corrige nombres o **desactiva** productos para que el planificador los ignore.")

    conexion = sqlite3.connect(DB_PATH)
    # Cargamos toda la tabla en un DataFrame de Pandas
    df_despensa = pd.read_sql_query("SELECT * FROM despensa", conexion)
    conexion.close()

    if df_despensa.empty:
        st.info("🛒 Tu despensa está vacía. Ve al escáner o al formulario para añadir tus primeros productos.")
    else:
        # Convertimos el 1 y 0 de SQLite a True/False para que Streamlit muestre un checkbox bonito
        df_despensa['activo'] = df_despensa['activo'].astype(bool)

        st.subheader("🗂️ Panel de Control de Productos")
        
        # Tabla interactiva
        df_editado = st.data_editor(
            df_despensa,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "supermercado": st.column_config.TextColumn("Súper", disabled=True),
                "producto_generico": st.column_config.TextColumn("Producto (Editable)"),
                "marca": st.column_config.TextColumn("Marca (Editable)"),
                "peso_unitario": st.column_config.NumberColumn("Peso (kg/L)", disabled=True),
                "unidades_pack": st.column_config.NumberColumn("Unidades", disabled=True),
                "precio_total": st.column_config.NumberColumn("Precio Total", disabled=True, format="%.2f €"),
                "precio_referencia": st.column_config.NumberColumn("€/kg o L", disabled=True, format="%.3f €"),
                "activo": st.column_config.CheckboxColumn("Activo (Usar en rutas)", default=True),
                "fecha_compra": st.column_config.TextColumn("Fecha", disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )

        if st.button("💾 Guardar Cambios en la Base de Datos", type="primary"):
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            
            # Recorremos la tabla editada y actualizamos SQLite
            for index, row in df_editado.iterrows():
                # Volvemos a convertir el True/False del checkbox a 1 o 0 para la base de datos
                activo_int = 1 if row['activo'] else 0 
                
                cursor.execute("""
                    UPDATE despensa
                    SET activo = ?, producto_generico = ?, marca = ?
                    WHERE id = ?
                """, (activo_int, row['producto_generico'], row['marca'], row['id']))
                
            conexion.commit()
            conexion.close()
            st.success("✅ ¡Base de datos actualizada con éxito!")
            st.rerun()

        st.divider()
        
        # Zona de borrado permanente por si te equivocas metiendo un producto
        st.subheader("🗑️ Zona de Peligro: Eliminar Registro")
        st.write("Si quieres borrar un producto para siempre (en lugar de desactivarlo), introduce su ID.")
        
        col_del1, col_del2 = st.columns([1, 3])
        with col_del1:
            id_borrar = st.number_input("ID a borrar:", min_value=0, step=1)
        with col_del2:
            st.write("") # Espaciador para alinear el botón
            st.write("")
            if st.button("❌ Eliminar Producto Definitivamente"):
                if id_borrar > 0:
                    conexion = sqlite3.connect(DB_PATH)
                    cursor = conexion.cursor()
                    cursor.execute("DELETE FROM despensa WHERE id = ?", (id_borrar,))
                    conexion.commit()
                    conexion.close()
                    st.success(f"Registro {id_borrar} eliminado del sistema.")
                    st.rerun()
                else:
                    st.warning("Introduce un ID válido mayor que 0.")
