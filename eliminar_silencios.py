#!/usr/bin/env python3
"""
ELIMINADOR DE SILENCIOS - 1080p 60fps con GPU
==============================================

Optimizado para videos de grabación de pantalla / gameplay / tutoriales.
Exporta SIEMPRE a 1080p 60fps con codificación GPU (NVENC / VideoToolbox / VAAPI).
Márgenes ultra-ajustados para apurar al máximo entre silencios.

Coloca tus videos en input_videos/ y ejecuta:
    python eliminar_silencios.py

Los videos procesados aparecerán en output_videos/

OPCIONES:
    --umbral         dB por debajo del cual es silencio (defecto: -35)
    --min-silencio   Segundos mínimos para considerarlo silencio (defecto: 0.4)
    --margen-inicio  Segundos extra ANTES del silencio (defecto: 0.10)
    --margen-fin     Segundos extra DESPUÉS del silencio (defecto: 0.05)
    --crf            Calidad de salida 0-51, menor = mejor (defecto: 18)
    --codec          Forzar codec: nvenc | videotoolbox | vaapi | cpu
    --analisis       Solo muestra los silencios, no edita nada
    --no-escala      No forzar resolución 1080p (usa la del original)
"""

import subprocess, sys, os, re, argparse, tempfile, time, shutil, json

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
CARPETA_INPUT  = os.path.join(SCRIPT_DIR, "input_videos")
CARPETA_OUTPUT = os.path.join(SCRIPT_DIR, "output_videos")
EXTENSIONES    = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".flv", ".webm"}

FPS_SALIDA    = "60/1"      # Siempre 60fps
FPS_SALIDA_F  = 60.0
RESOLUCION    = "1920:1080" # Siempre 1080p

# ─────────────────────────────────────────────────────────────────────────────
# COLORES TERMINAL
# ─────────────────────────────────────────────────────────────────────────────
def _c(t, c): return f"\033[{c}m{t}\033[0m"
def verde(t):    return _c(t, "92")
def azul(t):     return _c(t, "94")
def amarillo(t): return _c(t, "93")
def rojo(t):     return _c(t, "91")
def bold(t):     return _c(t, "1")
def gris(t):     return _c(t, "90")
def cyan(t):     return _c(t, "96")

# ─────────────────────────────────────────────────────────────────────────────
# DETECCIÓN DE GPU
# ─────────────────────────────────────────────────────────────────────────────

def detectar_gpu():
    """
    Devuelve (nombre_codec_video, nombre_codec_audio, label, extra_params)
    Orden de preferencia: NVENC → VideoToolbox → VAAPI → CPU (libx264)
    """

    # NVENC (Nvidia) — test con frames reales, más fiable en Windows
    r = subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=256x256:r=1:d=1",
         "-frames:v", "1",
         "-c:v", "h264_nvenc",
         "-f", "null", "-"],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        return "h264_nvenc", "aac", "Nvidia NVENC (GPU)", [
            "-preset", "p4",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "{crf}",
            "-b:v", "0",
            "-profile:v", "high",
            "-level", "4.2",
            "-bf", "2",
            "-g", "120",
            "-rc-lookahead", "32",
        ]
    else:
        err_corto = ""
        if r.stderr:
            # Extraer solo la línea de error relevante
            for linea in r.stderr.split("\n"):
                if "error" in linea.lower() or "nvenc" in linea.lower() or "cuda" in linea.lower():
                    err_corto = linea.strip()
                    break
        print(amarillo(f"\n  [NVENC] {err_corto or 'no disponible'}"))
        print(gris("  Tip: actualiza drivers Nvidia desde https://www.nvidia.com/drivers"))

    # VideoToolbox (Apple Silicon / macOS)
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=16x16:d=0.1",
         "-c:v", "h264_videotoolbox", "-f", "null", "-"],
        capture_output=True
    )
    if r.returncode == 0:
        return "h264_videotoolbox", "aac", "Apple VideoToolbox (GPU)", [
            "-q:v", "45",             # VideoToolbox no usa CRF, usa calidad 1-100
            "-profile:v", "high",
        ]

    # VAAPI (Linux AMD/Intel)
    r = subprocess.run(
        ["ffmpeg", "-y", "-vaapi_device", "/dev/dri/renderD128",
         "-f", "lavfi", "-i", "nullsrc=s=16x16:d=0.1",
         "-vf", "format=nv12,hwupload",
         "-c:v", "h264_vaapi", "-f", "null", "-"],
        capture_output=True
    )
    if r.returncode == 0:
        return "h264_vaapi", "aac", "VAAPI AMD/Intel (GPU)", [
            "-vaapi_device", "/dev/dri/renderD128",
            "-vf", f"scale={RESOLUCION},format=nv12,hwupload",  # se sobrescribe después
            "-profile:v", "high",
            "-compression_level", "0",
        ]

    # CPU fallback
    return "libx264", "aac", "libx264 (CPU — sin GPU)", [
        "-preset", "fast",
        "-crf", "{crf}",
        "-profile:v", "high",
        "-level", "4.2",
        "-g", "120",
        "-bf", "2",
    ]

# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def verificar_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
        version_line = r.stdout.split("\n")[0]
        print(gris(f"  ffmpeg: {version_line}"))
        return True
    except FileNotFoundError:
        print(rojo("Error: ffmpeg no encontrado."))
        print("  Windows: https://ffmpeg.org/download.html (añadir al PATH)")
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
    """Devuelve (fps_str, fps_float, ancho, alto) del video"""
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,width,height",
         "-of", "json", path],
        capture_output=True, text=True
    )
    try:
        data   = json.loads(r.stdout)
        stream = data["streams"][0]
        raw    = stream.get("r_frame_rate", "0/1")
        num, den = raw.split("/")
        fps_f  = float(num) / float(den)
        w      = stream.get("width", 0)
        h      = stream.get("height", 0)
        return raw, round(fps_f, 3), w, h
    except:
        return None, None, 0, 0

# ─────────────────────────────────────────────────────────────────────────────
# DETECCIÓN DE SILENCIOS
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

# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO DE SEGMENTOS
# ─────────────────────────────────────────────────────────────────────────────

def calcular_segmentos(silencios, duracion, margen_inicio, margen_fin):
    """
    Corta exactamente en el inicio del silencio (para no perder ni una sílaba).
    Reanuda margen_fin segundos DESPUÉS del silencio.
    """
    segmentos, cursor = [], 0.0
    for ini_sil, fin_sil in silencios:
        # El segmento de voz termina exactamente donde empieza el silencio
        # pero le dejamos margen_inicio extra para no cortar abrupto
        fin_seg    = min(duracion, ini_sil + margen_inicio)
        ini_sig    = max(0.0, fin_sil - margen_fin)   # Empieza ANTES de que acabe el silencio

        if cursor < fin_seg - 0.02:  # Descartar segmentos de menos de 20ms
            segmentos.append((round(cursor, 4), round(fin_seg, 4)))
        cursor = max(cursor, ini_sig)

    if cursor < duracion - 0.02:
        segmentos.append((round(cursor, 4), round(duracion, 4)))
    return segmentos

# ─────────────────────────────────────────────────────────────────────────────
# EXPORTACIÓN CON GPU - PIPELINE LIMPIO
# ─────────────────────────────────────────────────────────────────────────────

def construir_filtro_video(codec, no_escala):
    """
    Construye el filtro de video para escalar + fps.
    Para VAAPI el hwupload va integrado en los extra_params.
    """
    if codec == "h264_vaapi":
        # VAAPI necesita el filtro en los extra_params, se maneja aparte
        return None
    if no_escala:
        return f"fps=fps={FPS_SALIDA_F}"
    else:
        return f"scale={RESOLUCION}:flags=lanczos,fps=fps={FPS_SALIDA_F}"

def editar_con_gpu(video_path, segmentos, salida_path, codec, extra_params, crf, no_escala):
    """
    Encoda cada segmento individualmente con GPU/CPU, luego los une con concat demuxer.
    Robusto: evita todos los problemas de timestamps con multiples inputs o stream copy.
    """
    params_codec = [p.replace("{crf}", str(crf)) for p in extra_params]

    # VAAPI no soporta bien filter_complex -- fallback a CPU
    if codec == "h264_vaapi":
        codec = "libx264"
        params_codec = ["-preset", "fast", "-crf", str(crf), "-profile:v", "high", "-level", "4.2"]

    if no_escala:
        vf = f"fps=fps={FPS_SALIDA_F}"
    else:
        vf = f"scale={RESOLUCION}:flags=lanczos,fps=fps={FPS_SALIDA_F}"

    n = len(segmentos)

    with tempfile.TemporaryDirectory() as tmpdir:
        clips = []

        print(f"  {azul('Encodando')} {gris(str(n) + ' segmentos con ' + codec + '...')} ", end="", flush=True)
        t0 = time.time()

        for i, (ini, fin) in enumerate(segmentos):
            dur_seg   = fin - ini
            clip_path = os.path.join(tmpdir, f"seg_{i:05d}.mp4")

            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{ini:.6f}", "-i", video_path, "-t", f"{dur_seg:.6f}",
                "-vf", vf,
                "-c:v", codec, *params_codec,
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-fps_mode", "cfr", "-r", str(FPS_SALIDA_F),
                "-avoid_negative_ts", "make_zero",
                clip_path
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)

            if r.returncode != 0:
                # Fallback CPU
                cmd_cpu = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{ini:.6f}", "-i", video_path, "-t", f"{dur_seg:.6f}",
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-fps_mode", "cfr", "-r", str(FPS_SALIDA_F),
                    "-avoid_negative_ts", "make_zero",
                    clip_path
                ]
                r2 = subprocess.run(cmd_cpu, capture_output=True, text=True)
                if r2.returncode != 0:
                    print(rojo(f"\n  X Error segmento {i}: {r2.stderr[-300:]}"))
                    return False

            d = duracion_video(clip_path)
            if d and d > 0.01:
                clips.append(clip_path)

            if (i + 1) % 10 == 0 or (i + 1) == n:
                print(gris(f"{i+1}/{n}.."), end="", flush=True)

        t_enc = time.time() - t0
        print(verde(f" ok {len(clips)} clips en {t_enc:.1f}s"))

        if not clips:
            print(rojo("  No se generaron clips validos."))
            return False

        # Concat final con stream copy (todos clips tienen mismo codec/resolucion)
        lista_path = os.path.join(tmpdir, "lista.txt")
        with open(lista_path, "w", encoding="utf-8") as f:
            for p in clips:
                f.write(f"file '{p.replace(chr(92), chr(47))}'\n")

        print(f"  {azul('Uniendo clips...')} ", end="", flush=True)
        t1 = time.time()
        r = subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", lista_path,
            "-c", "copy", "-movflags", "+faststart",
            salida_path
        ], capture_output=True, text=True)

        if r.returncode != 0:
            print(rojo(f"\n  X Error concat: {r.stderr[-400:]}"))
            return False

        print(verde(f"ok en {time.time()-t1:.1f}s"))

    return True
def procesar_video(path, args, codec, extra_params):
    nombre    = os.path.basename(path)
    base, ext = os.path.splitext(nombre)
    # Siempre mp4 en salida (máxima compatibilidad)
    salida    = os.path.join(CARPETA_OUTPUT, f"{base}_editado.mp4")

    duracion = duracion_video(path)
    fps_str, fps_f, w, h = info_video(path)
    dur_str  = f"[{int(duracion//60)}:{duracion%60:05.2f}]" if duracion else ""
    res_str  = f"{w}×{h}" if w else "?"

    print(f"\n{'─'*65}")
    print(f"  {bold(nombre)}  {gris(dur_str)}")
    info_orig = "Original: %s @ %sfps" % (res_str, fps_f)
    print(f"  {gris(info_orig)}  →  {cyan('Salida: 1920x1080 @ 60fps')}")

    print(f"  {azul('Detectando silencios...')} ", end="", flush=True)
    silencios = detectar_silencios(path, args.umbral, args.min_silencio)

    if not silencios:
        print(amarillo("ninguno detectado"))
        if not args.analisis:
            print(gris("  Recodificando sin cortes..."))
            # Recodificar igualmente para normalizar a 1080p60
            _recodificar_solo(path, salida, codec, extra_params, args.crf, args.no_escala)
        return True

    total_sil = sum(f - i for i, f in silencios)
    pct       = (total_sil / duracion * 100) if duracion else 0
    print(f"{amarillo(str(len(silencios)))} silencios  "
          f"({total_sil:.1f}s = {pct:.0f}% del video)")

    # Tabla de silencios (max 20)
    if len(silencios) <= 20:
        print(f"  {'#':>3}  {'Inicio':>7}  {'Fin':>7}  {'Dur':>6}")
        for i, (ini, fin) in enumerate(silencios, 1):
            i_f = f"{int(ini//60):02d}:{ini%60:05.2f}"
            f_f = f"{int(fin//60):02d}:{fin%60:05.2f}"
            print(gris(f"  {i:>3}  {i_f}  {f_f}  {fin-ini:>5.2f}s"))
    else:
        print(gris(f"  (tabla omitida: {len(silencios)} silencios — demasiados para mostrar)"))

    if args.analisis:
        return True

    segmentos = calcular_segmentos(silencios, duracion, args.margen_inicio, args.margen_fin)
    dur_total_segs = sum(f - i for i, f in segmentos)
    pct_conservado = dur_total_segs / duracion * 100
    msg_segs = "Segmentos a conservar: %d  (%.1fs de %.1fs = %.0f%%)" % (len(segmentos), dur_total_segs, duracion, pct_conservado)
    print(f"  {gris(msg_segs)}")

    exito = editar_con_gpu(path, segmentos, salida, codec, extra_params, args.crf, args.no_escala)

    if exito and os.path.exists(salida):
        dur_final = duracion_video(salida)
        _, fps_final, wf, hf = info_video(salida)
        mb = os.path.getsize(salida) / (1024*1024)
        if dur_final and duracion:
            ahorro = duracion - dur_final
            print(f"\n  {verde('✓ Guardado:')} {gris(os.path.basename(salida))}")
            dur_fmt    = "%d:%05.2f" % (int(dur_final // 60), dur_final % 60)
            ahorro_pct = ahorro / duracion * 100
            res_fmt    = "%dx%d @ %sfps" % (wf, hf, fps_final)
            print(f"  {gris('Duracion: ' + dur_fmt)}  {verde('(ahorro: %.1fs = %.0f%%)' % (ahorro, ahorro_pct))}")
            print(f"  {gris('Resolucion final: ' + res_fmt)}")
            print(f"  {gris('Tamanio: %.1f MB' % mb)}")
    return exito


def _recodificar_solo(src, dst, codec, extra_params, crf, no_escala):
    """Recodifica sin cortes (cuando no hay silencios)."""
    vf = construir_filtro_video(codec, no_escala)
    params_codec = [p.replace("{crf}", str(crf)) for p in extra_params]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if vf: cmd += ["-vf", vf]
    cmd += ["-c:v", codec, *params_codec,
            "-c:a", "aac", "-b:a", "192k",
            "-vsync", "cfr", "-r", str(FPS_SALIDA_F),
            "-movflags", "+faststart", dst]
    subprocess.run(cmd)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Elimina silencios — salida 1080p 60fps con GPU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--umbral",        type=float, default=-35,
                        help="Umbral de silencio en dB (defecto: -35)")
    parser.add_argument("--min-silencio",  type=float, default=0.4,
                        help="Duración mínima del silencio en segundos (defecto: 0.4)")
    parser.add_argument("--margen-inicio", type=float, default=0.10,
                        help="Segundos extra ANTES del corte (defecto: 0.10)")
    parser.add_argument("--margen-fin",    type=float, default=0.05,
                        help="Segundos extra DESPUÉS del corte (defecto: 0.05)")
    parser.add_argument("--crf",           type=int,   default=18,
                        help="Calidad CRF 0-51 (defecto: 18, menor = mejor)")
    parser.add_argument("--codec",         type=str,   default=None,
                        choices=["nvenc", "videotoolbox", "vaapi", "cpu"],
                        help="Forzar codec GPU (defecto: autodetección)")
    parser.add_argument("--analisis",      action="store_true",
                        help="Solo analiza silencios, no edita")
    parser.add_argument("--no-escala",     action="store_true",
                        help="No forzar resolución 1080p (mantiene la original)")
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print(bold("  ELIMINADOR DE SILENCIOS  ·  1080p 60fps · GPU"))
    print(gris(f"  Umbral: {args.umbral} dB  |  Min silencio: {args.min_silencio}s"))
    print(gris(f"  Margen inicio: {args.margen_inicio}s  |  Margen fin: {args.margen_fin}s"))
    print(gris(f"  CRF calidad: {args.crf}  |  Salida: 1920×1080 @ 60fps"))
    print("=" * 65)

    if not verificar_ffmpeg():
        sys.exit(1)

    # ── Detección / selección de GPU ─────────────────────────────────────────
    if args.codec:
        mapa = {
            "nvenc":         ("h264_nvenc",         "aac", "Nvidia NVENC (forzado)",   ["-preset","p4","-tune","hq","-rc","vbr","-cq","{crf}","-b:v","0","-profile:v","high","-level","4.2","-g","120"]),
            "videotoolbox":  ("h264_videotoolbox",  "aac", "VideoToolbox (forzado)",   ["-q:v","45","-profile:v","high"]),
            "vaapi":         ("h264_vaapi",          "aac", "VAAPI (forzado)",          ["-profile:v","high","-compression_level","0"]),
            "cpu":           ("libx264",             "aac", "libx264 CPU (forzado)",    ["-preset","fast","-crf","{crf}","-profile:v","high","-level","4.2","-g","120"]),
        }
        codec, codec_audio, label, extra_params = mapa[args.codec]
    else:
        print(f"\n  {azul('Detectando GPU...')} ", end="", flush=True)
        codec, codec_audio, label, extra_params = detectar_gpu()
        print(verde(label))

    print(f"  {cyan('Codec: ' + label)}")

    os.makedirs(CARPETA_INPUT,  exist_ok=True)
    os.makedirs(CARPETA_OUTPUT, exist_ok=True)

    print(f"\n  Input:   {azul(CARPETA_INPUT)}")
    print(f"  Output:  {azul(CARPETA_OUTPUT)}")

    archivos = sorted([
        f for f in os.listdir(CARPETA_INPUT)
        if os.path.splitext(f)[1].lower() in EXTENSIONES
    ])

    if not archivos:
        print(f"\n{amarillo('  No hay videos en input_videos/')}")
        print(gris(f"  Formatos soportados: {', '.join(sorted(EXTENSIONES))}"))
        sys.exit(0)

    print(f"\n  {verde(str(len(archivos)))} video(s) encontrado(s):")
    for f in archivos:
        path = os.path.join(CARPETA_INPUT, f)
        d = duracion_video(path)
        _, fps_f, w, h = info_video(path)
        d_str  = f"  [{int(d//60)}:{d%60:05.2f}]" if d else ""
        res_str = f"  {w}×{h}@{fps_f}fps" if w else ""
        print(f"    - {f}{gris(d_str + res_str)}")

    if args.analisis:
        print(f"\n  {amarillo('Modo análisis activo: no se editará nada')}")
    else:
        r = input(f"\n  ¿Procesar? [S/n]: ").strip().lower()
        if r in ("n", "no"):
            print(gris("  Cancelado.\n"))
            sys.exit(0)

    ok, errores = 0, []
    t_inicio = time.time()

    for nombre in archivos:
        exito = procesar_video(
            os.path.join(CARPETA_INPUT, nombre),
            args, codec, extra_params
        )
        if exito: ok += 1
        else:     errores.append(nombre)

    t_total = time.time() - t_inicio
    print(f"\n{'=' * 65}")
    print(verde(f"  ✓ Completado: {ok}/{len(archivos)} videos  ({t_total:.0f}s total)"))
    if errores:
        print(rojo(f"  ✗ Con errores: {', '.join(errores)}"))
    if not args.analisis:
        print(f"  Resultados en: {azul(CARPETA_OUTPUT)}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()