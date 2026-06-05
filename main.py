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
    """Detecta si buscan botones o mercería y apunta a la tabla correcta usando tu lógica actual."""
    try:
        # Extraer palabras clave limpias (Tu código original)
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2]
        
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa", "dame", "opciones"]
        if not palabras or all(p in saludos for p in palabras):
            return []

        # 1. TUS PALABRAS MÁGICAS PARA MERCERÍA
        # Si el vendedor escribe cualquiera de estas, el bot mirará la hoja de mercería
        palabras_merceria = ["cinta", "palmita", "resorte", "elastico", "elástico", "plastiflecha", "candado"]
        es_consulta_merceria = any(p in palabras_merceria for p in palabras)
        
        resultados = []
        
        # 2. SI ES MERCERÍA: Busca en la nueva tabla
        if es_consulta_merceria:
            for palabra in palabras:
                if palabra in saludos:
                    continue
                # Aquí pones las columnas nuevas que hayas decidido para tu hoja de mercería
                res_prod = supabase.table("inventario_merceria").select("*").ilike("Producto", f"%{palabra}%").limit(5).execute()
                res_cod = supabase.table("inventario_merceria").select("*").ilike("Código", f"%{palabra}%").limit(5).execute()
                
                if res_prod.data:
                    resultados.extend(res_prod.data)
                if res_cod.data:
                    resultados.extend(res_cod.data)

        # 3. SI ES BOTÓN: Tu ruta original de ayer que sí funciona
        else:
            for palabra in palabras:
                if palabra in saludos:
                    continue
                # Busca en tu tabla original de botones (sin la columna categoría)
                res_modelo = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{palabra}%").limit(5).execute()
                res_uso = supabase.table("inventario_botones").select("*").ilike("Uso", f"%{palabra}%").limit(5).execute()
                
                if res_modelo.data:
                    resultados.extend(res_modelo.data)
                if res_uso.data:
                    resultados.extend(res_uso.data)

        # Eliminar duplicados y recortar a un máximo de 6 (Tu código original)
        resultados_unicos = {f['id']: f for f in resultados}.values()
        return list(resultados_unicos)[:6]

    except Exception as e:
        print(f"Error filtrando en Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Regresa al prompt original y al motor Sonnet de ayer."""
    inv_str = str(inventario) 

    prompt = f"""Eres "Botoncín" 🧵, el asistente virtual de la tienda de insumos textiles. Responde SIEMPRE en español, alegre, muy breve (máximo 5 líneas) y directo al grano.

INVENTARIO DISPONIBLE (SÓLO USA ESTOS DATOS):
{inv_str}

Pregunta: "{pregunta}"

Instrucciones:
1. SALUDO: Si te saludan, di "¡Hola! Soy Botoncín 🧵" y pregunta qué modelo buscan. Si van directo a una consulta, NO te presentes, ve al grano.
2. SIN STOCK/RESULTADOS: Si el inventario está vacío o no coincide lo que busca el cliente, indica amablemente que no encontraste stock disponible para esa solicitud exacta.
3. LOGICA COMERCIAL: Ordena por tamaño ascendente. Si el stock es 0, usa la 'fecha_llegada' (ej: 🚚 Próxima llegada: 15 de Junio). Si es menor a 500 piezas, avisa que quedan pocas unidades. 1 mazo = 1728 pzs, 1 gruesa = 144 pzs.
4. FORMATO DE RESPUESTA INTELIGENTE POR CATEGORÍA:
   - Armas una descripción natural y fluida según el producto.
   - Si es un BOTÓN: Muestra Código, Modelo, Tamaño, Stock, Fecha de llegada (si aplica) y el Link de la imagen.
   - Si es OTRO PRODUCTO (Cintas, Resortes, etc.): Genera una descripción general e intuitiva en una sola línea combinando sus datos (ej: "Cinta palmita de 20mm en color crudo"), seguido del Stock disponible, Fecha de llegada (si aplica) y su Link de imagen.
   - En ningún caso uses asteriscos dobles (**). Usa saltos de línea limpios y emojis para separar la información.
"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
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
