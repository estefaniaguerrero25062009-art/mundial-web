import os
import re
import urllib.parse
from functools import wraps
from datetime import date, datetime

from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_pymongo import PyMongo
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename

from config import Config
import models as m
from ai_asistente import responder_pregunta_ia, construir_contexto, verificar_documento_identidad

app = Flask(__name__)
app.config.from_object(Config)
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

mongo = PyMongo(app)
db = mongo.db

bcrypt = Bcrypt(app)


@app.template_filter("avatar_url")
def avatar_url(nombre):
    """Genera un avatar con las iniciales del jugador (sin usar fotos reales)."""
    nombre_codificado = urllib.parse.quote(nombre or "?")
    return f"https://ui-avatars.com/api/?name={nombre_codificado}&background=15803d&color=ffffff&bold=true&size=128"


@app.template_filter("bandera_url")
def bandera_url(codigo_pais, tamano="w80"):
    """URL de la bandera del país usando flagcdn (gratuito, sin necesidad de API key)."""
    if not codigo_pais:
        return ""
    return f"https://flagcdn.com/{tamano}/{codigo_pais}.png"


CODIGOS_PAIS = {
    "Argentina": "ar", "Brasil": "br", "Francia": "fr", "Alemania": "de",
    "España": "es", "Inglaterra": "gb-eng", "México": "mx", "Estados Unidos": "us",
    "Italia": "it", "Portugal": "pt", "Países Bajos": "nl", "Bélgica": "be",
    "Croacia": "hr", "Uruguay": "uy", "Colombia": "co", "Chile": "cl",
    "Japón": "jp", "Corea del Sur": "kr", "Marruecos": "ma", "Senegal": "sn",
    "Nigeria": "ng", "Ghana": "gh", "Canadá": "ca", "Costa Rica": "cr",
    "Ecuador": "ec", "Perú": "pe", "Paraguay": "py", "Arabia Saudita": "sa",
    "Qatar": "qa", "Australia": "au", "Dinamarca": "dk", "Polonia": "pl",
}


@app.template_filter("bandera_por_nombre")
def bandera_por_nombre(nombre_equipo, tamano="w40"):
    """Igual que bandera_url, pero a partir del nombre del equipo (para listados de partidos)."""
    codigo = CODIGOS_PAIS.get(nombre_equipo)
    if not codigo:
        return ""
    return f"https://flagcdn.com/{tamano}/{codigo}.png"


COLORES_EQUIPO = {
    "ar": "#75AADB", "br": "#FFDF00", "fr": "#0055A4", "de": "#000000",
    "es": "#C60B1E", "gb-eng": "#4a4a4a", "mx": "#006847", "us": "#B22234",
    "it": "#0066CC", "pt": "#C8102E", "nl": "#FF7F00", "be": "#ED2939",
    "hr": "#FF0000", "uy": "#75AADB", "co": "#FCD116", "cl": "#D52B1E",
    "jp": "#003399", "kr": "#C60C30", "ma": "#C1272D", "sn": "#00853F",
    "ng": "#008751", "gh": "#CE1126", "ca": "#FF0000", "cr": "#002B7F",
    "ec": "#FFD100", "pe": "#D91023", "py": "#D52B1E", "sa": "#165D31",
    "qa": "#8D1B3D", "au": "#FFCD00", "dk": "#C60C30", "pl": "#DC143C",
}


@app.template_filter("color_equipo")
def color_equipo(codigo_pais):
    return COLORES_EQUIPO.get(codigo_pais, "#22c55e")


login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Debes iniciar sesión para continuar."


@login_manager.user_loader
def load_user(user_id):
    doc = m.obtener_usuario_por_id(db, user_id)
    if doc:
        return m.Usuario(doc)
    return None


def requiere_admin(vista):
    """Decorador: solo deja pasar a usuarios con es_admin=True."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            flash("No tienes permisos de administrador para entrar aquí.", "error")
            return redirect(url_for("inicio"))
        return vista(*args, **kwargs)
    return envoltura


# Páginas pensadas para aficionados (no para administradores): si una cuenta
# admin intenta entrar a alguna de estas por URL directa, se le regresa a su panel.
RUTAS_SOLO_AFICIONADO = {
    "equipos", "detalle_equipo", "jugadores", "partidos", "detalle_partido",
    "apuestas", "boletos", "tabla_goles", "asistente_ia", "noticias",
    "eliminatorias", "detalle_eliminatoria",
}


@app.before_request
def bloquear_admin_de_paginas_aficionado():
    if (current_user.is_authenticated and current_user.es_admin
            and request.endpoint in RUTAS_SOLO_AFICIONADO):
        flash("Tu cuenta es de administrador; esa sección es solo para usuarios normales.", "error")
        return redirect(url_for("admin_panel"))


# Rutas pensadas solo para usuarios normales: un administrador no debería
# navegar ahí (no aporta y mezcla roles), así que se le redirige al panel.
ENDPOINTS_SOLO_USUARIO = {
    "inicio", "equipos", "detalle_equipo", "jugadores", "partidos", "detalle_partido",
    "noticias", "eliminatorias", "detalle_eliminatoria", "tabla_goles", "asistente_ia",
    "apuestas", "boletos",
}


@app.before_request
def redirigir_admin_fuera_del_sitio_publico():
    if (current_user.is_authenticated and current_user.es_admin
            and request.endpoint in ENDPOINTS_SOLO_USUARIO):
        flash("Tu cuenta es de administrador: usa el panel de administración.", "error")
        return redirect(url_for("admin_panel"))


# ---------------------------------------------------------------------------
# AUTENTICACIÓN
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def inicio():
    if current_user.es_admin:
        return redirect(url_for("admin_panel"))
    partidos_destacados = m.listar_partidos(db)[:4]
    noticias = m.listar_noticias(db)[:5]
    return render_template("home.html", partidos=partidos_destacados, noticias=noticias)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_panel") if current_user.es_admin else url_for("inicio"))

    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        contrasena = request.form.get("contrasena", "")

        doc = m.obtener_usuario_por_correo(db, correo)
        if doc and bcrypt.check_password_hash(doc["contrasena"], contrasena):
            login_user(m.Usuario(doc))
            flash("Bienvenido de nuevo, " + doc.get("nombre", "") + ".", "success")
            if doc.get("es_admin"):
                return redirect(url_for("admin_panel"))
            return redirect(url_for("inicio"))

        flash("Correo o contraseña incorrectos.", "error")

    return render_template("login.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        correo = request.form.get("correo", "").strip().lower()
        contrasena = request.form.get("contrasena", "")
        confirmar = request.form.get("confirmar_contrasena", "")
        ciudad = request.form.get("ciudad", "").strip()
        edad_raw = request.form.get("edad", "0")
        archivo = request.files.get("comprobante_identidad")

        errores = []
        if not nombre or not correo or not contrasena:
            errores.append("Todos los campos obligatorios deben completarse.")
        if contrasena != confirmar:
            errores.append("Las contraseñas no coinciden.")
        if m.obtener_usuario_por_correo(db, correo):
            errores.append("Ya existe una cuenta registrada con ese correo.")
        try:
            edad = int(edad_raw)
        except ValueError:
            edad = 0
            errores.append("La edad debe ser un número válido.")

        # La ciudad debe ser texto (solo letras, espacios, acentos y guiones)
        patron_ciudad = re.compile(r"^[A-Za-zÀ-ÿ\s\.\-']{3,60}$")
        if not ciudad or not patron_ciudad.match(ciudad):
            errores.append("Escribe el nombre de una ciudad válida (solo letras, sin números ni símbolos).")

        # El comprobante de identidad debe ser JPG o PNG (así siempre se puede
        # verificar con IA que de verdad sea una identificación).
        EXTENSIONES_PERMITIDAS = {"png", "jpg", "jpeg"}
        MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
        extension = ""
        if not archivo or archivo.filename == "":
            errores.append("Debes subir tu identificación (INE, CURP o acta de nacimiento).")
        else:
            extension = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else ""
            if extension not in EXTENSIONES_PERMITIDAS:
                errores.append("El comprobante debe ser una FOTO de tu INE/CURP/acta en formato JPG o PNG (no se aceptan PDF ni otros documentos).")

        # Verificación con IA: confirma que la imagen realmente parezca una
        # identificación oficial, no cualquier foto/documento al azar.
        if not errores and extension in MEDIA_TYPES:
            bytes_archivo = archivo.read()
            archivo.seek(0)
            es_valido, motivo = verificar_documento_identidad(bytes_archivo, MEDIA_TYPES[extension])
            if es_valido is False:
                errores.append("La imagen que subiste no parece ser una identificación oficial (INE, CURP o acta de nacimiento). Sube el documento correcto.")

        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("registro.html")

        nombre_archivo = secure_filename(f"{correo}_{archivo.filename}")
        ruta_archivo = os.path.join(app.config["UPLOAD_FOLDER"], nombre_archivo)
        archivo.save(ruta_archivo)

        clave_admin = request.form.get("clave_admin", "").strip()
        es_admin = bool(clave_admin) and clave_admin == app.config.get("ADMIN_SIGNUP_CODE")

        hash_contrasena = bcrypt.generate_password_hash(contrasena).decode("utf-8")
        m.crear_usuario(db, nombre, correo, ciudad, hash_contrasena, nombre_archivo, edad, es_admin=es_admin)

        if es_admin:
            flash("Cuenta de administrador creada exitosamente. Ya puedes iniciar sesión.", "success")
        else:
            flash("Cuenta creada exitosamente. Ahora puedes iniciar sesión.", "success")
        return redirect(url_for("login"))

    return render_template("registro.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# EQUIPOS
# ---------------------------------------------------------------------------

@app.route("/equipos")
@login_required
def equipos():
    lista = m.listar_equipos(db)
    return render_template("equipos.html", equipos=lista)


@app.route("/equipos/<id_equipo>")
@login_required
def detalle_equipo(id_equipo):
    equipo = m.obtener_equipo(db, id_equipo)
    if not equipo:
        flash("Equipo no encontrado.", "error")
        return redirect(url_for("equipos"))
    jugadores = m.listar_jugadores_por_equipo(db, id_equipo)
    return render_template("detalle_equipo.html", equipo=equipo, jugadores=jugadores)


# ---------------------------------------------------------------------------
# JUGADORES
# ---------------------------------------------------------------------------

@app.route("/jugadores")
@login_required
def jugadores():
    filtro = request.args.get("q", "")
    lista = m.listar_jugadores(db, filtro)
    equipos_dict = {str(e["_id"]): e for e in m.listar_equipos(db)}
    for j in lista:
        equipo = equipos_dict.get(str(j.get("id_equipo")))
        j["nombre_equipo"] = equipo["nombre"] if equipo else "—"
        j["codigo_pais_equipo"] = equipo.get("codigo_pais") if equipo else None
    return render_template("jugadores.html", jugadores=lista)


# ---------------------------------------------------------------------------
# PARTIDOS
# ---------------------------------------------------------------------------

@app.route("/partidos")
@login_required
def partidos():
    estado = request.args.get("estado", "todos")
    lista = m.listar_partidos(db, estado)
    return render_template("partidos.html", partidos=lista, estado_actual=estado)


@app.route("/partidos/<id_partido>")
@login_required
def detalle_partido(id_partido):
    partido = m.obtener_partido(db, id_partido)
    if not partido:
        flash("Partido no encontrado.", "error")
        return redirect(url_for("partidos"))
    return render_template("detalle_partido.html", partido=partido)


@app.route("/partidos/<id_partido>/editar-horario", methods=["GET", "POST"])
@login_required
@requiere_admin
def editar_horario_partido(id_partido):
    partido = m.obtener_partido(db, id_partido)
    if not partido:
        flash("Partido no encontrado.", "error")
        return redirect(url_for("partidos"))

    if request.method == "POST":
        nueva_fecha = request.form.get("fecha", "").strip()
        if not nueva_fecha:
            flash("Escribe una fecha/hora válida.", "error")
        else:
            m.actualizar_horario_partido(db, id_partido, nueva_fecha)
            flash("Horario actualizado correctamente.", "success")
            return redirect(url_for("detalle_partido", id_partido=id_partido))

    return render_template("editar_horario.html", partido=partido)


# ---------------------------------------------------------------------------
# APUESTAS
# ---------------------------------------------------------------------------

CUOTA_APUESTA = 1.8  # multiplicador simple: si aciertas, ganas monto × esta cuota


@app.route("/apuestas", methods=["GET", "POST"])
@login_required
def apuestas():
    if not current_user.es_mayor_de_edad:
        flash("Debes ser mayor de edad para acceder a las apuestas.", "error")
        return redirect(url_for("inicio"))

    if request.method == "POST":
        id_partido = request.form.get("id_partido")
        prediccion = request.form.get("prediccion")
        monto_raw = request.form.get("monto", "0")

        try:
            monto = float(monto_raw)
        except ValueError:
            monto = 0

        if not id_partido or not prediccion or monto <= 0:
            flash("Completa todos los campos de la apuesta.", "error")
        else:
            m.crear_apuesta(db, current_user.get_id(), id_partido, prediccion, monto, CUOTA_APUESTA)
            ganancia = round(monto * CUOTA_APUESTA, 2)
            flash(f"¡Apuesta registrada! Si aciertas, ganarías ${ganancia:.2f} (cuota {CUOTA_APUESTA}x). Revisa el resultado en tu historial una vez que termine el partido.", "success")

    lista_partidos = m.listar_partidos(db, "proximos")
    m.resolver_apuestas_pendientes(db)
    mis_apuestas = m.listar_apuestas_usuario(db, current_user.get_id())
    return render_template("apuestas.html", partidos=lista_partidos, apuestas=mis_apuestas, cuota=CUOTA_APUESTA)


# ---------------------------------------------------------------------------
# BOLETOS
# ---------------------------------------------------------------------------

PRECIOS_BOLETO = {
    "general": 500,
    "preferente": 900,
    "vip": 1800,
}


@app.route("/boletos", methods=["GET", "POST"])
@login_required
def boletos():
    if request.method == "POST":
        id_partido = request.form.get("id_partido")
        tipo_boleto = request.form.get("tipo_boleto")
        cantidad_raw = request.form.get("cantidad", "1")

        try:
            cantidad = max(1, int(cantidad_raw))
        except ValueError:
            cantidad = 1

        precio_unitario = PRECIOS_BOLETO.get(tipo_boleto, 0)

        if not id_partido or tipo_boleto not in PRECIOS_BOLETO:
            flash("Selecciona un partido y un tipo de boleto válidos.", "error")
        else:
            m.crear_boleto(db, current_user.get_id(), id_partido, tipo_boleto, cantidad, precio_unitario)
            flash("¡Boleto(s) comprado(s) con éxito! Revisa tu historial abajo.", "success")

    lista_partidos = m.listar_partidos(db, "proximos")
    mis_boletos = m.listar_boletos_usuario(db, current_user.get_id())
    partidos_dict = {str(p["_id"]): p for p in m.listar_partidos(db)}
    for b in mis_boletos:
        b["partido"] = partidos_dict.get(str(b.get("id_partido")))

    return render_template(
        "boletos.html",
        partidos=lista_partidos,
        boletos=mis_boletos,
        precios=PRECIOS_BOLETO,
    )


# ---------------------------------------------------------------------------
# TABLA DE GOLES
# ---------------------------------------------------------------------------

@app.route("/tabla-goles")
@login_required
def tabla_goles():
    goleadores = m.tabla_goleadores(db)
    return render_template("tabla_goles.html", goleadores=goleadores)


# ---------------------------------------------------------------------------
# ASISTENTE DE IA
# ---------------------------------------------------------------------------

@app.route("/asistente-ia", methods=["GET", "POST"])
@login_required
def asistente_ia():
    respuesta = None
    pregunta = ""

    if request.method == "POST":
        pregunta = request.form.get("pregunta", "").strip()
        if pregunta:
            contexto = construir_contexto(db)
            respuesta = responder_pregunta_ia(pregunta, contexto)
        else:
            flash("Escribe una pregunta para el asistente.", "error")

    return render_template("asistente_ia.html", respuesta=respuesta, pregunta=pregunta)


# ---------------------------------------------------------------------------
# NOTICIAS
# ---------------------------------------------------------------------------

@app.route("/noticias")
@login_required
def noticias():
    categoria = request.args.get("categoria", "todas")
    lista = m.listar_noticias(db, categoria)
    return render_template("noticias.html", noticias=lista, categoria_actual=categoria)


# ---------------------------------------------------------------------------
# ELIMINATORIAS
# ---------------------------------------------------------------------------

@app.route("/eliminatorias")
@login_required
def eliminatorias():
    lista = m.listar_eliminatorias(db)
    return render_template("eliminatorias.html", eliminatorias=lista)


@app.route("/eliminatorias/<id_eliminatoria>")
@login_required
def detalle_eliminatoria(id_eliminatoria):
    eliminatoria = m.obtener_eliminatoria(db, id_eliminatoria)
    if not eliminatoria:
        flash("Eliminatoria no encontrada.", "error")
        return redirect(url_for("eliminatorias"))
    return render_template("detalle_eliminatoria.html", eliminatoria=eliminatoria)


# ---------------------------------------------------------------------------
# ADMINISTRACIÓN (solo usuarios con es_admin=True)
# ---------------------------------------------------------------------------

@app.route("/admin")
@login_required
@requiere_admin
def admin_panel():
    return render_template("admin_panel.html")


@app.route("/admin/partidos")
@login_required
@requiere_admin
def admin_partidos():
    lista_partidos = m.listar_partidos(db)
    return render_template("admin_partidos.html", partidos=lista_partidos)


@app.route("/admin/partidos/<id_partido>/resultado", methods=["POST"])
@login_required
@requiere_admin
def admin_actualizar_resultado(id_partido):
    try:
        goles_local = int(request.form.get("goles_local", 0))
        goles_visitante = int(request.form.get("goles_visitante", 0))
    except ValueError:
        flash("Los goles deben ser números.", "error")
        return redirect(url_for("admin_partidos"))

    m.actualizar_resultado_partido(db, id_partido, goles_local, goles_visitante)
    flash("Resultado guardado. Las apuestas de ese partido ya se resolvieron automáticamente.", "success")
    return redirect(url_for("admin_partidos"))


@app.route("/admin/usuarios")
@login_required
@requiere_admin
def admin_usuarios():
    lista_usuarios = m.listar_usuarios(db)
    return render_template("admin_usuarios.html", usuarios=lista_usuarios)


@app.route("/admin/usuarios/<id_usuario>/verificar", methods=["POST"])
@login_required
@requiere_admin
def admin_verificar_usuario(id_usuario):
    nuevo_estado = request.form.get("verificado") == "1"
    m.marcar_usuario_verificado(db, id_usuario, nuevo_estado)
    flash("Estado de verificación actualizado.", "success")
    return redirect(url_for("admin_usuarios"))


ICONOS_NOTICIA = ["jersey", "calendario", "gol", "entrevista", "lesion", "plantilla", "estrella", "general"]
CATEGORIAS_NOTICIA = ["destacadas", "fichajes", "entrevistas", "general"]


@app.route("/admin/noticias")
@login_required
@requiere_admin
def admin_noticias():
    lista_noticias = m.listar_noticias(db)
    return render_template("admin_noticias.html", noticias=lista_noticias)


@app.route("/admin/noticias/nueva", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_nueva_noticia():
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        contenido = request.form.get("contenido", "").strip()
        fecha = request.form.get("fecha", "").strip()
        categoria = request.form.get("categoria", "general")
        icono = request.form.get("icono", "general")

        if not titulo or not contenido or not fecha:
            flash("Completa todos los campos.", "error")
        else:
            m.crear_noticia(db, titulo, contenido, fecha, categoria, icono)
            flash("Noticia creada correctamente.", "success")
            return redirect(url_for("admin_noticias"))

    return render_template("admin_noticia_form.html", noticia=None,
                            iconos=ICONOS_NOTICIA, categorias=CATEGORIAS_NOTICIA)


@app.route("/admin/noticias/<id_noticia>/editar", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_editar_noticia(id_noticia):
    noticia = m.obtener_noticia(db, id_noticia)
    if not noticia:
        flash("Noticia no encontrada.", "error")
        return redirect(url_for("admin_noticias"))

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        contenido = request.form.get("contenido", "").strip()
        fecha = request.form.get("fecha", "").strip()
        categoria = request.form.get("categoria", "general")
        icono = request.form.get("icono", "general")

        if not titulo or not contenido or not fecha:
            flash("Completa todos los campos.", "error")
        else:
            m.actualizar_noticia(db, id_noticia, titulo, contenido, fecha, categoria, icono)
            flash("Noticia actualizada correctamente.", "success")
            return redirect(url_for("admin_noticias"))

    return render_template("admin_noticia_form.html", noticia=noticia,
                            iconos=ICONOS_NOTICIA, categorias=CATEGORIAS_NOTICIA)


@app.route("/admin/noticias/<id_noticia>/eliminar", methods=["POST"])
@login_required
@requiere_admin
def admin_eliminar_noticia(id_noticia):
    m.eliminar_noticia(db, id_noticia)
    flash("Noticia eliminada.", "success")
    return redirect(url_for("admin_noticias"))


@app.route("/admin/usuarios/<id_usuario>/rol", methods=["POST"])
@login_required
@requiere_admin
def admin_cambiar_rol(id_usuario):
    if id_usuario == current_user.get_id():
        flash("No puedes quitarte el rol de administrador a ti mismo.", "error")
        return redirect(url_for("admin_usuarios"))
    nuevo_estado = request.form.get("es_admin") == "1"
    m.cambiar_rol_admin(db, id_usuario, nuevo_estado)
    flash("Admin asignado correctamente." if nuevo_estado else "Se quitaron los permisos de administrador.", "success")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<id_usuario>/eliminar", methods=["POST"])
@login_required
@requiere_admin
def admin_eliminar_usuario(id_usuario):
    if id_usuario == current_user.get_id():
        flash("No puedes eliminar tu propia cuenta de administrador.", "error")
    else:
        m.eliminar_usuario(db, id_usuario)
        flash("Usuario eliminado.", "success")
    return redirect(url_for("admin_usuarios"))


# ---------------------------------------------------------------------------
# ADMIN: EQUIPOS (CRUD completo)
# ---------------------------------------------------------------------------

@app.route("/admin/equipos")
@login_required
@requiere_admin
def admin_equipos():
    lista_equipos = m.listar_equipos(db)
    return render_template("admin_equipos.html", equipos=lista_equipos)


def _leer_formulario_equipo():
    return {
        "nombre": request.form.get("nombre", "").strip(),
        "codigo_pais": request.form.get("codigo_pais", "").strip().lower(),
        "origen": request.form.get("origen", "").strip(),
        "estadio": request.form.get("estadio", "").strip(),
        "apodo": request.form.get("apodo", "").strip(),
        "confederacion": request.form.get("confederacion", "").strip(),
        "titulos_mundiales": int(request.form.get("titulos_mundiales", 0) or 0),
        "mejor_resultado": request.form.get("mejor_resultado", "").strip(),
        "historia": request.form.get("historia", "").strip(),
        "bandera": "🏳️",
    }


@app.route("/admin/equipos/nuevo", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_nuevo_equipo():
    if request.method == "POST":
        datos = _leer_formulario_equipo()
        if not datos["nombre"] or not datos["codigo_pais"]:
            flash("El nombre y el código de país son obligatorios.", "error")
        else:
            m.crear_equipo(db, datos)
            flash("Equipo creado correctamente.", "success")
            return redirect(url_for("admin_equipos"))
    return render_template("admin_equipo_form.html", equipo=None)


@app.route("/admin/equipos/<id_equipo>/editar", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_editar_equipo(id_equipo):
    equipo = m.obtener_equipo(db, id_equipo)
    if not equipo:
        flash("Equipo no encontrado.", "error")
        return redirect(url_for("admin_equipos"))

    if request.method == "POST":
        datos = _leer_formulario_equipo()
        if not datos["nombre"] or not datos["codigo_pais"]:
            flash("El nombre y el código de país son obligatorios.", "error")
        else:
            m.actualizar_equipo(db, id_equipo, datos)
            flash("Equipo actualizado correctamente.", "success")
            return redirect(url_for("admin_equipos"))

    return render_template("admin_equipo_form.html", equipo=equipo)


@app.route("/admin/equipos/<id_equipo>/eliminar", methods=["POST"])
@login_required
@requiere_admin
def admin_eliminar_equipo(id_equipo):
    m.eliminar_equipo(db, id_equipo)
    flash("Equipo y sus jugadores eliminados.", "success")
    return redirect(url_for("admin_equipos"))


# ---------------------------------------------------------------------------
# ADMIN: JUGADORES (CRUD completo)
# ---------------------------------------------------------------------------

@app.route("/admin/jugadores")
@login_required
@requiere_admin
def admin_jugadores():
    lista_jugadores = m.listar_jugadores(db)
    equipos_dict = {str(e["_id"]): e["nombre"] for e in m.listar_equipos(db)}
    for j in lista_jugadores:
        j["nombre_equipo"] = equipos_dict.get(str(j.get("id_equipo")), "—")
    return render_template("admin_jugadores.html", jugadores=lista_jugadores)


def _leer_formulario_jugador():
    return {
        "nombre": request.form.get("nombre", "").strip(),
        "posicion": request.form.get("posicion", "").strip(),
        "numero": int(request.form.get("numero", 0) or 0),
        "id_equipo": request.form.get("id_equipo", ""),
        "goles": int(request.form.get("goles", 0) or 0),
        "dato": request.form.get("dato", "").strip(),
    }


@app.route("/admin/jugadores/nuevo", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_nuevo_jugador():
    if request.method == "POST":
        datos = _leer_formulario_jugador()
        if not datos["nombre"] or not datos["id_equipo"]:
            flash("El nombre y el equipo son obligatorios.", "error")
        else:
            m.crear_jugador(db, datos)
            flash("Jugador creado correctamente.", "success")
            return redirect(url_for("admin_jugadores"))
    equipos = m.listar_equipos(db)
    return render_template("admin_jugador_form.html", jugador=None, equipos=equipos)


@app.route("/admin/jugadores/<id_jugador>/editar", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_editar_jugador(id_jugador):
    jugador = m.obtener_jugador(db, id_jugador)
    if not jugador:
        flash("Jugador no encontrado.", "error")
        return redirect(url_for("admin_jugadores"))

    if request.method == "POST":
        datos = _leer_formulario_jugador()
        if not datos["nombre"] or not datos["id_equipo"]:
            flash("El nombre y el equipo son obligatorios.", "error")
        else:
            m.actualizar_jugador(db, id_jugador, datos)
            flash("Jugador actualizado correctamente.", "success")
            return redirect(url_for("admin_jugadores"))

    equipos = m.listar_equipos(db)
    return render_template("admin_jugador_form.html", jugador=jugador, equipos=equipos)


@app.route("/admin/jugadores/<id_jugador>/eliminar", methods=["POST"])
@login_required
@requiere_admin
def admin_eliminar_jugador(id_jugador):
    m.eliminar_jugador(db, id_jugador)
    flash("Jugador eliminado.", "success")
    return redirect(url_for("admin_jugadores"))


# ---------------------------------------------------------------------------
# ADMIN: PARTIDOS (crear y eliminar, además de editar horario/resultado)
# ---------------------------------------------------------------------------

@app.route("/admin/partidos/nuevo", methods=["GET", "POST"])
@login_required
@requiere_admin
def admin_nuevo_partido():
    if request.method == "POST":
        datos = {
            "equipo_local": request.form.get("equipo_local", "").strip(),
            "equipo_visitante": request.form.get("equipo_visitante", "").strip(),
            "fecha": request.form.get("fecha", "").strip(),
            "estadio": request.form.get("estadio", "").strip(),
            "pais_sede": request.form.get("pais_sede", "").strip(),
            "canal_transmision": request.form.get("canal_transmision", "").strip(),
            "canal_color": "#3b82f6",
        }
        if not datos["equipo_local"] or not datos["equipo_visitante"] or not datos["fecha"]:
            flash("Equipo local, visitante y fecha son obligatorios.", "error")
        else:
            m.crear_partido(db, datos)
            flash("Partido creado correctamente.", "success")
            return redirect(url_for("admin_partidos"))
    equipos = m.listar_equipos(db)
    return render_template("admin_partido_form.html", equipos=equipos)


@app.route("/admin/partidos/<id_partido>/eliminar", methods=["POST"])
@login_required
@requiere_admin
def admin_eliminar_partido(id_partido):
    m.eliminar_partido(db, id_partido)
    flash("Partido eliminado (junto con sus apuestas y boletos relacionados).", "success")
    return redirect(url_for("admin_partidos"))


# ---------------------------------------------------------------------------
# ADMIN: BOLETOS (estadísticas de ventas)
# ---------------------------------------------------------------------------

@app.route("/admin/boletos")
@login_required
@requiere_admin
def admin_boletos():
    estadisticas = m.estadisticas_boletos(db)
    lista_boletos = m.listar_todos_boletos(db)
    partidos_dict = {str(p["_id"]): p for p in m.listar_partidos(db)}
    for b in lista_boletos:
        b["partido"] = partidos_dict.get(str(b.get("id_partido")))
    return render_template("admin_boletos.html", stats=estadisticas, boletos=lista_boletos)


# ---------------------------------------------------------------------------
# ADMIN: APUESTAS (editar resultado manualmente)
# ---------------------------------------------------------------------------

@app.route("/admin/apuestas")
@login_required
@requiere_admin
def admin_apuestas():
    lista_apuestas = m.listar_todas_apuestas(db)
    partidos_dict = {str(p["_id"]): p for p in m.listar_partidos(db)}
    usuarios_dict = {str(u["_id"]): u["nombre"] for u in m.listar_usuarios(db)}
    for a in lista_apuestas:
        a["partido"] = partidos_dict.get(str(a.get("id_partido")))
        a["nombre_usuario"] = usuarios_dict.get(str(a.get("id_usuario")), "—")
    return render_template("admin_apuestas.html", apuestas=lista_apuestas)


@app.route("/admin/apuestas/<id_apuesta>/resultado", methods=["POST"])
@login_required
@requiere_admin
def admin_actualizar_resultado_apuesta(id_apuesta):
    nuevo_resultado = request.form.get("resultado", "pendiente")
    if nuevo_resultado not in ("pendiente", "ganada", "perdida"):
        flash("Resultado inválido.", "error")
    else:
        m.actualizar_resultado_apuesta(db, id_apuesta, nuevo_resultado)
        flash("Resultado de la apuesta actualizado.", "success")
    return redirect(url_for("admin_apuestas"))


if __name__ == "__main__":
    modo_debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=modo_debug)
