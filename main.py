import os
import re
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from supabase import create_client, Client

app = Flask(__name__)
client = Anthropic()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===========================================================
# CONSTANTES Y MAPEOS
# ===========================================================

# Sufijos de botones → columna y valor en Supabase
SUFIJOS_BOTONES = {
    "r":  ("TAGS",    "Rayado"),
    "l":  ("TAGS",    "Liso"),
    "m":  ("Acabado", "Mate"),
    "b":  ("Acabado", "Brillante"),
    "2":  ("Hoyos",   "2 hoyos"),
    "4":  ("Hoyos",   "4 hoyos"),
}

# Sufijos de mercería → color
SUFIJOS_MERCERIA = {
    "b":  "Blanco",
    "n":  "Negro",
    "m":  "Marino",
    "cr": "Crudo",
}

# Tamaños válidos de botones (líneas)
TAMAÑOS_VALIDOS = {"12","14","16","18","20","24","28","30","36","40","45","54","60"}

# Palabras que indican intención de búsqueda (no son criterios)
STOPWORDS = {
    "hola","buen","dia","tarde","noche","gracias","ok","disculpa",
    "dame","dime","muestra","muestrame","busco","necesito","quiero",
    "quisiera","favor","tienes","tengan","cuenten","hay","algun","alguna",
    "opciones","opcion","con","que","del","una","para","los","las","por",
    "boton","botón","modelo","estilo","tipo","talla","tamaño","cual","cuales",
    "del","sobre","sus","disponibles","disponible","actualmente","ahora",
}

# Palabras que ya son criterios estructurados (no buscar en TAGS)
PALABRAS_CRITERIO = {
    "mate","brillante","rayado","liso","teñible","teñir",
    "camisero","camisa","sastre","pantalon","fantasia","fantasía",
    "decorativo","pantalón","mazos","mazo","gruesa","gruesas",
    "piezas","unidades","imagen","foto","existencia","stock",
    "llegada","cuando","cuándo",
}

# Palabras de mercería (detectan tabla)
PALABRAS_MERCERIA = {
    "cinta","palmita","resorte","elastico","elástico","plastiflecha",
    "candado","fleco","satinado","bolsas","contactel","crochet","crochet","hilo",
    "encaje","velcro","sesgo","ribete","pretina","broches","broche","cierre",
}


# ===========================================================
# PARSER DE SKU
# ===========================================================

def parsear_sku_boton(texto: str) -> dict:
    """
    Parsea cualquier formato de SKU de botón.
    Formato real en Supabase: B + 4 dígitos (modelo) + 2 dígitos (tamaño) = 6 dígitos
    
    Ejemplos:
    - B221814-L  → modelo=2218, tamaño=14, sufijo=l
    - B221814    → modelo=2218, tamaño=14
    - B2218      → modelo=2218 (sin tamaño)
    - 2218       → modelo=2218
    - 221814     → modelo=2218, tamaño=14
    """
    resultado = {"modelo": None, "tamaño": None, "sufijo": None}

    # Formato completo con sufijo: B221814-L o B221814-SPL
    m = re.search(r'\bB(\d{4})(\d{2})[-]([A-Za-z0-9]{1,5})\b', texto, re.IGNORECASE)
    if m:
        resultado["modelo"] = m.group(1)
        resultado["tamaño"] = m.group(2)
        resultado["sufijo"] = m.group(3).lower()
        return resultado

    # 6 dígitos con sufijo sin B: 221814-L
    m = re.search(r'\b(\d{4})(\d{2})[-]([A-Za-z0-9]{1,5})\b', texto)
    if m:
        resultado["modelo"] = m.group(1)
        resultado["tamaño"] = m.group(2)
        resultado["sufijo"] = m.group(3).lower()
        return resultado

    # 6 dígitos sin sufijo: B221814 o 221814
    m = re.search(r'\bB?(\d{4})(\d{2})\b', texto, re.IGNORECASE)
    if m:
        resultado["modelo"] = m.group(1)
        resultado["tamaño"] = m.group(2)
        return resultado

    # Solo modelo 4 dígitos con sufijo: B2218-L o 2218-L
    m = re.search(r'\bB?(\d{4})[-]([A-Za-z0-9]{1,5})\b', texto, re.IGNORECASE)
    if m:
        resultado["modelo"] = m.group(1)
        resultado["sufijo"] = m.group(2).lower()
        return resultado

    # Solo modelo 4 dígitos: B2218 o 2218
    m = re.search(r'\bB?(\d{4})\b', texto, re.IGNORECASE)
    if m:
        resultado["modelo"] = m.group(1)
        return resultado

    return resultado


def parsear_modelo_merceria(texto: str) -> dict:
    """
    Parsea modelos de mercería:
    - E07-N   → base=E07, sufijo=n
    - CPA10-B → base=CPA10, sufijo=b
    - E07     → base=E07
    """
    resultado = {"base": None, "sufijo": None}

    # Con sufijo: E07-N, CPA10-B, BP15-CR
    m = re.search(r'\b([A-Za-z]{1,3}\d{1,4})[-]([A-Za-z]{1,2})\b', texto)
    if m:
        resultado["base"] = m.group(1).upper()
        resultado["sufijo"] = m.group(2).lower()
        return resultado

    # Sin sufijo: E07, CPA10
    m = re.search(r'\b([A-Za-z]{1,3}\d{1,4})\b', texto)
    if m and not m.group(1).upper().startswith('B'):
        resultado["base"] = m.group(1).upper()
        return resultado

    return resultado


# ===========================================================
# BÚSQUEDA EN SUPABASE
# ===========================================================

def buscar_botones(pregunta: str, pregunta_lower: str, palabras: list) -> list:
    """Búsqueda específica para tabla inventario_botones."""

    # --- Parsear SKU ---
    sku = parsear_sku_boton(pregunta)
    modelo = sku["modelo"]
    tamaño = sku["tamaño"]
    sufijo = sku["sufijo"]

    # --- Tamaño por palabras si no viene en SKU ---
    if not tamaño:
        m = re.search(r'(?:talla|tamaño|linea|línea|en)\s*(\d{2})', pregunta_lower)
        if m:
            tamaño = m.group(1)
        else:
            for n in re.findall(r'\b(\d{2})\b', pregunta):
                if n in TAMAÑOS_VALIDOS:
                    tamaño = n
                    break

    # --- Hoyos ---
    hoyos = None
    if re.search(r'2\s*hoyo|dos\s*hoyo', pregunta_lower):
        hoyos = "2 hoyos"
    elif re.search(r'4\s*hoyo|cuatro\s*hoyo', pregunta_lower):
        hoyos = "4 hoyos"
    # Sufijo de hoyos
    if sufijo in ("2", "4") and not hoyos:
        hoyos = f"{sufijo} hoyos"
        sufijo = None

    # --- Acabado ---
    acabado = None
    if sufijo in ("m", "b"):
        acabado = SUFIJOS_BOTONES[sufijo][1]
    elif "mate" in palabras:
        acabado = "Mate"
    elif "brillante" in palabras:
        acabado = "Brillante"

    # --- TAG filtro (sufijo o palabra) ---
    tag_filtro = None
    if sufijo in ("r", "l"):
        tag_filtro = SUFIJOS_BOTONES[sufijo][1]
    elif "rayado" in palabras:
        tag_filtro = "Rayado"
    elif "liso" in palabras:
        tag_filtro = "Liso"
    elif "teñible" in palabras or "teñir" in palabras:
        tag_filtro = "Teñible"

    # --- Uso ---
    uso = None
    if any(p in palabras for p in ["camisero", "camisa"]):
        uso = "Camisero"
    elif any(p in palabras for p in ["sastre", "pantalon", "pantalón", "saco"]):
        uso = "Sastre"
    elif any(p in palabras for p in ["fantasia", "fantasía", "decorativo"]):
        uso = "Fantasía"

    # --- Stock mínimo en MAZOS (Stock_Mazos ya está en mazos) ---
    stock_minimo_mazos = None
    m_mz = re.search(r'(\d+)\s*mazos?\b', pregunta_lower)
    m_gr = re.search(r'(\d+)\s*gruesas?\b', pregunta_lower)
    m_pz = re.search(r'(\d{2,6})\s*(?:unidades|piezas|pzs)\b', pregunta_lower)
    if m_mz:
        stock_minimo_mazos = int(m_mz.group(1))
        print(f"Stock mínimo: {stock_minimo_mazos} mazos")
    elif m_gr:
        # 1 mazo = 12 gruesas
        stock_minimo_mazos = round(int(m_gr.group(1)) / 12, 2)
        print(f"Stock mínimo: {stock_minimo_mazos} mazos (de {m_gr.group(1)} gruesas)")
    elif m_pz:
        # 1 mazo = 1728 piezas
        stock_minimo_mazos = round(int(m_pz.group(1)) / 1728, 2)

    # --- Palabras libres → TAGS (ej: "coco", "cuerno", "blusa") ---
    palabras_usadas = PALABRAS_CRITERIO | STOPWORDS
    if acabado:
        palabras_usadas.update(["mate", "brillante"])
    if uso:
        palabras_usadas.update(["camisero","camisa","sastre","pantalon","saco","fantasia","fantasía"])
    palabras_libres = [p for p in palabras
                       if p not in palabras_usadas and not p.isdigit() and len(p) > 2]

    # --- Construir query ---
    # El modelo en Supabase es el SKU completo: B221814
    # Buscamos con ilike para que "2218" encuentre B221814, B221816, etc.
    query = supabase.table("inventario_botones").select("*")

    if modelo and tamaño:
        # Busca modelo+tamaño exactos: B221814
        query = query.ilike("Modelo", f"%{modelo}{tamaño}%")
    elif modelo:
        # Solo modelo: trae todas las tallas del modelo
        query = query.ilike("Modelo", f"%{modelo}%")

    # Sufijo en el modelo (ej: -L, -SPL, -ANCLA)
    if sufijo and sufijo not in ("m", "b", "r", "l", "2", "4"):
        # Sufijo especial → buscar en nombre del modelo directamente
        query = query.ilike("Modelo", f"%-{sufijo.upper()}%")

    if hoyos:
        query = query.eq("Hoyos", hoyos)
    if acabado:
        query = query.eq("Acabado", acabado)
    if tag_filtro:
        query = query.ilike("TAGS", f"%{tag_filtro}%")
    if uso:
        query = query.eq("Uso", uso)
    if stock_minimo_mazos:
        query = query.gte("Stock_Mazos", stock_minimo_mazos)
    if palabras_libres:
        query = query.ilike("TAGS", f"%{palabras_libres[0]}%")

    hay_criterio = any([modelo, tamaño, hoyos, acabado, tag_filtro, uso,
                        stock_minimo_mazos, palabras_libres])

    # Sin criterios → búsqueda genérica en TAGS, Uso y Modelo
    if not hay_criterio:
        resultados = []
        for col in ["Modelo", "Uso", "TAGS"]:
            for p in palabras[:4]:
                try:
                    r = supabase.table("inventario_botones").select("*").ilike(col, f"%{p}%").limit(4).execute()
                    if r.data:
                        resultados.extend(r.data)
                except:
                    pass
        unicos = {r["id"]: r for r in resultados}
        return list(unicos.values())[:6]

    data = query.limit(20).execute().data or []

    # Filtro Python para palabras libres adicionales
    if len(palabras_libres) > 1 and data:
        for extra in palabras_libres[1:]:
            data = [r for r in data if extra in (r.get("TAGS") or "").lower()]

    return data[:6]


def buscar_merceria(pregunta: str, pregunta_lower: str, palabras: list) -> list:
    """Búsqueda específica para tabla inventario_merceria."""

    # --- Parsear modelo de mercería ---
    sku = parsear_modelo_merceria(pregunta)
    base = sku["base"]
    sufijo = sku["sufijo"]

    # Color del sufijo
    color = SUFIJOS_MERCERIA.get(sufijo) if sufijo else None

    # --- Medida (ej: "7mm", "20 mm") ---
    medida = None
    m = re.search(r'(\d+)\s*mm', pregunta_lower)
    if m:
        medida = m.group(1)

    # --- Stock mínimo en piezas para mercería ---
    stock_minimo = None
    m_mz = re.search(r'(\d+)\s*mazos?\b', pregunta_lower)
    m_gr = re.search(r'(\d+)\s*gruesas?\b', pregunta_lower)
    m_pz = re.search(r'(\d{2,6})\s*(?:unidades|piezas|pzs|rollos?|metros?)\b', pregunta_lower)
    if m_mz:
        stock_minimo = int(m_mz.group(1)) * 1728
    elif m_gr:
        stock_minimo = int(m_gr.group(1)) * 144
    elif m_pz:
        stock_minimo = int(m_pz.group(1))

    # --- Construir query ---
    query = supabase.table("inventario_merceria").select("*")

    if base:
        query = query.ilike("Modelo", f"%{base}%")
    if color:
        query = query.ilike("Color", f"%{color}%")
    if medida:
        query = query.ilike("Medida", f"%{medida}%")
    if stock_minimo:
        query = query.gte("Stock", stock_minimo)

    hay_criterio = any([base, color, medida, stock_minimo])

    # Sin criterios → búsqueda inversa por Descripción, TAGS, Color
    if not hay_criterio:
        resultados = []
        for col in ["Descripción", "Modelo", "TAGS", "Color", "Medida"]:
            for p in palabras[:4]:
                try:
                    r = supabase.table("inventario_merceria").select("*").ilike(col, f"%{p}%").limit(4).execute()
                    if r.data:
                        resultados.extend(r.data)
                except:
                    pass
        unicos = {r["id"]: r for r in resultados}
        return list(unicos.values())[:6]

    data = query.limit(6).execute().data or []
    return data


# ===========================================================
# FUNCIÓN PRINCIPAL DE BÚSQUEDA
# ===========================================================

def cargar_inventario_supabase(pregunta: str) -> list:
    """Orquesta la búsqueda en botones o mercería según la pregunta."""
    try:
        pregunta_lower = pregunta.lower()

        # Palabras limpias (sin stopwords, sin dígitos solos cortos)
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta)
                    if len(p) > 2 and p.lower() not in STOPWORDS]

        if not palabras and not re.search(r'\d', pregunta):
            return []

        # ¿Es mercería o botón?
        es_merceria = (
            any(p in PALABRAS_MERCERIA for p in palabras)
            or bool(re.search(r'\b([A-Za-z]{2,3}\d{1,4})\b', pregunta)
                    and not re.search(r'\bB\d{4}\b', pregunta, re.IGNORECASE))
        )

        if es_merceria:
            return buscar_merceria(pregunta, pregunta_lower, palabras)
        else:
            return buscar_botones(pregunta, pregunta_lower, palabras)

    except Exception as e:
        print(f"Error general en búsqueda: {e}")
        return []


# ===========================================================
# PROMPT DE IA
# ===========================================================

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía datos filtrados a Haiku y retorna respuesta formateada."""

    inv_str = str(inventario) if inventario else "[]"
    pregunta_lower = pregunta.lower()

    # Detectar intención para dar contexto extra al prompt
    es_fecha     = any(w in pregunta_lower for w in ["cuando","cuándo","llegada","llega","fecha"])
    es_imagen    = any(w in pregunta_lower for w in ["imagen","foto","picture"])
    es_existencia= any(w in pregunta_lower for w in ["existencia","stock","cuántos","cuantos","disponible"])

    intencion = ""
    if es_fecha:
        intencion = "El usuario pregunta por FECHA DE LLEGADA. Muestra el campo 'fecha_llegada'. Si es null, di que no hay fecha confirmada."
    elif es_imagen:
        intencion = "El usuario pide la IMAGEN. Muestra solo el primer resultado con su link de imagen."
    elif es_existencia:
        intencion = "El usuario pregunta por EXISTENCIA/STOCK. Muestra claramente cuántos mazos o unidades hay disponibles."

    prompt = f"""Eres "Botoncín" 🧵, asistente de inventario de insumos textiles BotonClass.
Responde en español, alegre, directo. Sin asteriscos dobles (**).

INVENTARIO DISPONIBLE:
{inv_str}

PREGUNTA: "{pregunta}"
{f'INTENCIÓN DETECTADA: {intencion}' if intencion else ''}

REGLAS:
1. Saludo genérico → "¡Hola! Soy Botoncín 🧵 ¿Qué buscas?"
2. Si inventario vacío → "No encontré coincidencias para tu búsqueda. Verifica el código o intenta con otros términos."
3. NO hagas preguntas de seguimiento. Termina con la información solicitada.
4. STOCK BOTONES: la columna es 'Stock_Mazos' (ya en mazos). Muéstralo como "X mazos".
   - Si piden N mazos, verifica: Stock_Mazos >= N.
   - 1 mazo = 12 gruesas = 1,728 piezas. Convierte si preguntan en otras unidades.
5. STOCK MERCERÍA: columna 'Stock' en piezas/rollos/metros.
6. Si Stock_Mazos = 0 o Stock = 0 → "Sin stock" y muestra fecha_llegada si existe.
7. Usa SOLO los campos presentes en los datos (no inventes).

FORMATO BOTÓN (tiene Tamaño/Hoyos/Acabado):
*Opción N:*
🔷 Modelo: [modelo]
📏 Tamaño: [tamaño]
⚪ Hoyos: [hoyos]
✨ Acabado: [acabado]
🎨 Tono: [tono]
👔 Uso: [uso]
🏷 Tags: [tags]
📦 Stock: [stock] mazos
🚚 Llegada: [fecha_llegada o "Sin fecha confirmada"]
🖼 Imagen: [link o "Sin imagen"]

FORMATO MERCERÍA (tiene Descripción/Medida/Color):
*Opción N:*
🔷 Modelo: [modelo]
📝 Descripción: [descripción]
📐 Medida: [medida]
🎨 Color: [color]
🏷 Tags: [tags]
📦 Stock: [stock]
🚚 Llegada: [fecha_llegada o "Sin fecha confirmada"]
🖼 Imagen: [link o "Sin imagen"]

Separa opciones con línea en blanco. Numera si hay varias.
"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ===========================================================
# RUTAS FLASK
# ===========================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de WhatsApp vía Twilio."""
    mensaje_entrante = request.form.get("Body", "").strip()

    # Modo mantenimiento
    if os.environ.get("MANTENIMIENTO", "false").lower() == "true":
        resp = MessagingResponse()
        resp.message("🔧 Botoncín está en mantenimiento.\nEstaremos de vuelta pronto. ¡Gracias por tu paciencia! 😊")
        return str(resp)

    inventario = cargar_inventario_supabase(mensaje_entrante)
    respuesta  = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta)
    return str(resp)


@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín v4 — BotonClass", 200


@app.route("/test", methods=["GET"])
def test_busqueda():
    """Prueba la búsqueda sin llamar a la IA (ahorra créditos)."""
    pregunta   = request.args.get("q", "")
    resultados = cargar_inventario_supabase(pregunta)
    return jsonify({"pregunta": pregunta, "total": len(resultados), "resultados": resultados})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
