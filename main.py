
import os
import re
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from supabase import create_client, Client

app = Flask(__name__)
client = Anthropic()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def cargar_inventario_supabase(pregunta: str):
    """Búsqueda precisa: detecta sufijos (B5568-B vs B5568-M), tablas, tamaños."""
    try:
        pregunta_lower = pregunta.lower()
        
        # Saludos que no generan búsqueda
        saludos = ["hola", "buen", "dia", "tarde", "noche", "gracias", "ok", "disculpa", "dame", "quisiera", "favor"]
        palabras = [p.strip().lower() for p in re.findall(r'\b\w+\b', pregunta) if len(p) > 2 and p not in saludos]
        
        if not palabras:
            return []

        resultados = []
        
        # =============== 1. BÚSQUEDA EXACTA POR CÓDIGO CON SUFIJO ===============
        # Busca: B5568-B, B5568-M, B0003, etc.
        codigo_match = re.search(r'\b[B]\d{3,4}[-]?[A-Z]?\b', pregunta, re.IGNORECASE)
        if codigo_match:
            codigo = codigo_match.group().upper()
            
            try:
                # Primero: búsqueda exacta
                res = supabase.table("inventario_botones").select("*").eq("Modelo", codigo).limit(6).execute()
                if res.data:
                    return res.data
                
                # Segunda opción: búsqueda sin guión
                codigo_sin_guion = codigo.replace("-", "")
                res = supabase.table("inventario_botones").select("*").eq("Modelo", codigo_sin_guion).limit(6).execute()
                if res.data:
                    return res.data
                
                # Tercera opción: búsqueda fuzzy por prefijo
                codigo_prefijo = codigo.rstrip("-ABMR")  # Elimina sufijo
                res = supabase.table("inventario_botones").select("*").ilike("Modelo", f"{codigo_prefijo}%").limit(6).execute()
                if res.data:
                    return res.data
            except Exception as e:
                print(f"Error búsqueda por código: {e}")

        # =============== 2. DETECTA MERCERÍA vs BOTONES ===============
        palabras_merceria = ["cinta", "palmita", "resorte", "elastico", "elástico", "plastiflecha", "candado", "fleco", "satinado", "bolsas", "contactel", "crochet", "hilo", "botones"]
        es_merceria = any(p in palabras_merceria for p in palabras)
        
        tabla = "inventario_merceria" if es_merceria else "inventario_botones"
        columnas_busqueda = ["Descripción", "Modelo", "TAGS"] if es_merceria else ["Modelo", "Uso", "TAGS"]
        
        # =============== 3. BÚSQUEDA POR CRITERIOS ESPECÍFICOS ===============
        for palabra in palabras[:3]:  # Máximo 3 palabras
            for columna in columnas_busqueda:
                try:
                    res = supabase.table(tabla).select("*").ilike(columna, f"%{palabra}%").limit(4).execute()
                    if res.data:
                        resultados.extend(res.data)
                except:
                    pass

        # =============== 4. BÚSQUEDA POR TAMAÑO (si mencionan talla/ancho/mm) ===============
        tamaño_match = re.search(r'(?:talla|tamaño|ancho|mm|línea|linea)\s*(\d+)', pregunta)
        if tamaño_match and tabla == "inventario_botones":
            tamaño = int(tamaño_match.group(1))
            try:
                # Para botones: filtra por Tamaño
                res = supabase.table(tabla).select("*").eq("Tamaño", tamaño).limit(6).execute()
                if res.data:
                    resultados.extend(res.data)
            except:
                pass
        elif tamaño_match and tabla == "inventario_merceria":
            tamaño = tamaño_match.group(1)
            try:
                # Para mercería: busca número en Descripción
                res = supabase.table(tabla).select("*").ilike("Descripción", f"%{tamaño}%").limit(6).execute()
                if res.data:
                    resultados.extend(res.data)
            except:
                pass

        # =============== 5. BÚSQUEDA POR HOYOS/ACABADO (solo botones) ===============
        if tabla == "inventario_botones":
            if "2 hoyo" in pregunta_lower or "dos hoyo" in pregunta_lower:
                try:
                    res = supabase.table(tabla).select("*").eq("Hoyos", "2 hoyos").limit(4).execute()
                    if res.data:
                        resultados.extend(res.data)
                except:
                    pass
            elif "4 hoyo" in pregunta_lower or "cuatro hoyo" in pregunta_lower:
                try:
                    res = supabase.table(tabla).select("*").eq("Hoyos", "4 hoyos").limit(4).execute()
                    if res.data:
                        resultados.extend(res.data)
                except:
                    pass
            
            # Acabado: Brillante, Mate
            if "mate" in pregunta_lower:
                try:
                    res = supabase.table(tabla).select("*").eq("Acabado", "Mate").limit(4).execute()
                    if res.data:
                        resultados.extend(res.data)
                except:
                    pass
            elif "brillante" in pregunta_lower:
                try:
                    res = supabase.table(tabla).select("*").eq("Acabado", "Brillante").limit(4).execute()
                    if res.data:
                        resultados.extend(res.data)
                except:
                    pass

        # =============== 6. ELIMINAR DUPLICADOS Y RETORNAR ===============
        resultados_unicos = {}
        for fila in resultados:
            resultados_unicos[fila['id']] = fila
        
        return list(resultados_unicos.values())[:6]

    except Exception as e:
        print(f"Error filtrando en Supabase: {e}")
        return []


def consultar_ia(pregunta: str, inventario: list) -> str:
    """Prompt optimizado para Haiku: breve pero completo."""
    inv_str = str(inventario)

    prompt = f"""Eres "Botoncín" 🧵, asistente de insumos textiles. Responde en español, breve (máx 6 líneas), alegre, sin asteriscos dobles.

INVENTARIO (usa solo estos datos):
{inv_str}

Pregunta: "{pregunta}"

Instrucciones:
1. Saludo: Si saludan genérico → "¡Hola! Soy Botoncín 🧵 ¿Qué buscas?". Si piden producto → directo.
2. Stock: Revisa la columna 'Stock'. Si >0 → disponible. Si 0 → "No hay stock". Si vacío → "No encontré ese modelo".
3. Unidades: Si piden mazos (1 mazo=1728 pzs) o gruesas (1 gruesa=144 pzs), calcula si hay suficiente. Ej: "Pides 2 mazos = 3456 pzs, tengo 5000 ✓".
4. Formato: Modelo • Tamaño • Hoyos/Acabado • Stock • Fecha llegada (si existe) • Link imagen. Usa emojis, saltos línea.
5. TAGS: Si incluyen "Teñible", "Básico", "Mate", menciona eso en respuesta.
"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=350,  # Reducido de 500 para ahorrar
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
    return "✅ Botoncín Optimizado v2 en Render", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
