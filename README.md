# PRISM ETL/EDA Assistant — Prototipo v1.2

## Si te salió "500 FUNCTION_INVOCATION_FAILED" en Vercel

Encontré la causa probable: Vercel cambió su forma de desplegar apps Python/FastAPI —
ya no usa el `vercel.json` viejo con `builds`/`routes`, y su propia documentación dice
explícitamente que `app.mount("/public", StaticFiles(...))` **no hace falta** en Vercel
(hay que usar una carpeta `public/` servida por su CDN en su lugar). Si el mount a la
carpeta del frontend fallaba por lo que sea en el entorno de Vercel, esa falla ocurría
al importar el módulo — es decir, tumbaba la función ENTERA en cada request, no solo "/".
Eso explica un 500 genérico en cualquier página.

Corregido en esta versión:
- `pyproject.toml` en la raíz con `[tool.vercel] entrypoint = "backend.app.main:app"`
  (zero-config actual de Vercel, en vez del `vercel.json` con `builds` legacy).
- El frontend ahora también vive en `public/index.html` en la raíz — Vercel lo sirve
  directo desde su CDN, sin pasar por la función Python.
- El mount de `StaticFiles` en `main.py` ahora es defensivo: si la carpeta no está,
  loguea una advertencia y sigue funcionando (solo se pierde el HTML en `/`, la API en
  `/api/*` sigue andando) — antes, esa falla tumbaba todo.
- Migré el arranque de `@app.on_event("startup")` (deprecado) a `lifespan`, que es el
  patrón que Vercel documenta explícitamente como soportado para FastAPI.
- `requirements.txt` también copiado a la raíz, por si Vercel lo busca ahí con un
  entrypoint en un subdirectorio custom.

Con esto **no pude probar contra una cuenta de Vercel real** (sigue siendo la limitación
de este entorno) — hacé el redeploy y avisame si el error persiste, con el mensaje/ID
exacto del log de Vercel, para seguir desde ahí.


## Usuarios y roles

Cuatro roles con jerarquía: `super_admin` > `admin` > `analista` > `report_viewer`.

| Rol | Puede |
|---|---|
| `super_admin` | Todo, incluida la gestión de cualquier usuario (incluidos otros admins) |
| `admin` | Todo excepto gestionar cuentas `admin`/`super_admin` — solo puede crear/editar/eliminar `analista` y `report_viewer` |
| `analista` | Analizar, limpiar, generar datos sintéticos, ver/usar gráficos y proyección, ver (no guardar) la config de IA |
| `report_viewer` | Solo lectura: ver historial, pedir gráficos/proyecciones sobre análisis ya hechos — no puede analizar, limpiar, ni generar datos |

**Primer arranque**: si no hay ningún usuario en la base, el sistema crea un `super_admin` automáticamente:
- Si seteás las variables de entorno `SUPER_ADMIN_USERNAME` y `SUPER_ADMIN_PASSWORD`, usa esas.
- Si no, genera un usuario `admin` con una contraseña aleatoria que se imprime **una sola vez** en el log de arranque (`uvicorn`/Vercel Functions). Copiala de ahí y cambiala apenas entres.

**Alternativa — precargar el usuario antes del primer deploy** (`scripts/seed_admin.py`): crea el esquema completo en Neon y siembra el super_admin con credenciales fijas, sin depender del log de arranque. Es idempotente (correrlo de nuevo no pisa una contraseña que ya hayas cambiado).

```bash
export DATABASE_URL="postgresql://usuario:pass@ep-xxxx.neon.tech/dbname?sslmode=require"
python3 scripts/seed_admin.py
```

Credenciales por defecto que crea el script (**cambiala apenas ingreses** — quedó hardcodeada en el script para que sea reproducible, no es secreta):
- Usuario: `admin`
- Contraseña: `7ataOx1lWVY303x2L2`

Para usar otras credenciales desde el arranque, seteá `ADMIN_USERNAME`/`ADMIN_PASSWORD` antes de correr el script.

⚠️ No pude probar este script contra un Postgres real desde este entorno (no hay Docker ni pude instalar Postgres localmente aquí) — sí verifiqué que el SQL carga bien y que el hashing de contraseña es exactamente el mismo que usa la app (`hash_password`/`verify_password` en `auth.py`), pero la conexión real a Neon queda para tu primera corrida.

**Variable obligatoria en producción: `JWT_SECRET`**. Si no la fijás, el sistema arranca igual pero cada instancia genera una clave distinta en memoria — en Vercel (donde puede haber más de una instancia sirviendo pedidos) esto hace que el login falle de forma intermitente (un token emitido por una instancia no lo valida otra). Generá una con `python3 -c "import secrets; print(secrets.token_hex(32))"` y fijala como variable de entorno antes de desplegar.

## Qué incluye

- **Autenticación y roles** (`app/services/auth.py`, `app/services/users.py`,
  `app/routers/auth.py`, `app/routers/users.py`): login con JWT, contraseñas con
  PBKDF2-HMAC-SHA256 (200k iteraciones, salt por usuario), y los 4 roles de arriba
  protegiendo cada endpoint existente. Probado de punta a punta con Playwright en un
  navegador real: login, creación de usuarios desde la interfaz, y confirmado que cada
  rol ve/oculta exactamente lo que debería (dropzone, datos sintéticos, pestaña Limpieza,
  panel Usuarios, botón de guardar IA).
-

## Cómo correrlo

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Abrir http://localhost:8000, cargar un .xlsx/.xls/.csv y hacer clic en "Analizar archivo".

## Qué incluye

- **Limpieza automática — la "T" del ETL** (`app/services/cleaning.py` + `app/routers/cleaning.py`):
  pestaña nueva que aplica una corrección por cada hallazgo de calidad con arreglo
  razonable: nulos (imputa mediana o valor más frecuente), negativos (valor absoluto),
  atípicos (winsoriza al rango IQR), fechas (normaliza a dd/mm/yyyy sin destruir valores
  que no logra interpretar), moneda (quita símbolos), numérico-como-texto (convierte),
  ciudades sin uniformar y categorías inconsistentes (mismo criterio de similitud que la
  regla que las detecta — antes el fixer era menos estricto que el detector y dejaba
  cosas sin resolver), y duplicados (elimina). Precios/códigos inconsistentes NO se tocan
  a propósito — son un conflicto de criterio de negocio, no algo que el sistema deba
  decidir solo. Después de limpiar, re-analiza automáticamente y muestra hallazgos antes
  vs. después; probado con el dataset sintético sucio: bajó de 14 hallazgos a 1 (el único
  no auto-corregible). En el camino encontré y corregí un bug real: el fixer de fechas
  generaba nulos nuevos en valores que no podía interpretar en vez de dejarlos intactos.
- **Datos sintéticos** (`app/services/synthetic_data.py` + `app/routers/synthetic.py`):
  panel en la barra lateral con 4 variantes coherentes, generables desde la interfaz sin
  archivo real:
  - *Ventas — serie de tiempo*: varias gestiones con tendencia y estacionalidad real
    (1200 registros por defecto), para probar Proyección.
  - *Datos sucios*: con cada problema que el motor de calidad detecta —nulos, negativos,
    atípicos, codificación errónea, fechas mezcladas, moneda inconsistente, ciudades sin
    uniformar, categorías inconsistentes, duplicados, precios inconsistentes— probado y
    confirmado que dispara 10 de las 12 reglas existentes.
  - *Esquema estrella*: Productos + Clientes (dimensión) y Ventas (hecho) con relaciones
    reales (1500 registros de hechos) — confirmado que Detección de Esquema lo reconoce
    como estrella automáticamente.
  - *Inventario genérico*: dataset limpio de otro dominio (almacén), para probar
    diccionario e insights sin el sesgo de los otros tres escenarios.
  "Generar y analizar" corre todo el pipeline sin pasar por upload manual (reutiliza la
  misma lógica de `/api/analyze` vía una función compartida); "Descargar .xlsx" da el
  archivo crudo para inspeccionar o reutilizar afuera.
- **Proyección/predicción** (`app/services/forecasting.py` + `app/services/forecast_advisor.py`
  + `app/routers/forecast.py`): pestaña separada que reutiliza el mismo motor de
  interpretación de preguntas de Gráficos, pero exige una columna de tiempo (sin fecha no
  hay nada que proyectar) y extrae el horizonte de la pregunta ("próximo trimestre" → 3
  meses, "2 años" → 24 meses, sin pista → 3 por defecto, editable a mano). Dos métodos
  deterministas —tendencia lineal (mínimos cuadrados) y promedio móvil— con banda de
  incertidumbre simple (±1.96 desvíos del residuo histórico). La IA nunca calcula los
  números de la proyección, igual que en insights: como mucho ayuda a interpretar la
  pregunta libre, pero el resultado se valida contra columnas reales antes de usarse.
  Probado con series continuas (confirma que la tendencia lineal extrapola bien una serie
  con pendiente clara) y con horizonte extraído de "próximo trimestre" (3 períodos).
- **Interfaz reorganizada por proceso**: en vez de todo apilado en una sola vista, cada
  proceso tiene su propia pestaña — Log, Diccionario, Calidad, Esquema, Análisis,
  Gráficos — y solo muestra los datos de ese proceso. Las pestañas se habilitan recién
  cuando hay un análisis cargado (nuevo o desde el historial).
- **Gráficos guiados por pregunta** (`app/services/chart_advisor.py` +
  `app/routers/charts.py`): el usuario escribe qué quiere ver en lenguaje natural (ej.
  "quiero ver la venta de productos a lo largo del trimestre"). El sistema identifica
  medida (columna numérica), agrupación (columna categórica) y granularidad temporal por
  palabras clave/sinónimos sobre el diccionario ya generado, y sugiere el tipo de gráfico
  estándar para esa combinación (serie de tiempo → línea; comparación entre categorías →
  barras). Si hay ambigüedad real —dos o más columnas igual de plausibles para lo pedido,
  por ejemplo "cantidad" vs "ganancia bruta" vs "ganancia neta", o "producto" vs "canal de
  venta" sin que la pregunta lo aclare— la interfaz pregunta antes de graficar en vez de
  adivinar. Con el checkbox "Usar IA" activado, se le pasa la pregunta y la lista de
  columnas disponibles a la IA para una interpretación más flexible de frases libres —
  pero el resultado SIEMPRE se valida contra columnas reales antes de usarse; si la IA
  inventa un nombre de columna, se descarta y cae al heurístico normal.
- **Cache de datos crudos por análisis** (`app/services/data_cache.py`): necesario para
  poder agregar los datos con cualquier combinación de medida/agrupación al graficar, sin
  volver a pedir el archivo. Vive en memoria del proceso — en Vercel (serverless) no hay
  garantía de que sobreviva entre invocaciones; si pasa, el mensaje de error lo indica y
  pide volver a analizar el archivo. Persistirlo en Neon es la alternativa si hace falta
  que sobreviva sí o sí (no implementado todavía, ver "Qué falta").
- **Detección de claves sin asumir nombres de campo** (`app/services/key_detection.py`):
  los nombres de columna no se conocen de antemano —dependen del archivo que suba cada
  usuario— así que "columna tipo clave" (usado por diccionario, esquema, calidad e
  insights) combina dos señales genéricas en un módulo compartido: patrón de nombre
  amplio (id, cod, sku, folio, referencia, clave, key, pk) + señal estructural (secuencia
  entera consecutiva 1,2,3,4..., sin importar el nombre de la columna). Antes cada módulo
  tenía su propia lista — quedó centralizado para no desalinearse.
- **Ingesta** (`app/services/ingestion.py`): lee Excel (todas las hojas) o CSV, separando
  automáticamente múltiples tablas dentro de una misma hoja usando filas vacías como
  delimitador.
- **Perfilado** (`app/services/profiling.py`): infiere el tipo de cada columna (numérico,
  fecha, categórico, texto, numérico-como-texto), nulos/únicos, rango min/max.
- **Diccionario de datos** (`app/services/dictionary.py`): expande abreviaturas comunes
  (fec→fecha, cod→código, desc→descripción, etc.), sugiere nombre de columna legible y
  arma una descripción en texto natural con las estadísticas del perfilado.
- **Motor de reglas de calidad** (`app/services/quality/`), una regla por archivo:
  codificación errónea (mojibake), nulos, negativos, atípicos (IQR), formato de fecha
  dd/mm/yyyy, moneda inconsistente, numérico-como-texto, abreviaturas de ciudad sin
  uniformar, categorías con nombres inconsistentes, registros duplicados, precios
  inconsistentes por producto/código, códigos con más de una descripción. Ordenados por
  severidad (alta/media/baja).
- **Detección de esquema** (`app/services/schema_detection.py`): con 2+ tablas, clasifica
  cada una como dimensión u hecho (por columnas tipo clave: `*_id`, `id_*`, `cod`, `sku`),
  busca relaciones por coincidencia de nombre + solapamiento real de valores, y sugiere si
  el patrón es estrella o copo de nieve. Es una sugerencia narrada, nunca se aplica sola.
- **Análisis de datos / EDA** (`app/services/insights.py`): estadísticas descriptivas por
  columna numérica (media, mediana, desvío, cuartiles), frecuencias de las categóricas,
  correlaciones relevantes (|r| ≥ 0.5) entre medidas, y una lista de análisis sugeridos
  (series de tiempo, comparaciones por categoría, tablas cruzadas) — excluyendo a propósito
  las columnas tipo clave para que no se sugieran como métricas de negocio.
- **Configuración de IA** (`app/services/ai_providers.py` + `app/routers/ai_config.py`):
  Anthropic, OpenAI-compatible, NVIDIA NIM, Gemini, Ollama (local), o "sin IA". Guarda,
  prueba conexión al vuelo. Con el checkbox "Usar IA" del análisis: mejora las
  descripciones del diccionario y agrega una narrativa breve por tabla en el módulo de
  EDA (a partir del resumen ya calculado, nunca de las filas crudas). Si la IA no
  responde, todo sigue funcionando solo con heurística.
- **Historial de análisis** (`app/services/history.py` + `app/routers/history.py`): cada
  análisis se guarda completo con su `analysis_id`. Neon/Postgres si hay `DATABASE_URL`,
  SQLite local si no. `GET /api/history` (listado), `GET /api/history/{id}` (completo).
  Panel de historial en la interfaz para volver a ver un análisis sin re-subir el archivo.
- **Log de proceso narrado**: cada paso de cada módulo anterior genera una línea de texto
  explicando lo que hizo, visible en vivo en la interfaz.

## Consideraciones para el despliegue en Vercel + Neon

- Seteá `DATABASE_URL` (la que te da Neon) en las variables de entorno de Vercel para que
  la config de IA y el historial persistan entre invocaciones. Sin esa variable, el
  backend sigue funcionando pero cada invocación arranca en blanco (filesystem efímero).
- Los planes de Vercel limitan el tamaño del body (~4.5 MB en Hobby) y el tiempo de
  ejecución (10s Hobby, 60s Pro) de las funciones serverless. Un Excel grande puede pegar
  contra cualquiera de los dos — si pasa, hay que subir de plan o mover el procesamiento
  pesado a una cola/worker en vez de resolverlo en la misma función.
- `vercel.json` incluido es un punto de partida — **no probado contra una cuenta de Vercel
  real** (no hay forma de hacerlo desde acá).

## Probado con

Además de los datasets anteriores (nombres convencionales tipo `cod_prod`/`id_venta`,
y 2 tablas relacionadas), se probó con un dataset de nombres completamente distintos
(`referencia`, `secuencial`, `importe`, `rubro`) para confirmar que la detección de
claves no depende de haber visto esos nombres antes — `secuencial` se detectó como clave
por ser una serie entera consecutiva, sin ningún patrón de nombre reconocible.

## Qué falta (próximas iteraciones)

- Verificar el despliegue real en Vercel + Neon con una cuenta real (ver guía de
  despliegue más abajo — todavía no ejecutada contra una cuenta real).

- Métodos de proyección más avanzados (estacionalidad, suavizado exponencial) si la
  tendencia lineal / promedio móvil no alcanza para series con patrones estacionales.
- La proyección agrupada (por producto, canal, etc.) puede dar series ruidosas o con
  ceros intercalados si una categoría no tiene datos en todos los períodos — es un
  resultado matemáticamente correcto sobre esos datos, pero vale la pena revisar la
  cantidad de puntos históricos por categoría antes de confiar en la tendencia.

- Persistir las filas crudas en Neon (no solo en cache de memoria) para que graficar
  siga funcionando aunque el proceso serverless se haya reciclado.
- El heurístico de gráficos por ahora solo sugiere línea o barras (serie de tiempo /
  comparación entre categorías); no sugiere torta, dispersión, ni combina más de una
  medida en el mismo gráfico.

- Historial como JSON completo por análisis, no un modelo relacional normalizado — si hace
  falta buscar por columna a través de análisis distintos, es el siguiente paso natural.
- Exportación del diccionario, calidad e insights a Excel/DOCX.
- Manejo de secretos de IA fuera de texto plano (variable de entorno o vault) antes de
  cualquier despliegue expuesto más allá de uso propio.
- Verificar el despliegue real en Vercel con una cuenta real.
