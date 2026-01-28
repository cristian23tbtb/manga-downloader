import os
import sys
import re
import json
import zipfile
import unicodedata


class CBRGenerator:
    def __init__(self):
        pass
    
    def extract_tomo_number(self, volume_name):
        match = re.search(r'(\d+)', volume_name)
        if match:
            return match.group(1)
        return "1"
    
    def extract_chapter_numbers(self, chapter_name):
        match = re.search(r'(\d+\.?\d*)', chapter_name)
        if match:
            return match.group(1)
        return "0"
    
    def count_total_chapters(self, manga_dir, metadata=None):
        total_chapters = 0
        
        if metadata and 'volumes' in metadata:
            for volume in metadata.get('volumes', []):
                total_chapters += len(volume.get('chapters', []))
            if total_chapters > 0:
                return total_chapters
        
        if not os.path.exists(manga_dir):
            return 0
        
        try:
            chapter_dirs = []
            for item in os.listdir(manga_dir):
                item_path = os.path.join(manga_dir, item)
                if os.path.isdir(item_path) and not item.endswith('.cbr'):
                    chapter_dirs.append(item_path)
            
            for chapter_dir in chapter_dirs:
                try:
                    has_subdirs = False
                    has_images = False
                    for subitem in os.listdir(chapter_dir):
                        subitem_path = os.path.join(chapter_dir, subitem)
                        if os.path.isdir(subitem_path):
                            has_subdirs = True
                        elif subitem.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                            has_images = True
                    
                    if has_subdirs:
                        for subitem in os.listdir(chapter_dir):
                            subitem_path = os.path.join(chapter_dir, subitem)
                            if os.path.isdir(subitem_path):
                                total_chapters += 1
                    elif has_images:
                        total_chapters += 1
                except:
                    continue
        except:
            pass
        
        return total_chapters
    
    def format_chapter_number(self, chapter_num, total_chapters):
        try:
            num = float(chapter_num)
            if total_chapters > 100:
                if num % 1 == 0:
                    return f"{int(num):03d}"
                else:
                    return f"{num:06.2f}".rstrip('0').rstrip('.')
            else:
                if num % 1 == 0:
                    return f"{int(num):02d}"
                else:
                    return f"{num:05.2f}".rstrip('0').rstrip('.')
        except:
            return str(chapter_num)
    
    def detect_source_type(self, volume_dir, metadata=None):
        if metadata:
            source_type = metadata.get('_source_type')
            if source_type:
                if source_type == 'mangatv' and metadata.get('_manga_type') == 'manga' and metadata.get('_tomos_structure'):
                    return 'inventario_oculto'
                if source_type == 'inventario_oculto':
                    try:
                        has_subdirs = any(os.path.isdir(os.path.join(volume_dir, item)) for item in os.listdir(volume_dir))
                        has_images = any(item.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')) for item in os.listdir(volume_dir))
                        if has_images and not has_subdirs:
                            return 'olympus_scan'
                    except:
                        pass
                return source_type
            if 'manhwa_title' in metadata:
                return 'olympus_scan'
            elif 'manga_title' in metadata:
                return 'inventario_oculto'
        
        parent_dir = os.path.dirname(volume_dir)
        manga_meta = os.path.join(parent_dir, 'manga_metadata.json')
        manhwa_meta = os.path.join(parent_dir, 'manhwa_metadata.json')
        
        if os.path.exists(manhwa_meta):
            return 'olympus_scan'
        elif os.path.exists(manga_meta):
            return 'inventario_oculto'
        
        has_subdirs = False
        has_images = False
        
        for item in os.listdir(volume_dir):
            item_path = os.path.join(volume_dir, item)
            if os.path.isdir(item_path):
                has_subdirs = True
                break
            elif item.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                has_images = True
        
        if has_images and not has_subdirs:
            return 'olympus_scan'
        elif has_subdirs:
            return 'inventario_oculto'
        
        return 'inventario_oculto'
    
    def load_metadata(self, downloads_dir):
        manga_metadata_path = os.path.join(downloads_dir, 'manga_metadata.json')
        manhwa_metadata_path = os.path.join(downloads_dir, 'manhwa_metadata.json')
        
        if os.path.exists(manhwa_metadata_path):
            try:
                with open(manhwa_metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    if not metadata.get('_source_type'):
                        metadata['_source_type'] = 'olympus_scan'
                    return metadata
            except:
                pass
        
        if os.path.exists(manga_metadata_path):
            try:
                with open(manga_metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    if not metadata.get('_source_type'):
                        metadata['_source_type'] = 'inventario_oculto'
                    return metadata
            except:
                pass
        
        return None
    
    def get_title_from_metadata(self, volume_dir, metadata):
        if metadata:
            if 'manhwa_title' in metadata:
                return metadata.get('manhwa_title', 'Manhwa')
            elif 'manga_title' in metadata:
                return metadata.get('manga_title', 'Manga')
        
        parent_dir = os.path.dirname(volume_dir)
        manhwa_title_file = os.path.join(parent_dir, 'manhwa_title.txt')
        manga_title_file = os.path.join(parent_dir, 'manga_title.txt')
        
        if os.path.exists(manhwa_title_file):
            with open(manhwa_title_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        
        if os.path.exists(manga_title_file):
            with open(manga_title_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        
        parent_dir_name = os.path.basename(os.path.dirname(volume_dir))
        if parent_dir_name and parent_dir_name != '.':
            return parent_dir_name
        
        return "Manga"
    
    def create_cbr(self, images_dir, output_path, cover_image_path=None):
        def natural_sort_key(text):
            def normalize_text(t):
                nfd = unicodedata.normalize('NFD', t)
                return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
            
            def convert(text_part):
                if text_part.isdigit():
                    return (0, int(text_part))
                try:
                    return (0, float(text_part))
                except ValueError:
                    normalized = normalize_text(text_part.lower())
                    return (1, normalized)
            parts = re.split(r'(\d+\.?\d*)', text)
            result = []
            for part in parts:
                if part:
                    result.append(convert(part))
            return result
        
        all_images = []
        for root, dirs, files in os.walk(images_dir):
            dirs.sort(key=natural_sort_key)
            files.sort(key=natural_sort_key)
            for img_file in files:
                if img_file.lower().startswith('temp_'):
                    continue
                if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    img_path = os.path.join(root, img_file)
                    rel_path = os.path.relpath(img_path, images_dir)
                    rel_path_for_sort = rel_path.replace('\\', '/')
                    all_images.append((img_path, rel_path, rel_path_for_sort))
        
        if not all_images:
            print(f"[ERROR] No se encontraron imágenes en: {images_dir}")
            return None
        
        all_images.sort(key=lambda x: natural_sort_key(x[2]))
        
        def normalize_path_for_zip(rel_path):
            def replace_decimal_dot(text):
                result = re.sub(r'(\d+)\.(\d+)', r'\1_\2', text)
                return result
            
            path_parts = rel_path.split(os.sep)
            normalized_parts = []
            for part in path_parts:
                normalized_parts.append(replace_decimal_dot(part))
            return os.sep.join(normalized_parts)
        
        normalized_images = []
        for img_path, rel_path, rel_path_for_sort in all_images:
            normalized_rel_path = normalize_path_for_zip(rel_path)
            normalized_images.append((img_path, normalized_rel_path))
        
        if cover_image_path and os.path.exists(cover_image_path):
            cover_image_path = os.path.normpath(os.path.abspath(cover_image_path))
            cover_basename = os.path.basename(cover_image_path)
            cover_tuple = None
            
            for img_tuple in all_images:
                img_path_normalized = os.path.normpath(os.path.abspath(img_tuple[0]))
                
                if (img_path_normalized == cover_image_path or 
                    (os.path.basename(img_tuple[0]) == cover_basename and 
                     os.path.dirname(img_path_normalized) == os.path.dirname(cover_image_path))):
                    cover_tuple = img_tuple
                    break
            
            if cover_tuple:
                cover_index = None
                for idx, (img_path, rel_path) in enumerate(normalized_images):
                    if img_path == cover_tuple[0]:
                        cover_index = idx
                        break
                
                if cover_index is not None:
                    cover_img_path, cover_rel_path = normalized_images.pop(cover_index)
                    extension = os.path.splitext(cover_img_path)[1]
                    if not extension:
                        extension = os.path.splitext(cover_basename)[1]
                    if not extension:
                        extension = ".jpg"
                    normalized_images.insert(0, (cover_img_path, f"00_cover{extension}"))
                    print(f"[INFO] Portada personalizada: {cover_basename} -> 00_cover{extension}")
            else:
                extension = os.path.splitext(cover_image_path)[1]
                if not extension:
                    extension = ".jpg"
                normalized_images.insert(0, (cover_image_path, f"00_cover{extension}"))
                print(f"[INFO] Portada personalizada: {cover_basename} -> 00_cover{extension}")
        
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for img_path, normalized_rel_path in normalized_images:
                zipf.write(img_path, normalized_rel_path)
        
        print(f"[OK] Archivo CBR creado: {os.path.basename(output_path)}")
        if len(normalized_images) >= 1:
            print(f"     Portada/Preview: {os.path.basename(normalized_images[0][0])}")
        return output_path
    
    def generate_cbr_inventario_oculto(self, volume_dir, output_dir, manga_title, metadata=None, cover_image_path=None):
        volume_name = os.path.basename(volume_dir)
        tomo_number = self.extract_tomo_number(volume_name)
        
        try:
            tomo_number_int = int(tomo_number)
            tomo_number_formatted = f"{tomo_number_int:02d}"
        except ValueError:
            tomo_number_formatted = tomo_number
        
        chapters = []
        for item in os.listdir(volume_dir):
            item_path = os.path.join(volume_dir, item)
            if os.path.isdir(item_path):
                chapters.append(item)
        
        if not chapters:
            print(f"[ERROR] No se encontraron capítulos en: {volume_name}")
            return None
        
        def get_chapter_sort_key(chap_name):
            chapter_num = self.extract_chapter_numbers(chap_name)
            try:
                return float(chapter_num)
            except:
                return 0.0
        
        chapters.sort(key=get_chapter_sort_key)
        first_chapter = self.extract_chapter_numbers(chapters[0])
        last_chapter = self.extract_chapter_numbers(chapters[-1])
        
        try:
            first_num = float(first_chapter)
            last_num = float(last_chapter)
            if first_num > last_num:
                first_num, last_num = last_num, first_num
                first_chapter, last_chapter = last_chapter, first_chapter
        except:
            pass
        
        manga_dir = os.path.dirname(volume_dir)
        total_chapters = self.count_total_chapters(manga_dir, metadata)
        first_chapter_formatted = self.format_chapter_number(first_chapter, total_chapters)
        last_chapter_formatted = self.format_chapter_number(last_chapter, total_chapters)
        
        cbr_filename = f"{manga_title} - Tomo {tomo_number_formatted} (#{first_chapter_formatted}-{last_chapter_formatted})"
        safe_cbr_name = re.sub(r'[<>:"/\\|?*]', '_', cbr_filename)
        cbr_path = os.path.join(output_dir, f"{safe_cbr_name}.cbr")
        
        return self.create_cbr(volume_dir, cbr_path, cover_image_path)
    
    def generate_cbr_olympus_single(self, chapter_dir, output_dir, manhwa_title, cover_image_path=None, metadata=None):
        chapter_name = os.path.basename(chapter_dir)
        chapter_number = self.extract_chapter_numbers(chapter_name)
        
        manga_dir = os.path.dirname(chapter_dir)
        total_chapters = self.count_total_chapters(manga_dir, metadata)
        chapter_number_formatted = self.format_chapter_number(chapter_number, total_chapters)
        
        cbr_filename = f"{manhwa_title} - Capítulo {chapter_number_formatted}"
        safe_cbr_name = re.sub(r'[<>:"/\\|?*]', '_', cbr_filename)
        cbr_path = os.path.join(output_dir, f"{safe_cbr_name}.cbr")
        
        return self.create_cbr(chapter_dir, cbr_path, cover_image_path)
    
    def generate_cbr_from_folder(self, volume_dir, output_dir='downloads', title=None, metadata=None, cover_image_path=None):
        if not os.path.exists(volume_dir):
            print(f"[ERROR] La carpeta no existe: {volume_dir}")
            return None
        
        source_type = self.detect_source_type(volume_dir, metadata)
        
        if not title:
            title = self.get_title_from_metadata(volume_dir, metadata)
        
        if source_type in ('olympus_scan', 'mangatv', 'lectorknight'):
            return self.generate_cbr_olympus_single(volume_dir, output_dir, title, cover_image_path, metadata)
        else:
            return self.generate_cbr_inventario_oculto(volume_dir, output_dir, title, metadata, cover_image_path)
    
    def generate_cbr_from_multiple_chapters(self, chapter_dirs, output_dir, manhwa_title, cover_image_path=None, metadata=None):
        if not chapter_dirs:
            return None
        
        def get_chapter_sort_key(chap_dir):
            chapter_name = os.path.basename(chap_dir)
            chapter_num = self.extract_chapter_numbers(chapter_name)
            try:
                return float(chapter_num)
            except:
                return 0.0
        
        chapter_dirs.sort(key=get_chapter_sort_key)
        
        if len(chapter_dirs) == 0:
            print("[ERROR] No se proporcionaron capítulos")
            return None
        
        first_chapter_name = os.path.basename(chapter_dirs[0])
        last_chapter_name = os.path.basename(chapter_dirs[-1])
        
        print(f"[DEBUG] Generando CBR para {len(chapter_dirs)} capítulos")
        print(f"[DEBUG] Primer capítulo: {first_chapter_name}")
        print(f"[DEBUG] Último capítulo: {last_chapter_name}")
        
        first_chapter = self.extract_chapter_numbers(first_chapter_name)
        last_chapter = self.extract_chapter_numbers(last_chapter_name)
        
        print(f"[DEBUG] Números extraídos - Primero: {first_chapter}, Último: {last_chapter}")
        
        if chapter_dirs:
            manga_dir = os.path.dirname(chapter_dirs[0])
            total_chapters = self.count_total_chapters(manga_dir, metadata)
        else:
            total_chapters = 0
        
        first_chapter_formatted = self.format_chapter_number(first_chapter, total_chapters)
        last_chapter_formatted = self.format_chapter_number(last_chapter, total_chapters)
        
        cbr_filename = f"{manhwa_title} - Capítulos {first_chapter_formatted}-{last_chapter_formatted}"
        print(f"[DEBUG] Nombre del CBR: {cbr_filename}")
        safe_cbr_name = re.sub(r'[<>:"/\\|?*]', '_', cbr_filename)
        cbr_path = os.path.join(output_dir, f"{safe_cbr_name}.cbr")
        
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp()
        try:
            for chapter_dir in chapter_dirs:
                chapter_name = os.path.basename(chapter_dir)
                chapter_folder = os.path.join(temp_dir, chapter_name)
                os.makedirs(chapter_folder, exist_ok=True)
                
                for root, dirs, files in os.walk(chapter_dir):
                    dirs.sort()
                    files.sort()
                    for img_file in files:
                        if img_file.lower().startswith('temp_'):
                            continue
                        if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                            src_path = os.path.join(root, img_file)
                            rel_path = os.path.relpath(src_path, chapter_dir)
                            dest_path = os.path.join(chapter_folder, rel_path)
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            shutil.copy2(src_path, dest_path)
            
            return self.create_cbr(temp_dir, cbr_path, cover_image_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def generate_all_cbrs(self, downloads_dir='downloads'):
        if not os.path.exists(downloads_dir):
            print(f"[ERROR] El directorio no existe: {downloads_dir}")
            return []
        
        metadata = self.load_metadata(downloads_dir)
        title = None
        if metadata:
            if 'manhwa_title' in metadata:
                title = metadata.get('manhwa_title')
                print(f"\n[INFO] Manhwa detectado: {title}")
            elif 'manga_title' in metadata:
                title = metadata.get('manga_title')
                print(f"\n[INFO] Manga detectado: {title}")
        
        tomo_folders = []
        for item in os.listdir(downloads_dir):
            item_path = os.path.join(downloads_dir, item)
            if os.path.isdir(item_path) and not item.endswith('.cbr'):
                tomo_folders.append(item_path)
        
        if not tomo_folders:
            print(f"[INFO] No se encontraron carpetas de tomos en: {downloads_dir}")
            return []
        
        print(f"\n{'='*60}")
        print(f"GENERADOR DE CBR")
        print(f"{'='*60}")
        print(f"\nCarpetas encontradas: {len(tomo_folders)}")
        
        generated_cbrs = []
        
        for idx, volume_dir in enumerate(tomo_folders, start=1):
            volume_name = os.path.basename(volume_dir)
            print(f"\n[{idx}/{len(tomo_folders)}] Procesando: {volume_name}")
            
            cbr_path = self.generate_cbr_from_folder(volume_dir, downloads_dir, title, metadata)
            
            if cbr_path:
                generated_cbrs.append(cbr_path)
        
        return generated_cbrs


def main():
    print("="*60)
    print("GENERADOR DE CBR - CREA ARCHIVOS CBR DESDE IMÁGENES DESCARGADAS")
    print("="*60)
    
    generator = CBRGenerator()
    
    if len(sys.argv) > 1:
        volume_dir = sys.argv[1]
        if os.path.isdir(volume_dir):
            print(f"\nGenerando CBR desde: {volume_dir}")
            cbr_path = generator.generate_cbr_from_folder(volume_dir)
            if cbr_path:
                print(f"\n{'='*60}")
                print("¡CBR GENERADO!")
                print(f"Archivo: {os.path.abspath(cbr_path)}")
                print(f"{'='*60}\n")
            else:
                print("\n[ERROR] No se pudo generar el CBR")
        else:
            print(f"[ERROR] La carpeta no existe: {volume_dir}")
    else:
        downloads_dir = 'downloads'
        generated_cbrs = generator.generate_all_cbrs(downloads_dir)
        
        if generated_cbrs:
            print(f"\n{'='*60}")
            print(f"¡GENERACIÓN COMPLETADA! ({len(generated_cbrs)} CBRs creados)")
            print(f"{'='*60}")
            print("\nArchivos CBR generados:")
            for cbr_path in generated_cbrs:
                print(f"  - {os.path.basename(cbr_path)}")
            print(f"\nUbicación: {os.path.abspath(downloads_dir)}")
            print(f"{'='*60}\n")
        else:
            print("\n[INFO] No se generaron archivos CBR")


if __name__ == '__main__':
    main()
