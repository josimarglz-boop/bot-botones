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
    """Busca en Supabase de forma inteligente y unificada para evitar pérdidas de stock."""
    try:
        pregunta_limpia = pregunta.strip().lower()
        
        # Filtro de saludos idéntico para ahorro total de tokens
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa"]
        palabras_inspeccion = [p for p in re.findall(r'\b\w+\b', pregunta_limpia) if len(p) > 2]
        if not palabras_inspeccion or all(p in saludos for p in palabras_inspeccion):
            return []

        # Limpiamos plurales comunes de forma rápida para mejorar el acierto en las columnas de texto
        pregunta_limpia = re.sub(r'(botones|camiseros|teñibles|cintas|elasticos)\b', lambda m: m.group(1)[:-1], pregunta_limpia)

        resultados = []
        # Tomamos las 2 palabras más importantes que no sean saludos para enfocar la puntería
        palabras_clave = [p for p in palabras_inspeccion if p not in saludos][:2]

        if palabras_clave:
            # Si hay al menos una palabra clave, buscamos de forma amplia usando la primera (origen)
            p1 = palabras_clave[0]
            # Quitamos la 's' final de la palabra clave si la tiene para buscar en singular
            if p1.endswith('s') and len(p1) > 3: 
                p1 = p1[:-1]

            res_modelo = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{p1}%").limit(10).execute()
            res_uso = supabase.table("inventario_botones").select("*").ilike("Uso", f"%{p1}%").limit(10).execute()
            res_cat = supabase.table("inventario_botones").select("*").ilike("Categoría", f"%{p1}%").limit(10).execute()

            if res_modelo.data: resultados.extend(res_modelo.data)
            if res_uso.data: resultados.extend(res_uso.data)
            if res_cat.data: resultados.extend(res_cat.data)

        # Si se usaron dos palabras clave (ej: "camisero" y "18"), filtramos en caliente para dejar los más exactos
        if len(palabras_clave) > 1:
            p2 = palabras_clave[1]
            if p2.endswith('s') and len(p2) > 3: 
                p2 = p2[:-1]
            
            filtrados_exactos = [
                r for r in resultados 
                if p2 in str(r.get("Modelo", "")).lower() 
                or p2 in str(r.get("Uso", "")).lower() 
                or p2 in str(r.get("Categoría", "")).lower() 
                or p2 in str(r.get("Tamaño", "")).lower()
            ]
            if filtrados_exactos:
                resultados = filtrados_exactos

        # Eliminar duplicados y recortar estrictamente a un máximo de 6 para cuidar el bolsillo
        resultados_unicos = {f['id']: f for f in resultados}.values()
        return list(resultados_unicos)[:6]

    except Exception as e:
        print(f"Error optimizado en Supabase: {e}")
        return []

def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía la consulta al modelo Sonnet con límites estrictos de tokens y formato pulido."""
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

    # Usamos el modelo Sonnet que está activo en tu cuenta, pero ultra blindado por los filtros previos
    message = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=500,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de WhatsApp vía Twilio."""
    mensaje_entrante = request.form.get("Body", "").strip()
    
    # Carga el inventario usando los filtros mejorados
    inventario = cargar_inventario_supabase(mensaje_entrante)
    respuesta_texto = consultar_ia(mensaje_entrante, inventario)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "✅ Botoncín Inteligente e Híbrido corriendo en Render", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
