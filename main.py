
import os
import re
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from supabase import create_client, Client

app = Flask(__name__)
client = Anthropic()

# Conexión automática con tus variables de Render
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def cargar_inventario_supabase(pregunta: str):
    """Detecta si buscan botones o mercería y apunta a las columnas reales de tu Supabase, incluyendo TAGS."""
    try:
        pregunta_limpia = pregunta.lower()
        
        # --- NUEVA MEJORA DE DETECCIÓN DE HOYOS ---
        # Si dice "4 hoyos" o "2 hoyos", extraemos la combinación exacta para no buscar "hoyos" a secas
        patron_hoyos = re.search(r'(\d+)\s*hoyo', pregunta_limpia)
        termino_hoyos = None
        if patron_hoyos:
            termino_hoyos = f"{patron_hoyos.group(1)} hoyos" # Ejemplo: "4 hoyos"
        
        # Extraer palabras clave limpias
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2]
        
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa", "dame", "opciones", "quisiera", "favor", "tenemos", "colores"]
        
        # Filtrar palabras vacías o saludos
        palabras_filtradas = [p for p in palabras if p not in saludos]
        
        # Si detectamos "4 hoyos", reemplazamos la palabra suelta "hoyos" y el número para que no ensucien la búsqueda
        if termino_hoyos:
            # Eliminamos "hoyos", "hoyo" y el número de la lista de palabras sueltas
            palabras_filtradas = [p for p in palabras_filtradas if p not in ["hoyos", "hoyo", patron_hoyos.group(1)]]
            # Agregamos el término compuesto exacto "4 hoyos"
            palabras_filtradas.append(termino_hoyos)

        if not palabras_filtradas:
            return []

        # 1. PALABRAS MÁGICAS PARA MERCERÍA
        palabras_merceria = ["cinta", "palmita", "resorte", "elastico", "elástico", "plastiflecha", "candado", "fleco", "satinado", "bolsas", "contactel"]
        es_consulta_merceria = any(p in palabras_merceria for p in palabras_filtradas)
        
        resultados = []
        
        # 2. RUTA MERCERÍA: Busca estrictamente en su tabla
        if es_consulta_merceria:
            for palabra in palabras_filtradas:
                res_desc = supabase.table("inventario_merceria").select("*").ilike("Descripción", f"%{palabra}%").limit(3).execute()
                res_mod = supabase.table("inventario_merceria").select("*").ilike("Modelo", f"%{palabra}%").limit(3).execute()
                res_tags = supabase.table("inventario_merceria").select("*").ilike("TAGS", f"%{palabra}%").limit(3).execute()
                
                if res_desc.data:
                    resultados.extend(res_desc.data)
                if res_mod.data:
                    resultados.extend(res_mod.data)
                if res_tags.data:
                    resultados.extend(res_tags.data)

        # 3. RUTA BOTONES: Busca estrictamente en su tabla
        else:
            for palabra in palabras_filtradas:
                res_modelo = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{palabra}%").limit(4).execute()
                res_uso = supabase.table("inventario_botones").select("*").ilike("Uso", f"%{palabra}%").limit(4).execute()
                res_tags_btn = supabase.table("inventario_botones").select("*").ilike("TAGS", f"%{palabra}%").limit(4).execute()
                
                if res_modelo.data:
                    resultados.extend(res_modelo.data)
                if res_uso.data:
                    resultados.extend(res_uso.data)
                if res_tags_btn.data:
                    resultados.extend(res_tags_btn.data)

        # CORREGIDO: Eliminación de duplicados limpia y real sin código fantasma
    resultados_unicos = {}
    for fila in resultados:
    # Busca 'id' en minúsculas, si no lo encuentra busca 'ID', y si no, usa el propio objeto como clave
    clave = fila.get('id', fila.get('ID', str(fila)))
    resultados_unicos[clave] = fila
            
        return list(resultados_unicos.values())[:6]

    except Exception as e:
        print(f"Error filtrando en Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Usa el prompt comercial optimizado y el modelo de Haiku real."""
    inv_str = str(inventario) 

    prompt = f"""Eres "Botoncín" 🧵, el asistente virtual de la tienda de insumos textiles. Responde SIEMPRE en español, alegre, breve (máximo 7 líneas) y directo al grano.
    
INVENTARIO DISPONIBLE EN BASE DE DATOS (Usa estrictamente estos valores, presta atención a la columna 'Stock'):
{inv_str}

Pregunta del cliente: "{pregunta}"

Instrucciones obligatorias:
1. SALUDO: Si te saludan de forma genérica, di "¡Hola! Soy Botoncín 🧵" y pregunta qué buscan. Si van directo a pedir un producto, NO te presentes, ve directo a la información.
2. DISPONIBILIDAD: Revisa el valor de la columna 'Stock' con mayúscula. Si viene un número mayor a 0, indica que sí hay disponibilidad. Si el inventario está vacío o no encuentras el modelo, di amablemente que no tienes stock.
3. LOGICA UNIDADES: Si el cliente te pide una cantidad en "mazos" (1 mazo = 1728 pzs) o "gruesas" (1 gruesa = 144 pzs), calcula mentalmente si el 'Stock' disponible cubre lo que pide. En tu respuesta confirma alegremente si completas los mazos/gruesas solicitados o cuántos le puedes ofrecer según las piezas totales en stock.
4. FORMATO DE RESPUESTA:
   - Presenta la información limpia usando saltos de línea y emojis. No uses asteriscos dobles (**).
   - Muestra siempre el Modelo, la Descripción, el Stock disponible y al final pon el Link de la imagen correspondiente.
5. DICCIONARIO DE SUFIJOS: Presta extrema atención a la parte final del 'Modelo' (ej: B5529-2 o B5936-R). Interpreta y asocia los sufijos de las claves según esta guía para responder exactamente lo que pide el cliente:
   - Sufijo "-2" = Tiene 2 hoyos.
   - Sufijo "-4" = Tiene 4 hoyos.
   - Sufijo "-R" = Acabado Rayado.
   - Sufijo "-L" = Acabado Liso.
   - Sufijo "-B" = Acabado Brillante.
   - Sufijo "-M" = Acabado Mate.
Si el cliente te pregunta por el botón "5529 de 4 hoyos", busca en el inventario provisto el modelo que termine exactamente en "-4" (B5529-4) y muestra exclusivamente el stock de ese modelo. No los mezcles ni digas que no hay existencias si el registro está en el inventario.
"""

    # 
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    
    # Validación segura del contenido
    if message.content and hasattr(message.content[0], 'text'):
        return message.content[0].text
    
    return "Lo siento, tuve un pequeño problema al procesar la información. ¿Podrías repetir tu pregunta? 🧵"

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
    return "✅ Botoncín Original y Estable corriendo en Render", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
