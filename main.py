import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from supabase import create_client, Client

app = Flask(__name__)
client = Anthropic()

# Conexión directa a tu nueva base de datos de Supabase usando las variables de Railway
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Inicializamos el cliente de Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def cargar_inventario_supabase():
    """Trae TODOS tus botones desde Supabase sin límites de Google Sheets."""
    try:
        # Hacemos la consulta a la tabla exacta que creamos juntos
        response = supabase.table("inventario_botones").select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error cargando inventario desde Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía la pregunta y el inventario a Claude y retorna la respuesta."""
    # Como Supabase es súper ligero, ahora sí le pasamos el catálogo completo a Claude
    inv_str = str(inventario) 

    prompt = f"""Eres el asistente de inventario de botones de una empresa textil.
Responde SIEMPRE en español, de forma breve y clara (máximo 6 líneas).

INVENTARIO ACTUAL DESDE BASE DE DATOS:
{inv_str}

El vendedor pregunta: "{pregunta}"

Instrucciones CRÍTICAS:
- Si preguntan por un CÓDIGO específico (ej: B5871-R), busca EXACTAMENTE ese código en el inventario.
- Los códigos pueden tener sufijos (-R, -L, -M, -B, etc.) que indican variantes — respétalos.
- Si el código exacto NO existe, busca códigos que empiecen igual.
- Para búsquedas por características (talla, hoyos, material, color, teñible), filtra con lógica inteligente.
- Muestra: código COMPLETO, modelo, talla (tamano), hoyos, acabado, tono, uso, tags, stock y el link de la imagen.
- Formato WhatsApp: usa emojis, saltos de línea, sin markdown ni asteriscos.
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

    # Ahora cargamos desde Supabase
    inventario = cargar_inventario_supabase()

    if not inventario:
        respuesta_texto = "⚠️ No pude conectar con la base de datos de Supabase en este momento. Intenta en unos segundos."
    else:
        respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Bot de inventario activo y conectado a Supabase", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)