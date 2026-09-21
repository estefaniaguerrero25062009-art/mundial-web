"""
Integración con la API de IA (Anthropic Claude) para el proyecto ¿Y si, si? 2027.

Dos usos:
1. Asistente conversacional: el usuario hace una pregunta sobre el torneo y la IA
   responde usando el contexto de equipos/partidos de nuestra propia base de datos.
2. Verificación de identidad: cuando alguien se registra, la IA revisa la imagen
   subida y confirma si de verdad parece una identificación oficial (INE, CURP,
   acta de nacimiento) antes de aceptar el registro.

Requiere una variable de entorno ANTHROPIC_API_KEY en tu archivo .env.
Consigue una clave gratuita/de prueba en https://console.anthropic.com/
Si no hay clave configurada, ambas funciones avisan cómo activarla en vez de fallar,
y el registro cae de vuelta a la validación básica por formato de archivo.
"""
import os
import base64

try:
    import anthropic
    ANTHROPIC_DISPONIBLE = True
except ImportError:
    ANTHROPIC_DISPONIBLE = False


def _cliente():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not ANTHROPIC_DISPONIBLE or not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def responder_pregunta_ia(pregunta, contexto=""):
    client = _cliente()

    if not ANTHROPIC_DISPONIBLE:
        return ("La librería 'anthropic' no está instalada. Corre: "
                "pip install anthropic")

    if not client:
        return ("Para usar el asistente de IA, agrega tu clave en el archivo .env: "
                "ANTHROPIC_API_KEY=tu_clave_aqui\n"
                "Puedes obtener una en https://console.anthropic.com/")

    try:
        mensaje_sistema = (
            "Eres el asistente virtual del sitio deportivo '¿Y si, si? 2027', "
            "un torneo internacional de fútbol ficticio para un proyecto escolar. "
            "Responde de forma breve, amigable y en español, usando el contexto "
            "proporcionado sobre equipos y partidos cuando sea relevante."
        )
        prompt_completo = pregunta
        if contexto:
            prompt_completo = f"Contexto disponible:\n{contexto}\n\nPregunta del usuario: {pregunta}"

        respuesta = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            system=mensaje_sistema,
            messages=[{"role": "user", "content": prompt_completo}],
        )
        return respuesta.content[0].text
    except Exception as e:
        return f"Ocurrió un error al consultar la IA: {e}"


def construir_contexto(db):
    """Arma un resumen corto de equipos y próximos partidos para dar contexto a la IA."""
    import models as m
    equipos = m.listar_equipos(db)
    partidos = m.listar_partidos(db)[:5]

    lineas = ["Equipos participantes: " + ", ".join(e["nombre"] for e in equipos)]
    if partidos:
        lineas.append("Próximos partidos:")
        for p in partidos:
            lineas.append(f"- {p['equipo_local']} vs {p['equipo_visitante']} ({p['fecha']})")
    return "\n".join(lineas)


def verificar_documento_identidad(bytes_archivo, media_type):
    """
    Usa Claude (visión) para revisar si la imagen subida parece una identificación
    oficial (INE, CURP o acta de nacimiento).

    Regresa (es_valido, mensaje):
      - es_valido=True  -> parece un documento de identidad, se puede aceptar
      - es_valido=False -> NO parece un documento de identidad, se debe rechazar
      - Si no hay clave de IA configurada, regresa (None, mensaje) para indicar
        que no se pudo verificar y se debe caer de vuelta a la validación básica.
    """
    client = _cliente()
    if not client:
        return None, "Verificación por IA no configurada (sin ANTHROPIC_API_KEY)."

    if media_type not in ("image/jpeg", "image/png"):
        return None, "Solo se puede verificar por IA en formato JPG o PNG."

    try:
        imagen_b64 = base64.b64encode(bytes_archivo).decode("utf-8")
        respuesta = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": imagen_b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "¿Esta imagen es una identificación oficial mexicana (INE/credencial "
                            "para votar), una CURP, o un acta de nacimiento? Responde ÚNICAMENTE "
                            "con la palabra SI o NO, sin explicación adicional."
                        ),
                    },
                ],
            }],
        )
        texto = respuesta.content[0].text.strip().upper()
        es_valido = texto.startswith("SI") or texto.startswith("SÍ")
        return es_valido, None
    except Exception as e:
        return None, f"No se pudo verificar el documento con IA: {e}"
