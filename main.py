
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
    """Detecta si buscan botones o mercería y apunta a las columnas reales."""
    try:
        pregunta_limpia = pregunta.lower()
        
        # 1️⃣ [AQUÍ VA TU LÓGICA DE BOTONES QUE AGREGAMOS ANTES]
        patron_sufijo = re.search(r'(\d+)\s*(mate|rayado|liso|brillante|brillo)', pregunta_limpia)
        termino_sufijo_compacto = None
        if patron_sufijo:
            numero_modelo = patron_sufijo.group(1)
            palabra_descriptiva = patron_sufijo.group(2)
            mapa_sufijos = {"mate": "m", "rayado": "r", "liso": "l", "brillante": "b", "brillo": "b"}
            sufijo_letra = mapa_sufijos.get(palabra_descriptiva)
            if sufijo_letra:
                termino_sufijo_compacto = f"{numero_modelo}{sufijo_letra}"

        # 2️⃣ ⭐ ¡AQUÍ AGREGASTE LA NUEVA LÍNEA DE COLORES! ⭐
        patron_color = re.search(r'(\d+)\s*(negro|blanco|rojo|azul|amarillo|verde|rosa)', pregunta_limpia)
        termino_merceria_compacto = None
        if patron_color:
            modelo_merceria = patron_color.group(1)
            color_texto = patron_color.group(2)
            mapa_colores = {"negro": "ne", "blanco": "bl", "rojo": "ro", "azul": "az", "amarillo": "am", "verde": "vd", "rosa": "rs"}
            codigo_color = mapa_colores.get(color_texto)
            if codigo_color:
                termino_merceria_compacto = f"{modelo_merceria}{codigo_color}"

        # 3️⃣ [LÓGICA DE HOYOS QUE YA TENÍAS]
        patron_hoyos = re.search(r'(\d+)\s*hoyo', pregunta_limpia)
        termino_hoyos = None
        if patron_hoyos:
            termino_hoyos = f"{patron_hoyos.group(1)} hoyos"
        
        # 4️⃣ [EXTRACCIÓN Y LIMPIEZA DE PALABRAS]
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2]
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa", "dame", "opciones", "quisiera", "favor", "tenemos", "colores"]
        palabras_filtradas = [p for p in palabras if p not in saludos]
        
        # [LIMPIEZA DE HOYOS]
        if termino_hoyos:
            palabras_filtradas = [p for p in palabras_filtradas if p not in ["hoyos", "hoyo", patron_hoyos.group(1)]]
            palabras_filtradas.append(termino_hoyos)
            
        # [LIMPIEZA DE SUFIJOS DE BOTONES]
        if termino_sufijo_compacto:
            palabras_filtradas = [p for p in palabras_filtradas if p not in [numero_modelo, palabra_descriptiva]]
            palabras_filtradas.append(termino_sufijo_compacto)

        # 5️⃣ ⭐ REINJECTAMOS EL TÉRMINO DE MERCERÍA COMPACTO ⭐
        if termino_merceria_compacto:
            # Eliminamos el número suelto y el color en texto para que no estorben
            palabras_filtradas = [p for p in palabras_filtradas if p not in [modelo_merceria, color_texto]]
            # Agregamos el tag armado (ej: "20ne")
            palabras_filtradas.append(termino_merceria_compacto)

        if not palabras_filtradas:
            return []

        # 1. PALABRAS MÁGICAS PARA MERCERÍA
        palabras_merceria = ["cinta", "palmita", "resorte", "elastico", "elástico", "plastiflecha", "candado", "fleco", "satinado", "bolsas", "contactel"]
        es_consulta_merceria = any(p in palabras_merceria for p in palabras_filtradas)
        
        resultados = []
        
        # 2. RUTA MERCERÍA
        if es_consulta_merceria:
            for palabra in palabras_filtradas:
                res = supabase.table("inventario_merceria").select("*").or_(
                    f"Descripción.ilike.%{palabra}%,Modelo.ilike.%{palabra}%,TAGS.ilike.%{palabra}%"
                ).limit(3).execute()
                if res.data:
                    resultados.extend(res.data)

        # 3. RUTA BOTONES (Aquí buscará "5571m" directamente en el .or_ que lee tus TAGS)
        else:
            for palabra in palabras_filtradas:
                res = supabase.table("inventario_botones").select("*").or_(
                    f"Modelo.ilike.%{palabra}%,Uso.ilike.%{palabra}%,TAGS.ilike.%{palabra}%"
                ).limit(4).execute()
                if res.data:
                    resultados.extend(res.data)

        # Eliminación de duplicados
        resultados_unicos = {}
        for fila in resultados:
            resultados_unicos[fila['id']] = fila
            
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
   - Sufijo "R" = Acabado Rayado.
   - Sufijo "L" = Acabado Liso.
   - Sufijo "B" = Acabado Brillante.
   - Sufijo "M" = Acabado Mate.
Si el cliente te pregunta por el botón "5529 de 4 hoyos", busca en el inventario provisto el modelo que termine exactamente en "-4" (B5529-4) y muestra exclusivamente el stock de ese modelo. No los mezcles ni digas que no hay existencias si el registro está en el inventario.
"""

    # 
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
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
    return "✅ Botoncín Original y Estable corriendo en Render", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
