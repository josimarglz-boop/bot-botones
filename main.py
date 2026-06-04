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
    """Busca y filtra en Supabase solo los productos relevantes para reducir costos y escalar."""
    try:
        # Extraemos palabras de más de 2 caracteres para buscar (evitamos "de", "el", "un")
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2]
        
        if not palabras:
            # Si es un saludo genérico ("hola"), traemos una muestra pequeña para que no vaya vacío
            respuesta = supabase.table("inventario_botones").select("*").limit(5).execute()
            return respuesta.data

        # Armamos una consulta avanzada usando los filtros de Supabase (ilike busca texto ignorando mayúsculas)
        # Buscaremos principalmente por el código/modelo o el tipo de uso (ej: camisero, sastre)
        resultados = []
        for palabra in palabras:
            # Busca si la palabra coincide con el Modelo o con el Uso
            res_modelo = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{palabra}%").execute()
            res_uso = supabase.table("inventario_botones").select("*").ilike("Uso", f"%{palabra}%").execute()
            
            if res_modelo.data:
                resultados.extend(res_modelo.data)
            if res_uso.data:
                resultados.extend(res_uso.data)

        # Eliminamos duplicados si una fila coincidió en ambas búsquedas
        resultados_unicos = {f['id']: f for f in resultados}.values()
        return list(resultados_unicos)

    except Exception as e:
        print(f"Error filtrando en Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía la pregunta al carismático Botoncín con un subset filtrado de datos."""
    inv_str = str(inventario) 

    prompt = f"""Eres "Botoncín" 🧵, el asistente virtual, carismático y experto de la tienda de insumos textiles. Tu objetivo es orientar a los vendedores con precisión, alegría y ayudar a mover el inventario de forma inteligente.
Responde SIEMPRE en español, con tono entusiasta, breve y claro (máximo 6-7 líneas).

INVENTARIO FILTRADO DISPONIBLE PARA ESTA CONSULTA:
{inv_str}

El vendedor pregunta: "{pregunta}"

Instrucciones de Personalidad y Lógica Comercial:
1. LÓGICA DE SALUDO Y TONO: Identifica la intención del usuario. Si el usuario te saluda directamente (ej: "hola", "buenas tardes"), preséntate alegremente como Botoncín usando emojis textiles. Si el usuario va directo a una consulta o corrección (ej: "es el B3020", "tienes camiseros"), NO te presentes ni digas "¡Hola! Soy Botoncín", ve directo a la confirmación de datos con un tono amable y servicial, sin repetir tu nombre en cada mensaje.
2. SI NO HAY RESULTADOS: Si el inventario filtrado está vacío o no corresponde a lo que pide el usuario, infórmale con amabilidad que no encontraste ese modelo específico en el sistema y sugírele revisar el código.
3. PRIORIZACIÓN DE STOCK: Muestra primero los modelos con MAYOR STOCK disponible. Coloca una bombilla 💡 junto al modelo con más stock.
4. ORDEN POR TAMAÑO: Si preguntan por un código específico, muestra sus variantes ordenadas por tamaño de forma ASCENDENTE.
5. REGLA DE UNIDADES DE MAYOREO (MAZOS Y GRUESAS):
   - 1 MAZO = 1,728 unidades (piezas).
   - 1 GRUESA = 144 unidades (piezas).
   - Si el vendedor pide la mercancía en "mazos" o "gruesas", realiza la conversión matemática multiplicando la cantidad solicitada por su equivalente en piezas para verificar si el stock disponible en la base de datos es suficiente para cubrir el pedido.
6. REGLA DE FECHAS DE LLEGADA (Columna 'fecha_llegada'):
   - Si el stock es 0, avisa que está agotado hoy, pero muestra la fecha de la columna 'fecha_llegada' (ej: "🚚 Próxima llegada: 15 de Junio").
   - Si el stock es BAJO (menos de 500 piezas), genera urgencia diciendo que quedan pocas piezas y añade la fecha de llegada del nuevo lote.
7. DATOS OBLIGATORIOS: Muestra siempre código, modelo, tamaño, stock, fecha de llegada (si aplica) y el link de la imagen.
8. FORMATO WHATSAPP: Usa saltos de línea para separar opciones. NO uses asteriscos dobles (**), dale formato limpio solo con texto y emojis.
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

    # Carga SOLO los datos relacionados con la pregunta
    inventario = cargar_inventario_supabase(mensaje_entrante)

    respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín corriendo estable y optimizado en Supabase", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
