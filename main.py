import os
import csv
import io
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic

app = Flask(__name__)
client = Anthropic()

SHEET_URL = os.environ.get("SHEET_URL", "")

def cargar_inventario():
    """Descarga y parsea el Google Sheet como CSV."""
    try:
        res = requests.get(SHEET_URL, timeout=10)
        res.raise_for_status()
        reader = csv.DictReader(io.StringIO(res.text))
        return list(reader)
    except Exception as e:
        print(f"Error cargando inventario: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía la pregunta y el inventario a Claude y retorna la respuesta."""
    inv_str = str(inventario[:100])  # máximo 100 productos por llamada

    prompt = f"""Eres el asistente de inventario de botones de una empresa textil.
Responde SIEMPRE en español, de forma breve y clara (máximo 5 líneas).

INVENTARIO ACTUAL:
{inv_str}

El vendedor pregunta: "{pregunta}"

Instrucciones:
- Detecta TODOS los criterios mencionados (talla, hoyos, material, color, teñible, cantidad de mazos, etc.)
- Filtra usando AND para todos los criterios detectados
- Muestra los resultados con: código, nombre, talla, hoyos, material, teñible, mazos disponibles y precio
- Si no hay coincidencia exacta, sugiere el más cercano
- Si piden mazos y el stock es insuficiente, avísalo claramente
- Formato de respuesta para WhatsApp: usa emojis simples y saltos de línea, sin markdown
"""

    message = client.messages.create(
        model="claude-sonnet-4-5"  # ← antes era "claude-opus-4-5",
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

    inventario = cargar_inventario()

    if not inventario:
        respuesta_texto = "⚠️ No pude cargar el inventario en este momento. Intenta en unos segundos."
    else:
        respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Bot de inventario activo", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
