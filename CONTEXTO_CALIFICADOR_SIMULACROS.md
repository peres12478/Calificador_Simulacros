# Contexto integral del proyecto - Calificador de Simulacros

**Fecha de revisión:** 18 de noviembre de 2026  
**Base examinada:** `DOC-20261111-WA0003.zip`  
**Estado reportado por el usuario:** el programa ya funciona y califica correctamente los simulacros reales. Esta revisión no dispone de esas hojas respondidas para repetir esa validación práctica.

## 1. Objetivo principal

Construir y mantener una **aplicación de escritorio para calificar masivamente hojas de respuestas** de simulacros tipo ICFES. El operador deposita los PDF (o imágenes) de estudiantes en la carpeta `hojas_a_calificar`, selecciona la sesión, carga la clave de respuestas y pulsa **Calificar**. El programa interpreta las respuestas marcadas en cada hoja, identifica el grupo y el número de lista, compara cada respuesta con la clave y muestra las calificaciones por área y totales. Luego permite revisar un estudiante concreto o exportar los resultados.

**Requisito prioritario:** preservar intacta la lógica de detección/calificación que ya funciona. Los cambios pedidos en esta revisión son de **presentación, ordenación y revisión individual**, no de la forma en que se asignan los aciertos.

## 2. Estructura de la aplicación

- `calificador_simulacros.py`: archivo principal. Contiene configuración de las sesiones, lectura de PDF e imágenes, alineación óptica, reconocimiento de marcas, calificación, interfaz gráfica, comparación visual y exportación CSV.
- `plantillas/plantilla_sesion_1.pdf`: plantilla en blanco para la sesión 1.
- `plantillas/plantilla_sesion_2.pdf`: plantilla en blanco para la sesión 2.
- `claves/`: debe contener las **hojas con respuestas correctas marcadas**, con los nombres `clave_sesion1.pdf` y `clave_sesion2.pdf`, o las claves se pueden seleccionar desde la interfaz.
- `hojas_a_calificar/`: destino de los PDF o imágenes de los estudiantes. Se buscan archivos en esta carpeta y sus subcarpetas.
- `LEEME.txt`: instrucciones de uso e instalación.

El ZIP original **no contenía** `clave_sesion1.pdf`, `clave_sesion2.pdf` ni hojas reales respondidas. Solo incluía las dos plantillas en blanco y los archivos de instrucciones de esas carpetas. Es necesario proporcionar las claves antes de calificar.

## 3. Entorno y dependencias

Lenguaje: **Python**. Interfaz: **Tkinter** (aplicación local, no sitio web). Librerías: **OpenCV**, **NumPy**, **PyMuPDF** (`fitz`) y **Pillow**. No requiere Excel instalado para crear el CSV, aunque el archivo se puede abrir con Excel.

Comandos habituales, ejecutados dentro de la carpeta `calificador`:

```bash
python -m pip install opencv-python numpy pymupdf pillow
python calificador_simulacros.py
```

En Windows, también se puede utilizar el comando `py` si está disponible.

## 4. Tipos de simulacro que acepta

| Sesión | Área | Preguntas | Cantidad |
| --- | --- | --- | ---: |
| Sesión 1 | Matemáticas | 1-25 | 25 |
| Sesión 1 | Lectura Crítica | 26-66 | 41 |
| Sesión 1 | Sociales y Ciudadanas | 67-91 | 25 |
| Sesión 1 | Ciencias Naturales | 92-120 | 29 |
| Sesión 2 | Sociales y Ciudadanas | 1-25 | 25 |
| Sesión 2 | Matemáticas | 26-50 | 25 |
| Sesión 2 | Ciencias Naturales | 51-79 | 29 |
| Sesión 2 | Inglés | 80-135 | 56 |

- Sesión 1: **120 preguntas**, todas con 4 opciones.
- Sesión 2: **135 preguntas**: preguntas 1-79 con 4 opciones, 80-89 con 8 opciones, 90-120 con 3 opciones y 121-135 con 4 opciones.
- Hay plantillas para **GRADO 10 y GRADO 11** en ambas sesiones. Las hojas permiten marcar grupo 1-5 (casillas A-E) y número de lista 1-40.
- El curso `10-1` corresponde a grado 10, grupo 1; `10-2` a grado 10, grupo 2, etc. Es la forma en que el programa representa los grupos que el usuario ejemplificó como 101, 102, 103.

## 5. Cómo funciona internamente

1. **Carga:** permite elegir la carpeta o un PDF/imagen. Cada página de un PDF de varias páginas se considera una hoja independiente.
2. **Preparación:** abre la plantilla de la sesión correspondiente e identifica posiciones de casillas, preguntas, grupo y número de lista.
3. **Alineación:** trata de ajustar escaneos o fotografías a la plantilla usando métodos de correspondencia visual y, cuando corresponde, ajuste geométrico y corrección del contraste.
4. **Detección:** calcula qué círculos están oscurecidos; identifica respuestas individuales, preguntas en blanco y marcas dobles. También lee el grupo y la lista.
5. **Clave:** lee las respuestas correctas de una hoja clave marcada. Hay herramientas de visualización y corrección manual de respuestas de la clave.
6. **Calificación:** compara la respuesta detectada en cada pregunta con la correcta. Registra buenas, malas, duplicadas y sin responder, con desglose por área y porcentaje total.
7. **Resultados:** presenta una fila por hoja o por página, aunque varias procedan del mismo PDF. Las hojas que fallen se conservan con su error y no detienen todo el lote.
8. **Exportación:** genera un archivo CSV compatible con Excel.

Las correcciones manuales de una clave están en memoria durante la ejecución; **no se guardan permanentemente en un archivo de clave**. Después de cambiar una clave hay que volver a calificar para actualizar los resultados del lote.

## 6. Solicitudes nuevas integradas en esta versión

### D. Reconocimiento de grados 10 y 11

- Se incorporó la plantilla real de grado 11 de la sesión 1 que proporcionó el usuario.
- Se creó la plantilla equivalente de grado 11 para la sesión 2, conservando la geometría de la sesión 2 y cambiando únicamente el rótulo impreso del grado.
- Después de alinear cada hoja, el programa compara visualmente la región del encabezado donde aparece «GRADO 10» o «GRADO 11» con las dos referencias de esa sesión. Así el grado detectado procede de la hoja y no queda fijado en el grado 10 de la plantilla base.
- Se mantienen las mismas 120/135 preguntas, cinco grupos y 40 números de lista.

### A. Exportación CSV organizada por grupo y número de lista

**Problema informado:** en el documento exportado se necesitaba identificar claramente a los estudiantes por su **grupo** y por su **número de lista**, sin depender de la identificación derivada del nombre del PDF.

**Implementación:**

- El CSV incluye **dos columnas diferentes:** `Grupo` y `N.º de lista`.
- Se eliminó del CSV la columna `Nombre`, que originalmente se calculaba a partir del nombre del documento. Ese nombre continúa disponible **dentro de la interfaz** para facilitar la localización y edición, pero ya no se exporta.
- El orden de las columnas empieza con: `Grupo; N.º de lista; Sesión`, seguidas de aciertos por área, total, porcentaje, duplicadas, sin responder y estado.
- Los **grupos se ordenan**: `10-1`, después `10-2`, después `10-3`, etc. (orden ascendente de grupo).
- Dentro de cada grupo, los números de lista aparecen **de menor a mayor**: 1, 2, 3, ..., 40.
- Si una hoja no tiene grupo o número válido, el programa deja el dato vacío y coloca el registro correspondiente al final del orden que no puede determinar; **no inventa datos**.
- El CSV respeta los filtros activos de la pantalla, pero aplica siempre el orden descrito, independientemente del orden visual de la tabla.
- El grupo se escribe en CSV como fórmula de texto (`="10-1"`) para evitar que Excel lo convierta automáticamente en fecha.
- Se mantiene la exportación con separador `;`, codificación UTF-8 con BOM y porcentaje con coma decimal para facilitar la apertura en Excel en entornos regionales de Colombia.

**Ejemplo ilustrativo (datos ficticios):**

```csv
Grupo;N.º de lista;Sesión;...;Total buenas;...
="10-1";1;Sesión 1;...;98;...
="10-1";7;Sesión 1;...;105;...
="10-1";24;Sesión 1;...;93;...
10-2;40;Sesión 1;...;96;...
10-2;12;Sesión 1;...;101;...
10-3;24;Sesión 1;...;108;...
```

**Criterio de orden actualizado:** se respeta el ejemplo `10-1`, `10-2`, `10-3` y el requisito de que el número de lista 1 aparezca primero. Por eso el orden es ascendente tanto para el grupo como para la lista.

### B. Acción `Comparar respuestas` para cada hoja calificada

**Problema informado:** cuando se califican varios PDF, el usuario necesita poder abrir, **desde la fila de cada hoja**, la comparación entre las respuestas que el sistema detectó y la **hoja clave de ese simulacro**. La comparación de un estudiante no debe mezclarse con la de otro.

**Implementación:**

- Cada resultado tiene una celda de acción **`🔎 Comparar respuestas`** cerca del número de lista y el grupo; se activa con un clic.
- Abre una ventana dedicada a **esa hoja o página específica**, no al conjunto.
- Presenta, pregunta por pregunta: `N.º`, `Área`, `Respuesta buena`, `Respuesta del estudiante` y `Resultado`.
- Clasifica el resultado como **Buena, Mala, Duplicada o Faltó**, usando la misma calificación ya calculada.
- Ofrece un filtro **`Solo las que no son buenas`**.
- Incluye **`Ver hoja calificada`** para observar las marcas revisadas sobre la hoja del estudiante.
- Añade **`Hoja vs clave`** para visualizar la hoja calificada y la plantilla con las respuestas correctas marcadas. Las imágenes se muestran una detrás de otra, con títulos identificativos; no se mezclan hojas de estudiantes diferentes.
- La comparación utiliza una **copia de la clave con la que fue evaluada esa hoja**. Así, si el operador cambia la clave cargada posteriormente, la visualización de una calificación ya realizada no cambia silenciosamente. Se debe volver a calificar para recalcular notas con la clave nueva.
- Una hoja cuyo procesamiento falló muestra `No disponible` en vez de una comparación inexistente.

En Tkinter, la celda de acción funciona como un **control clicable dentro de la tabla** (no como un botón `ttk.Button` incrustado por separado). Se diseñó así para que cada fila tenga un acceso directo sin sustituir el componente de tabla que ya funcionaba.

### C. Ajustes de interfaz

- La tabla principal muestra primero `N.º lista`, `Grupo`, `Comparar respuestas` y después el nombre editable y las calificaciones, para que el acceso directo sea visible sin desplazarse horizontalmente.
- Se mantiene la edición del número de lista, nombre y grupo con doble clic.
- Se conserva el filtro por grupo, el filtro por nombre y la información de estado y errores.

## 7. Qué se conservó sin cambios

El código original que realiza las operaciones críticas **no fue modificado** en estas funciones: `cargar_plantilla`, `leer_marcas`, `procesar_hoja`, `leer_clave`, `cargar_clave`, `calificar_hoja`, `filas_comparacion` y `procesar_lote`. Se conservaron también sus parámetros principales de alineación y lectura de marcas.

**No se introdujeron OCR, reconocimiento de nombres escritos, fórmulas nuevas de puntaje ni cambios de plantillas.**

## 8. Verificación realizada y límites

- Las cuatro plantillas (grados 10 y 11, sesiones 1 y 2) se abren correctamente: la Sesión 1 reconstruye 120 preguntas y la Sesión 2 reconstruye 135.
- Se procesaron las cuatro plantillas en blanco mediante el flujo de lectura: las cuatro detectaron el grado esperado, el total de preguntas, los cinco grupos y los 40 números de lista.
- En ambas se identifican 5 opciones de grupo y 40 casillas de número de lista.
- Se verificó con datos sintéticos la estructura de las columnas CSV, el orden por grupo y lista, y el mantenimiento de la misma cantidad de columnas incluso ante errores.
- Se verificó en una interfaz Tkinter que el acceso `Comparar respuestas` aparece en cada fila, abre una ventana individual y no genera duplicados por clics repetidos.
- Se verificó que se puede generar la representación visual de hoja frente a clave utilizando una plantilla.
- Se comprobó que las ocho funciones críticas de lectura y calificación mencionadas arriba son idénticas a las del archivo original.

**Importante:** no se contó con hojas reales respondidas ni las claves reales de cada sesión dentro de este ZIP. Por tanto, la versión revisada superó pruebas de estructura e interfaz, pero debe probarse nuevamente con un conjunto conocido de hojas reales para confirmar la operación completa en el equipo del usuario. Esta limitación no contradice que el usuario ya validó el funcionamiento de la versión anterior en sus simulacros.

## 9. Procedimiento recomendado para usarla

1. Extraer el ZIP conservando sus carpetas.
2. Instalar las dependencias e iniciar `calificador_simulacros.py`.
3. Seleccionar Sesión 1 o 2.
4. Poner la clave correspondiente en `claves/` o cargarla desde el botón **Cargar clave**.
5. Colocar los documentos o imágenes de estudiantes en `hojas_a_calificar/`.
6. Pulsar el botón **hojas_a_calificar** y después **Calificar**.
7. Revisar las filas, identificar el grupo y la lista, corregir datos si una lectura quedó dudosa.
8. Usar **Comparar respuestas** en el estudiante que se quiera auditar; emplear **Hoja vs clave** si se requiere ver la comparación visual.
9. Exportar con **Exportar a Excel (CSV)** y abrir el CSV en Excel.
10. Confirmar que, por ejemplo, el grupo `10-1` aparezca antes de `10-2`, y que dentro de `10-1` la lista 40 aparezca antes de 24, antes de 1.

## 10. Posibles extensiones futuras (no implementadas)

- Exportar `.xlsx` auténtico con formato, hojas y filtros, además del CSV actual.
- Mostrar una alerta cuando el mismo número de lista aparezca repetido dentro de un grupo.
- Conservar un historial permanente de calificaciones y versiones de claves, para auditoría.
- Añadir un selector explícito de sentido de ordenación de la lista y de los grupos.
- Exportar un reporte de comparaciones por pregunta para auditoría individual.

Estas son propuestas, **no funciones incluidas en esta versión**.
