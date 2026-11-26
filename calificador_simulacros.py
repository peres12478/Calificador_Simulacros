# -*- coding: utf-8 -*-
"""
Calificador de simulacros – hojas de respuestas Sesión 1 (120 preguntas) y Sesión 2 (135).

Instalación:   pip install opencv-python numpy pymupdf pillow
Ejecución:     python calificador_simulacros.py

Carpetas del proyecto (se crean solas la primera vez):
    plantillas/         plantilla_sesion_1.pdf  y  plantilla_sesion_2.pdf  (hojas en blanco)
    claves/             clave_sesion1.pdf y clave_sesion2.pdf (la plantilla con las respuestas buenas marcadas)
    hojas_a_calificar/  hojas de los estudiantes (fotos, escaneos o PDF)
"""

import csv
import math
import os
import queue
import re
import threading
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageTk

# ======================================================================
# CONFIGURACIÓN
# ======================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_PLANTILLAS = os.path.join(BASE_DIR, "plantillas")
CARPETA_CLAVES = os.path.join(BASE_DIR, "claves")
CARPETA_HOJAS = os.path.join(BASE_DIR, "hojas_a_calificar")

# areas:    (Área, pregunta inicial, pregunta final) en el orden de la hoja.
# opciones: (pregunta inicial, pregunta final, cuántas opciones tiene cada fila).
# grado:    se detecta en cada hoja comparando la zona impresa del encabezado (10/11).
MODELOS = {
    "Sesión 1": {
        "plantilla": os.path.join(CARPETA_PLANTILLAS, "plantilla_sesion_1.pdf"),
        "clave": os.path.join(CARPETA_CLAVES, "clave_sesion1.pdf"),
        "grado": "10",
        "plantillas_grado": {
            "10": os.path.join(CARPETA_PLANTILLAS, "plantilla_sesion_1.pdf"),
            "11": os.path.join(CARPETA_PLANTILLAS, "plantilla_sesion_1_grado11.pdf"),
        },
        "areas": [
            ("Matemáticas", 1, 25),
            ("Lectura Crítica", 26, 66),
            ("Sociales y Ciudadanas", 67, 91),
            ("Ciencias Naturales", 92, 120),
        ],
        "opciones": [(1, 120, 4)],
    },
    "Sesión 2": {
        "plantilla": os.path.join(CARPETA_PLANTILLAS, "plantilla_sesion_2.pdf"),
        "clave": os.path.join(CARPETA_CLAVES, "clave_sesion2.pdf"),
        "grado": "10",
        "plantillas_grado": {
            "10": os.path.join(CARPETA_PLANTILLAS, "plantilla_sesion_2.pdf"),
            "11": os.path.join(CARPETA_PLANTILLAS, "plantilla_sesion_2_grado11.pdf"),
        },
        "areas": [
            ("Sociales y Ciudadanas", 1, 25),
            ("Matemáticas", 26, 50),
            ("Ciencias Naturales", 51, 79),
            ("Inglés", 80, 135),
        ],
        "opciones": [(1, 79, 4), (80, 89, 8), (90, 120, 3), (121, 135, 4)],
    },
}
MODELO_TEXTO = {"Sesión 1 · 120 preguntas": "Sesión 1", "Sesión 2 · 135 preguntas": "Sesión 2"}

# Hoja clave de cada sesión (se puede cambiar desde la ventana con «Cargar clave»)
CLAVES = {m: cfg["clave"] for m, cfg in MODELOS.items()}

DPI = 200
N_LISTA = 40                 # el número de lista va de 1 a 40
LETRAS = "ABCDEFGH"          # las filas pueden tener 3, 4 u 8 opciones: se detecta sola
UMBRAL_MARCA = 25            # cuánto más oscura que una burbuja vacía debe estar para contar como marca
ALINEACION_MINIMA = 0.85     # por debajo, se considera que la hoja no es del modelo elegido
EXT_IMAGEN = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
EXT_VALIDAS = (".pdf",) + EXT_IMAGEN


def total_modelo(modelo):
    return max(fin for _, _, fin in MODELOS[modelo]["areas"])


# ======================================================================
# NÚCLEO: LECTURA DE HOJAS CONTRA LA PLANTILLA
# ======================================================================
def renderizar_pdf(ruta, dpi=DPI):
    """Devuelve una imagen en escala de grises por cada página del PDF."""
    doc = fitz.open(ruta)
    paginas = []
    for pag in doc:
        pix = pag.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        paginas.append(img.reshape(pix.height, pix.stride)[:, :pix.width].copy())
    doc.close()
    return paginas


def cargar_hojas(ruta):
    """Devuelve [(número de página o None, imagen gris)]. Cada página de un PDF es una hoja."""
    if ruta.lower().endswith(".pdf"):
        pags = renderizar_pdf(ruta)
        return [((i + 1) if len(pags) > 1 else None, g) for i, g in enumerate(pags)]
    datos = np.fromfile(ruta, dtype=np.uint8)      # soporta tildes/ñ en la ruta
    img = cv2.imdecode(datos, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("No se pudo leer la imagen.")
    return [(None, img)]


def _normalizar(g):
    """Corrige sombras y brillo desigual: el papel queda blanco y la tinta oscura."""
    gf = g.astype(np.float32)
    fondo = cv2.dilate(gf, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (35, 35)))
    fondo = cv2.GaussianBlur(fondo, (0, 0), 15)
    return np.clip(gf / np.maximum(fondo, 30.0) * 255.0, 0, 255).astype(np.uint8)


# ---------- plantilla ----------
def _burbujas_plantilla(T):
    _, bw = cv2.threshold(T, 200, 255, cv2.THRESH_BINARY_INV)
    contornos, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cand = []
    for c in contornos:
        x, y, w, h = cv2.boundingRect(c)
        if not (0.007 * T.shape[1] <= w <= 0.021 * T.shape[1]) or not 0.8 <= w / h <= 1.25:
            continue
        per = cv2.arcLength(c, True)
        if per == 0 or 4 * np.pi * cv2.contourArea(c) / per ** 2 < 0.75:
            continue
        cand.append((x + w / 2, y + h / 2, (w + h) / 4))
    cand.sort(key=lambda b: -b[2])
    unicos = []
    for b in cand:
        if all((b[0] - k[0]) ** 2 + (b[1] - k[1]) ** 2 > (0.6 * k[2]) ** 2 for k in unicos):
            unicos.append(b)
    # descartar "agujeros" de letras blancas sobre fondo oscuro (títulos de las áreas):
    # una burbuja real está rodeada de papel claro
    h, w = T.shape
    buenas = []
    for cx, cy, r in unicos:
        a, z = int(1.5 * r), int(2.0 * r)
        x0, y0 = int(cx) - z, int(cy) - z
        if x0 < 0 or y0 < 0 or y0 + 2 * z + 1 > h or x0 + 2 * z + 1 > w:
            continue
        yy, xx = np.mgrid[-z:z + 1, -z:z + 1]
        d = np.hypot(xx, yy)
        parche = T[y0:y0 + 2 * z + 1, x0:x0 + 2 * z + 1]
        if np.median(parche[(d >= a) & (d <= z)]) > 200:
            buenas.append((cx, cy, r))
    return buenas


def _estructura_plantilla(burb, palabras, total, opciones, areas, modelo):
    """Estructura exacta de la plantilla, guiada por los números impresos junto a cada
    fila. Funciona con cualquier distribución (subcolumnas, bloques de 3, 4 u 8 opciones).
    Devuelve (filas, burbujas_del_grupo | None, número_de_lista | None, radio, radio_lista)."""
    if len(burb) < 100:
        raise ValueError(f"No se reconocieron las burbujas de la plantilla de la {modelo}.")
    # Dos tamaños de burbuja: las grandes (respuestas y grupo) y las pequeñas (número de lista).
    radios = [b[2] for b in burb]
    r = float(np.median([x for x in radios if x >= 0.85 * float(np.percentile(radios, 90))]))
    grandes = [b for b in burb if abs(b[2] - r) <= 0.12 * r]
    chicas = [b for b in burb if 0.7 * r <= b[2] <= 0.9 * r]
    if len(grandes) < 100:
        raise ValueError(f"No se reconocieron las burbujas de la plantilla de la {modelo}.")

    lista, r_lista = None, None
    if len(chicas) >= N_LISTA // 2:
        r_lista = float(np.median([b[2] for b in chicas]))
        digitos = [(i, w[2], (w[1] + w[3]) / 2, int(w[4])) for i, w in enumerate(palabras)
                   if re.fullmatch(r"\d{1,2}", w[4]) and 1 <= int(w[4]) <= N_LISTA]
        asignadas = {}                 # n.º -> (distancia, índice de la palabra, x, y)
        for bx, by, _ in chicas:
            cand = [(bx - xr, i, n) for i, xr, yc, n in digitos
                    if 0 < bx - xr <= 4 * r_lista and abs(yc - by) <= 0.9 * r_lista]
            if cand:
                d, i, n = min(cand)
                if n not in asignadas or d < asignadas[n][0]:
                    asignadas[n] = (d, i, bx, by)
        if len(asignadas) >= N_LISTA // 2:
            if sorted(asignadas) != list(range(1, N_LISTA + 1)):
                raise ValueError(f"No se encontraron los {N_LISTA} círculos del número de lista "
                                 f"en la plantilla de la {modelo}.")
            lista = [(n, float(asignadas[n][2]), float(asignadas[n][3])) for n in range(1, N_LISTA + 1)]
            usadas = {v[1] for v in asignadas.values()}
            palabras = [w for i, w in enumerate(palabras) if i not in usadas]

    items = [(y, x, 0, None) for x, y, _ in grandes]
    for x0, y0, x1, y1, t in palabras:
        if re.fullmatch(r"\d{1,3}", t) and 1 <= int(t) <= total:
            items.append(((y0 + y1) / 2, (x0 + x1) / 2, 1, int(t)))
    items.sort(key=lambda t: t[0])
    filas_y = []
    for it in items:
        if filas_y and abs(it[0] - np.mean([q[0] for q in filas_y[-1]])) <= 0.8 * r:
            filas_y[-1].append(it)
        else:
            filas_y.append([it])

    candidatos, huerfanas = [], []
    for fila in filas_y:
        fila.sort(key=lambda t: t[1])
        actual = None
        for y, x, tipo, val in fila:
            if tipo == 1:
                actual = {"n": val, "ops": []}
                candidatos.append(actual)
            elif actual is not None:
                actual["ops"].append((x, y))
            else:
                huerfanas.append((x, y))
    por_n = {}
    for c in candidatos:
        if len(c["ops"]) >= 3 and (c["n"] not in por_n or len(c["ops"]) > len(por_n[c["n"]]["ops"])):
            por_n[c["n"]] = c
    faltan = [n for n in range(1, total + 1) if n not in por_n]
    if faltan:
        raise ValueError(f"En la plantilla de la {modelo} no se encontraron las filas de las preguntas: "
                         f"{faltan[:10]}{'…' if len(faltan) > 10 else ''}.")

    def esperado(n):
        for ini, fin, k in opciones:
            if ini <= n <= fin:
                return k
        return None

    # filas completas -> retículas modelo (posición de A y separación) por cantidad de opciones
    reticulas = {}
    for n, c in por_n.items():
        k = esperado(n)
        if k and len(c["ops"]) == k:
            xs = sorted(x for x, _ in c["ops"])
            paso = float(np.median(np.diff(xs)))
            reticulas.setdefault(k, []).append([xs[0] + i * paso for i in range(k)])
    filas = []
    for n in range(1, total + 1):
        c = por_n[n]
        xs = sorted(x for x, _ in c["ops"])
        y = float(np.mean([yy for _, yy in c["ops"]]))
        k = esperado(n)
        if k and len(xs) != k:
            sirve = [L for L in reticulas.get(k, [])
                     if sum(any(abs(x - p) <= 0.5 * r for p in L) for x in xs) >= min(2, len(xs))]
            if not sirve:
                raise ValueError(f"No se pudo reconstruir la pregunta {n} de la plantilla ({modelo}).")
            mejor = max(sirve, key=lambda L: sum(any(abs(x - p) <= 0.5 * r for p in L) for x in xs))
            xs = list(mejor)
        area = next(a for a, ini, fin in areas if ini <= n <= fin)
        filas.append({"n": n, "area": area, "opciones": [(float(x), y) for x in xs]})

    grupo = None
    huerfanas.sort(key=lambda p: p[1])
    cl = []
    for x, y in huerfanas:
        if cl and abs(y - np.mean([q[1] for q in cl[-1]])) <= 0.8 * r:
            cl[-1].append((x, y))
        else:
            cl.append([(x, y)])
    cinco = [sorted(g) for g in cl if len(g) == 5]
    if cinco:
        grupo = [(float(x), float(y)) for x, y in cinco[0]]
    return filas, grupo, lista, r, r_lista


def palabras_pdf(ruta):
    """Palabras de la primera página con su posición en píxeles (x0, y0, x1, y1, texto)."""
    doc = fitz.open(ruta)
    try:
        k = DPI / 72.0
        return [(w[0] * k, w[1] * k, w[2] * k, w[3] * k, w[4]) for w in doc[0].get_text("words")]
    finally:
        doc.close()


def _grado_de_palabras(palabras):
    """Lee el número del grado impreso en la plantilla («GRADO 10»)."""
    for i, w in enumerate(palabras[:-1]):
        if w[4].upper() == "GRADO" and re.fullmatch(r"\d{1,2}", palabras[i + 1][4]):
            return palabras[i + 1][4]
    return None


_cache_plantillas = {}


def cargar_plantilla(modelo):
    if modelo in _cache_plantillas:
        return _cache_plantillas[modelo]
    cfg = MODELOS[modelo]
    ruta = cfg["plantilla"]
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No se encontró la plantilla de la {modelo}:\n{ruta}\n\n"
                                "Colócala en la carpeta 'plantillas'.")
    T = renderizar_pdf(ruta)[0]
    palabras = palabras_pdf(ruta)
    filas, grupo, lista, r, r_lista = _estructura_plantilla(
        _burbujas_plantilla(T), palabras, total_modelo(modelo), cfg["opciones"], cfg["areas"], modelo)
    pl = {"img": T, "filas": filas, "grupo": grupo, "lista": lista, "r_lista": r_lista,
          "r": r, "modelo": modelo, "feat": {},
          "grado": _grado_de_palabras(palabras) or cfg.get("grado", "")}
    _cache_plantillas[modelo] = pl
    return pl


_cache_referencias_grado = {}


def detectar_grado_hoja(norm, modelo):
    """Detecta 10/11 leyendo visualmente el texto impreso del encabezado ya alineado."""
    if modelo not in _cache_referencias_grado:
        refs = {}
        cfg = MODELOS[modelo]
        for grado, ruta in cfg["plantillas_grado"].items():
            if not os.path.exists(ruta):
                raise FileNotFoundError(f"No se encontró la plantilla de grado {grado}: {ruta}")
            ref = renderizar_pdf(ruta)[0]
            # Región fija del encabezado donde aparece «GRADO 10» o «GRADO 11».
            x0, y0, x1, y1 = [round(v * DPI / 72.0) for v in (445, 21, 511, 40)]
            refs[grado] = ref[y0:y1, x0:x1]
        _cache_referencias_grado[modelo] = refs

    x0, y0, x1, y1 = [round(v * DPI / 72.0) for v in (445, 21, 511, 40)]
    recorte = norm[y0:y1, x0:x1]
    diferencias = {}
    for grado, referencia in _cache_referencias_grado[modelo].items():
        if recorte.shape != referencia.shape:
            referencia = cv2.resize(referencia, (recorte.shape[1], recorte.shape[0]))
        diferencias[grado] = float(np.mean(cv2.absdiff(recorte, referencia)))
    return min(diferencias, key=diferencias.get)


# ---------- alineación foto/escaneo -> plantilla ----------
def _puntaje_anillos(norm, pl):
    """Qué fracción de las burbujas de la plantilla tiene su anillo en esa posición.
    Sirve para saber si la hoja quedó bien alineada (y si es del modelo correcto)."""
    r = pl["r"]
    inv = 255.0 - norm.astype(np.float32)
    h, w = inv.shape
    yy, xx = np.mgrid[-int(2.2 * r):int(2.2 * r) + 1, -int(2.2 * r):int(2.2 * r) + 1]
    d = np.hypot(xx, yy)
    anillo = (d >= 0.8 * r) & (d <= 1.2 * r)
    fuera = (d >= 1.6 * r) & (d <= 2.1 * r)
    ok = total = 0
    posiciones = [p for f in pl["filas"] for p in f["opciones"]] + list(pl.get("grupo") or [])
    for x, y in posiciones:
        x0, y0 = int(round(x)) - int(2.2 * r), int(round(y)) - int(2.2 * r)
        if x0 < 0 or y0 < 0 or y0 + yy.shape[0] > h or x0 + xx.shape[1] > w:
            continue
        p = inv[y0:y0 + yy.shape[0], x0:x0 + yy.shape[1]]
        total += 1
        if p[anillo].mean() - p[fuera].mean() > 8:
            ok += 1
    return ok / total if total else 0.0


def _homografia(g, pl, tipo):
    """Homografía foto -> plantilla por características (ORB o AKAZE) + RANSAC."""
    T = pl["img"]
    clahe = cv2.createCLAHE(3.0, (8, 8))
    if tipo == "orb":
        det = cv2.ORB_create(nfeatures=6000, scaleFactor=1.2, nlevels=10, fastThreshold=10)
        norma, razon = cv2.NORM_HAMMING, 0.8
    elif tipo == "sift" and hasattr(cv2, "SIFT_create"):
        det = cv2.SIFT_create(nfeatures=5000)
        norma, razon = cv2.NORM_L2, 0.75
    elif tipo == "akaze" and hasattr(cv2, "AKAZE_create"):
        det = cv2.AKAZE_create(threshold=0.0005)
        norma, razon = cv2.NORM_HAMMING, 0.8
    else:
        return None, g
    if tipo not in pl["feat"]:
        pl["feat"][tipo] = det.detectAndCompute(clahe.apply(T), None)
    kp_t, des_t = pl["feat"][tipo]
    s = min(1.0, 2600.0 / max(g.shape))
    gs = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else g
    kp_s, des_s = det.detectAndCompute(clahe.apply(gs), None)
    if des_s is None or des_t is None or len(kp_s) < 30:
        return None, gs
    pares = cv2.BFMatcher(norma).knnMatch(des_s, des_t, k=2)
    buenos = [m for m, n in (p for p in pares if len(p) == 2) if m.distance < razon * n.distance]
    if len(buenos) < 20:
        return None, gs
    src = np.float32([kp_s[m.queryIdx].pt for m in buenos]).reshape(-1, 1, 2)
    dst = np.float32([kp_t[m.trainIdx].pt for m in buenos]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None or int(mask.sum()) < 20:
        return None, gs
    return H, gs


def _refinar(warp, pl):
    """Ajuste fino (sub-píxel) de la alineación comparando con la plantilla (ECC)."""
    T = pl["img"]
    Ht, Wt = T.shape
    s = 0.5
    chico = lambda im: cv2.GaussianBlur(cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA),  # noqa: E731
                                        (0, 0), 1.5).astype(np.float32)
    a, b = chico(T), chico(_normalizar(warp))
    M = np.eye(3, dtype=np.float32)
    try:
        _, M = cv2.findTransformECC(a, b, M, cv2.MOTION_HOMOGRAPHY,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5),
                                    None, 5)
    except cv2.error:
        return warp
    S = np.diag([s, s, 1.0]).astype(np.float32)
    Mf = np.linalg.inv(S) @ M @ S
    return cv2.warpPerspective(warp, Mf, (Wt, Ht), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def _esquinas_pagina(g):
    """Las 4 esquinas de la hoja (papel claro sobre fondo más oscuro) o None."""
    s = min(1.0, 1000.0 / max(g.shape))
    gs = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else g
    blur = cv2.GaussianBlur(gs, (9, 9), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contornos, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    c = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.2 * gs.size:
        return None
    casco = cv2.convexHull(c)
    pts = None
    for eps in (0.02, 0.03, 0.045, 0.06):
        ap = cv2.approxPolyDP(casco, eps * cv2.arcLength(casco, True), True)
        if len(ap) == 4:
            pts = ap.reshape(-1, 2).astype(np.float32)
            break
    if pts is None:
        pts = cv2.boxPoints(cv2.minAreaRect(casco)).astype(np.float32)
    suma, dif = pts.sum(axis=1), pts[:, 1] - pts[:, 0]
    orden = [pts[np.argmin(suma)], pts[np.argmin(dif)], pts[np.argmax(suma)], pts[np.argmax(dif)]]
    return np.float32(orden) / s


def _warp_por_esquinas(g, esq, pl):
    """Prueba las 4 orientaciones posibles y devuelve la hoja alineada con mejor puntaje."""
    Ht, Wt = pl["img"].shape
    dst = np.float32([[0, 0], [Wt, 0], [Wt, Ht], [0, Ht]])
    mejor = None
    for k in range(4):
        M = cv2.getPerspectiveTransform(np.roll(esq, -k, axis=0), dst)
        w = cv2.warpPerspective(g, M, (Wt, Ht), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=255)
        # puntaje aproximado: se compara con la plantilla a baja resolución
        a = cv2.resize(pl["img"], None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA).astype(np.float32)
        b = cv2.resize(_normalizar(w), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA).astype(np.float32)
        corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        if mejor is None or corr > mejor[0]:
            mejor = (corr, w)
    return mejor[1]


def alinear(g, pl):
    """Lleva la hoja (foto, escaneo o PDF) al espacio de la plantilla.
    Devuelve (imagen normalizada alineada, método, puntaje de alineación)."""
    Ht, Wt = pl["img"].shape
    mejor = None

    def evaluar(nombre, img, refinar=True):
        nonlocal mejor
        if refinar:
            img = _refinar(img, pl)
        norm = _normalizar(img)
        pt = _puntaje_anillos(norm, pl)
        if mejor is None or pt > mejor[2]:
            mejor = (norm, nombre, pt)
        return pt

    if g.shape == (Ht, Wt) and evaluar("directa", g, refinar=False) >= 0.9:
        return mejor
    for tipo in ("orb", "sift", "akaze"):
        H, gs = _homografia(g, pl, tipo)
        if H is not None:
            warp = cv2.warpPerspective(gs, H, (Wt, Ht), flags=cv2.INTER_CUBIC,
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=255)
            if evaluar(tipo, warp) >= 0.9:
                return mejor
    esq = _esquinas_pagina(g)
    if esq is not None:
        if evaluar("esquinas", _warp_por_esquinas(g, esq, pl)) >= 0.9:
            return mejor
    evaluar("escala", cv2.resize(g, (Wt, Ht), interpolation=cv2.INTER_AREA))
    if mejor[2] < ALINEACION_MINIMA:
        raise ValueError(
            f"La hoja no coincide con la plantilla de la {pl['modelo']} "
            f"(alineación {100 * mejor[2]:.0f} %). Revisa que sea del modelo elegido y que "
            "la foto muestre la hoja completa, de frente y con buena luz.")
    return mejor


# ---------- lectura de marcas ----------
def _oscuridad_disco(inv, x, y, rr, disco):
    h, w = inv.shape
    x0, y0 = int(round(x)) - rr, int(round(y)) - rr
    if x0 < 0 or y0 < 0 or y0 + 2 * rr + 1 > h or x0 + 2 * rr + 1 > w:
        return 0.0
    return float(inv[y0:y0 + 2 * rr + 1, x0:x0 + 2 * rr + 1][disco].mean())


def _decidir(puntajes):
    """Índices marcados. Si una destaca claramente sobre las demás, es la marca real."""
    marc = [j for j, v in enumerate(puntajes) if v > UMBRAL_MARCA]
    if len(marc) > 1:
        marc.sort(key=lambda j: -puntajes[j])
        if puntajes[marc[0]] >= 1.6 * puntajes[marc[1]]:
            marc = [marc[0]]
    return sorted(marc)


def leer_marcas(norm, pl):
    """Devuelve (preguntas, grupo, lista). Su 'valor' es el elegido, '' (sin marca) o '*' (doble)."""
    r = pl["r"]
    inv = 255.0 - norm.astype(np.float32)
    rr = max(3, int(round(0.55 * r)))
    yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
    disco = (xx ** 2 + yy ** 2) <= rr ** 2

    oscuro = [[_oscuridad_disco(inv, x, y, rr, disco) for x, y in f["opciones"]] for f in pl["filas"]]
    # nivel normal de cada opción (A, B, C...) = el que tienen las burbujas vacías
    base = []
    for j in range(len(LETRAS)):
        v = [fila[j] for fila in oscuro if len(fila) > j]
        base.append(float(np.percentile(v, 25)) if v else 0.0)

    preguntas = []
    for f, fila in zip(pl["filas"], oscuro):
        sc = [fila[j] - base[j] for j in range(len(fila))]
        marc = _decidir(sc)
        resp = LETRAS[marc[0]] if len(marc) == 1 else ("" if not marc else "*")
        preguntas.append({
            "n": f["n"], "area": f["area"], "marcadas": marc, "resp": resp,
            "burbujas": [(x, y, r, float(sc[j])) for j, (x, y) in enumerate(f["opciones"])],
        })

    grupo = None
    if pl.get("grupo"):
        d = [_oscuridad_disco(inv, x, y, rr, disco) for x, y in pl["grupo"]]
        med = float(np.median(d))
        sc = [v - med for v in d]
        marc = _decidir(sc)
        grupo = {"valor": str(marc[0] + 1) if len(marc) == 1 else ("" if not marc else "*"),
                 "marcadas": marc,
                 "burbujas": [(x, y, r, float(sc[j])) for j, (x, y) in enumerate(pl["grupo"])]}

    lista = None
    if pl.get("lista"):
        rl = pl["r_lista"]
        rr_l = max(3, int(round(0.55 * rl)))
        yl, xl = np.mgrid[-rr_l:rr_l + 1, -rr_l:rr_l + 1]
        disco_l = (xl ** 2 + yl ** 2) <= rr_l ** 2
        d = [_oscuridad_disco(inv, x, y, rr_l, disco_l) for _, x, y in pl["lista"]]
        med = float(np.median(d))
        sc = [v - med for v in d]
        marc = _decidir(sc)
        lista = {"valor": str(pl["lista"][marc[0]][0]) if len(marc) == 1 else ("" if not marc else "*"),
                 "marcadas": marc,
                 "burbujas": [(x, y, rl, float(sc[j])) for j, (_, x, y) in enumerate(pl["lista"])]}
    return preguntas, grupo, lista


def procesar_hoja(g, modelo):
    """Lee una hoja (imagen gris) de la sesión indicada."""
    pl = cargar_plantilla(modelo)
    norm, metodo, puntaje = alinear(g, pl)
    preguntas, grupo, lista = leer_marcas(norm, pl)
    grado = detectar_grado_hoja(norm, modelo)
    return {"modelo": modelo, "norm": norm, "metodo": metodo, "alineacion": puntaje,
            "preguntas": preguntas, "grupo": grupo, "lista": lista, "grado": grado}



# ======================================================================
# CLAVES Y CALIFICACIÓN
# ======================================================================
_cache_claves = {}      # modelo -> respuestas tal como se leyeron de la clave
_correcciones = {}      # modelo -> {n.º de pregunta: letra corregida a mano}


def leer_clave(modelo):
    """Lee el archivo clave del modelo. Devuelve la respuesta leída de cada pregunta
    ('' = sin marca, '*' = doble marca); no exige que todas sean válidas."""
    ruta = CLAVES[modelo]
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"No se encontró la hoja clave de la {modelo}:\n{ruta}\n\n"
            "Cárgala con «Cargar clave» o colócala en la carpeta 'claves'.")
    hoja = procesar_hoja(cargar_hojas(ruta)[0][1], modelo)
    return [p["resp"] for p in hoja["preguntas"]]


def cargar_clave(modelo):
    """Clave lista para calificar (con las correcciones manuales aplicadas)."""
    if modelo not in _cache_claves:
        _cache_claves[modelo] = leer_clave(modelo)
    clave = list(_cache_claves[modelo])
    for n, letra in _correcciones.get(modelo, {}).items():
        clave[n - 1] = letra
    malas = [i + 1 for i, c in enumerate(clave) if c not in LETRAS]
    if malas:
        raise ValueError(
            "En la hoja clave hay preguntas sin marca única "
            f"(números: {malas[:15]}).\n\nPulsa «Ver respuestas de la clave» "
            "y corrígelas con doble clic.")
    return clave


def datos_clave(modelo):
    """Filas (n.º, área, respuesta correcta, estado) para mostrar la clave en una tabla."""
    if modelo not in _cache_claves:
        _cache_claves[modelo] = leer_clave(modelo)
    leida = _cache_claves[modelo]
    corr = _correcciones.get(modelo, {})
    filas = []
    for area, ini, fin in MODELOS[modelo]["areas"]:
        for n in range(ini, fin + 1):
            letra = corr.get(n, leida[n - 1])
            if n in corr:
                estado = "Corregida a mano"
            elif letra in LETRAS:
                estado = "OK"
            elif letra == "":
                estado = "⚠ Revisar (sin marca)"
            else:
                estado = "⚠ Revisar (doble marca)"
            filas.append((n, area, letra if letra in LETRAS else "—", estado))
    return filas


def calificar_hoja(hoja, clave, modelo):
    """Compara la hoja leída con la clave. Devuelve un resumen liviano (sin imágenes)."""
    est = [p["resp"] for p in hoja["preguntas"]]
    marcas = []
    for p in hoja["preguntas"]:
        if p["resp"] == "":
            marcas.append("—")
        elif p["resp"] == "*":
            marcas.append(" + ".join(LETRAS[j] for j in p["marcadas"]))
        else:
            marcas.append(p["resp"])
    areas, tb = [], {"buenas": 0, "malas": 0, "duplicadas": 0, "faltaron": 0}
    for area, ini, fin in MODELOS[modelo]["areas"]:
        c = {"buenas": 0, "malas": 0, "duplicadas": 0, "faltaron": 0}
        for n in range(ini, fin + 1):
            e, k = est[n - 1], clave[n - 1]
            if e == k:
                c["buenas"] += 1
            elif e == "":
                c["faltaron"] += 1
            elif e == "*":
                c["duplicadas"] += 1
            else:
                c["malas"] += 1
        for clave_c in tb:
            tb[clave_c] += c[clave_c]
        areas.append({"area": area, "preguntas": fin - ini + 1, **c})
    total = total_modelo(modelo)
    return {"modelo": modelo, "est": est, "marcas": marcas, "clave": list(clave),
            "areas": areas, "total": total, **tb, "pct": round(100 * tb["buenas"] / total, 1),
            "metodo": hoja["metodo"], "alineacion": hoja["alineacion"],
            "grupo": (hoja["grupo"] or {}).get("valor"), "grado_hoja": hoja["grado"],
            "n_lista": (hoja["lista"] or {}).get("valor")}


def filas_comparacion(res):
    """Filas (n.º, área, correcta, marcada, resultado): Buena / Mala / Duplicada / Faltó."""
    filas = []
    for area, ini, fin in MODELOS[res["modelo"]]["areas"]:
        for n in range(ini, fin + 1):
            e, k = res["est"][n - 1], res["clave"][n - 1]
            estado = ("Buena" if e == k else "Faltó" if e == "" else
                      "Duplicada" if e == "*" else "Mala")
            filas.append((n, area, k, res["marcas"][n - 1], estado))
    return filas


# ======================================================================
# NOMBRES Y GRADOS (desde el nombre del archivo o su subcarpeta)
# ======================================================================
def normalizar_texto(t):
    """Minúsculas y sin tildes: «Ángel» y «angel» son lo mismo."""
    t = unicodedata.normalize("NFD", str(t))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.casefold()).strip()


def clave_grado(g):
    return re.sub(r"[^0-9a-z]+", "-", normalizar_texto(g)).strip("-")


_RE_GRADO = re.compile(r"(?<!\d)(\d{1,2})\s*[-_.°ºª]\s*(\d{1,2})(?!\d)")
_RE_GRADO_LETRA = re.compile(r"(?<!\d)(\d{1,2})\s*([A-Za-z])(?![A-Za-z0-9])")


def _buscar_grado(texto):
    m = _RE_GRADO.search(texto)
    if m:
        return f"{m.group(1)}-{m.group(2)}", m.span()
    m = _RE_GRADO_LETRA.search(texto)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}", m.span()
    return None


def datos_de_archivo(ruta, base=None, pagina=None):
    """Nombre y grado a partir de la subcarpeta (si la hay) y del nombre del archivo.
    Ejemplos:  10-1/Ana Perez.jpg → Ana Perez, 10-1   ·   Juan Gomez 11-2.pdf → Juan Gomez, 11-2"""
    stem = os.path.splitext(os.path.basename(ruta))[0]
    grado = ""
    if base:
        rel = os.path.relpath(os.path.dirname(ruta), base)
        carpetas = [] if rel in (".", "") else [c for c in rel.split(os.sep) if c and c != ".."]
        if carpetas:
            g = _buscar_grado(carpetas[-1])
            grado = g[0] if g else carpetas[-1].strip()
    nombre = stem
    g = _buscar_grado(stem)
    if g:
        nombre = stem[:g[1][0]] + " " + stem[g[1][1]:]
        grado = grado or g[0]
    nombre = re.sub(r"(?i)\b(grado|grupo|curso)\b", " ", nombre)
    nombre = re.sub(r"[_\-.]+", " ", nombre)
    nombre = re.sub(r"\s+", " ", nombre).strip() or stem
    if pagina:
        nombre += f" (pág. {pagina})"
    return nombre, grado or "Sin grado"


# ======================================================================
# CALIFICACIÓN POR LOTES
# ======================================================================
def listar_hojas(carpeta):
    rutas = []
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            if a.lower().endswith(EXT_VALIDAS) and not a.startswith((".", "~")):
                rutas.append(os.path.join(raiz, a))
    return sorted(rutas, key=lambda r: [int(t) if t.isdigit() else t.lower()
                                        for t in re.split(r"(\d+)", r)])


def procesar_lote(rutas, base, modelo, progreso=None):
    """Califica todas las hojas. Si una falla, queda registrada con su error y se sigue."""
    cargar_plantilla(modelo)
    clave = cargar_clave(modelo)
    registros = []
    for i, ruta in enumerate(rutas, 1):
        if progreso:
            progreso(i, len(rutas), os.path.basename(ruta))
        try:
            hojas = cargar_hojas(ruta)
        except Exception as e:  # noqa: archivo dañado o ilegible
            nombre, grado = datos_de_archivo(ruta, base)
            registros.append({"ruta": ruta, "pagina": None, "archivo": os.path.basename(ruta),
                              "nombre": nombre, "grado": grado, "modelo": modelo,
                              "error": f"No se pudo abrir el archivo ({e})", "res": None})
            continue
        for pag, g in hojas:
            nombre, grado = datos_de_archivo(ruta, base, pag)
            reg = {"ruta": ruta, "pagina": pag, "archivo": os.path.basename(ruta),
                   "nombre": nombre, "grado": grado, "modelo": modelo, "error": None, "res": None}
            try:
                res = calificar_hoja(procesar_hoja(g, modelo), clave, modelo)
                reg["res"] = res
                grupo = res["grupo"]
                reg["grupo"] = grupo
                reg["n_lista"] = res["n_lista"]
                if grupo not in (None, "", "*"):      # el grupo marcado en la hoja manda
                    reg["grado"] = f"{res['grado_hoja']}-{grupo}" if res["grado_hoja"] else f"Grupo {grupo}"
            except Exception as e:  # noqa
                reg["error"] = str(e)
            registros.append(reg)
    return registros


# ======================================================================
# EXPORTACIÓN: GRUPO + N.º DE LISTA, INDEPENDIENTES DEL NOMBRE DEL PDF
# ======================================================================
def grupo_para_exportar(reg):
    """Código de curso (p. ej. 10-1). Respeta correcciones hechas en la tabla.

    La marca del grupo se combina con el grado impreso en la plantilla durante
    procesar_lote; si una hoja falló, puede recuperarse de su subcarpeta.
    """
    grado = str(reg.get("grado") or "").strip()
    if grado and normalizar_texto(grado) != "sin grado":
        return grado
    resultado = reg.get("res") or {}
    grupo = reg.get("grupo")
    grado_hoja = resultado.get("grado_hoja")
    if str(grupo).isdigit() and grado_hoja:
        return f"{grado_hoja}-{grupo}"
    return ""  # no inventar un grupo si no se reconoció


def clave_exportacion(reg):
    """Ordena cursos ascendentemente y, dentro de cada curso, lista 1, 2, 3...

    Los datos de grupo/lista no detectados van al final, nunca se estiman.
    """
    grupo = grupo_para_exportar(reg)
    m = re.fullmatch(r"\s*(\d{1,2})\s*[-_. ]\s*(\d{1,2})\s*", grupo)
    if not m:
        m = re.fullmatch(r"(\d{2})(\d)", grupo)  # admite 101 -> 10-1
    curso = (0, int(m.group(1)), int(m.group(2))) if m else (1, 0, 0)
    lista = str(reg.get("n_lista") or "")
    numero = (0, int(lista)) if lista.isdigit() and 1 <= int(lista) <= N_LISTA else (1, 0)
    return curso + numero + (normalizar_texto(reg.get("nombre", "")),)


def estado_registro(reg):
    if reg.get("error"):
        return "✘ " + reg["error"].split("\n")[0][:70]
    res = reg.get("res")
    if not res:
        return "Sin resultado"
    avisos = []
    if reg.get("n_lista") == "":
        avisos.append("n.º de lista sin marcar")
    elif reg.get("n_lista") == "*":
        avisos.append("n.º de lista duplicado")
    if reg.get("grupo") == "":
        avisos.append("grupo sin marcar")
    elif reg.get("grupo") == "*":
        avisos.append("grupo duplicado")
    if res["duplicadas"]:
        avisos.append(f"{res['duplicadas']} duplicada(s)")
    if res["faltaron"]:
        avisos.append(f"{res['faltaron']} sin responder")
    return ("⚠ " + ", ".join(avisos)) if avisos else "✔ OK"


def construir_csv(registros, modelo):
    """Construye el reporte CSV sin necesitar Tkinter; devuelve encabezado y filas.

    Cada fila representa una sola hoja/página, aun cuando provenga de un PDF
    de varias páginas. No incluye el nombre del archivo, que no es un ID seguro.
    """
    areas = MODELOS[modelo]["areas"]
    encabezado = (["Grupo", "N.º de lista", "Sesión"]
                  + [col for a, i, f in areas
                     for col in (f"{a} (buenas de {f - i + 1})", f"Nota {a}")]
                  + ["Total buenas", "Total preguntas", "Porcentaje", "Duplicadas",
                     "Sin responder", "Estado"])
    filas = []
    for reg in sorted(registros, key=clave_exportacion):
        lista = str(reg.get("n_lista") or "")
        if not lista.isdigit() or not 1 <= int(lista) <= N_LISTA:
            lista = ""
        grupo_excel = grupo_para_exportar(reg)
        # Excel suele convertir «10-1» en fecha al abrir un CSV. La fórmula
        # devuelve el texto literal y evita esa conversión automática.
        if re.fullmatch(r"\d{1,2}-\d{1,2}", grupo_excel):
            grupo_excel = f'="{grupo_excel}"'
        base = [grupo_excel, lista, reg["modelo"]]
        res = reg.get("res")
        if res is None:
            filas.append(base + [""] * (2 * len(areas) + 5) + [estado_registro(reg)])
        else:
            notas = []
            for j, (area, ini, fin) in enumerate(areas):
                buenas = res["areas"][j]["buenas"]
                columna = chr(ord("D") + 2 * j)
                fila_excel = len(filas) + 2
                notas.extend([buenas, f"=5/{fin - ini + 1}*{columna}{fila_excel}"])
            filas.append(base + notas
                        + [res["buenas"], res["total"], str(res["pct"]).replace(".", ","),
                           res["duplicadas"], res["faltaron"], estado_registro(reg)])
    return encabezado, filas


# ======================================================================
# IMÁGENES DE REVISIÓN
# ======================================================================
def dibujar_debug(hoja):
    """Hoja alineada con todas las burbujas: verde = vacía, rojo = marcada."""
    img = cv2.cvtColor(hoja["norm"], cv2.COLOR_GRAY2BGR)
    filas = [(p["burbujas"], p["marcadas"]) for p in hoja["preguntas"]]
    for extra in (hoja.get("grupo"), hoja.get("lista")):
        if extra:
            filas.append((extra["burbujas"], extra["marcadas"]))
    for burbujas, marcadas in filas:
        for j, b in enumerate(burbujas):
            color = (0, 0, 255) if j in marcadas else (0, 170, 0)
            cv2.circle(img, (int(b[0]), int(b[1])), int(b[2]), color, 2)
    return [img]


def dibujar_calificada(hoja, clave):
    """Hoja alineada: verde = acierto, rojo = marca incorrecta, naranja = la que debió marcar."""
    VERDE, ROJO, NARANJA = (0, 170, 0), (0, 0, 255), (0, 140, 255)
    img = cv2.cvtColor(hoja["norm"], cv2.COLOR_GRAY2BGR)
    for n, p in enumerate(hoja["preguntas"], 1):
        bs = p["burbujas"]
        correcta = LETRAS.index(clave[n - 1])

        def aro(i, color, grosor=3):
            if i < len(bs):
                cv2.circle(img, (int(bs[i][0]), int(bs[i][1])), int(bs[i][2]) + 4,
                           color, grosor, cv2.LINE_AA)

        if p["marcadas"] == [correcta]:
            aro(correcta, VERDE)
        else:
            for i in p["marcadas"]:
                aro(i, ROJO)
            aro(correcta, NARANJA)
    for extra in (hoja.get("grupo"), hoja.get("lista")):      # grupo y n.º de lista (azul)
        if extra:
            for j in extra["marcadas"]:
                b = extra["burbujas"][j]
                cv2.circle(img, (int(b[0]), int(b[1])), int(b[2]) + 4, (255, 120, 0), 3, cv2.LINE_AA)
    return [img]


def imagenes_de_hoja(ruta, pagina, modelo, clave=None):
    """Imágenes de una hoja; acepta la misma clave usada al calificarla."""
    g = next(g for p, g in cargar_hojas(ruta) if p == pagina)
    hoja = procesar_hoja(g, modelo)
    return dibujar_calificada(hoja, clave if clave is not None else cargar_clave(modelo)), dibujar_debug(hoja)


def imagen_clave_visual(modelo, clave):
    """Dibuja la solución sobre una copia de la plantilla en blanco."""
    pl = cargar_plantilla(modelo)
    img = cv2.cvtColor(pl["img"], cv2.COLOR_GRAY2BGR)
    for fila in pl["filas"]:
        n = fila["n"]
        letra = clave[n - 1]
        if letra not in LETRAS:
            continue
        j = LETRAS.index(letra)
        if j >= len(fila["opciones"]):
            continue
        x, y = fila["opciones"][j]
        cv2.circle(img, (round(x), round(y)), round(pl["r"]) + 4, (255, 100, 0), 3,
                   cv2.LINE_AA)
    return img


def imagenes_comparacion(reg):
    """Confronta una sola hoja con la clave congelada de esa calificación."""
    res = reg["res"]
    g = next(g for p, g in cargar_hojas(reg["ruta"]) if p == reg["pagina"])
    hoja = procesar_hoja(g, reg["modelo"])
    return ([dibujar_calificada(hoja, res["clave"])[0],
             imagen_clave_visual(reg["modelo"], res["clave"])])


def diagnostico_clave(modelo):
    ruta = CLAVES[modelo]
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No existe la hoja clave:\n{ruta}")
    hoja = procesar_hoja(cargar_hojas(ruta)[0][1], modelo)
    claras = sum(1 for p in hoja["preguntas"] if p["resp"] in LETRAS)
    msg = (f"Clave de la {modelo}: alineada ({100 * hoja['alineacion']:.0f} %), "
           f"{claras} de {len(hoja['preguntas'])} respuestas con marca clara. "
           "Verde = vacía, rojo = marcada.")
    return msg, dibujar_debug(hoja)


# ======================================================================
# INTERFAZ GRÁFICA
# ======================================================================
TODOS = "Todos"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Calificador de Simulacros – Pruebas de Estado")
        self.geometry("1180x780")
        self.minsize(1000, 620)

        self.modelo_txt = tk.StringVar(value=list(MODELO_TEXTO)[0])
        self.fuente = None                       # ("carpeta" | "archivo", ruta)
        self.texto_fuente = tk.StringVar(value="Ninguna carpeta ni archivo seleccionado.")
        self.estado = tk.StringVar(value="Elige el modelo, la carpeta o el archivo y pulsa «Calificar».")
        self.filtro_grado = tk.StringVar(value=TODOS)
        self.filtro_nombre = tk.StringVar()
        self.cola = queue.Queue()
        self.registros = []
        self.registros_modelo = None
        self.orden = (None, False)
        self.ocupado = False
        self._ventanas_comparacion = {}
        self._crear_widgets()
        self.filtro_nombre.trace_add("write", lambda *_: self._aplicar_filtros())

    # ---------- construcción ----------
    def _crear_widgets(self):
        estilo = ttk.Style(self)
        estilo.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        estilo.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        estilo.configure("Grande.TButton", font=("Segoe UI", 11, "bold"), padding=8)

        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        f1 = ttk.LabelFrame(top, text=" 1. Sesión ", padding=10)
        f1.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Combobox(f1, textvariable=self.modelo_txt, values=list(MODELO_TEXTO),
                     state="readonly", width=24, font=("Segoe UI", 11)).pack()

        f2 = ttk.LabelFrame(top, text=" 2. Hojas a calificar ", padding=10)
        f2.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        fila = ttk.Frame(f2)
        fila.pack(anchor="w")
        ttk.Button(fila, text="📁 Elegir carpeta…", command=self._elegir_carpeta).pack(side="left")
        ttk.Button(fila, text="📄 Elegir archivo…", command=self._elegir_archivo).pack(side="left", padx=6)
        ttk.Button(fila, text="🏠 hojas_a_calificar", command=self._usar_carpeta_proyecto).pack(side="left")
        ttk.Label(f2, textvariable=self.texto_fuente, wraplength=520).pack(anchor="w", pady=(6, 0))

        f3 = ttk.LabelFrame(top, text=" 3. Resultado ", padding=10)
        f3.grid(row=0, column=2, sticky="nsew")
        self.btn_calificar = ttk.Button(f3, text="✔ Calificar", style="Grande.TButton",
                                        command=self._calificar)
        self.btn_calificar.pack()
        top.columnconfigure(1, weight=1)

        clave_f = ttk.Frame(self, padding=(12, 2))
        clave_f.pack(fill="x")
        ttk.Label(clave_f, text="Clave:").pack(side="left")
        ttk.Button(clave_f, text="📂 Cargar clave…", command=self._cargar_clave_archivo).pack(side="left", padx=6)
        ttk.Button(clave_f, text="📋 Ver respuestas de la clave", command=self._ver_clave).pack(side="left")
        ttk.Button(clave_f, text="🔍 Ver detección de la clave",
                   command=self._ver_deteccion_clave).pack(side="left", padx=6)

        filtros = ttk.LabelFrame(self, text=" Filtros ", padding=(10, 6))
        filtros.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Label(filtros, text="Grupo:").pack(side="left")
        self.cmb_grado = ttk.Combobox(filtros, textvariable=self.filtro_grado, values=[TODOS],
                                      state="readonly", width=12)
        self.cmb_grado.pack(side="left", padx=(4, 14))
        self.cmb_grado.bind("<<ComboboxSelected>>", lambda e: self._aplicar_filtros())
        ttk.Label(filtros, text="Nombre:").pack(side="left")
        ttk.Entry(filtros, textvariable=self.filtro_nombre, width=28).pack(side="left", padx=(4, 6))
        ttk.Button(filtros, text="Limpiar", command=self._limpiar_filtros).pack(side="left")
        ttk.Button(filtros, text="💾 Exportar a Excel (CSV)",
                   command=self._exportar_csv).pack(side="right")

        self.barra = ttk.Progressbar(self, mode="determinate")
        self.barra.pack(fill="x", padx=12, pady=(8, 0))

        marco = ttk.Frame(self)
        marco.pack(fill="both", expand=True, padx=12, pady=8)
        self.tabla = ttk.Treeview(marco, show="headings", selectmode="browse")
        sy = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        sx = ttk.Scrollbar(marco, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        self.tabla.pack(side="left", fill="both", expand=True)
        self.tabla.tag_configure("error", background="#f8d7d7")
        self.tabla.tag_configure("aviso", background="#fff4cc")
        self.tabla.bind("<Double-1>", self._doble_clic)
        self.tabla.bind("<ButtonRelease-1>", self._clic_comparar)
        self._preparar_columnas(self._modelo())

        ttk.Label(self, text="Clic en 'Comparar respuestas': revisión individual · "
                             "doble clic en Lista/Nombre/Grupo: editar · clic en título: ordenar",
                  foreground="#555").pack(anchor="w", padx=12)
        ttk.Label(self, textvariable=self.estado, relief="sunken", anchor="w",
                  padding=4).pack(fill="x", side="bottom", pady=(4, 0))

    def _modelo(self):
        return MODELO_TEXTO[self.modelo_txt.get()]

    # ---------- selección de hojas ----------
    def _actualizar_fuente(self):
        tipo, ruta = self.fuente
        if tipo == "carpeta":
            n = len(listar_hojas(ruta))
            self.texto_fuente.set(f"Carpeta: {ruta}\n{n} archivo(s) de hojas encontrados (incluye subcarpetas).")
        else:
            self.texto_fuente.set(f"Archivo: {ruta}")
        self.estado.set("Listo. Pulsa «Calificar».")

    def _elegir_carpeta(self):
        r = filedialog.askdirectory(title="Selecciona la carpeta con las hojas", initialdir=CARPETA_HOJAS)
        if r:
            self.fuente = ("carpeta", r)
            self._actualizar_fuente()

    def _elegir_archivo(self):
        r = filedialog.askopenfilename(
            title="Selecciona la hoja de respuestas", initialdir=CARPETA_HOJAS,
            filetypes=[("Hojas de respuestas", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
                       ("Todos los archivos", "*.*")])
        if r:
            self.fuente = ("archivo", r)
            self._actualizar_fuente()

    def _usar_carpeta_proyecto(self):
        os.makedirs(CARPETA_HOJAS, exist_ok=True)
        self.fuente = ("carpeta", CARPETA_HOJAS)
        self._actualizar_fuente()

    # ---------- tareas en segundo plano ----------
    def _estado_ocupado(self, si, determinado=False):
        self.ocupado = si
        self.btn_calificar.config(state="disabled" if si else "normal")
        self.barra.stop()
        if si and not determinado:
            self.barra.config(mode="indeterminate")
            self.barra.start(12)
        elif si:
            self.barra.config(mode="determinate", value=0)
        else:
            self.barra.config(mode="determinate", value=0)

    def _ejecutar(self, func, al_final, *args):
        """Corre func(*args) en otro hilo y llama a al_final(resultado) en la ventana."""
        if self.ocupado:
            return
        self._estado_ocupado(True)
        self.estado.set("Procesando… esto puede tardar unos segundos.")

        def correr():
            try:
                self.cola.put(("ok", al_final, func(*args)))
            except Exception as e:  # noqa
                self.cola.put(("error", str(e)))

        threading.Thread(target=correr, daemon=True).start()
        self.after(100, self._revisar_cola)

    def _revisar_cola(self):
        terminado = False
        while True:
            try:
                msg = self.cola.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "prog":
                _, i, n, texto = msg
                self.barra.config(maximum=n, value=i - 1)
                self.estado.set(f"Calificando {i} de {n}: {texto}")
            elif msg[0] == "ok":
                self._estado_ocupado(False)
                msg[1](msg[2])
                terminado = True
            elif msg[0] == "error":
                self._estado_ocupado(False)
                self.estado.set("Ocurrió un error.")
                messagebox.showerror("Error", msg[1])
                terminado = True
        if not terminado and self.ocupado:
            self.after(100, self._revisar_cola)

    # ---------- calificar ----------
    def _calificar(self):
        if not self.fuente:
            messagebox.showwarning("Falta elegir", "Primero elige una carpeta o un archivo con las hojas.")
            return
        tipo, ruta = self.fuente
        modelo = self._modelo()
        if tipo == "carpeta":
            rutas, base = listar_hojas(ruta), ruta
            if not rutas:
                messagebox.showwarning("Carpeta vacía", "No hay hojas (PDF o imágenes) en esa carpeta.")
                return
        else:
            rutas, base = [ruta], os.path.dirname(ruta)
        self._estado_ocupado(True, determinado=True)
        self.estado.set("Preparando plantilla y clave…")

        def correr():
            try:
                regs = procesar_lote(rutas, base, modelo,
                                     lambda i, n, t: self.cola.put(("prog", i, n, t)))
                self.cola.put(("ok", self._mostrar_resultados, (modelo, regs)))
            except Exception as e:  # noqa
                self.cola.put(("error", str(e)))

        threading.Thread(target=correr, daemon=True).start()
        self.after(100, self._revisar_cola)

    def _mostrar_resultados(self, datos):
        modelo, regs = datos
        self.registros, self.registros_modelo = regs, modelo
        self.orden = (None, False)
        self.filtro_grado.set(TODOS)
        self.filtro_nombre.set("")
        self._preparar_columnas(modelo)
        self._refrescar_grados()
        self._aplicar_filtros()
        errores = sum(1 for r in regs if r["error"])
        if errores:
            messagebox.showwarning("Revisa estas hojas", f"{errores} hoja(s) no se pudieron calificar. "
                                   "Aparecen en rojo; haz doble clic para ver el motivo.")

    # ---------- tabla de resultados ----------
    def _preparar_columnas(self, modelo):
        areas = MODELOS[modelo]["areas"]
        cols = ["lista", "grado", "comparar", "nombre"] + [f"a{i}" for i in range(len(areas))] + ["buenas", "pct", "estado"]
        self.tabla.configure(columns=cols, displaycolumns=cols)
        titulos = {"lista": "N.º lista", "nombre": "Nombre (opcional)", "grado": "Grupo", "buenas": "Total buenas",
                   "pct": "%", "estado": "Estado", "comparar": "Comparación por hoja"}
        anchos = {"lista": 75, "nombre": 240, "grado": 80, "buenas": 100, "pct": 70,
                  "estado": 230, "comparar": 180}
        for i, (area, ini, fin) in enumerate(areas):
            titulos[f"a{i}"] = f"{area} (de {fin - ini + 1})"
            anchos[f"a{i}"] = 150
        for c in cols:
            self.tabla.heading(c, text=titulos[c], command=lambda c=c: self._ordenar(c))
            self.tabla.column(c, width=anchos[c], anchor="w" if c in ("nombre", "estado") else "center",
                              stretch=(c == "nombre"))

    @staticmethod
    def _texto_lista(reg):
        v = reg.get("n_lista")
        return v if v not in (None, "", "*") else "—"

    @staticmethod
    def _estado_texto(reg):
        return estado_registro(reg)

    def _valores(self, reg):
        if reg["error"]:
            n_areas = len(MODELOS[self.registros_modelo]["areas"])
            return ([self._texto_lista(reg), reg["grado"], "No disponible", reg["nombre"]]
                    + ["—"] * n_areas + ["—", "—", self._estado_texto(reg)])
        r = reg["res"]
        return ([self._texto_lista(reg), reg["grado"], "🔎 Comparar respuestas", reg["nombre"]]
                + [f"{a['buenas']}/{a['preguntas']}" for a in r["areas"]]
                + [f"{r['buenas']}/{r['total']}", f"{r['pct']:.1f}", self._estado_texto(reg)])

    def _clave_orden(self, reg, col):
        r = reg["res"]
        if col == "lista":
            v = self._texto_lista(reg)
            return int(v) if v.isdigit() else 10 ** 6
        if col == "nombre":
            return normalizar_texto(reg["nombre"])
        if col == "comparar":
            return bool(r)
        if col == "grado":
            return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", clave_grado(reg["grado"]))]
        if r is None:
            return -1
        if col.startswith("a"):
            return r["areas"][int(col[1:])]["buenas"]
        if col in ("buenas", "pct"):
            return r["buenas"]
        return self._estado_texto(reg)

    def _ordenar(self, col):
        anterior, desc = self.orden
        self.orden = (col, (not desc) if anterior == col else (col not in ("lista", "nombre", "grado", "estado")))
        self._aplicar_filtros()

    def _refrescar_grados(self):
        grados = {}
        for r in self.registros:
            grados.setdefault(clave_grado(r["grado"]), r["grado"])
        orden = sorted(grados.values(), key=lambda g: [int(t) if t.isdigit() else t
                                                       for t in re.split(r"(\d+)", clave_grado(g))])
        self.cmb_grado.config(values=[TODOS] + orden)
        if self.filtro_grado.get() not in [TODOS] + orden:
            self.filtro_grado.set(TODOS)

    def _visibles(self):
        palabras = normalizar_texto(self.filtro_nombre.get()).split()
        grado = self.filtro_grado.get()
        vis = []
        for i, reg in enumerate(self.registros):
            if grado != TODOS and clave_grado(reg["grado"]) != clave_grado(grado):
                continue
            nombre = normalizar_texto(reg["nombre"])
            if any(p not in nombre for p in palabras):
                continue
            vis.append(i)
        col, desc = self.orden
        if col:
            vis.sort(key=lambda i: self._clave_orden(self.registros[i], col), reverse=desc)
        else:
            # Orden predeterminado estable: curso ascendente y lista 1, 2, 3...
            vis.sort(key=lambda i: clave_exportacion(self.registros[i]))
        return vis

    def _aplicar_filtros(self):
        self.tabla.delete(*self.tabla.get_children())
        if not self.registros:
            return
        vis = self._visibles()
        for i in vis:
            reg = self.registros[i]
            etiqueta = "error" if reg["error"] else ("aviso" if self._estado_texto(reg).startswith("⚠") else "")
            self.tabla.insert("", "end", iid=str(i), values=self._valores(reg), tags=(etiqueta,))
        self.estado.set(f"Mostrando {len(vis)} de {len(self.registros)} hojas · {self.registros_modelo}")

    def _limpiar_filtros(self):
        self.filtro_grado.set(TODOS)
        self.filtro_nombre.set("")
        self._aplicar_filtros()

    def _clic_comparar(self, ev):
        """Columna de acción: acceso a la comparación de ESTA hoja del lote."""
        if self.tabla.identify_region(ev.x, ev.y) != "cell":
            return
        item = self.tabla.identify_row(ev.y)
        col = self.tabla.identify_column(ev.x)
        if not item or not col:
            return
        nombre_col = self.tabla["columns"][int(col[1:]) - 1]
        if nombre_col != "comparar":
            return
        reg = self.registros[int(item)]
        if reg.get("res") and not reg.get("error"):
            self._abrir_detalle(reg)
        else:
            messagebox.showinfo("No disponible", "Esta hoja no pudo calificarse; revisa el estado.")

    def _doble_clic(self, ev):
        item = self.tabla.identify_row(ev.y)
        col = self.tabla.identify_column(ev.x)
        if not item or not col:
            return
        reg = self.registros[int(item)]
        nombre_col = self.tabla["columns"][int(col[1:]) - 1]
        if nombre_col == "comparar":
            return  # la columna ya se activa con un solo clic
        if nombre_col == "lista":
            nuevo = simpledialog.askstring("Editar n.º de lista", f"Número de lista (1 a {N_LISTA}):",
                                           initialvalue="" if self._texto_lista(reg) == "—" else self._texto_lista(reg),
                                           parent=self)
            if nuevo and nuevo.strip().isdigit() and 1 <= int(nuevo.strip()) <= N_LISTA:
                reg["n_lista"] = str(int(nuevo.strip()))
        elif nombre_col == "nombre":
            nuevo = simpledialog.askstring("Editar nombre", "Nombre del estudiante:",
                                           initialvalue=reg["nombre"], parent=self)
            if nuevo and nuevo.strip():
                reg["nombre"] = nuevo.strip()
        elif nombre_col == "grado":
            nuevo = simpledialog.askstring("Editar grupo", "Grupo del estudiante (ej. 10-1):",
                                           initialvalue=reg["grado"], parent=self)
            if nuevo and nuevo.strip():
                reg["grado"] = nuevo.strip()
                reg["grupo"] = "manual"
                self._refrescar_grados()
        else:
            self._abrir_detalle(reg)
            return
        self._aplicar_filtros()

    # ---------- exportar ----------
    def _exportar_csv(self):
        if not self.registros:
            messagebox.showwarning("Sin resultados", "Primero califica algunas hojas.")
            return
        ruta = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV (Excel)", "*.csv")],
                                            initialfile="resultados_por_grupo_y_lista.csv")
        if not ruta:
            return
        # Respeta los filtros, pero NO el orden de clics de la tabla:
        # Ordena cursos y números de lista de menor a mayor.
        visibles = [self.registros[i] for i in self._visibles()]
        encabezado, filas = construir_csv(visibles, self.registros_modelo)
        try:
            with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
                w = csv.writer(archivo, delimiter=";")
                w.writerow(encabezado)
                w.writerows(filas)
        except OSError as e:
            messagebox.showerror("Error al exportar", str(e))
            return
        self.estado.set(f"Exportadas {len(filas)} hojas a {ruta}. Orden: grupo y lista ascendentes.")

    # ---------- detalle de un estudiante ----------
    def _abrir_detalle(self, reg):
        if reg["error"] or not reg["res"]:
            messagebox.showinfo("No se pudo calificar", f"{reg['archivo']}\n\n{reg['error']}")
            return
        anterior = self._ventanas_comparacion.get(id(reg))
        if anterior is not None and anterior.winfo_exists():
            anterior.lift()
            anterior.focus_force()
            return
        r = reg["res"]
        top = tk.Toplevel(self)
        self._ventanas_comparacion[id(reg)] = top
        top.bind("<Destroy>", lambda ev: self._ventanas_comparacion.pop(id(reg), None)
                 if ev.widget is top else None)
        top.title(f"Comparar respuestas · Grupo {reg['grado']} · Lista {self._texto_lista(reg)} · {reg['modelo']}")
        top.geometry("780x700")
        lineas = [f"{reg['nombre']} · Grado {reg['grado']} · N.º de lista {self._texto_lista(reg)}",
                  "   ".join(f"{a['area']}: {a['buenas']}/{a['preguntas']}" for a in r["areas"]),
                  f"Total: {r['buenas']}/{r['total']} ({r['pct']} %)   ✘ Malas: {r['malas']}   "
                  f"⚠ Duplicadas: {r['duplicadas']}   ○ Faltó: {r['faltaron']}",
                  f"Grupo marcado en la hoja: {r['grupo'] or '—'}   ·   "
                  f"Alineación con la plantilla: {100 * r['alineacion']:.0f} % ({r['metodo']})"]
        ttk.Label(top, text="\n".join(lineas), padding=8, wraplength=740).pack(fill="x")
        botones = ttk.Frame(top)
        botones.pack(fill="x", padx=8)
        ttk.Button(botones, text="🖼 Ver hoja calificada",
                   command=lambda: self._ver_imagenes(reg, 0)).pack(side="left")
        ttk.Button(botones, text="📄 Hoja vs clave",
                   command=lambda: self._ver_comparacion_visual(reg)).pack(side="left", padx=6)
        ttk.Button(botones, text="🔎 Ver detección",
                   command=lambda: self._ver_imagenes(reg, 1)).pack(side="left", padx=6)
        solo = tk.BooleanVar(value=False)
        ttk.Checkbutton(botones, text="Solo las que no son buenas", variable=solo,
                        command=lambda: llenar()).pack(side="left", padx=12)

        cuerpo = ttk.Frame(top)
        cuerpo.pack(fill="both", expand=True, padx=8, pady=6)
        cols = ("n", "area", "correcta", "marcada", "estado")
        tabla = ttk.Treeview(cuerpo, columns=cols, show="headings")
        for c, t, w, a in (("n", "N.º", 55, "center"), ("area", "Área", 210, "w"),
                           ("correcta", "Respuesta buena", 120, "center"),
                           ("marcada", "Respuesta del estudiante", 170, "center"),
                           ("estado", "Resultado", 110, "center")):
            tabla.heading(c, text=t)
            tabla.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(cuerpo, orient="vertical", command=tabla.yview)
        tabla.configure(yscrollcommand=sb.set)
        for e, color in (("Buena", "#d9f2d9"), ("Mala", "#f8d7d7"),
                         ("Duplicada", "#ffe0b3"), ("Faltó", "#fff4cc")):
            tabla.tag_configure(e, background=color)
        tabla.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        filas = filas_comparacion(r)

        def llenar():
            tabla.delete(*tabla.get_children())
            for f in filas:
                if solo.get() and f[4] == "Buena":
                    continue
                tabla.insert("", "end", values=f, tags=(f[4],))

        llenar()
        ttk.Button(top, text="Cerrar", command=top.destroy).pack(pady=8)

    def _ver_imagenes(self, reg, cual):
        def trabajo():
            cal, det = imagenes_de_hoja(reg["ruta"], reg["pagina"], reg["modelo"], reg["res"]["clave"])
            return (f"{reg['nombre']} – " + ("hoja calificada (verde: acierto · rojo: marca incorrecta · "
                    "naranja: la que debió marcar)" if cual == 0 else "detección (verde: vacía · rojo: marcada)"),
                    cal if cual == 0 else det)
        self._ejecutar(trabajo, self._abrir_visor)

    def _ver_comparacion_visual(self, reg):
        """La calificación y la plantilla-clave se muestran con la misma clave guardada."""
        def trabajo():
            imgs = imagenes_comparacion(reg)
            return (f"Comparación · {reg['modelo']} · Grupo {reg['grado']} · "
                    f"Lista {self._texto_lista(reg)}", imgs,
                    ["HOJA DEL ESTUDIANTE · Verde: acierto / Rojo: marca incorrecta / "
                     "Naranja: respuesta correcta",
                     "HOJA CLAVE · Los aros azules indican las respuestas correctas"])
        self._ejecutar(trabajo, self._abrir_visor)

    def _abrir_visor(self, datos):
        msg, imgs = datos[:2]
        etiquetas = datos[2] if len(datos) > 2 else []
        self.estado.set(msg)
        top = tk.Toplevel(self)
        top.title(msg)
        top.geometry("1000x760")
        lienzo = tk.Canvas(top)
        sy = ttk.Scrollbar(top, orient="vertical", command=lienzo.yview)
        lienzo.configure(yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        lienzo.pack(side="left", fill="both", expand=True)
        marco = ttk.Frame(lienzo)
        lienzo.create_window((0, 0), window=marco, anchor="nw")
        top.fotos = []
        for j, img in enumerate(imgs):
            if j < len(etiquetas):
                ttk.Label(marco, text=etiquetas[j], font=("Segoe UI", 11, "bold"),
                          padding=8).pack(fill="x")
            h, w = img.shape[:2]
            pil = Image.fromarray(cv2.cvtColor(cv2.resize(img, (950, int(h * 950 / w))), cv2.COLOR_BGR2RGB))
            foto = ImageTk.PhotoImage(pil)
            top.fotos.append(foto)
            ttk.Label(marco, image=foto).pack(pady=4)
        marco.update_idletasks()
        lienzo.configure(scrollregion=lienzo.bbox("all"))
        lienzo.bind("<Enter>", lambda e: lienzo.bind_all(
            "<MouseWheel>", lambda ev: lienzo.yview_scroll(int(-ev.delta / 120), "units")))

    # ---------- clave ----------
    def _cargar_clave_archivo(self):
        modelo = self._modelo()
        r = filedialog.askopenfilename(
            title=f"Selecciona la clave de la {modelo}", initialdir=CARPETA_CLAVES,
            filetypes=[("Hoja clave", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff"),
                       ("Todos los archivos", "*.*")])
        if not r:
            return
        CLAVES[modelo] = r
        _cache_claves.pop(modelo, None)
        _correcciones.pop(modelo, None)
        self.estado.set(f"Clave de la {modelo} cargada: {os.path.basename(r)}")
        self._ver_clave()

    def _ver_clave(self):
        modelo = self._modelo()
        self._ejecutar(lambda: (cargar_plantilla(modelo), datos_clave(modelo))[1],
                       lambda filas: self._abrir_tabla_clave(modelo, filas))

    def _ver_deteccion_clave(self):
        modelo = self._modelo()
        self._ejecutar(diagnostico_clave, self._abrir_visor, modelo)

    def _abrir_tabla_clave(self, modelo, filas):
        top = tk.Toplevel(self)
        top.title(f"Respuestas de la clave – {modelo}")
        top.geometry("620x640")
        resumen = tk.StringVar()
        ttk.Label(top, textvariable=resumen, padding=8, wraplength=580).pack(fill="x")
        marco = ttk.Frame(top)
        marco.pack(fill="both", expand=True, padx=8)
        cols = ("n", "area", "resp", "estado")
        tabla = ttk.Treeview(marco, columns=cols, show="headings")
        for c, t, w, a in (("n", "N.º", 60, "center"), ("area", "Área", 220, "w"),
                           ("resp", "Respuesta correcta", 130, "center"),
                           ("estado", "Estado", 160, "w")):
            tabla.heading(c, text=t)
            tabla.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(marco, orient="vertical", command=tabla.yview)
        tabla.configure(yscrollcommand=sb.set)
        tabla.tag_configure("warn", background="#fff4cc")
        tabla.tag_configure("corr", background="#d9e8ff")
        tabla.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def etiqueta(estado):
            return "warn" if estado.startswith("⚠") else ("corr" if estado.startswith("Corr") else "")

        for f in filas:
            tabla.insert("", "end", iid=str(f[0]), values=f, tags=(etiqueta(f[3]),))

        def actualizar():
            vals = [tabla.item(i, "values") for i in tabla.get_children()]
            dudosas = sum(1 for v in vals if str(v[3]).startswith("⚠"))
            texto = f"{os.path.basename(CLAVES[modelo])} · {len(vals)} preguntas. "
            texto += (f"⚠ {dudosas} por revisar: haz doble clic en la fila para corregirla."
                      if dudosas else "Todas las respuestas tienen una marca válida. "
                      "Doble clic en una fila para corregirla si algo no coincide.")
            resumen.set(texto)

        def editar(_ev):
            sel = tabla.selection()
            if not sel:
                return
            n = int(sel[0])
            letra = simpledialog.askstring(
                "Corregir respuesta", f"Respuesta correcta de la pregunta {n}:", parent=top)
            if letra is None:
                return
            letra = letra.strip().upper()
            if letra not in LETRAS:
                messagebox.showwarning("Letra no válida",
                                       f"Escribe una letra entre {LETRAS[0]} y {LETRAS[-1]}.", parent=top)
                return
            _correcciones.setdefault(modelo, {})[n] = letra
            v = list(tabla.item(sel[0], "values"))
            v[2], v[3] = letra, "Corregida a mano"
            tabla.item(sel[0], values=v, tags=("corr",))
            actualizar()

        tabla.bind("<Double-1>", editar)
        actualizar()
        ttk.Button(top, text="Cerrar", command=top.destroy).pack(pady=8)


if __name__ == "__main__":
    for carpeta in (CARPETA_PLANTILLAS, CARPETA_CLAVES, CARPETA_HOJAS):
        os.makedirs(carpeta, exist_ok=True)
    App().mainloop()
