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
    """Busca de forma ultra estricta en Supabase para enviar el mínimo de datos a la IA."""
    try:
        # Extraer palabras clave limpias
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2]
        
        # Si no hay palabras clave o es un saludo corto, NO mandamos inventario (ahorro total)
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa"]
        if not palabras or all(p in saludos for p in palabras):
            return []

        resultados = []
        for palabra in palabras:
            if palabra in saludos:
                continue
            # Buscamos coincidencias en Modelo o Uso, limitando a 5 respuestas máximo por palabra
            res_modelo = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{palabra}%").limit(5).execute()
            res_uso = supabase.table("inventario_botones").select("*").ilike("Uso", f"%{palabra}%").limit(5).execute()
            
            if res_modelo.data:
                resultados.extend(res_modelo.data)
            if res_uso.data:
                resultados.extend(res_uso.data)

        # Eliminar duplicados y recortar a un máximo de 6 productos totales para proteger el bolsillo
        resultados_unicos = {f['id']: f for f in resultados}.values()
        return list(resultados_unicos)[:6]

    except Exception as e:
        print(f"Error filtrando en Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía la consulta al modelo económico Haiku con los datos estrictamente necesarios."""
    inv_str = str(inventario) 

    prompt = f"""Eres "Botoncín" 🧵, el asistente virtual de la tienda de insumos textiles. Responde SIEMPRE en español, alegre, muy breve (máximo 5 líneas) y directo al grano.

INVENTARIO DISPONIBLE (SÓLO USA ESTOS DATOS):
{inv_str}

Pregunta: "{pregunta}"

Instrucciones:
1. SALUDO: Si te saludan, di "¡Hola! Soy Botoncín 🧵" y pregunta qué modelo buscan. Si van directo a una consulta, NO te presentes, ve al grano.
2. SIN STOCK/RESULTADOS: Si el inventario está vacío o no coincide, indica amablemente que no encontraste stock disponible para ese modelo exacto.
3. LOGICA COMERCIAL: Ordena por tamaño ascendente. Si el stock es 0, usa la 'fecha_llegada' (ej: 🚚 Próxima llegada: 15 de Junio). Si es menor a 500 piezas, avisa que quedan pocas unidades. 1 mazo = 1728 pzs, 1 gruesa = 144 pzs.
4. FORMATO DE RESPUESTA INTELIGENTE POR CATEGORÍA:
   - Armas una descripción natural y fluida según el producto.
   - Si es un BOTÓN: Muestra Código, Modelo, Tamaño, Stock, Fecha de llegada (si aplica) y el Link de la imagen.
   - Si es OTRO PRODUCTO (Cintas, Resortes, etc.): Genera una descripción general e intuitiva en una sola línea combinando sus datos (ej: "Cinta palmita de 20mm en color crudo"), seguido del Stock disponible, Fecha de llegada (si aplica) y su Link de imagen.
   - En ningún caso uses asteriscos dobles (**). Usa saltos de línea limpios y emojis para separar la información.
"""

    # Cambiamos al modelo claude-3-5-haiku para reducir el costo un 90%
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=500,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de WhatsApp vía Twilio."""
    mensaje_entrante = request.form.get("Body", "").strip()
    
    # Carga solo lo necesario
    inventario = cargar_inventario_supabase(mensaje_entrante)
    respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín Híbrido y Económico corriendo en Render", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
