import os
import glob
from pathlib import Path

def delete_001_images(manga_path):
    if not os.path.exists(manga_path):
        print(f"Error: La ruta '{manga_path}' no existe")
        return
    
    deleted_count = 0
    checked_chapters = 0
    
    for chapter_dir in sorted(Path(manga_path).iterdir()):
        if not chapter_dir.is_dir():
            continue
        
        if not chapter_dir.name.startswith("Capítulo"):
            continue
        
        checked_chapters += 1
        chapter_path = chapter_dir
        
        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.webp']
        files_deleted_in_chapter = 0
        
        for ext in image_extensions:
            pattern_001 = chapter_path / f"001{ext.replace('*', '')}"
            if pattern_001.exists():
                try:
                    os.remove(pattern_001)
                    print(f"Eliminado: {chapter_path.name}/{pattern_001.name}")
                    files_deleted_in_chapter += 1
                    deleted_count += 1
                except Exception as e:
                    print(f"Error al eliminar {pattern_001}: {e}")
            
            pattern_001_webp = chapter_path / f"001-webp{ext.replace('*', '')}"
            if pattern_001_webp.exists():
                try:
                    os.remove(pattern_001_webp)
                    print(f"Eliminado: {chapter_path.name}/{pattern_001_webp.name}")
                    files_deleted_in_chapter += 1
                    deleted_count += 1
                except Exception as e:
                    print(f"Error al eliminar {pattern_001_webp}: {e}")
        
        for file_path in chapter_path.glob("001.*"):
            if file_path.is_file():
                try:
                    os.remove(file_path)
                    print(f"Eliminado: {chapter_path.name}/{file_path.name}")
                    files_deleted_in_chapter += 1
                    deleted_count += 1
                except Exception as e:
                    print(f"Error al eliminar {file_path}: {e}")
    
    print(f"\nResumen:")
    print(f"  Capítulos revisados: {checked_chapters}")
    print(f"  Archivos eliminados: {deleted_count}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    manga_path = os.path.join(script_dir, "downloads", "L.A.G")
    
    print(f"Buscando imágenes '001' en: {manga_path}")
    print("=" * 60)
    
    confirm = input("¿Estás seguro de que deseas eliminar todas las imágenes '001'? (s/n): ")
    if confirm.lower() in ['s', 'si', 'sí', 'y', 'yes']:
        delete_001_images(manga_path)
    else:
        print("Operación cancelada.")
