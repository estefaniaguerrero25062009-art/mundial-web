# ¿Y si, si? 2027 — Sitio Web Deportivo

Proyecto escolar: sitio web de una copa de fútbol internacional (32 equipos),
construido con **Flask** y **MongoDB Atlas**.

## 1. Requisitos
- Python 3.12 (evita 3.14, da problemas de SSL con MongoDB en Windows)
- Cuenta de MongoDB Atlas

## 2. Instalación

```bash
cd ysisi2027
python -m pip install -r requirements.txt
```

## 3. Configuración

```bash
copy .env.example .env
```

Edita `.env` y pega tu cadena de conexión real de MongoDB Atlas, tu `SECRET_KEY`,
y opcionalmente tu `ANTHROPIC_API_KEY` (para el Asistente de IA y la verificación
de identidad).

## 4. Cargar datos de ejemplo

```bash
python seed_data.py
```

Carga los 32 equipos (con 13 jugadores cada uno: 5 estrellas reales confirmadas +
8 más también con nombres reales), partidos de fase de grupos con fechas relativas
a HOY, noticias con íconos temáticos, y los 8 grupos + fase eliminatoria.

## 5. Ejecutar

```bash
python app.py
```

Abre **http://127.0.0.1:5000**

## 6. Rol de administrador

Todo se hace desde el propio sitio, con una clave secreta de registro:

1. En tu `.env`, define `ADMIN_SIGNUP_CODE=tu_clave_secreta` (cámbiala del
   valor de ejemplo antes de entregar el proyecto).
2. Ve a `/registro` y completa el formulario normal, pero en el campo
   opcional **"Clave de administrador"** escribe esa misma clave.
3. Esa cuenta se crea automáticamente con permisos de administrador.
4. Desde ahí, ese administrador puede ascender a cualquier otro usuario
   registrado con el botón **"Hacer admin"** en `/admin/usuarios` — ya no
   hace falta volver a usar la clave ni tocar MongoDB para nada.

El panel de administrador (`/admin`) permite:
- **Equipos** — crear, editar y eliminar
- **Jugadores** — crear, editar y eliminar
- **Partidos** — crear, capturar marcador final (resuelve apuestas automáticamente), editar horario y eliminar
- **Noticias** — crear, editar y eliminar
- **Usuarios** — verificar identidad, ascender/quitar administrador, y eliminar cuentas
- **Boletos** — estadísticas de ventas (total vendido, ganancias, desglose por tipo)
- **Apuestas** — editar manualmente si una apuesta fue ganada, perdida o sigue pendiente

## 7. Asistente de IA y verificación de identidad (opcional)

Si agregas `ANTHROPIC_API_KEY` en tu `.env`:
- El Asistente de IA (`/asistente-ia`) responde preguntas reales sobre el torneo.
- El registro verifica con IA que la imagen subida (JPG/PNG) realmente
  parezca una identificación oficial (INE, CURP o acta), no cualquier archivo.

Sin la clave, el sitio funciona igual, solo esas dos funciones muestran un
aviso de que falta configurar la clave.

## 8. Subir a producción (Render)

1. Sube el proyecto a GitHub (sin subir `.env` — ya está en `.gitignore`).
2. En Render.com: New → Web Service → conecta tu repo.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app` (ya está en el `Procfile`)
5. Agrega tus variables de entorno (`MONGO_URI`, `SECRET_KEY`, `ANTHROPIC_API_KEY`).
6. En MongoDB Atlas → Network Access, agrega `0.0.0.0/0` (Render no tiene IP fija).

**Nota:** el plan gratis de Render borra archivos subidos (`static/uploads/`)
al reiniciarse, ya que su almacenamiento es temporal.
