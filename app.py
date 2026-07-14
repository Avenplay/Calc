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
