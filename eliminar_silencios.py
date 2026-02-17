#!/usr/bin/env python3
"""
ELIMINADOR DE SILENCIOS - Sin perdida de calidad
=================================================

Coloca tus videos en input_videos/ y ejecuta:
    python eliminar_silencios.py

Los videos procesados apareceran en output_videos/

OPCIONES:
    --umbral         dB por debajo del cual es silencio (defecto: -30)
                     Mas negativo = menos silencios detectados (ej: -40)
                     Menos negativo = mas silencios detectados (ej: -25)

    --min-silencio   Segundos minimos para considerarlo silencio (defecto: 0.5)
    
    --margen-inicio  Segundos extra ANTES del silencio (defecto: 0.5)
                     CLAVE: Preserva el final de la frase ANTERIOR al silencio
                     Si se cortan finales de frases, AUMENTA ESTE (ej: 0.7 o 1.0)
                     
    --margen-fin     Segundos extra DESPUES del silencio (defecto: 0.15)
                     Preserva el inicio de la frase SIGUIENTE al silencio
                     
    --analisis       Solo muestra los silencios, no edita nada

COMO FUNCIONA:
    Silencio detectado: 10.0s - 12.0s
    Con margen-inicio=0.5 y margen-fin=0.15:
    → Corta desde 9.5s hasta 12.15s
    Asi preserva 0.5s antes del silencio (fin de frase anterior)

EJEMPLOS:
    # Uso basico
    python eliminar_silencios.py
    
    # Si se cortan los finales de frases, aumenta margen-inicio
    python eliminar_silencios.py --margen-inicio 0.8
    
    # Ajuste completo
    python eliminar_silencios.py --umbral -35 --min-silencio 0.6 --margen-inicio 0.7
    
    # Solo ver que detecta
    python eliminar_silencios.py --analisis
"""

import subprocess, sys, os, re, argparse, tempfile, time, shutil

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
CARPETA_INPUT  = os.path.join(SCRIPT_DIR, "input_videos")
CARPETA_OUTPUT = os.path.join(SCRIPT_DIR, "output_videos")
EXTENSIONES    = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".flv", ".webm"}

# Colores terminal
def _c(t, c): return f"\033[{c}m{t}\033[0m"
def verde(t):    return _c(t, "92")
def azul(t):     return _c(t, "94")
def amarillo(t): return _c(t, "93")
def rojo(t):     return _c(t, "91")
def bold(t):     return _c(t, "1")
def gris(t):     return _c(t, "90")


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def verificar_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except FileNotFoundError:
        print(rojo("Error: ffmpeg no encontrado."))
        print("  Windows: https://ffmpeg.org/download.html  (añadir al PATH)")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        return False


def duracion_video(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    try:    return float(r.stdout.strip())
    except: return None


def info_video(path):
    """Obtiene fps, codec de video y codec de audio."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,codec_name",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    lines = r.stdout.strip().split("\n")
    codec_v = lines[0] if len(lines) > 0 else "h264"
    fps_raw = lines[1] if len(lines) > 1 else "30/1"
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den)
    except:
        fps = 30.0

    r2 = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    codec_a = r2.stdout.strip() or "aac"
    return fps, codec_v, codec_a


# ─────────────────────────────────────────────────────────────────────────────
# DETECCION DE SILENCIOS
# ─────────────────────────────────────────────────────────────────────────────

def detectar_silencios(path, umbral_db, min_silencio):
    r = subprocess.run(
        ["ffmpeg", "-i", path,
         "-af", f"silencedetect=noise={umbral_db}dB:d={min_silencio}",
         "-f", "null", "-"],
        capture_output=True, text=True
    )
    silencios, inicio = [], None
    for linea in r.stderr.split("\n"):
        if "silence_start" in linea:
            m = re.search(r"silence_start: ([\d.]+)", linea)
            if m: inicio = float(m.group(1))
        elif "silence_end" in linea and inicio is not None:
            m = re.search(r"silence_end: ([\d.]+)", linea)
            if m:
                silencios.append((inicio, float(m.group(1))))
                inicio = None
    if inicio is not None:
        d = duracion_video(path)
        if d: silencios.append((inicio, d))
    return silencios


def calcular_segmentos(silencios, duracion, margen_inicio, margen_fin):
    """
    Convierte silencios en segmentos de voz a conservar.
    
    Los silencios son (inicio_silencio, fin_silencio).
    Los segmentos son lo que SE CONSERVA (la voz).
    
    margen_inicio: extiende el audio conservado HACIA el silencio desde antes
    margen_fin: extiende el audio conservado HACIA el silencio desde después
    """
    segmentos, cursor = [], 0.0
    for ini_sil, fin_sil in silencios:
        # Queremos conservar hasta DENTRO del silencio para no cortar frases
        # ini_sil es donde EMPIEZA el silencio, queremos conservar UN POCO MÁS
        fin_segmento = min(duracion, ini_sil + margen_inicio)
        
        # fin_sil es donde TERMINA el silencio, empezamos a conservar UN POCO ANTES  
        inicio_siguiente = max(0.0, fin_sil - margen_fin)
        
        # Agregar el segmento de voz que va desde cursor hasta fin_segmento
        if cursor < fin_segmento:
            segmentos.append((round(cursor, 4), round(fin_segmento, 4)))
        
        # Mover cursor al inicio del siguiente segmento
        cursor = inicio_siguiente
        
    # Último segmento hasta el final del video
    if cursor < duracion:
        segmentos.append((round(cursor, 4), round(duracion, 4)))
    return segmentos


# ─────────────────────────────────────────────────────────────────────────────
# EDICION RAPIDA - el truco esta aqui
# ─────────────────────────────────────────────────────────────────────────────

def editar_rapido(video_path, segmentos, salida_path):
    """
    Metodo rapido sin fades - confía en el margen para preservar el audio natural:

    1. Extrae cada segmento con -c copy (SIN recodificar, conserva todo)
    2. Los une con concat demuxer

    El margen (--margen) es clave: deja espacio antes/después para que
    las frases terminen naturalmente sin cortarse.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        clips = []

        print(f"  {azul('Extrayendo segmentos...')} ", end="", flush=True)
        t0 = time.time()

        for i, (ini, fin) in enumerate(segmentos):
            duracion_seg = fin - ini
            clip_path = os.path.join(tmpdir, f"seg_{i:05d}.mp4")

            # -c copy: copia todo sin tocar nada
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{ini:.4f}",
                "-i", video_path,
                "-t", f"{duracion_seg:.4f}",
                "-c", "copy",  # Video Y audio sin recodificar
                "-avoid_negative_ts", "1",
                clip_path
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(clip_path):
                print(rojo(f"\n  Error en segmento {i}: {r.stderr[-500:]}"))
                return False
            clips.append(clip_path)

        t_extraccion = time.time() - t0
        print(gris(f"{len(clips)} clips en {t_extraccion:.1f}s"))

        # Crear archivo de lista para concat
        lista_path = os.path.join(tmpdir, "lista.txt")
        with open(lista_path, "w", encoding="utf-8") as f:
            for clip in clips:
                ruta_normalizada = clip.replace("\\", "/")
                f.write(f"file '{ruta_normalizada}'\n")

        print(f"  {azul('Uniendo clips...')} ", end="", flush=True)
        t1 = time.time()

        # concat demuxer
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", lista_path,
            "-c", "copy",
            salida_path
        ]
        r = subprocess.run(cmd_concat, capture_output=True, text=True)

        if r.returncode != 0:
            print(rojo(f"\n  Error al unir: {r.stderr[-800:]}"))
            return False

        t_concat = time.time() - t1
        print(verde(f"OK en {t_concat:.1f}s"))

    return True


# ─────────────────────────────────────────────────────────────────────────────
# PROCESADO DE UN VIDEO
# ─────────────────────────────────────────────────────────────────────────────

def procesar_video(path, args):
    nombre    = os.path.basename(path)
    base, ext = os.path.splitext(nombre)
    salida    = os.path.join(CARPETA_OUTPUT, f"{base}_editado{ext}")

    duracion = duracion_video(path)
    dur_str  = f"[{int(duracion//60)}:{duracion%60:05.2f}]" if duracion else ""

    print(f"\n{'─'*60}")
    print(f"  {bold(nombre)}  {gris(dur_str)}")

    # Deteccion
    print(f"  {azul('Detectando silencios...')} ", end="", flush=True)
    silencios = detectar_silencios(path, args.umbral, args.min_silencio)

    if not silencios:
        print(amarillo("ninguno detectado"))
        if not args.analisis:
            print(gris("  Copiando sin cambios..."))
            shutil.copy2(path, salida)
        return True

    total_sil = sum(f - i for i, f in silencios)
    pct       = (total_sil / duracion * 100) if duracion else 0
    print(f"{amarillo(str(len(silencios)))} silencios  "
          f"({total_sil:.1f}s = {pct:.0f}% del video)")

    # Mostrar tabla resumen
    if len(silencios) <= 15:
        print(f"  {'#':>3}  {'Inicio':>7}  {'Fin':>7}  {'Dur':>6}")
        for i, (ini, fin) in enumerate(silencios, 1):
            i_fmt = f"{int(ini//60):02d}:{ini%60:05.2f}"
            f_fmt = f"{int(fin//60):02d}:{fin%60:05.2f}"
            print(gris(f"  {i:>3}  {i_fmt}  {f_fmt}  {fin-ini:>5.2f}s"))
    else:
        print(gris(f"  (tabla omitida, mas de 15 silencios)"))

    if args.analisis:
        return True

    # Edicion
    segmentos = calcular_segmentos(silencios, duracion, args.margen_inicio, args.margen_fin)
    print(f"  {gris(f'Segmentos de voz a conservar: {len(segmentos)}')}")

    exito = editar_rapido(path, segmentos, salida)

    if exito and os.path.exists(salida):
        dur_final = duracion_video(salida)
        mb        = os.path.getsize(salida) / (1024*1024)
        if dur_final:
            ahorro = duracion - dur_final if duracion else 0
            print(f"  {verde('Guardado:')} {gris(os.path.basename(salida))}")
            print(f"  {gris(f'Duracion: {int(dur_final//60)}:{dur_final%60:05.2f}')}  "
                  f"{verde(f'(ahorro: {ahorro:.1f}s)')}")
            print(f"  {gris(f'Tamanio: {mb:.1f} MB')}")
    return exito


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Elimina silencios de los videos en input_videos/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--umbral",       type=float, default=-30,
                        help="Umbral de silencio en dB (defecto: -30)")
    parser.add_argument("--min-silencio", type=float, default=0.5,
                        help="Duracion minima del silencio en segundos (defecto: 0.5)")
    parser.add_argument("--margen-inicio", type=float, default=0.5,
                        help="Segundos extra ANTES de cada corte (defecto: 0.5)")
    parser.add_argument("--margen-fin",    type=float, default=0.15,
                        help="Segundos extra DESPUES de cada corte (defecto: 0.15)")
    parser.add_argument("--analisis",     action="store_true",
                        help="Solo analiza, no edita")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print(bold("  ELIMINADOR DE SILENCIOS  (sin perdida de calidad)"))
    print(gris(f"  Umbral: {args.umbral} dB  |  Min silencio: {args.min_silencio}s"))
    print(gris(f"  Margen inicio: {args.margen_inicio}s  |  Margen fin: {args.margen_fin}s"))
    print("=" * 70)

    if not verificar_ffmpeg(): sys.exit(1)

    os.makedirs(CARPETA_INPUT,  exist_ok=True)
    os.makedirs(CARPETA_OUTPUT, exist_ok=True)

    print(f"\n  Input:   {azul(CARPETA_INPUT)}")
    print(f"  Output:  {azul(CARPETA_OUTPUT)}")

    # Buscar videos
    archivos = sorted([
        f for f in os.listdir(CARPETA_INPUT)
        if os.path.splitext(f)[1].lower() in EXTENSIONES
    ])

    if not archivos:
        print(f"\n{amarillo('  No hay videos en input_videos/')}")
        print(gris(f"  Formatos: {', '.join(sorted(EXTENSIONES))}"))
        sys.exit(0)

    print(f"\n  {verde(str(len(archivos)))} video(s) encontrado(s):")
    for f in archivos:
        d = duracion_video(os.path.join(CARPETA_INPUT, f))
        d_str = f"  [{int(d//60)}:{d%60:05.2f}]" if d else ""
        print(f"    - {f}{gris(d_str)}")

    if args.analisis:
        print(f"\n  {amarillo('Modo analisis activo: no se editara nada')}")
    else:
        r = input(f"\n  Procesar? [S/n]: ").strip().lower()
        if r in ("n", "no"):
            print(gris("  Cancelado.\n"))
            sys.exit(0)

    # Procesar
    ok, errores = 0, []
    t_inicio = time.time()

    for nombre in archivos:
        exito = procesar_video(os.path.join(CARPETA_INPUT, nombre), args)
        if exito: ok += 1
        else:     errores.append(nombre)

    # Resumen
    t_total = time.time() - t_inicio
    print(f"\n{'=' * 60}")
    print(verde(f"  Completado: {ok}/{len(archivos)} videos  ({t_total:.0f}s total)"))
    if errores:
        print(rojo(f"  Con errores: {', '.join(errores)}"))
    if not args.analisis:
        print(f"  Resultados en: {azul(CARPETA_OUTPUT)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()