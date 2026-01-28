#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import zipfile
from collections import defaultdict

def extract_manga_title_and_tomo(cbr_filename):
    tomo_match = re.match(r'^(.+?)\s*-\s*Tomo\s+(\d+)', cbr_filename)
    if tomo_match:
        manga_title = tomo_match.group(1).strip()
        tomo_number = int(tomo_match.group(2))
        return manga_title, tomo_number
    
    capitulo_match = re.match(r'^(.+?)\s*-\s*Capítulo\s+(\d+\.?\d*)', cbr_filename)
    if capitulo_match:
        manga_title = capitulo_match.group(1).strip()
        try:
            tomo_number = int(float(capitulo_match.group(2)))
        except:
            tomo_number = 1
        return manga_title, tomo_number
    
    capitulos_match = re.match(r'^(.+?)\s*-\s*Capítulos\s+(\d+\.?\d*)-(\d+\.?\d*)', cbr_filename)
    if capitulos_match:
        manga_title = capitulos_match.group(1).strip()
        try:
            first_num = int(float(capitulos_match.group(2)))
            tomo_number = first_num
        except:
            tomo_number = 1
        return manga_title, tomo_number
    
    return None, None

def create_zip_from_cbrs(cbr_files, output_zip):
    try:
        if not cbr_files:
            print("[ERROR] No hay archivos CBR para incluir")
            return False
        
        for cbr_file in cbr_files:
            if not os.path.exists(cbr_file):
                print(f"[ERROR] Archivo CBR no encontrado: {cbr_file}")
                return False
        
        if os.path.exists(output_zip):
            try:
                os.remove(output_zip)
            except Exception as e:
                print(f"[ERROR] No se pudo eliminar archivo existente: {e}")
                return False
        
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for cbr_file in cbr_files:
                cbr_basename = os.path.basename(cbr_file)
                zipf.write(cbr_file, cbr_basename)
        
        if os.path.exists(output_zip) and os.path.getsize(output_zip) > 0:
            file_size_mb = os.path.getsize(output_zip) / (1024 * 1024)
            print(f"       Tamaño: {file_size_mb:.2f} MB")
            return True
        else:
            print("[ERROR] El archivo ZIP se creó pero está vacío")
            return False
    except Exception as e:
        print(f"[ERROR] Error al crear ZIP: {e}")
        import traceback
        traceback.print_exc()
        return False

def group_cbrs_by_manga(downloads_dir):
    cbr_files = []
    
    for root, dirs, files in os.walk(downloads_dir):
        for file in files:
            if file.lower().endswith('.cbr'):
                cbr_path = os.path.join(root, file)
                cbr_files.append((cbr_path, file))
    
    manga_groups = defaultdict(list)
    
    for cbr_path, cbr_filename in cbr_files:
        manga_title, tomo_number = extract_manga_title_and_tomo(cbr_filename)
        if manga_title and tomo_number:
            manga_groups[manga_title].append((tomo_number, cbr_path, cbr_filename))
    
    for manga_title in manga_groups:
        manga_groups[manga_title].sort(key=lambda x: x[0])
    
    return manga_groups

def create_zip_name(manga_title, first_tomo, last_tomo):
    safe_title = re.sub(r'[^a-zA-Z0-9]', '', manga_title)
    return f"{safe_title}-T{first_tomo:02d}-{last_tomo:02d}.zip"

def create_zips_from_cbrs(downloads_dir='downloads', tomo_range=4):
    if not os.path.exists(downloads_dir):
        print(f"[ERROR] El directorio no existe: {downloads_dir}")
        return []
    
    manga_groups = group_cbrs_by_manga(downloads_dir)
    
    if not manga_groups:
        print(f"[INFO] No se encontraron archivos CBR en: {downloads_dir}")
        return []
    
    print(f"\n{'='*60}")
    print("CREADOR DE ARCHIVOS ZIP")
    print(f"{'='*60}\n")
    print(f"Rango de tomos por ZIP: {tomo_range}")
    print(f"Mangas encontrados: {len(manga_groups)}\n")
    
    created_zips = []
    
    for manga_title, cbr_list in manga_groups.items():
        print(f"\n{'='*60}")
        print(f"Manga: {manga_title}")
        print(f"Total de tomos: {len(cbr_list)}")
        print(f"{'='*60}\n")
        
        i = 0
        while i < len(cbr_list):
            group = cbr_list[i:i+tomo_range]
            first_tomo = group[0][0]
            last_tomo = group[-1][0]
            
            zip_name = create_zip_name(manga_title, first_tomo, last_tomo)
            zip_path = os.path.join(downloads_dir, zip_name)
            
            cbr_files = [cbr_path for _, cbr_path, _ in group]
            tomo_numbers = [str(tomo) for tomo, _, _ in group]
            
            print(f"[INFO] Creando: {zip_name}")
            print(f"       Tomos incluidos: {', '.join(tomo_numbers)}")
            
            if create_zip_from_cbrs(cbr_files, zip_path):
                created_zips.append(zip_path)
                print(f"[OK] ZIP creado: {zip_name}\n")
            else:
                print(f"[ERROR] No se pudo crear: {zip_name}\n")
            
            i += tomo_range
    
    return created_zips

def main():
    print("="*60)
    print("CREADOR DE ARCHIVOS ZIP DESDE CBRs")
    print("="*60)
    
    downloads_dir = 'downloads'
    tomo_range = 4
    
    if len(sys.argv) > 1:
        downloads_dir = sys.argv[1]
    
    if len(sys.argv) > 2:
        try:
            tomo_range = int(sys.argv[2])
        except ValueError:
            print(f"[ADVERTENCIA] Rango de tomos inválido: {sys.argv[2]}. Usando 4 por defecto.")
    
    created_zips = create_zips_from_cbrs(downloads_dir, tomo_range)
    
    if created_zips:
        print(f"\n{'='*60}")
        print(f"¡GENERACIÓN COMPLETADA! ({len(created_zips)} ZIPs creados)")
        print(f"{'='*60}")
        print("\nArchivos ZIP generados:")
        for zip_path in created_zips:
            file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            print(f"  - {os.path.basename(zip_path)} ({file_size_mb:.2f} MB)")
        print(f"\nUbicación: {os.path.abspath(downloads_dir)}")
        print(f"{'='*60}\n")
    else:
        print("\n[INFO] No se generaron archivos ZIP")

if __name__ == '__main__':
    main()
