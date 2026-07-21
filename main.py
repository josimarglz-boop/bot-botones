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
    """Búsqueda ultra-inteligente: entiende sufijos (5936-R=rayado, 5936-L=liso, cinta-B=blanco)."""
    try:
        pregunta_lower = pregunta.lower()
        
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa", 
                   "dame", "dime", "muestra", "muéstrame", "busco", "necesito", "quiero", 
                   "quisiera", "favor", "tienes", "tengan", "cuenten", "hay", "algun", "alguna",
                   "opciones", "opcion", "con", "que", "del", "una", "para", "los", "las", "por"]
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2 and p not in saludos]
        
        if not palabras:
            return []

        resultados = []
        
        # =============== MAPEO DE SUFIJOS ===============
        # Botones: sufijos en TAGS o columnas específicas
        sufijo_botones = {
            "r": ("rayado", "TAGS"),      # -R = Rayado (en TAGS)
            "l": ("liso", "TAGS"),         # -L = Liso (en TAGS)
            "m": ("mate", "Acabado"),      # -M = Mate (columna Acabado)
            "b": ("brillante", "Acabado"), # -B = Brillante (columna Acabado)
            "2": ("2 hoyos", "Hoyos"),    # -2 = 2 hoyos (columna Hoyos)
            "4": ("4 hoyos", "Hoyos"),    # -4 = 4 hoyos (columna Hoyos)
        }
        
        # Mercería: sufijos de colores en TAGS
        sufijo_merceria = {
            "b": "Blanco",    # -B = Blanco
            "n": "Negro",     # -N = Negro
            "m": "Marino",    # -M = Marino
            "cr": "Crudo",    # -CR = Crudo
        }
        
        # =============== 1. BÚSQUEDA EXACTA POR CÓDIGO + SUFIJO ===============
        # Busca: 5936-R, 5936-L, 5936-2, cinta-B, resorte-N, etc.
        codigo_sufijo_match = re.search(r'\b(\d{3,4})[-]?([RLMB24]{1,2}|CR|cr|Cr)\b', pregunta, re.IGNORECASE)
        
        if codigo_sufijo_match:
            codigo_base = codigo_sufijo_match.group(1)
            sufijo = codigo_sufijo_match.group(2).lower()
            
            # Detecta si es botón o mercería
            es_merceria = any(p in palabras for p in ["cinta", "resorte", "elastico", "elástico", "hilo", "encaje"])
            tabla = "inventario_merceria" if es_merceria else "inventario_botones"
            
            try:
                if tabla == "inventario_botones" and sufijo in sufijo_botones:
                    valor_busqueda, columna = sufijo_botones[sufijo]
                    
                    # Primero busca el código base exacto
                    res = supabase.table(tabla).select("*").ilike("Modelo", f"%{codigo_base}%").limit(10).execute()
                    
                    if res.data:
                        # Filtra por el criterio del sufijo
                        res_filtrado = []
                        for r in res.data:
                            if columna == "TAGS":
                                if valor_busqueda.lower() in r.get("TAGS", "").lower():
                                    res_filtrado.append(r)
                            elif columna == "Acabado":
                                if valor_busqueda.lower() in r.get("Acabado", "").lower():
                                    res_filtrado.append(r)
                            elif columna == "Hoyos":
                                hoyos_val = r.get("Hoyos", "")
                                if valor_busqueda in hoyos_val or str(valor_busqueda.split()[0]) in hoyos_val:
                                    res_filtrado.append(r)
                        
                        if res_filtrado:
                            return res_filtrado[:6]
                        else:
                            return res.data[:6]  # Si no hay sufijo exacto, retorna todas las variantes
                
                elif tabla == "inventario_merceria" and sufijo in sufijo_merceria:
                    color = sufijo_merceria[sufijo]
                    res = supabase.table(tabla).select("*").ilike("Modelo", f"%{codigo_base}%").limit(10).execute()
                    
                    if res.data:
                        # Filtra por color en TAGS o Descripción
                        res_filtrado = []
                        for r in res.data:
                            if color.lower() in r.get("TAGS", "").lower() or color.lower() in r.get("Descripción", "").lower():
                                res_filtrado.append(r)
                        
                        if res_filtrado:
                            return res_filtrado[:6]
                        return res.data[:6]
            
            except Exception as e:
                print(f"Error búsqueda sufijo: {e}")

        # =============== 2. BÚSQUEDA POR PALABRA DESCRIPTIVA + CÓDIGO ===============
        # Ej: "botón 5936 rayado" → busca 5936 con "rayado" en TAGS
        # Ej: "botón 5936 liso" → busca 5936 con "liso" en TAGS
        
        palabras_criterios = {
            "rayado": ("rayado", "TAGS"),
            "liso": ("liso", "TAGS"),
            "mate": ("mate", "Acabado"),
            "brillante": ("brillante", "Acabado"),
            "blanco": ("Blanco", "TAGS"),
            "negro": ("Negro", "TAGS"),
            "marino": ("Marino", "TAGS"),
            "crudo": ("Crudo", "TAGS"),
        }
        
        codigo_solo = re.search(r'\b(\d{3,4})\b', pregunta)
        if codigo_solo:
            codigo = codigo_solo.group(1)
            
            # Busca si hay palabra descriptiva
            for palabra_clave, (valor_buscar, columna) in palabras_criterios.items():
                if palabra_clave in palabras:
                    try:
                        res = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{codigo}%").limit(10).execute()
                        
                        if res.data:
                            res_filtrado = []
                            for r in res.data:
                                if valor_buscar.lower() in r.get(columna, "").lower():
                                    res_filtrado.append(r)
                            
                            if res_filtrado:
                                return res_filtrado[:6]
                    except:
                        pass

        # =============== 3. DETECTA MERCERÍA vs BOTONES ===============
        palabras_merceria = ["cinta", "palmita", "resorte", "elastico", "elástico", "plastiflecha", "candado", "fleco", "satinado", "bolsas", "contactel", "crochet", "hilo", "botones"]
        es_merceria = any(p in palabras_merceria for p in palabras)
        
        tabla = "inventario_merceria" if es_merceria else "inventario_botones"
        columnas_busqueda = ["Descripción", "Modelo", "TAGS"] if es_merceria else ["Modelo", "Uso", "TAGS"]
        
        # =============== 4. BÚSQUEDA GENÉRICA POR PALABRAS CLAVE ===============
        for palabra in palabras[:6]:  # Ampliado: ahora "palabras" ya viene limpia de filler words
            for columna in columnas_busqueda:
                try:
                    res = supabase.table(tabla).select("*").ilike(columna, f"%{palabra}%").limit(4).execute()
                    if res.data:
                        resultados.extend(res.data)
                except:
                    pass

        # =============== 5. BÚSQUEDA POR TAMAÑO ===============
        tamaño_match = re.search(r'(?:talla|tamaño|ancho|mm|línea|linea)\s*(\d+)', pregunta)
        if tamaño_match and tabla == "inventario_botones":
            tamaño = int(tamaño_match.group(1))
            try:
                res = supabase.table(tabla).select("*").eq("Tamaño", tamaño).limit(10).execute()
                if res.data:
                    if resultados:
                        # Cruza: solo los que ya encontramos Y tienen el tamaño correcto
                        ids_tamaño = {r['id'] for r in res.data}
                        resultados = [r for r in resultados if r['id'] in ids_tamaño]
                        if not resultados:
                            # Si el cruce queda vacío, usa solo los del tamaño pedido
                            resultados = res.data
                    else:
                        resultados = res.data
            except:
                pass

        # =============== 5.5 BÚSQUEDA POR STOCK MÍNIMO (unidades, piezas, mazos, gruesas) ===============
        stock_minimo = None

        # Detecta mazos → convierte a piezas (1 mazo = 1728 pzs)
        mazos_match = re.search(r'(\d+)\s*mazos?\b', pregunta_lower)
        if mazos_match:
            stock_minimo = int(mazos_match.group(1)) * 1728
            print(f"Detectado: {mazos_match.group(1)} mazos = {stock_minimo} piezas mínimas")

        # Detecta gruesas → convierte a piezas (1 gruesa = 144 pzs)
        elif re.search(r'(\d+)\s*gruesas?\b', pregunta_lower):
            gruesas_match = re.search(r'(\d+)\s*gruesas?\b', pregunta_lower)
            stock_minimo = int(gruesas_match.group(1)) * 144
            print(f"Detectado: {gruesas_match.group(1)} gruesas = {stock_minimo} piezas mínimas")

        # Detecta unidades/piezas directas
        elif re.search(r'(\d{3,6})\s*(?:unidades|piezas|pzs|pz)\b', pregunta_lower):
            stock_match = re.search(r'(\d{3,6})\s*(?:unidades|piezas|pzs|pz)\b', pregunta_lower)
            stock_minimo = int(stock_match.group(1))

        if stock_minimo is not None:
            try:
                res = supabase.table(tabla).select("*").gte("Stock", stock_minimo).limit(8).execute()
                if res.data:
                    if resultados:
                        ids_filtrados = {r['id'] for r in res.data}
                        resultados = [r for r in resultados if r['id'] in ids_filtrados]
                        if not resultados:
                            resultados = res.data
                    else:
                        resultados = res.data
            except Exception as e:
                print(f"Error filtro stock: {e}")

        # =============== 6. ELIMINAR DUPLICADOS Y RETORNAR ===============
        resultados_unicos = {}
        for fila in resultados:
            resultados_unicos[fila['id']] = fila
        
        return list(resultados_unicos.values())[:6]

    except Exception as e:
        print(f"Error filtrando en Supabase: {e}")
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
