#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║           ELIMINADOR DE SILENCIOS EN VÍDEO                      ║
║   Lee vídeos de input_videos y guarda en output_videos          ║
╚══════════════════════════════════════════════════════════════════╝

USO:
    Pon tus vídeos en la carpeta input_videos y ejecuta:

        python eliminar_silencios.py

    El script procesará todos los vídeos y los guardará en output_videos.

OPCIONES OPCIONALES:
    --umbral         Volumen en dB por debajo del cual se considera silencio (defecto: -30)
    --min-silencio   Duración mínima en segundos para considerarlo silencio (defecto: 0.4)
    --margen         Segundos de audio que se conservan antes/después del corte (defecto: 0.05)
    --modo-analisis  Solo analiza y muestra los silencios, sin editar el vídeo

EJEMPLOS:
    python eliminar_silencios.py
    python eliminar_silencios.py --umbral -25 --min-silencio 0.3
    python eliminar_silencios.py --modo-analisis
"""

import subprocess
import sys
import os
import re
import argparse
import tempfile
import time

# ─── Carpetas del proyecto ────────────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
CARPETA_INPUT  = os.path.join(SCRIPT_DIR, "input_videos")
CARPETA_OUTPUT = os.path.join(SCRIPT_DIR, "output_videos")

# Formatos de vídeo soportados
EXTENSIONES_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"}


# ─── Colores para la terminal ─────────────────────────────────────────────────
def color(text, code): return f"\033[{code}m{text}\033[0m"
def verde(t):    return color(t, "92")
def azul(t):     return color(t, "94")
def amarillo(t): return color(t, "93")
def rojo(t):     return color(t, "91")
def negrita(t):  return color(t, "1")
def gris(t):     return color(t, "90")


def verificar_ffmpeg():
    """Comprueba que ffmpeg está instalado."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(rojo("✗ Error: ffmpeg no está instalado."))
        print("  Instálalo desde: https://ffmpeg.org/download.html")
        print("  Y asegúrate de añadirlo al PATH de Windows.")
        return False


def obtener_duracion(video_path):
    """Obtiene la duración total del vídeo en segundos."""
    resultado = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    try:
        return float(resultado.stdout.strip())
    except ValueError:
        return None


def detectar_silencios(video_path, umbral_db=-30, min_silencio=0.4):
    """Detecta los silencios en el vídeo. Devuelve lista de (inicio, fin) en segundos."""
    print(f"  {azul('Analizando audio...')}  ", end="", flush=True)

    comando = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={umbral_db}dB:d={min_silencio}",
        "-f", "null", "-"
    ]

    resultado = subprocess.run(comando, capture_output=True, text=True)
    salida = resultado.stderr

    silencios = []
    inicio = None

    for linea in salida.split('\n'):
        if 'silence_start' in linea:
            match = re.search(r'silence_start: ([\d.]+)', linea)
            if match:
                inicio = float(match.group(1))
        elif 'silence_end' in linea and inicio is not None:
            match = re.search(r'silence_end: ([\d.]+)', linea)
            if match:
                fin = float(match.group(1))
                silencios.append((inicio, fin))
                inicio = None

    # Si el video termina en silencio
    if inicio is not None:
        duracion = obtener_duracion(video_path)
        if duracion:
            silencios.append((inicio, duracion))

    print(f"{amarillo(str(len(silencios)))} silencios encontrados")
    return silencios


def silencios_a_segmentos_activos(silencios, duracion_total, margen=0.05):
    """Convierte lista de silencios en segmentos de audio activo a conservar."""
    segmentos = []
    cursor = 0.0

    for inicio_sil, fin_sil in silencios:
        inicio_sil_ajustado = max(0, inicio_sil - margen)
        fin_sil_ajustado    = min(duracion_total, fin_sil + margen)

        if cursor < inicio_sil_ajustado:
            segmentos.append((cursor, inicio_sil_ajustado))

        cursor = fin_sil_ajustado

    if cursor < duracion_total:
        segmentos.append((cursor, duracion_total))

    return segmentos


def editar_video(video_path, segmentos, salida_path):
    """Corta y une los segmentos activos usando ffmpeg."""
    if not segmentos:
        print(rojo("  Error: no hay segmentos de audio para procesar."))
        return False

    print(f"  {azul('Editando...')}  ", end="", flush=True)
    inicio_tiempo = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        if len(segmentos) > 50:
            exito = _editar_por_lista(video_path, segmentos, salida_path, tmpdir)
        else:
            exito = _editar_por_filtro(video_path, segmentos, salida_path)

    if exito:
        segundos = time.time() - inicio_tiempo
        print(verde(f"Listo  ({segundos:.1f}s)"))

    return exito


def _editar_por_filtro(video_path, segmentos, salida_path):
    """Metodo rapido con filter_complex (para 50 segmentos o menos)."""
    filter_parts = []
    for i, (inicio, fin) in enumerate(segmentos):
        filter_parts.append(
            f"[0:v]trim=start={inicio:.4f}:end={fin:.4f},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={inicio:.4f}:end={fin:.4f},asetpts=PTS-STARTPTS[a{i}]"
        )

    concat_v = "".join(f"[v{i}]" for i in range(len(segmentos)))
    concat_a = "".join(f"[a{i}]" for i in range(len(segmentos)))
    filter_concat = (
        ";".join(filter_parts) +
        f";{concat_v}concat=n={len(segmentos)}:v=1:a=0[vout]"
        f";{concat_a}concat=n={len(segmentos)}:v=0:a=1[aout]"
    )

    comando = [
        "ffmpeg", "-y", "-i", video_path,
        "-filter_complex", filter_concat,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        salida_path
    ]

    resultado = subprocess.run(comando, capture_output=True, text=True)

    if resultado.returncode != 0:
        print(rojo(f"\n  Error ffmpeg:"))
        print(gris(resultado.stderr[-1500:]))
        return False

    return True


def _editar_por_lista(video_path, segmentos, salida_path, tmpdir):
    """Metodo alternativo para videos con muchos cortes (mas de 50 segmentos)."""
    print(f"\n  {gris('(muchos segmentos, usando metodo por lista...)')}")
    clips = []
    lista_archivo = os.path.join(tmpdir, "lista.txt")

    for i, (inicio, fin) in enumerate(segmentos):
        clip_path = os.path.join(tmpdir, f"clip_{i:04d}.mp4")
        duracion  = fin - inicio
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(inicio), "-i", video_path,
             "-t", str(duracion), "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", clip_path],
            capture_output=True
        )
        clips.append(clip_path)
        print(f"\r  Extrayendo segmento {i+1}/{len(segmentos)}...", end="", flush=True)

    with open(lista_archivo, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    resultado = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lista_archivo,
         "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", "-b:a", "192k",
         salida_path],
        capture_output=True, text=True
    )

    if resultado.returncode != 0:
        print(rojo(f"\n  Error al concatenar:"))
        print(gris(resultado.stderr[-1000:]))
        return False

    return True


def procesar_video(video_path, args):
    """Procesa un unico video: detecta silencios y edita."""
    nombre      = os.path.basename(video_path)
    nombre_base = os.path.splitext(nombre)[0]
    extension   = os.path.splitext(nombre)[1]
    salida_path = os.path.join(CARPETA_OUTPUT, f"{nombre_base}_editado{extension}")

    duracion = obtener_duracion(video_path)
    dur_fmt  = ""
    if duracion:
        dur_fmt = f"  [{int(duracion//60)}:{duracion%60:05.2f}]"

    print(f"\n{'─'*58}")
    print(f"  {negrita(nombre)}{gris(dur_fmt)}")

    # Detectar silencios
    silencios = detectar_silencios(video_path, args.umbral, args.min_silencio)

    if not silencios:
        print(f"  {verde('Sin silencios detectables.')}")
        if not args.modo_analisis:
            print(gris("  (El video se copia tal cual a output_videos)"))
            import shutil
            shutil.copy2(video_path, salida_path)
        return True

    # Resumen de silencios
    total_sil = sum(fin - ini for ini, fin in silencios)
    pct       = (total_sil / duracion * 100) if duracion else 0
    print(f"  {gris(f'Tiempo en silencio: {total_sil:.1f}s ({pct:.0f}%)')}"
          f"  ->  {verde(f'se recuperan {total_sil:.1f}s')}")

    if args.modo_analisis:
        return True

    # Editar
    segmentos = silencios_a_segmentos_activos(silencios, duracion, args.margen)
    exito     = editar_video(video_path, segmentos, salida_path)

    if exito and os.path.exists(salida_path):
        dur_final = obtener_duracion(salida_path)
        tamanio_mb = os.path.getsize(salida_path) / (1024 * 1024)
        if dur_final:
            print(f"  {gris(f'Duracion final: {int(dur_final//60)}:{dur_final%60:05.2f}  |  {tamanio_mb:.1f} MB')}")
        print(f"  {verde('Guardado:')} {gris(os.path.basename(salida_path))}")

    return exito


def main():
    parser = argparse.ArgumentParser(
        description="Elimina silencios de todos los videos en input_videos/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--umbral",        type=float, default=-30,
                        help="Umbral de silencio en dB (defecto: -30)")
    parser.add_argument("--min-silencio",  type=float, default=0.4,
                        help="Duracion minima del silencio en segundos (defecto: 0.4)")
    parser.add_argument("--margen",        type=float, default=0.05,
                        help="Margen en segundos alrededor del corte (defecto: 0.05)")
    parser.add_argument("--modo-analisis", action="store_true",
                        help="Solo analiza, no edita")
    args = parser.parse_args()

    # ─── Cabecera ────────────────────────────────────────────────────────────
    print("\n" + "=" * 58)
    print(negrita("  ELIMINADOR DE SILENCIOS"))
    print(f"  {gris(f'Umbral: {args.umbral} dB  |  Min. silencio: {args.min_silencio}s  |  Margen: {args.margen}s')}")
    print("=" * 58)

    # ─── Verificaciones ──────────────────────────────────────────────────────
    if not verificar_ffmpeg():
        sys.exit(1)

    # Crear carpetas si no existen
    os.makedirs(CARPETA_INPUT,  exist_ok=True)
    os.makedirs(CARPETA_OUTPUT, exist_ok=True)

    print(f"\n  Input:   {azul(CARPETA_INPUT)}")
    print(f"  Output:  {azul(CARPETA_OUTPUT)}")

    # ─── Buscar videos en input_videos ───────────────────────────────────────
    archivos = sorted([
        f for f in os.listdir(CARPETA_INPUT)
        if os.path.splitext(f)[1].lower() in EXTENSIONES_VIDEO
    ])

    if not archivos:
        print(f"\n{amarillo('  No hay videos en la carpeta input_videos/')}")
        print(gris(f"  Formatos soportados: {', '.join(sorted(EXTENSIONES_VIDEO))}"))
        sys.exit(0)

    print(f"\n  {verde(str(len(archivos)))} video{'s' if len(archivos) != 1 else ''} encontrado{'s' if len(archivos) != 1 else ''}:")
    for f in archivos:
        print(f"    - {f}")

    if args.modo_analisis:
        print(f"\n  {amarillo('Modo analisis: no se editara ningun video')}")
    else:
        respuesta = input(f"\n  Procesar todos? [S/n]: ").strip().lower()
        if respuesta in ('n', 'no'):
            print(gris("  Cancelado.\n"))
            sys.exit(0)

    # ─── Procesar cada video ─────────────────────────────────────────────────
    ok = 0
    errores = []
    inicio_total = time.time()

    for nombre in archivos:
        video_path = os.path.join(CARPETA_INPUT, nombre)
        exito = procesar_video(video_path, args)
        if exito:
            ok += 1
        else:
            errores.append(nombre)

    # ─── Resumen final ───────────────────────────────────────────────────────
    tiempo_total = time.time() - inicio_total
    print(f"\n{'=' * 58}")
    print(verde(f"  Completado: {ok}/{len(archivos)} videos procesados  ({tiempo_total:.0f}s)"))
    if errores:
        print(rojo(f"  Errores en: {', '.join(errores)}"))
    if not args.modo_analisis:
        print(f"  Resultados en: {azul(CARPETA_OUTPUT)}")
    print("=" * 58 + "\n")


if __name__ == "__main__":
    main()