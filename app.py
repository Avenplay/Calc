import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime
import json
import os
import time
from PIL import Image
from google import genai
import requests
import warnings

# Suprimir avisos
warnings.filterwarnings('ignore', category=UserWarning)

# ------------------------------------------
# CONFIGURACIÓN GLOBAL
# ------------------------------------------
st.set_page_config(page_title="Optimizador de Compra", layout="wide")
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
    st.write("Introduce la contraseña maestra del búnker financiero.")
    contrasena = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary", width="stretch"):
        if contrasena == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("❌ Contraseña incorrecta.")
    return False

if not check_password():
    st.stop()

# ==========================================
# CÓDIGO PRINCIPAL - VERSIÓN 2.0
# ==========================================
LISTA_SUPERS = ["Mercadona", "Carrefour", "Lidl", "Aldi", "Dia", "Alcampo", "Eroski", "Consum", "Otro"]

def get_db_conexion():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

@st.cache_resource
def init_db():
    conexion = get_db_conexion()
    cursor = conexion.cursor()
    # NUEVA TABLA V2: Enfocada 100% en analítica de precios y rutas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registro_precios (
            id SERIAL PRIMARY KEY,
            supermercado TEXT,
            categoria TEXT,
            producto_generico TEXT,
            marca TEXT,
            es_marca_blanca BOOLEAN,
            peso_unitario REAL,
            unidades_pack INTEGER,
            precio_total REAL,
            precio_normalizado REAL,
            activo INTEGER DEFAULT 1,
            fecha_compra TEXT
        )
    """)
    conexion.commit()
    conexion.close()
    return True

init_db()

def limpiar_temporales():
    for f in os.listdir("."):
        if f.startswith("temp_") and f.endswith(".png"):
            try:
                os.remove(f)
            except:
                pass

st.title("🛒 Motor de Inteligencia de Compra")

# ------------------------------------------
# PESTAÑAS DE NAVEGACIÓN
# ------------------------------------------
tab_masivo, tab_ticket, tab_rutas, tab_db = st.tabs([
    "📝 1. Ingreso Masivo (IA)", 
    "🧾 2. Subir Ticket", 
    "🗺️ 3. Calcular Ruta Barata", 
    "📊 4. Base de Datos"
])

# ==========================================
# PESTAÑA 1: INGRESO MASIVO POR TEXTO (IA)
# ==========================================
with tab_masivo:
    st.header("Volcado de Precios Rápido")
    st.write("Pega aquí tu lista de precios o notas del supermercado. La IA lo estructurará, le asignará categorías y calculará el precio por Kilo/Litro.")
    
    # 1. SOLUCIÓN: clear_on_submit=True limpia el cuadro de texto automáticamente al darle al botón
    with st.form("form_masivo", clear_on_submit=True):
        super_masivo = st.selectbox("¿De qué supermercado son estos precios?", LISTA_SUPERS)
        texto_masivo = st.text_area("Lista de productos (Ej: fideos finos hacendado 0.5kg 1,2€)", height=150)
        btn_procesar = st.form_submit_button("🧠 Extraer con Inteligencia Artificial", type="primary", width="stretch")
        
    if btn_procesar and texto_masivo:
        with st.spinner("La IA está leyendo y categorizando tus productos..."):
            try:
                client = genai.Client(api_key=api_key)
                
               # 2. SOLUCIÓN: Reglas estrictas para adivinar la marca blanca y forzar pesos por defecto
                prompt = f"""
                Analiza esta lista de productos del supermercado '{super_masivo}':
                {texto_masivo}
                
                Devuelve ÚNICAMENTE un JSON estricto que sea una lista de objetos. Cada objeto debe tener estas claves exactas:
                - "categoria": Infiere una categoría lógica (ej: "Pasta", "Frescos", "Limpieza").
                - "producto_generico": El nombre base absoluto y minimalista. ELIMINA adjetivos redundantes con la categoría (ej: si es categoría 'Frescos', pon 'tomate', NUNCA 'tomate fresco'). Si es pasta, pon 'tallarines', NUNCA 'tallarines largos'. TODO EN MINÚSCULAS y en singular.
                - "marca": Si no se especifica en el texto, deduce la marca blanca principal de '{super_masivo}' (ej: si es Mercadona pon 'Hacendado', si es Carrefour pon 'Carrefour', Lidl pon 'Milbona' o 'Balea'). NUNCA uses la palabra 'Blanca'.
                - "es_marca_blanca": true o false (booleano).
                - "peso_unitario": float con el peso en Kg o Litros de una unidad. Si el texto no lo dice, asume 1.0.
                - "unidades_pack": int (si es suelto pon 1).
                - "precio_total": float con el precio total en euros.
                """
                response = client.models.generate_content(model='gemini-2.5-flash', contents=[prompt])
                
                raw_text = response.text.strip()
                if "```json" in raw_text: raw_text = raw_text.split("```json")[1]
                if "```" in raw_text: raw_text = raw_text.rsplit("```", 1)[0]
                
                datos_extraidos = json.loads(raw_text.strip())
                
                # 3. SOLUCIÓN: Calculamos el precio_normalizado en Python para mostrarlo en la tabla previa
                for item in datos_extraidos:
                    try:
                        peso = float(item.get('peso_unitario', 1.0))
                        uds = int(item.get('unidades_pack', 1))
                        precio = float(item.get('precio_total', 0.0))
                        
                        peso_total = peso * uds
                        if peso_total > 0:
                            item['precio_normalizado'] = round(precio / peso_total, 2)
                        else:
                            item['precio_normalizado'] = precio
                    except:
                        item['precio_normalizado'] = 0.0
                        
                st.session_state['datos_masivos'] = datos_extraidos
                st.success("¡Extracción completada! Revisa los datos antes de guardarlos.")
            except Exception as e:
                st.error(f"Error en la IA: {e}")

    if 'datos_masivos' in st.session_state:
        st.divider()
        st.write("### 🔍 Revisión Final (Puedes editar las celdas directamente)")
        
        df_masivo = pd.DataFrame(st.session_state['datos_masivos'])
        
        # Reordenamos las columnas para que el precio_normalizado se vea al final de la tabla
        columnas_orden = ['categoria', 'producto_generico', 'marca', 'es_marca_blanca', 'peso_unitario', 'unidades_pack', 'precio_total', 'precio_normalizado']
        df_masivo = df_masivo[columnas_orden]
        
        df_editado = st.data_editor(df_masivo, num_rows="dynamic", width="stretch")
        
        if st.button("💾 Guardar Todo en la Base de Datos", width="stretch"):
            conexion = get_db_conexion()
            cursor = conexion.cursor()
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            
            for _, row in df_editado.iterrows():
                # Ahora simplemente leemos el precio normalizado desde la tabla, ya no lo calculamos aquí
                cursor.execute("""
                    INSERT INTO registro_precios 
                    (supermercado, categoria, producto_generico, marca, es_marca_blanca, peso_unitario, unidades_pack, precio_total, precio_normalizado, fecha_compra) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (super_masivo, str(row['categoria']).title(), str(row['producto_generico']).lower(), str(row['marca']).title(), 
                      bool(row['es_marca_blanca']), float(row['peso_unitario']), int(row['unidades_pack']), 
                      float(row['precio_total']), float(row['precio_normalizado']), fecha_hoy))
                
            conexion.commit()
            conexion.close()
            del st.session_state['datos_masivos']
            st.success("✅ ¡Base de datos actualizada masivamente!")
            st.rerun()

# ==========================================
# PESTAÑA 2: ESCÁNER DE TICKETS
# ==========================================
with tab_ticket:
    st.header("Subir Ticket Físico")
    st.write("Si tienes el ticket en papel, súbelo aquí. La IA intentará inferir las categorías automáticamente.")
    # El código aquí es el mismo del ticket anterior, pero adaptado a la tabla nueva si en el futuro decides usarlo.
    st.info("Para esta versión 2.0 nos estamos centrando en el Ingreso Masivo y la Planificación. ¡Puedes usar la pestaña 1 para meter datos a velocidad de vértigo!")

# ==========================================
# PESTAÑA 3: PLANIFICADOR Y RUTAS (LA MAGIA)
# ==========================================
with tab_rutas:
    # Creamos la lista de la compra en la memoria de la sesión
    if 'lista_compra' not in st.session_state:
        st.session_state['lista_compra'] = []

    st.header("📝 1. Construir Lista de la Compra")
    
    conexion = get_db_conexion()
    df_db = pd.read_sql_query("SELECT * FROM registro_precios WHERE activo = 1", conexion)
    conexion.close()
    
    if df_db.empty:
        st.warning("Tu base de datos está vacía. Usa el 'Ingreso Masivo' para empezar.")
    else:
        col_select, col_lista = st.columns(2)
        
       # --- PARTE A: NAVEGADOR POR CATEGORÍAS ---
        with col_select:
            st.subheader("🛒 Pasillos (Buscador)")
            categorias_existentes = sorted(df_db['categoria'].unique().tolist())
            cat_seleccionada = st.selectbox("Selecciona un pasillo:", ["-- Elige Categoría --"] + categorias_existentes)
            
            if cat_seleccionada != "-- Elige Categoría --":
                df_cat = df_db[df_db['categoria'] == cat_seleccionada]
                # Obtenemos solo los nombres genéricos sin duplicados
                productos_unicos = sorted(df_cat['producto_generico'].unique().tolist())
                
                # INTERFAZ LIMPIA: Usamos multiselect en lugar de la tabla de checkboxes
                productos_a_añadir = st.multiselect(
                    f"¿Qué necesitas de {cat_seleccionada}?", 
                    options=productos_unicos,
                    placeholder="Haz clic aquí para seleccionar..."
                )
                
                if st.button("⬇️ Añadir a la Ruta", type="primary", width="stretch"):
                    if productos_a_añadir:
                        for p in productos_a_añadir:
                            if p not in st.session_state['lista_compra']:
                                st.session_state['lista_compra'].append(p)
                        st.success(f"✅ Productos añadidos a tu lista.")
                        st.rerun()
                    else:
                        st.warning("⚠️ Selecciona al menos un producto primero.")

        # --- PARTE B: LA LISTA FINAL Y CÁLCULO ---
        with col_lista:
            st.subheader("📋 Tu Lista Actual")
            todos_los_productos = sorted(df_db['producto_generico'].unique().tolist())
            
            # El multiselect permite ver lo que hay, borrar con la 'x', y buscar cosas extra a mano
            lista_actual = st.multiselect(
                "Añade o quita productos de tu lista final:", 
                options=todos_los_productos,
                default=st.session_state['lista_compra']
            )
            # Actualizamos la memoria con los cambios manuales
            st.session_state['lista_compra'] = lista_actual

            if st.button("🗑️ Vaciar Lista"):
                st.session_state['lista_compra'] = []
                st.rerun()

        st.divider()
        
        # --- PARTE C: LAS 3 RUTAS CLÁSICAS ---
        if st.session_state['lista_compra']:
            if st.button("🚀 Calcular las 3 Mejores Opciones", type="primary", width="stretch"):
                items_buscados = st.session_state['lista_compra']
                df_matches = df_db[df_db['producto_generico'].isin(items_buscados)]
                
                if not df_matches.empty:
                    st.header("🗺️ Resultados de Rutas")
                    
                    # 1. RUTA: EL MAYOR AHORRO (MIX)
                    st.subheader("🟢 RUTA 1: El Mayor Ahorro (Varios Supermercados)")
                    st.write("Comprando cada producto donde el Kilo/Litro es más barato.")
                    
                    idx_min = df_matches.groupby('producto_generico')['precio_normalizado'].idxmin()
                    df_mix = df_matches.loc[idx_min]
                    total_mix = df_mix['precio_total'].sum()
                    
                    st.metric("Gasto Total Estimado (Caja)", f"{total_mix:.2f} €")
                    
                    # Columnas limpias sin fechas ni IDs
                    df_mostrar_mix = df_mix[['producto_generico', 'marca', 'supermercado', 'precio_total', 'precio_normalizado']].copy()
                    df_mostrar_mix.columns = ['Producto', 'Marca', 'Supermercado', 'Precio Caja (€)', 'Precio Real (€/Kg-L)']
                    df_mostrar_mix['Producto'] = df_mostrar_mix['Producto'].str.title()
                    st.dataframe(df_mostrar_mix, width="stretch", hide_index=True)
                    
                    # 2 y 3. RUTAS: COMPRA CÓMODA
                    idx_min_super = df_matches.groupby(['supermercado', 'producto_generico'])['precio_normalizado'].idxmin()
                    df_super = df_matches.loc[idx_min_super]
                    
                    agg_super = df_super.groupby('supermercado').agg(
                        Items_Encontrados=('producto_generico', 'nunique'),
                        Costo_Total=('precio_total', 'sum')
                    ).reset_index()
                    
                    agg_super = agg_super.sort_values(by=['Items_Encontrados', 'Costo_Total'], ascending=[False, True])
                    top_supers = agg_super.head(2)
                    
                    for i, row in top_supers.iterrows():
                        super_name = row['supermercado']
                        st.divider()
                        st.subheader(f"🔵 RUTA {i+2}: Compra Cómoda en {super_name}")
                        st.write(f"Tienen {row['Items_Encontrados']} de los {len(items_buscados)} productos que buscas.")
                        
                        st.metric("Gasto Total Estimado", f"{row['Costo_Total']:.2f} €")
                        
                        df_this_super = df_super[df_super['supermercado'] == super_name]
                        df_show_sup = df_this_super[['producto_generico', 'marca', 'precio_total', 'precio_normalizado']].copy()
                        df_show_sup.columns = ['Producto', 'Marca', 'Precio Caja (€)', 'Precio Real (€/Kg-L)']
                        df_show_sup['Producto'] = df_show_sup['Producto'].str.title()
                        
                        st.dataframe(df_show_sup, width="stretch", hide_index=True)

# ==========================================
# PESTAÑA 4: BASE DE DATOS LIMPÍA Y EDITABLE
# ==========================================
with tab_db:
    st.header("📊 Tu Registro de Precios")
    if not df_db.empty:
        st.write("Corrige los nombres directamente en la tabla (ej: quita 'fresco' de tomate) o marca 'Borrar' para eliminar.")
        
        df_func = df_db[['id', 'categoria', 'producto_generico', 'marca', 'supermercado', 'precio_total', 'precio_normalizado', 'fecha_compra']].copy()
        df_func.columns = ['id', 'Categoría', 'Producto', 'Marca', 'Supermercado', 'Precio Caja (€)', 'Precio (€/Kg-L)', 'fecha_compra']
        df_func['Borrar'] = False
        
        edited_df = st.data_editor(
            df_func,
            hide_index=True,
            column_config={
                "id": None,           
                "fecha_compra": None  
            },
            # He quitado 'Categoría' y 'Producto' de disabled para que puedas editarlos
            disabled=["Marca", "Supermercado", "Precio Caja (€)", "Precio (€/Kg-L)"],
            width="stretch"
        )
        
        col_borrar, col_guardar = st.columns(2)
        
        with col_borrar:
            if st.button("🗑️ Eliminar Seleccionados", width="stretch"):
                ids_borrar = edited_df[edited_df['Borrar'] == True]['id'].tolist()
                if ids_borrar:
                    conexion = get_db_conexion()
                    cursor = conexion.cursor()
                    cursor.execute(f"UPDATE registro_precios SET activo = 0 WHERE id IN ({','.join(map(str, ids_borrar))})")
                    conexion.commit()
                    conexion.close()
                    st.success("✅ Productos eliminados.")
                    st.rerun()
                    
        with col_guardar:
            if st.button("💾 Guardar Correcciones de Texto", type="primary", width="stretch"):
                conexion = get_db_conexion()
                cursor = conexion.cursor()
                for index, row in edited_df.iterrows():
                    # Esto actualizará la base de datos con cualquier letra o nombre que cambies a mano
                    cursor.execute("""
                        UPDATE registro_precios 
                        SET categoria = %s, producto_generico = %s 
                        WHERE id = %s
                    """, (row['Categoría'], row['Producto'], row['id']))
                conexion.commit()
                conexion.close()
                st.success("✅ Base de datos limpia y normalizada.")
                st.rerun()
    else:
        st.info("Base de datos en blanco.")
