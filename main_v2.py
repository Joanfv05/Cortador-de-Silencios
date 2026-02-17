import subprocess
from pathlib import Path

# Carpetas
input_folder = Path("input_videos")
output_folder = Path("output_videos")
output_folder.mkdir(exist_ok=True)

# Verificar que existe la carpeta de entrada
if not input_folder.exists():
    print(f"ERROR: La carpeta '{input_folder}' no existe")
    exit(1)

# Listar videos disponibles
videos = list(input_folder.glob("*.mp4"))
if not videos:
    print(f"No se encontraron archivos .mp4 en '{input_folder}'")
    exit(1)

print(f"Encontrados {len(videos)} videos para procesar")

for video_file in videos:
    output_file = output_folder / f"editado_{video_file.name}"
    print(f"\nProcesando: {video_file.name}")
    
    # Comando simple que FUNCIONA
    cmd = [
        "ffmpeg",
        "-i", str(video_file),
        "-af", "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-30dB",
        "-c:v", "copy",      # Video sin cambios
        "-c:a", "aac",       # Audio recodificado sin silencios
        "-y",
        str(output_file)
    ]
    
    print(f"Ejecutando: {' '.join(cmd[:5])}...")  # Mostrar comando abreviado
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✓ COMPLETADO: {output_file.name}")
    except subprocess.CalledProcessError as e:
        print(f"✗ ERROR procesando {video_file.name}:")
        print(f"  Error: {e.stderr[:200]}")

print("\n" + "="*50)
print("¡PROCESAMIENTO COMPLETADO!")
print(f"Videos procesados: {len(videos)}")
print(f"Resultados en: {output_folder}")