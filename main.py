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

# --- DICCIONARIOS DE TRADUCCIÓN DE SUFIJOS ---
SUFIJOS_BOTONES = {
    'M': 'mate',
    'B': 'brillante',
    'L': 'liso',
    'R': 'rayado',
    '4': '4 hoyos',
    '2': '2 hoyos'
}

SUFIJOS_MERCERIA = {
    'B': 'Blanco',
    'N': 'Negro',
    'M': 'Marino',
    'CR': 'Crudo'
}


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
        
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "por", "favor"]
        palabras = [p for p in palabras if p not in saludos]
        
        # --- BÚSQUEDA INTELIGENTE POR SUFIJO (FILTRO DE ENTRADA) ---
        es_boton = "boton" in pregunta_limpia or "botón" in pregunta_limpia
        
        if es_boton:
            if "mate" in pregunta_limpia:
                palabras.append("m")
            elif "brillante" in pregunta_limpia:
                palabras.append("b")
            elif "liso" in pregunta_limpia:
                palabras.append("l")
            elif "rayado" in pregunta_limpia:
                palabras.append("r")
        else:
            if "blanco" in pregunta_limpia:
                palabras.append("b")
            elif "negro" in pregunta_limpia:
                palabras.append("n")
            elif "marino" in pregunta_limpia:
                palabras.append("m")
            elif "crudo" in pregunta_limpia:
                palabras.append("cr")

        # Determinar tabla destino
        if es_boton or "broche" in pregunta_limpia:
            tabla_destino = "inventario_botones"
        else:
            tabla_destino = "inventario_merceria"
            
        query = supabase.table(tabla_destino).select("*")
        
        if termino_hoyos:
            query = query.ilike('Descripción', f'%{termino_hoyos}%')
            
        # Si no hay "X hoyos", buscar por palabras clave comunes o tags
        elif palabras:
            condiciones_or = []
            for p in palabras:
                condiciones_or.append(f"Modelo.ilike.%{p}%")
                condiciones_or.append(f"Descripción.ilike.%{p}%")
                condiciones_or.append(f"tags.ilike.%{p}%")
            
            query = query.or_(",".join(condiciones_or))
            
        respuesta = query.limit(15).execute()
        data = respuesta.data
        
        if not data:
            return "No encontré productos específicos para esa solicitud en el inventario actual."
            
        texto_inventario = f"Resultados encontrados en [{tabla_destino}]:\n"
        for item in data:
            # --- NUEVO BLOQUE TRADUCTOR DE SUFIJOS (FILTRO DE SALIDA) ---
            modelo = item.get('Modelo', '')
            descripcion = item.get('Descripción', 'N/A')
            sufijo = modelo[-1].upper() if modelo else ''
            
            detalles_sufijo = []
            if "boton" in tabla_destino:
                if sufijo in SUFIJOS_BOTONES:
                    detalles_sufijo.append(f"Acabado/Variante: {SUFIJOS_BOTONES[sufijo]}")
            else:
                # Mercería: revisa si viene con guion (FLECO05-N) o directo al final
                letra_color = modelo.split('-')[-1].upper() if '-' in modelo else sufijo
                if letra_color in SUFIJOS_MERCERIA:
                    detalles_sufijo.append(f"Color: {SUFIJOS_MERCERIA[letra_color]}")
            
            if detalles_sufijo:
                descripcion = f"{descripcion} ({' | '.join(detalles_sufijo)})"

            texto_inventario += (
                f"- Modelo: {modelo}, Descripción: {descripcion}, "
                f"Stock: {item.get('Stock Físico M', item.get('Stock Real', 0))}, "
                f"Fecha Llegada: {item.get('fecha_llegada', 'N/A')}\n"
            )
            
        return texto_inventario
        
    except Exception as e:
        return f"Error consultando la base de datos: {str(e)}"


def consultar_ia(pregunta, inventario):
    """Envía la pregunta y el inventario real a Claude estructurando las instrucciones del sistema."""
    prompt = f"""
Tu nombre es "Bot Botones", un asistente virtual experto en atención al cliente para una tienda de botones y mercería. Tu objetivo es responder las dudas de stock del cliente basándote ÚNICAMENTE en el inventario real extraído de la base de datos que se te proporciona abajo.

REGLAS DE ORO DE COMPORTAMIENTO:
1. **Veracidad Absoluta**: Responde basándote solo en los datos provistos en la sección "INVENTARIO DISPONIBLE". Si un producto no aparece o su stock es 0, indica amablemente que no hay disponibilidad o sugiere una variante que SÍ esté en la lista. Jamás inventes existencias.
2. **Formato de Unidades**: 
   - En la tabla de botones, las cantidades reflejan unidades sueltas. Sé claro (ej: "Tenemos 50 unidades disponibles").
   - En la tabla de mercería, el stock representa metros (ej: "Tenemos 1400 metros disponibles").
3. **Análisis de Claves y Sufijos**: Los códigos de los productos contienen sufijos que indican sus variantes. El inventario provisto ya incluye la traducción automática de estas características en la descripción de cada fila (ej: 'Color: Negro' o 'Acabado/Variante: mate'). Confía estrictamente en las descripciones enriquecidas y responde al cliente basándote en el modelo exacto que cumple con lo que pide.
4. **Fechas de Llegada**: Si el producto deseado no tiene stock inmediato pero tiene una "Fecha Llegada" asignada en el inventario, infórmale al cliente cuándo recibiremos más mercancía para que pueda apartarla.
5. **Tono y Brevedad**: Mantén una comunicación profesional, sumamente clara

---
INVENTARIO DISPONIBLE EN BASE DE DATOS:
{inventario}
---

Pregunta del Cliente: "{pregunta}"

Respuesta del Bot:
"""

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
