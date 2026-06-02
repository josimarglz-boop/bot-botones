import os
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

def cargar_inventario_supabase():
    """Trae todo el catálogo desde la tabla de Supabase."""
    try:
        respuesta = supabase.table("inventario_botones").select("*").execute()
        return respuesta.data
    except Exception as e:
        print(f"Error consultando Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía la pregunta y el catálogo a Claude con las reglas comerciales."""
    inv_str = str(inventario) 

    prompt = f"""Eres el asistente de inventario de botones de una empresa textil. Tu objetivo es orientar al vendedor con precisión y ayudar a mover el inventario de forma inteligente.
Responde SIEMPRE en español, de forma breve y clara (máximo 6 líneas).

INVENTARIO ACTUAL DESDE BASE DE DATOS (SUPABASE):
{inv_str}

El vendedor pregunta: "{pregunta}"

Instrucciones CRÍTICAS de respuesta y lógica comercial:
- Si el vendedor busca por características generales (ej: "camisero", "brillante", "blanco") sin dar un código específico, busca todos los modelos que coincidan en la base de datos y ordénalos de manera que muestres **PRIMERO aquellos modelos que tengan el MAYOR STOCK disponible** (para ayudar a rotar el producto con exceso o rezagado).
- Coloca una bombilla 💡 junto al modelo con más stock y añade una breve nota de sugerencia (ej: "💡 Modelo altamente sugerido por alta disponibilidad").
- Si preguntan por un CÓDIGO o MODELO específico, busca todas las variantes de ese código y ordénalas por tamaño de forma ASCENDENTE (de menor a mayor tamaño).
- REGLA DE CONVERSIÓN TEXTIL CRÍTICA: En nuestro negocio, 1 MAZO equivale exactamente a 1,728 unidades (piezas). Si un vendedor te pregunta por mazos, multiplica la cantidad de mazos por 1,728 para obtener las piezas totales requeridas y compáralas contra el 'stock' disponible para validar si alcanza.
- Muestra siempre: código COMPLETO, modelo, tamaño, hoyos, acabado, tono, uso, stock disponible y el link de la imagen.
- Formato WhatsApp: usa emojis, saltos de línea para separar opciones, sin markdown ni asteriscos.
"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de WhatsApp vía Twilio."""
    mensaje_entrante = request.form.get("Body", "").strip()
    numero_vendedor = request.form.get("From", "")

    print(f"Mensaje de {numero_vendedor}: {mensaje_entrante}")

    # Carga los datos desde Supabase
    inventario = cargar_inventario_supabase()

    if not inventario:
        respuesta_texto = "⚠️ No pude conectar con la base de datos de Supabase en este momento. Intenta en unos segundos."
    else:
        respuesta_texto = consular_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Bot de botones corriendo estable en Supabase", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
