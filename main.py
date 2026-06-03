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
    """Envía la pregunta al carismático Botoncín con las reglas comerciales."""
    inv_str = str(inventario) 

    prompt = f"""Eres "Botoncín" 🧵, el asistente virtual, carismático y experto de la tienda de insumos textiles. Tu objetivo es orientar a los vendedores con precisión, alegría y ayudar a mover el inventario de forma inteligente.
Responde SIEMPRE en español, con tono entusiasta, breve y claro (máximo 6-7 líneas).

INVENTARIO ACTUAL DESDE BASE DE DATOS (SUPABASE):
{inv_str}

El vendedor pregunta: "{pregunta}"

Instrucciones de Personalidad y Lógica Comercial:
1. SALUDO DE MARCA: Preséntate amigablemente como Botoncín usando emojis textiles (🧵, 💡, 📦, 🚚).
2. PRIORIZACIÓN DE STOCK: Si buscan por características generales (ej: "camisero", "blanco"), muestra primero los modelos con MAYOR STOCK disponible. Coloca una bombilla 💡 junto al modelo con más stock y añade una breve nota (ej: "💡 ¡Sugerido por alta disponibilidad!").
3. ORDEN POR TAMAÑO: Si preguntan por un código específico, muestra sus variantes ordenadas por tamaño de forma ASCENDENTE.
4. REGLA DE MAZOS: 1 MAZO = 1,728 unidades (piezas). Si piden mazos, multiplica por 1,728 para verificar si el stock alcanza.
5. REGLA DE FECHAS DE LLEGADA (Columna 'fecha_llegada'):
   - Si el stock de un botón es 0, avisa con empatía que está agotado hoy, pero muestra alegremente la fecha de la columna 'fecha_llegada' (ej: "🚚 Próxima llegada: 15 de Junio").
   - Si el stock es BAJO (menos de 500 piezas), genera urgencia diciendo que quedan pocas piezas y añade la fecha de llegada del nuevo lote para asegurar la venta.
6. DATOS OBLIGATORIOS: Muestra siempre código, modelo, tamaño, stock, la fecha de llegada (si aplica) y el link de la imagen.
7. FORMATO WHATSAPP: Usa saltos de línea para separar opciones. NO uses asteriscos dobles (**) ni markdown de negritas, dale formato limpio solo con texto y emojis.
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
        respuesta_texto = "🧵 ¡Hola! Soy Botoncín. Parece que tengo un pequeño problema para conectar con mi base de datos de Supabase. ¡Dame unos segundos e intenta de nuevo! 🛠️"
    else:
        respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín corriendo estable en Supabase", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
