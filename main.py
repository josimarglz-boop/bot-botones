
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
    """Búsqueda ULTRA ESPECÍFICA adaptada a tu BD: Botones, Cintas, Resortes, etc."""
    try:
        pregunta_lower = pregunta.lower()
        
        # Saludos cortos → no gastar tokens
        saludos = ["hola", "buenos", "gracias", "ok", "si", "no"]
        if all(s in pregunta_lower for s in saludos) or len(pregunta_lower) < 3:
            return []

        resultados = []

        # =============== 1. BÚSQUEDA POR MODELO EXACTO ===============
        # Buscar códigos como B0003, B0330, B1240, etc.
        modelo_match = re.search(r'\b[B][0-9]{3,4}\b', pregunta, re.IGNORECASE)
        if modelo_match:
            modelo = modelo_match.group().upper()
            try:
                res = supabase.table("inventario_botones").select("*").eq("Modelo", modelo).limit(10).execute()
                if res.data:
                    # Si además pidió tamaño específico, filtrar
                    tamaño_match = re.search(r'(?:talla|tamaño|linea|línea)\s*(\d+)', pregunta)
                    if tamaño_match:
                        tamaño = int(tamaño_match.group(1))
                        res_filtrado = [r for r in res.data if r.get('Tamaño') == tamaño]
                        if res_filtrado:
                            return res_filtrado[:6]
                    return res.data[:6]
            except Exception as e:
                print(f"Error búsqueda por modelo: {e}")

        # =============== 2. BÚSQUEDA POR CATEGORÍA ===============
        # Si pregunta por "cinta", "resorte", "hilo", etc.
        categorias_palabras = {
            "cinta": "Cinta",
            "resorte": "Resorte",
            "hilo": "Hilo",
            "botón": "Botón",
            "encaje": "Encaje",
            "elástico": "Elástico",
            "cinta métrica": "Cinta Métrica"
        }
        
        for palabra, categoria in categorias_palabras.items():
            if palabra in pregunta_lower:
                try:
                    res = supabase.table("inventario_botones").select("*").eq("Categoría", categoria).limit(8).execute()
                    if res.data:
                        return res.data[:8]
                except Exception as e:
                    print(f"Error búsqueda por categoría: {e}")

        # =============== 3. BÚSQUEDA POR CRITERIOS ESPECÍFICOS (para botones) ===============
        query = supabase.table("inventario_botones").select("*")
        criterios_aplicados = False

        # Tamaño
        tamaño_match = re.search(r'(?:talla|tamaño|linea|línea)\s*(\d+)', pregunta)
        if tamaño_match:
            tamaño = int(tamaño_match.group(1))
            try:
                query = query.eq("Tamaño", tamaño)
                criterios_aplicados = True
            except:
                pass

        # Hoyos: "2 hoyos", "4 hoyos", "de pata"
        if "2 hoyo" in pregunta_lower or "dos hoyo" in pregunta_lower:
            try:
                query = query.eq("Hoyos", "2 hoyos")
                criterios_aplicados = True
            except:
                pass
        elif "4 hoyo" in pregunta_lower or "cuatro hoyo" in pregunta_lower:
            try:
                query = query.eq("Hoyos", "4 hoyos")
                criterios_aplicados = True
            except:
                pass
        elif "pata" in pregunta_lower:
            try:
                query = query.eq("Hoyos", "De Pata")
                criterios_aplicados = True
            except:
                pass

        # Tono/Color: Blanco, Dorado, Níquel, Oro Rosa, etc.
        tonos = ["blanco", "dorado", "níquel", "niquelado", "oro rosa", "plata", "plateado", "negro", "gris"]
        for tono_palabra in tonos:
            if tono_palabra in pregunta_lower:
                # Mapeo a valores reales de tu BD
                tono_map = {
                    "blanco": "Blanco",
                    "dorado": "Dorado",
                    "níquel": "Níquel",
                    "niquelado": "Níquel",
                    "oro rosa": "Oro Rosa",
                    "plata": "Plata",
                    "plateado": "Plata"
                }
                tono_real = tono_map.get(tono_palabra, tono_palabra.capitalize())
                try:
                    query = query.eq("Tono", tono_real)
                    criterios_aplicados = True
                    break
                except:
                    pass

        # Uso: Camisero, Sastre, Fantasía
        if "camisero" in pregunta_lower or "camisa" in pregunta_lower:
            try:
                query = query.eq("Uso", "Camisero")
                criterios_aplicados = True
            except:
                pass
        elif "sastre" in pregunta_lower or "pantalón" in pregunta_lower or "saco" in pregunta_lower:
            try:
                query = query.eq("Uso", "Sastre")
                criterios_aplicados = True
            except:
                pass
        elif "fantasía" in pregunta_lower or "vintage" in pregunta_lower or "decorativo" in pregunta_lower:
            try:
                query = query.eq("Uso", "Fantasía")
                criterios_aplicados = True
            except:
                pass

        # TAGS: Teñible, Básico, Formal, elegante, etc.
        if "teñible" in pregunta_lower or "teñir" in pregunta_lower or "tinte" in pregunta_lower:
            try:
                # Buscar en TAGS que contenga "Teñible"
                query = query.ilike("TAGS", "%Teñible%")
                criterios_aplicados = True
            except:
                pass

        if criterios_aplicados:
            try:
                res = query.limit(6).execute()
                if res.data:
                    return res.data
            except Exception as e:
                print(f"Error aplicando criterios: {e}")

        # =============== 4. BÚSQUEDA FUZZY POR PALABRAS CLAVE ===============
        # Última opción: buscar en Modelo, TAGS, etc. por similitud
        palabras = [p.strip().lower() for p in re.findall(r'\b\w{3,}\b', pregunta) 
                   if len(p) > 2 and p not in saludos and p not in ["del", "una", "para", "que", "los", "las", "por", "talla"]]
        
        for palabra in palabras[:2]:  # Máximo 2 palabras para no gastar tokens
            try:
                res_modelo = supabase.table("inventario_botones").select("*").ilike("Modelo", f"%{palabra}%").limit(4).execute()
                res_tags = supabase.table("inventario_botones").select("*").ilike("TAGS", f"%{palabra}%").limit(4).execute()
                
                if res_modelo.data:
                    return res_modelo.data[:6]
                if res_tags.data:
                    return res_tags.data[:6]
            except:
                pass

        return []

    except Exception as e:
        print(f"Error general en filtrado: {e}")
        return []


def consultar_ia(pregunta: str, inventario: list) -> str:
    """Envía a Haiku los datos filtrados para respuesta económica."""
    inv_str = str(inventario)

    prompt = f"""Eres "Botoncín" 🧵, el asistente de insumos textiles. Responde en español, breve (máximo 5 líneas), alegre y directo.

DATOS DISPONIBLES (USA SOLO ESTOS):
{inv_str}

Pregunta: "{pregunta}"

INSTRUCCIONES:
1. SALUDO: Si te saludan, di "¡Hola! Soy Botoncín 🧵 ¿Qué modelo buscas?". Si van directo, ve al grano.
2. SIN RESULTADOS: Si el inventario está vacío, di amablemente que no encontraste ese modelo exacto.
3. FORMATO DE RESPUESTA:
   • Modelo, Tamaño, Hoyos, Tono, Stock disponible
   • Si Stock < 500 pzs: avisa "Pocas unidades"
   • Si Stock = 0: muestra "Próxima llegada: [fecha]" si existe fecha_llegada
   • Si tiene Imagen, muestra el link
   • Usa emojis naturales, sin asteriscos dobles
4. CONVERSIÓN: 1 mazo = 1,728 pzs, 1 gruesa = 144 pzs. Si piden "3 mazos", calcula pzs necesarias vs stock
5. SMART TAGS: Si la búsqueda menciona "teñible" y los TAGS incluyen eso, resáltalo
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
    return "✅ Botoncín Ultra-Específico en Render", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
