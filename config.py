import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Reemplaza esta cadena con tu propia URI de MongoDB Atlas
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://USUARIO:PASSWORD@cluster0.mongodb.net/ysisi2027?retryWrites=true&w=majority")
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esta-clave-secreta-por-una-segura")
    DB_NAME = "ysisi2027"
    # Opcional: para el Asistente de IA (/asistente-ia) y la verificación de
    # identidad. Consigue tu clave en https://console.anthropic.com/
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    # Clave secreta para registrarse como administrador desde el propio sitio
    # (sin necesidad de tocar MongoDB). Cámbiala en tu .env antes de entregar
    # el proyecto, y compártela solo con quien deba ser admin.
    ADMIN_SIGNUP_CODE = os.environ.get("ADMIN_SIGNUP_CODE", "ysisi2027admin")
