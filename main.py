import os
import re
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from supabase import create_client, Client

app = Flask(__name__)
client = Anthropic()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def cargar_inventario_supabase(pregunta: str):
    """Búsqueda con filtros encadenados directamente en Supabase."""
    try:
        pregunta_lower = pregunta.lower()

        # Palabras vacías que no aportan a la búsqueda
        stopwords = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa",
                     "dame", "dime", "muestra", "muéstrame", "busco", "necesito", "quiero",
                     "quisiera", "favor", "tienes", "tengan", "cuenten", "hay", "algun", "alguna",
                     "opciones", "opcion", "con", "que", "del", "una", "para", "los", "las", "por",
                     "boton", "botón", "modelo", "talla", "tamaño", "unidades", "piezas"]
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta)
                    if len(p) > 2 and p not in stopwords]

        if not palabras and not re.search(r'\d', pregunta):
            return []

        # =============== EXTRAE TODOS LOS CRITERIOS DE LA PREGUNTA ===============

        # 1. Código + sufijo (ej: 5936-R, 5936-L)
        codigo_sufijo = re.search(r'\b(\d{3,4})[-]?([RLMBrlmb24]{1,2}|CR|cr)\b', pregunta)
        codigo_base = codigo_sufijo.group(1) if codigo_sufijo else None
        sufijo = codigo_sufijo.group(2).lower() if codigo_sufijo else None

        # Si no hay sufijo, busca código solo (ej: 5936)
        if not codigo_base:
            codigo_solo = re.search(r'\b(\d{3,4})\b', pregunta)
            codigo_base = codigo_solo.group(1) if codigo_solo else None

        # 2. Tamaño (ej: "tamaño 30", "talla 16")
        tamaño_match = re.search(r'(?:talla|tamaño|linea|línea)\s*(\d+)', pregunta_lower)
        tamaño = tamaño_match.group(1) if tamaño_match else None

        # 3. Hoyos (ej: "2 hoyos", "4 hoyos")
        hoyos = None
        if re.search(r'2\s*hoyo|dos\s*hoyo', pregunta_lower):
            hoyos = "2 hoyos"
        elif re.search(r'4\s*hoyo|cuatro\s*hoyo', pregunta_lower):
            hoyos = "4 hoyos"

        # 4. Acabado (ej: "mate", "brillante", sufijo -M, -B)
        acabado = None
        sufijo_acabado = {"m": "Mate", "b": "Brillante"}
        if sufijo in sufijo_acabado:
            acabado = sufijo_acabado[sufijo]
        elif "mate" in palabras:
            acabado = "Mate"
        elif "brillante" in palabras:
            acabado = "Brillante"

        # 5. TAGS por sufijo o palabra (rayado, liso)
        tag_filtro = None
        if sufijo == "r" or "rayado" in palabras:
            tag_filtro = "rayado"
        elif sufijo == "l" or "liso" in palabras:
            tag_filtro = "liso"
        elif "teñible" in palabras or "teñir" in palabras:
            tag_filtro = "teñible"

        # 6. Uso (ej: "camisero", "sastre", "fantasía")
        uso = None
        if any(p in palabras for p in ["camisero", "camisa"]):
            uso = "Camisero"
        elif any(p in palabras for p in ["sastre", "pantalon", "pantalón", "saco"]):
            uso = "Sastre"
        elif any(p in palabras for p in ["fantasia", "fantasía", "vintage", "decorativo"]):
            uso = "Fantasía"

        # 7. Stock mínimo (mazos, gruesas, unidades)
        stock_minimo = None
        mazos_m = re.search(r'(\d+)\s*mazos?\b', pregunta_lower)
        gruesas_m = re.search(r'(\d+)\s*gruesas?\b', pregunta_lower)
        unidades_m = re.search(r'(\d{3,6})\s*(?:unidades|piezas|pzs)\b', pregunta_lower)
        if mazos_m:
            stock_minimo = int(mazos_m.group(1)) * 1728
            print(f"Stock mínimo: {mazos_m.group(1)} mazos = {stock_minimo} pzs")
        elif gruesas_m:
            stock_minimo = int(gruesas_m.group(1)) * 144
            print(f"Stock mínimo: {gruesas_m.group(1)} gruesas = {stock_minimo} pzs")
        elif unidades_m:
            stock_minimo = int(unidades_m.group(1))

        # 8. Detecta mercería vs botones
        palabras_merceria = ["cinta", "palmita", "resorte", "elastico", "elástico",
                             "plastiflecha", "candado", "fleco", "satinado", "hilo", "encaje"]
        es_merceria = any(p in palabras for p in palabras_merceria)
        tabla = "inventario_merceria" if es_merceria else "inventario_botones"

        # =============== CONSTRUYE QUERY ENCADENADO EN SUPABASE ===============
        query = supabase.table(tabla).select("*")

        # Aplica filtros en orden de especificidad
        if codigo_base:
            query = query.ilike("Modelo", f"%{codigo_base}%")
        if tamaño and not es_merceria:
            query = query.eq("Tamaño", tamaño)
        if hoyos and not es_merceria:
            query = query.eq("Hoyos", hoyos)
        if acabado and not es_merceria:
            query = query.eq("Acabado", acabado)
        if tag_filtro:
            query = query.ilike("TAGS", f"%{tag_filtro}%")
        if uso and not es_merceria:
            query = query.eq("Uso", uso)
        if stock_minimo:
            query = query.gte("Stock", stock_minimo)

        # Si no hay ningún criterio específico, busca por palabras clave en columnas
        if not any([codigo_base, tamaño, hoyos, acabado, tag_filtro, uso, stock_minimo]):
            columnas = ["Descripción", "Modelo", "TAGS"] if es_merceria else ["Modelo", "Uso", "TAGS"]
            resultados = []
            for palabra in palabras[:4]:
                for col in columnas:
                    try:
                        res = supabase.table(tabla).select("*").ilike(col, f"%{palabra}%").limit(4).execute()
                        if res.data:
                            resultados.extend(res.data)
                    except:
                        pass
            unicos = {r['id']: r for r in resultados}
            return list(unicos.values())[:6]

        resultado = query.limit(6).execute()
        return resultado.data if resultado.data else []

    except Exception as e:
        print(f"Error en búsqueda: {e}")
        return []



def consultar_ia(pregunta: str, inventario: list) -> str:
    """Prompt optimizado para Haiku: breve pero completo."""
    inv_str = str(inventario)

    prompt = f"""Eres "Botoncín" 🧵, asistente de insumos textiles. Responde en español, alegre, directo, sin asteriscos dobles (**).

INVENTARIO (usa solo estos datos):
{inv_str}

Pregunta: "{pregunta}"

Instrucciones:
1. Saludo: Si saludan genérico → "¡Hola! Soy Botoncín 🧵 ¿Qué buscas?". Si piden producto → directo.
2. Stock: Revisa columna 'Stock'. Si >0 → disponible. Si 0 → "No hay stock". Si inventario vacío → explica que no hay coincidencia exacta y sugiere alternativas si las hay.
3. Unidades: Si piden mazos (1 mazo=1728 pzs) o gruesas (1 gruesa=144 pzs), calcula si hay suficiente.
4. Sufijos botones: -R=Rayado, -L=Liso, -M=Mate, -B=Brillante, -2=2hoyos, -4=4hoyos, resáltalo.
5. Sufijos mercería: -B=Blanco, -N=Negro, -M=Marino, -CR=Crudo, resáltalo.
6. TAGS: Si incluyen "Teñible", "Básico", resáltalo.
7. IMPORTANTE: Usa SOLO los campos que existan en el dato (no inventes ni dejes campos vacíos). Si un producto no tiene Tamaño/Hoyos (ej: mercería), omite esas líneas.

FORMATO si el producto es un BOTÓN (tiene campos Tamaño/Hoyos/Acabado):
*Opción N:*
🔷 Modelo: [modelo]
📏 Tamaño: [tamaño]
⚪ Hoyos: [hoyos]
✨ Acabado: [acabado]
🎨 Tono: [tono]
👔 Uso: [uso]
🏷️ Tags: [tags]
📦 Stock: [stock] unidades
🖼️ Imagen: [link]

FORMATO si el producto es MERCERÍA (tiene campo Descripción, no tiene Tamaño/Hoyos):
*Opción N:*
🔷 Modelo: [modelo]
📝 Descripción: [descripción]
🏷️ Tags: [tags]
📦 Stock: [stock] unidades
🖼️ Imagen: [link]

Separa cada opción con línea en blanco. Numéralas si hay varias. Sé breve en el texto introductorio.
"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=550,  # Ligero incremento para soportar formato visual con varios productos
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de WhatsApp vía Twilio."""
    mensaje_entrante = request.form.get("Body", "").strip()
    
    inventario = cargar_inventario_supabase(mensaje_entrante)
    respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)


@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín Sufijos Ultra-Inteligente v3 en Render", 200

@app.route("/test", methods=["GET"])
def test_busqueda():
    pregunta = request.args.get("q", "")
    resultados = cargar_inventario_supabase(pregunta)
    return {"pregunta": pregunta, "resultados": resultados, "total": len(resultados)}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
