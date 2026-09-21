from flask_login import UserMixin
from bson.objectid import ObjectId
from datetime import datetime


class Usuario(UserMixin):
    """Representa al documento de la colección 'usuarios' para Flask-Login."""

    def __init__(self, doc):
        self.doc = doc

    def get_id(self):
        return str(self.doc["_id"])

    @property
    def nombre(self):
        return self.doc.get("nombre")

    @property
    def correo(self):
        return self.doc.get("correo")

    @property
    def edad(self):
        return self.doc.get("edad", 0)

    @property
    def es_mayor_de_edad(self):
        return self.edad >= 18

    @property
    def es_admin(self):
        return bool(self.doc.get("es_admin", False))

    @property
    def verificado(self):
        return bool(self.doc.get("verificado", False))


# ---------- Helpers genéricos ----------

def to_object_id(id_str):
    try:
        return ObjectId(id_str)
    except Exception:
        return None


def documento_a_dict(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


# ---------- Operaciones sobre USUARIO ----------

def crear_usuario(db, nombre, correo, ciudad, contrasena_hash, comprobante_identidad, edad):
    usuario = {
        "nombre": nombre,
        "correo": correo,
        "ciudad": ciudad,
        "contrasena": contrasena_hash,
        "comprobante_identidad": comprobante_identidad,
        "edad": edad,
        "es_admin": False,
        "verificado": False,
        "fecha_registro": datetime.utcnow(),
    }
    resultado = db.usuarios.insert_one(usuario)
    return resultado.inserted_id


def listar_usuarios(db):
    return list(db.usuarios.find().sort("fecha_registro", -1))


def marcar_usuario_verificado(db, id_usuario, verificado=True):
    oid = to_object_id(id_usuario)
    if not oid:
        return False
    resultado = db.usuarios.update_one({"_id": oid}, {"$set": {"verificado": verificado}})
    return resultado.modified_count > 0


def obtener_usuario_por_correo(db, correo):
    return db.usuarios.find_one({"correo": correo})


def obtener_usuario_por_id(db, id_usuario):
    oid = to_object_id(id_usuario)
    if not oid:
        return None
    return db.usuarios.find_one({"_id": oid})


# ---------- Operaciones sobre EQUIPO ----------

def listar_equipos(db):
    return list(db.equipos.find())


def obtener_equipo(db, id_equipo):
    oid = to_object_id(id_equipo)
    if not oid:
        return None
    return db.equipos.find_one({"_id": oid})


def listar_jugadores_por_equipo(db, id_equipo):
    oid = to_object_id(id_equipo)
    if not oid:
        return []
    return list(db.jugadores.find({"id_equipo": oid}))


# ---------- Operaciones sobre JUGADOR ----------

def listar_jugadores(db, filtro=None):
    query = {}
    if filtro:
        query = {"nombre": {"$regex": filtro, "$options": "i"}}
    return list(db.jugadores.find(query))


def tabla_goleadores(db, limite=15):
    """Devuelve los jugadores ordenados por goles descendente, con el nombre y bandera de su equipo."""
    equipos_dict = {str(e["_id"]): e for e in listar_equipos(db)}
    jugadores_lista = list(db.jugadores.find({"goles": {"$exists": True}}).sort("goles", -1).limit(limite))
    for j in jugadores_lista:
        equipo = equipos_dict.get(str(j.get("id_equipo")))
        j["nombre_equipo"] = equipo["nombre"] if equipo else "—"
        j["codigo_pais_equipo"] = equipo.get("codigo_pais") if equipo else None
    return jugadores_lista


# ---------- Operaciones sobre PARTIDO ----------

def listar_partidos(db, estado=None):
    query = {}
    if estado and estado != "todos":
        query["estado"] = estado
    return list(db.partidos.find(query).sort("fecha", 1))


def obtener_partido(db, id_partido):
    oid = to_object_id(id_partido)
    if not oid:
        return None
    return db.partidos.find_one({"_id": oid})


def actualizar_horario_partido(db, id_partido, nueva_fecha):
    oid = to_object_id(id_partido)
    if not oid:
        return False
    resultado = db.partidos.update_one({"_id": oid}, {"$set": {"fecha": nueva_fecha}})
    return resultado.modified_count > 0


def actualizar_resultado_partido(db, id_partido, goles_local, goles_visitante):
    """El admin marca el marcador final de un partido; lo deja como 'finalizados'."""
    oid = to_object_id(id_partido)
    if not oid:
        return False
    db.partidos.update_one(
        {"_id": oid},
        {"$set": {"goles_local": goles_local, "goles_visitante": goles_visitante, "estado": "finalizados"}},
    )
    resolver_apuestas_partido(db, id_partido)
    return True


def resolver_apuestas_partido(db, id_partido):
    """Revisa las apuestas 'pendiente' de un partido ya finalizado y marca Ganada/Perdida."""
    partido = obtener_partido(db, id_partido)
    if not partido or partido.get("estado") != "finalizados":
        return 0

    if partido["goles_local"] > partido["goles_visitante"]:
        resultado_real = "local"
    elif partido["goles_local"] < partido["goles_visitante"]:
        resultado_real = "visitante"
    else:
        resultado_real = "empate"

    oid = to_object_id(id_partido)
    apuestas_pendientes = db.apuestas.find({"id_partido": oid, "resultado": "pendiente"})
    actualizadas = 0
    for apuesta in apuestas_pendientes:
        gano = apuesta["prediccion"] == resultado_real
        db.apuestas.update_one(
            {"_id": apuesta["_id"]},
            {"$set": {"resultado": "ganada" if gano else "perdida", "es_ganador": gano}},
        )
        actualizadas += 1
    return actualizadas


def resolver_apuestas_pendientes(db):
    """Recorre todos los partidos finalizados y resuelve cualquier apuesta que siga en pendiente."""
    partidos_finalizados = db.partidos.find({"estado": "finalizados"})
    for partido in partidos_finalizados:
        resolver_apuestas_partido(db, str(partido["_id"]))


# ---------- Operaciones sobre APUESTA ----------

def crear_apuesta(db, id_usuario, id_partido, prediccion, monto, cuota=1.8):
    apuesta = {
        "id_usuario": to_object_id(id_usuario),
        "id_partido": to_object_id(id_partido),
        "prediccion": prediccion,
        "monto": monto,
        "cuota": cuota,
        "ganancia_potencial": round(monto * cuota, 2),
        "resultado": "pendiente",
        "es_ganador": None,
        "fecha": datetime.utcnow(),
    }
    resultado = db.apuestas.insert_one(apuesta)
    return resultado.inserted_id


def listar_apuestas_usuario(db, id_usuario):
    oid = to_object_id(id_usuario)
    if not oid:
        return []
    return list(db.apuestas.find({"id_usuario": oid}).sort("fecha", -1))


# ---------- Operaciones sobre BOLETO ----------

def generar_folio():
    import uuid
    return "YSS-" + uuid.uuid4().hex[:8].upper()


def crear_boleto(db, id_usuario, id_partido, tipo_boleto, cantidad, precio_unitario):
    boleto = {
        "id_usuario": to_object_id(id_usuario),
        "id_partido": to_object_id(id_partido),
        "tipo_boleto": tipo_boleto,
        "cantidad": cantidad,
        "precio_unitario": precio_unitario,
        "total": round(cantidad * precio_unitario, 2),
        "folio": generar_folio(),
        "fecha_compra": datetime.utcnow(),
    }
    resultado = db.boletos.insert_one(boleto)
    return resultado.inserted_id


def listar_boletos_usuario(db, id_usuario):
    oid = to_object_id(id_usuario)
    if not oid:
        return []
    return list(db.boletos.find({"id_usuario": oid}).sort("fecha_compra", -1))


# ---------- Operaciones sobre NOTICIA ----------

def listar_noticias(db, categoria=None):
    query = {}
    if categoria and categoria != "todas":
        query["categoria"] = categoria
    return list(db.noticias.find(query).sort("fecha", -1))


def obtener_noticia(db, id_noticia):
    oid = to_object_id(id_noticia)
    if not oid:
        return None
    return db.noticias.find_one({"_id": oid})


def crear_noticia(db, titulo, contenido, fecha, categoria, icono):
    noticia = {
        "titulo": titulo,
        "contenido": contenido,
        "fecha": fecha,
        "categoria": categoria,
        "icono": icono,
    }
    resultado = db.noticias.insert_one(noticia)
    return resultado.inserted_id


def actualizar_noticia(db, id_noticia, titulo, contenido, fecha, categoria, icono):
    oid = to_object_id(id_noticia)
    if not oid:
        return False
    db.noticias.update_one(
        {"_id": oid},
        {"$set": {"titulo": titulo, "contenido": contenido, "fecha": fecha, "categoria": categoria, "icono": icono}},
    )
    return True


# ---------- Operaciones sobre ELIMINATORIA ----------

def listar_eliminatorias(db):
    return list(db.eliminatorias.find())


def obtener_eliminatoria(db, id_eliminatoria):
    oid = to_object_id(id_eliminatoria)
    if not oid:
        return None
    return db.eliminatorias.find_one({"_id": oid})
