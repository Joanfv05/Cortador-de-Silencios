import os
import subprocess
import sys

def pausa_final():
    input("\nPulsa ENTER para cerrar la ventana...")

print("🎬 AUTO-EDITOR – Eliminador de silencios\n")

# Carpetas (relativas al archivo .py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
carpeta_entrada = os.path.join(BASE_DIR, "input_videos")
carpeta_salida = os.path.join(BASE_DIR, "output_videos")

# Crear carpetas si no existen
os.makedirs(carpeta_entrada, exist_ok=True)
os.makedirs(carpeta_salida, exist_ok=True)

# Verificar auto-editor
try:
    subprocess.run(
        ["auto-editor", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        shell=True
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

    if extension.lower() in extensiones_validas:
        video_input = os.path.join(carpeta_entrada, archivo)
        video_output = os.path.join(carpeta_salida, f"{nombre}_editado{extension}")

        print(f"▶️ Procesando: {archivo}")

        comando = [
            "auto-editor",
            video_input,
            "--edit", "audio:threshold=0.03",
            "--margin", "0.2sec",
            "-o", video_output
        ]

        print("Ejecutando:")
        print(" ".join(comando), "\n")

        resultado = subprocess.run(comando)

        if resultado.returncode == 0:
            print(f"✅ Completado: {nombre}_editado{extension}\n")
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
