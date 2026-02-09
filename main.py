import os
import subprocess
import sys
from pathlib import Path

def pausa_final():
    input("\nPulsa ENTER para cerrar la ventana...")

print("🎬 AUTO-EDITOR – Eliminador de silencios\n")

# Carpetas relativas al script
BASE_DIR = Path(__file__).parent
carpeta_entrada = BASE_DIR / "input_videos"
carpeta_salida = BASE_DIR / "output_videos"


# Crear carpetas si no existen
carpeta_entrada.mkdir(exist_ok=True)
carpeta_salida.mkdir(exist_ok=True)

# Verificar auto-editor
try:
    subprocess.run(
        ["auto-editor", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )
    print("✅ auto-editor está instalado\n")
except:
    print("❌ auto-editor NO está instalado")
    print("👉 Instálalo con: pip install auto-editor")
    pausa_final()
    sys.exit(1)

# Extensiones válidas
extensiones_validas = [".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm"]

videos_procesados = 0

for archivo in os.listdir(carpeta_entrada):
    nombre, extension = os.path.splitext(archivo)
    if extension.lower() not in extensiones_validas:
        continue

    video_input = carpeta_entrada / archivo
    video_output = carpeta_salida / f"{nombre}_editado{extension}"

    print(f"▶️ Procesando: {archivo}")

    # Comando clásico auto-editor (análisis + edición con barra de progreso)
    comando = [
    "auto-editor",
    str(video_input),
    "--edit", "audio:threshold=0.03",  # solo corta el audio
    "--margin", "0.2sec",
    "-o", str(video_output)
]
    # Ejecutar auto-editor
    resultado = subprocess.run(comando)

    if resultado.returncode == 0:
        print(f"✅ Completado: {video_output.name}\n")
        videos_procesados += 1
    else:
        print(f"❌ Error procesando {archivo}\n")

if videos_procesados > 0:
    print(f"🎉 Procesados {videos_procesados} vídeo(s)")
    print(f"📁 Carpeta de salida: {carpeta_salida}")
else:
    print("⚠️ No se encontraron vídeos en 'input_videos'")
    print("Formatos compatibles:", ", ".join(extensiones_validas))

pausa_final()
