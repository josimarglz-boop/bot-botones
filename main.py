
import os
import re
import json
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
    "botones","modelos","color","colores","tono","tonos","tienen","tiene","este","esta",
}

# Palabras que ya son criterios estructurados (no buscar en TAGS)
PALABRAS_CRITERIO = {
    "mate","brillante","rayado","liso","teñible","teñir",
    "camisero","camisa","sastre","pantalon","fantasia","fantasía",
    "decorativo","pantalón","mazos","mazo","gruesa","gruesas",
    "piezas","unidades","imagen","foto","existencia","stock",
    "fotos","imagenes","imágenes","fotografia","fotografía","picture","manda","mandame","envia","enviame",
    "llegada","cuando","cuándo","fecha","llega","próxima",
    "proxima","disponible","disponibles","cuantos","cuántos",
}

# Palabras de mercería (detectan tabla)
PALABRAS_MERCERIA = {
    "cinta","palmita","resorte","elastico","elástico","plastiflecha",
    "candado","fleco","satinado","bolsas","contactel","crochet","crochet","hilo",
    "encaje","velcro","sesgo","ribete","pretina","broches","broche","cierre",
}

# Tonos / colores: lo que escribe el vendedor → valor en columna Tono (o Color en mercería)
# Las frases de varias palabras van primero para que "oro rosa" no se lea como "oro".
TONOS = [
    ("tono fabrica", "Tono Fábrica"), ("tono fábrica", "Tono Fábrica"),
    ("oro rosa", "Oro Rosa"), ("oro viejo", "Oro Viejo"), ("plata vieja", "Plata Vieja"),
    ("gris oxford", "Gris Oxford"), ("niquel mate", "Níquel Mate"), ("níquel mate", "Níquel Mate"),
    ("blanco", "Blanco"), ("blancos", "Blanco"), ("blanca", "Blanco"), ("blancas", "Blanco"),
    ("negro", "Negro"), ("negros", "Negro"), ("negra", "Negro"), ("negras", "Negro"),
    ("dorada", "Dorado"), ("doradas", "Dorado"), ("plateado", "Plata Vieja"), ("plateada", "Plata Vieja"),
    ("marino", "Marino"), ("azul", "Azul"), ("beige", "Beige"), ("cafe", "Café"), ("café", "Café"),
    ("cobre", "Cobre"), ("dorado", "Dorado"), ("dorados", "Dorado"), ("oro", "Dorado"),
    ("gris", "Gris"), ("hueso", "Hueso"), ("humo", "Humo"), ("laton", "Latón"), ("latón", "Latón"),
    ("lila", "Lila"), ("metalico", "Metálico"), ("metálico", "Metálico"), ("militar", "Militar"),
    ("niquel", "Níquel"), ("níquel", "Níquel"), ("olivo", "Olivo"), ("transparente", "Transparente"),
    ("verde", "Verde"), ("ambar", "Ámbar"), ("ámbar", "Ámbar"), ("arena", "Arena"),
    ("holografico", "Holográfico"), ("holográfico", "Holográfico"), ("crudo", "Crudo"),
    ("plata", "Plata Vieja"),
    # Colores que hoy no hay en inventario: se reconocen para avisar qué tonos SÍ hay
    ("rojo", "Rojo"), ("roja", "Rojo"), ("rosa", "Rosa"), ("amarillo", "Amarillo"),
    ("morado", "Morado"), ("naranja", "Naranja"), ("vino", "Vino"), ("guinda", "Guinda"),
    ("turquesa", "Turquesa"), ("rey", "Azul Rey"), ("celeste", "Celeste"), ("mostaza", "Mostaza"),
]


def detectar_tono(pregunta_lower: str):
    """Regresa (tono, palabras_que_uso) o (None, set())."""
    for frase, tono in TONOS:
        if re.search(rf"\b{frase}\b", pregunta_lower):
            return tono, set(frase.split())
    return None, set()


def sin_acentos(texto: str) -> str:
    """'Elástico' → 'elastico' (para comparar en Python)."""
    import unicodedata
    t = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def patron_sin_acentos(texto: str) -> str:
    """'Níquel' → 'N_quel': el _ de SQL acepta cualquier letra, así encuentra Níquel y Niquel."""
    return re.sub(r"[áéíóúÁÉÍÓÚñÑ]", "_", texto)


# ===========================================================
# PARSER DE SKU
# ===========================================================

def parsear_sku_boton(texto: str) -> dict:
    """
    Parsea el código de botón que escribe el vendedor.
    Códigos reales: B + modelo (4 o 5 dígitos) + tamaño (2 dígitos), con sufijo opcional.

    - B221814-L  → modelo=2218,  tamaño=14, sufijo=l
    - B221814    → modelo=2218,  tamaño=14
    - B1000820   → modelo=10008, tamaño=20      (7 dígitos)
    - B2218 / 2218   → modelo=2218               (4 dígitos)
    - B10008 / 10008 → modelo=10008              (5 dígitos)
    - B2954-13X18    → modelo=2954, sufijo=13x18
    Cantidades ("1728 piezas", "1000 mazos") NO se toman como modelo.
    """
    resultado = {"modelo": None, "tamaño": None, "sufijo": None}

    m = re.search(
        r'\bB?(\d{4,7})'                                       # dígitos del código
        r'(?:-([A-Za-z0-9]{1,6}(?:-[A-Za-z0-9]{1,6})?))?'      # sufijo: -L, -SPL, -4-SPL, -13X18
        r'\b(?!\s*(?:mazos?|gruesas?|piezas?|pzs?|unidades|rollos?|metros?|mts?)\b)',
        texto, re.IGNORECASE)
    if not m:
        return resultado

    digitos = m.group(1)
    if m.group(2):
        resultado["sufijo"] = m.group(2).lower()

    if len(digitos) in (6, 7):          # modelo + tamaño
        resultado["modelo"] = digitos[:-2]
        resultado["tamaño"] = digitos[-2:]
    else:                               # 4 o 5 dígitos: solo modelo
        resultado["modelo"] = digitos
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
        # \b evita que "imagEN 8317" se lea como "en 83"
        m = re.search(r'\b(?:talla|tamaño|linea|línea|en)\s*(\d{2})\b', pregunta_lower)
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
    elif re.search(r'\bpata\b', pregunta_lower):
        hoyos = "De Pata"
    # Sufijo de hoyos
    if sufijo in ("2", "4") and not hoyos:
        hoyos = f"{sufijo} hoyos"
        sufijo = None

    # --- Tono / color ---
    tono, palabras_tono = detectar_tono(pregunta_lower)

    # --- Acabado ---
    acabado = None
    if "mate" in palabras_tono:
        pass  # "níquel mate" es un tono, no el acabado
    elif sufijo in ("m", "b"):
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
    palabras_usadas.update(palabras_tono)
    palabras_usadas.update(["hoyo", "hoyos", "dos", "cuatro", "pata"])
    # Fuera cualquier palabra con números (B010324, 2218, 4hoyos): son códigos, no TAGS
    palabras_libres = [p for p in palabras
                       if p not in palabras_usadas and not re.search(r'\d', p) and len(p) > 2]

    # --- Construir query ---
    # El modelo en Supabase es el SKU completo: B221814
    # Buscamos con ilike para que "2218" encuentre B221814, B221816, etc.
    def ejecutar(con_tono: bool) -> list:
        query = supabase.table("inventario_botones").select("*")

        if modelo and tamaño:
            # Busca modelo+tamaño exactos: B221814
            query = query.ilike("Modelo", f"B{modelo}{tamaño}%")
        elif modelo:
            # Solo modelo: trae todas las tallas del modelo
            query = query.ilike("Modelo", f"B{modelo}%")   # empieza con B2218, no B732218

        # Sufijo en el modelo (ej: -L, -SPL, -ANCLA)
        if sufijo and sufijo not in ("m", "b", "r", "l", "2", "4"):
            # Sufijo especial → buscar en nombre del modelo directamente
            query = query.ilike("Modelo", f"%-{sufijo.upper()}%")

        # ilike en vez de eq: tolera mayúsculas ("4 Hoyos") y espacios sobrantes ("Mate ")
        if hoyos:
            query = query.ilike("Hoyos", f"%{hoyos[:6]}%")       # "4 hoyo" → 4 hoyos / 4 Hoyos
        if acabado:
            query = query.ilike("Acabado", f"%{acabado}%")
        if tag_filtro:
            query = query.ilike("TAGS", f"%{tag_filtro}%")
        if uso:
            query = query.ilike("Uso", f"%{uso[:5]}%")           # "Camis" → Camisero / Camisas
        if tono and con_tono:
            query = query.ilike("Tono", f"%{patron_sin_acentos(tono)}%")
        if stock_minimo_mazos:
            query = query.gte("Stock_Mazos", stock_minimo_mazos)
        if palabras_libres:
            query = query.ilike("TAGS", f"%{palabras_libres[0]}%")

        data = query.order("Stock_Mazos", desc=True).limit(150).execute().data or []

        # Solo modelo ("1523"): preferir B1523xx sobre B15238xx (otro modelo de 5 dígitos)
        if modelo and not tamaño:
            exactos = [r for r in data
                       if re.match(rf"^B{modelo}\d{{2}}(-|$)", str(r.get("Modelo", "")), re.I)]
            if exactos:
                data = exactos

        # Tamaño sin modelo ("plata vieja 18"): filtra por la columna Tamaño
        if tamaño and not modelo:
            def _tam(r):
                try:
                    return float(r.get("Tamaño")) == float(tamaño)
                except (TypeError, ValueError):
                    return False
            data = [r for r in data if _tam(r)]

        # Filtro Python para palabras libres adicionales
        for extra in palabras_libres[1:]:
            data = [r for r in data if extra in (r.get("TAGS") or "").lower()]
        return data

    hay_criterio = any([modelo, tamaño, hoyos, acabado, tag_filtro, uso, tono,
                        stock_minimo_mazos, palabras_libres])

    # Sin criterios → búsqueda genérica en TAGS, Uso y Modelo
    if not hay_criterio:
        resultados = []
        for col in ["Modelo", "Uso", "TAGS"]:
            for p in palabras[:4]:
                try:
                    r = supabase.table("inventario_botones").select("*").ilike(col, f"%{p}%").order("Stock_Mazos", desc=True).limit(4).execute()
                    if r.data:
                        resultados.extend(r.data)
                except:
                    pass
        unicos = {r["id"]: r for r in resultados}
        ordenados = sorted(unicos.values(), key=lambda r: r.get("Stock_Mazos") or 0, reverse=True)
        return ordenados[:6], ""

    # Código completo con sufijo (B221814-L, B2954-13X18): primero busca el código exacto
    if modelo and sufijo:
        exacto = (supabase.table("inventario_botones").select("*")
                  .ilike("Modelo", f"B{modelo}{tamaño or ''}-{sufijo}%")
                  .order("Stock_Mazos", desc=True).limit(6).execute().data or [])
        if exacto:
            return exacto, ""

    data = ejecutar(con_tono=True)

    # Pidieron un tono que ese modelo no tiene → mostrar los tonos que sí hay
    if not data and tono and modelo:
        alternativas = ejecutar(con_tono=False)
        if alternativas:
            tonos_hay = sorted({(r.get("Tono") or "").strip() for r in alternativas} - {""})
            nota = (f"El modelo B{modelo}{tamaño or ''} NO existe en tono {tono}. "
                    f"Tonos disponibles: {', '.join(tonos_hay) or 'sin tono registrado'}. "
                    f"Avísalo primero y luego muestra estas opciones.")
            return alternativas[:6], nota

    # Código con sufijo que no existe (B221814-L): mostrar lo que sí hay de ese modelo
    if not data and modelo and sufijo:
        base_cod = f"B{modelo}{tamaño or ''}"
        parecidos = (supabase.table("inventario_botones").select("*")
                     .ilike("Modelo", f"{base_cod}%")
                     .order("Stock_Mazos", desc=True).limit(6).execute().data or [])
        if parecidos:
            nota = (f"El código exacto {base_cod}-{sufijo.upper()} NO existe. "
                    f"Avísalo primero y luego muestra estas variantes de {base_cod} que sí hay.")
            return parecidos, nota

    return data[:6], ""


def buscar_merceria(pregunta: str, pregunta_lower: str, palabras: list) -> list:
    """Búsqueda específica para tabla inventario_merceria."""

    # --- Parsear modelo de mercería ---
    sku = parsear_modelo_merceria(pregunta)
    base = sku["base"]
    sufijo = sku["sufijo"]

    # Color del sufijo, o por palabra ("palmita negra", "contactel blanco")
    color = SUFIJOS_MERCERIA.get(sufijo) if sufijo else None
    if not color:
        color, _ = detectar_tono(pregunta_lower)

    # Tipo de producto por palabra ("palmita", "elástico") → filtra Descripción
    producto = next((p for p in palabras if p in PALABRAS_MERCERIA), None)

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
        query = query.ilike("Color", f"%{patron_sin_acentos(color)}%")
    if medida:
        query = query.ilike("Medida", f"%{medida}%")
    if stock_minimo:
        query = query.gte("Stock", stock_minimo)

    hay_criterio = any([base, color, producto, medida, stock_minimo])

    # Sin criterios → búsqueda inversa por Descripción, TAGS, Color
    if not hay_criterio:
        resultados = []
        for col in ["Descripción", "Modelo", "TAGS", "Color", "Medida"]:
            for p in palabras[:4]:
                try:
                    r = supabase.table("inventario_merceria").select("*").ilike(col, f"%{p}%").order("Stock", desc=True).limit(4).execute()
                    if r.data:
                        resultados.extend(r.data)
                except:
                    pass
        unicos = {r["id"]: r for r in resultados}
        ordenados = sorted(unicos.values(), key=lambda r: r.get("Stock") or 0, reverse=True)
        return ordenados[:6], ""

    data = query.order("Stock", desc=True).limit(200).execute().data or []

    # Producto por palabra: se busca en Descripción y en TAGS, sin importar acentos
    # ("elastico" encuentra "Elástico"; "bolsas" encuentra TAGS "sudaderas, pants, bolsas")
    if producto and not base:
        clave = sin_acentos(producto).rstrip("s")
        data = [r for r in data
                if clave in sin_acentos(f"{r.get('Descripción') or ''} {r.get('TAGS') or ''}")]

    return data[:6], ""


# ===========================================================
# FUNCIÓN PRINCIPAL DE BÚSQUEDA
# ===========================================================

def cargar_inventario_supabase(pregunta: str) -> tuple:
    """
    Orquesta la búsqueda en botones o mercería según la pregunta.
    Regresa (resultados, nota). La nota es contexto extra para la IA (puede ir vacía).
    """
    try:
        pregunta_lower = pregunta.lower()

        # Palabras limpias (sin stopwords, sin dígitos solos cortos)
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta)
                    if len(p) > 2 and p.lower() not in STOPWORDS]

        if not palabras and not re.search(r'\d', pregunta):
            return [], ""

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
        return [], ""


# ===========================================================
# PROMPT DE IA
# ===========================================================

def limpiar_registro(registro: dict) -> dict:
    """
    Quita los campos vacíos de un registro para que la IA no los muestre.
    - Elimina None, "", espacios, "nan", "null"
    - Elimina 'id' (no le sirve al agente)
    - Conserva el 0 (Stock en 0 SÍ es información)
    - Convierte 24.0 → 24
    """
    limpio = {}
    for campo, valor in registro.items():
        if campo == "id" or valor is None:
            continue
        if isinstance(valor, str):
            valor = valor.strip()
            if valor == "" or valor.lower() in ("nan", "null", "none"):
                continue
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        limpio[campo] = valor
    return limpio


MAX_FOTOS = 3   # máximo de fotos por respuesta (cada foto es un mensaje que Twilio cobra)


def pide_imagen(pregunta: str) -> bool:
    return bool(re.search(r'\b(imagen|imagenes|imágenes|foto|fotos|fotografia|fotografía|picture)\b',
                          pregunta.lower()))


def url_imagen_directa(url: str):
    """
    Convierte links de Google Drive al formato directo que WhatsApp sí puede descargar.
    drive.google.com/uc?export=view&id=XXX  → lh3.googleusercontent.com/d/XXX
    drive.google.com/file/d/XXX/view        → lh3.googleusercontent.com/d/XXX
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    m = re.search(r'[?&]id=([A-Za-z0-9_-]{10,})', url) or re.search(r'/d/([A-Za-z0-9_-]{10,})', url)
    if m and ("drive.google.com" in url or "googleusercontent.com" in url):
        return f"https://lh3.googleusercontent.com/d/{m.group(1)}"
    return url if url.startswith("http") else None


def juntar_fotos(inventario: list) -> list:
    """
    Regresa [(url, "B831720, B831724"), ...] sin repetir la misma foto.
    Varios tamaños suelen compartir foto: se manda una sola vez con todos los modelos.
    """
    fotos = {}   # url → {"modelos": [...], "tonos": [...]}
    for r in inventario:
        url = url_imagen_directa(r.get("Imagen"))
        if not url:
            continue
        f = fotos.setdefault(url, {"modelos": [], "tonos": []})
        modelo = str(r.get("Modelo", "")).strip()
        tono = str(r.get("Tono") or "").strip()
        if modelo and modelo not in f["modelos"]:
            f["modelos"].append(modelo)
        if tono and tono not in f["tonos"]:
            f["tonos"].append(tono)

    salida = []
    for url, f in list(fotos.items())[:MAX_FOTOS]:
        pie = ", ".join(f["modelos"])
        if f["tonos"]:
            pie += " · " + " / ".join(f["tonos"])   # "B601918, B601916 · Tono Fábrica"
        salida.append((url, pie))
    return salida


def consultar_ia(pregunta: str, inventario: list, nota: str = "") -> str:
    """Envía datos filtrados a Haiku y retorna respuesta formateada."""

    inventario = [limpiar_registro(r) for r in inventario]
    inv_str = json.dumps(inventario, ensure_ascii=False) if inventario else "[]"
    pregunta_lower = pregunta.lower()

    # Detectar intención para dar contexto extra al prompt
    es_fecha     = any(w in pregunta_lower for w in ["cuando","cuándo","llegada","llega","fecha"])
    es_imagen    = pide_imagen(pregunta)
    es_existencia= any(w in pregunta_lower for w in ["existencia","stock","cuántos","cuantos","disponible"])

    intencion = ""
    if es_fecha:
        intencion = "El usuario pregunta por FECHA DE LLEGADA. Muestra el campo 'fecha_llegada'. Si es null, di que no hay fecha confirmada."
    elif es_imagen:
        intencion = ("El usuario pide la IMAGEN. Las fotos se envían aparte como imagen de WhatsApp, "
                     "así que NO escribas la línea 🖼 Imagen ni ningún link. Muestra TODOS los resultados con su ficha. "
                     "Si al menos uno trae Imagen, termina con: '📷 Te mando la foto enseguida.' "
                     "Si NINGÚN resultado trae Imagen, termina con: '📷 Este modelo aún no tiene imagen cargada.' "
                     "Nunca digas que no encontraste el modelo si hay resultados.")
    elif es_existencia:
        intencion = "El usuario pregunta por EXISTENCIA/STOCK. Muestra claramente cuántos mazos o unidades hay disponibles."

    prompt = f"""Eres "Botoncín" 🧵, asistente de inventario de insumos textiles BotonClass.
Responde en español, alegre, directo. Sin asteriscos dobles (**).

INVENTARIO DISPONIBLE:
{inv_str}

PREGUNTA: "{pregunta}"
{f'INTENCIÓN DETECTADA: {intencion}' if intencion else ''}
{f'NOTA IMPORTANTE: {nota}' if nota else ''}

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
7b. Respeta el ORDEN del inventario: ya viene de mayor a menor existencia. No lo reordenes.
8. CAMPOS VACÍOS: si un campo NO viene en el registro, OMITE esa línea completa.
   No escribas "N/A", "Sin dato", "Sin imagen", "Sin fecha" ni dejes la etiqueta vacía.
   Ejemplo: si un botón no trae 'Hoyos', no pongas la línea ⚪ Hoyos.

FORMATO BOTÓN (cada línea solo si el campo existe):
*Opción N:*
🔷 Modelo: [Modelo]
📏 Tamaño: [Tamaño]
⚪ Hoyos: [Hoyos]
✨ Acabado: [Acabado]
🎨 Tono: [Tono]
👔 Uso: [Uso]
🏷 Tags: [TAGS]
📦 Stock: [Stock_Mazos] mazos
🚚 Llegada: [fecha_llegada]
🖼 Imagen: [Imagen]

FORMATO MERCERÍA (cada línea solo si el campo existe):
*Opción N:*
🔷 Modelo: [Modelo]
📝 Descripción: [Descripción]
📐 Medida: [Medida]
🎨 Color: [Color]
📦 Presentación: [Presentación]
🏷 Tags: [TAGS]
📦 Stock: [Stock]
🚚 Llegada: [fecha_llegada]
🖼 Imagen: [Imagen]

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

    inventario, nota = cargar_inventario_supabase(mensaje_entrante)
    respuesta  = consultar_ia(mensaje_entrante, inventario, nota)

    resp = MessagingResponse()
    resp.message(respuesta)

    # Si pidieron imagen/foto: cada foto va en su propio mensaje, con los modelos como pie de foto
    if pide_imagen(mensaje_entrante):
        for url, modelos in juntar_fotos(inventario):
            foto = resp.message(f"📷 {modelos}")
            foto.media(url)

    return str(resp)


@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín v4 — BotonClass", 200


@app.route("/test", methods=["GET"])
def test_busqueda():
    """Prueba la búsqueda sin llamar a la IA (ahorra créditos)."""
    pregunta   = request.args.get("q", "")
    resultados, nota = cargar_inventario_supabase(pregunta)
    fotos = juntar_fotos(resultados) if pide_imagen(pregunta) else []
    return jsonify({"pregunta": pregunta, "total": len(resultados), "nota": nota,
                    "fotos": [{"url": u, "modelos": m} for u, m in fotos],
                    "resultados": resultados})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
