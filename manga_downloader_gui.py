import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import shutil
import re
import unicodedata
import json
from manga_downloader import MangaDownloader, load_config, save_metadata
from olympus_scan_downloader import OlympusScanDownloader, save_metadata as save_metadata_olympus
from mangatv_downloader import MangaTVDownloader, save_metadata as save_metadata_mangatv
from lectorknight_downloader import LectorKnightDownloader, save_metadata as save_metadata_lectorknight
from zonatmo_downloader import ZonaTMODownloader, save_metadata as save_metadata_zonatmo
from tomosmanga_downloader import TomosMangaDownloader, save_metadata as save_metadata_tomosmanga
from cbr_generator import CBRGenerator
from create_rar import group_cbrs_by_manga, create_zip_from_cbrs, create_zip_name, extract_manga_title_and_tomo

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class MangaDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Descargador de Manga - Generador de CBR")
        self.root.geometry("900x700")
        
        self.config = load_config()
        self.website_names = {
            'Inventario Oculto': 'inventario_oculto',
            'Olympus Scan': 'olympus_scan',
            'MangaTV': 'mangatv',
            'Lector KNS': 'lectorknight',
            'ZonaTMO': 'zonatmo',
            'TomosManga': 'tomosmanga'
        }
        self.website_ids = {v: k for k, v in self.website_names.items()}
        self.selected_website = tk.StringVar(value='inventario_oculto')
        self.selected_website_name = tk.StringVar(value='Inventario Oculto')
        self.logo_label = None
        self.logo_image_ref = None
        self.downloader = None
        self.volumes = []
        self.manga_title = ""
        self.manga_type = "manga"
        self.download_thread = None
        self.is_downloading = False
        self.load_thread = None
        self.is_loading_cancelled = False
        self.checkboxes = []
        self.selected_cover = {}
        self.mode = tk.StringVar(value="download")
        self.cbr_checkboxes = []
        self.rar_checkboxes = []
        self.mangas_data = []
        self.rar_mangas_data = []
        self.generator = CBRGenerator()
        self.tomos_structure = None
        
        self.setup_ui()
    
    def get_volume_label(self):
        if self.selected_website.get() == 'olympus_scan' or self.selected_website.get() == 'mangatv' or self.selected_website.get() == 'lectorknight' or self.selected_website.get() == 'zonatmo' or self.selected_website.get() == 'tomosmanga':
            return "Capítulos"
        return "Tomos"
    
    def update_website_logo(self):
        for widget in self.logo_frame.winfo_children():
            widget.destroy()
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        website_id = self.selected_website.get()
        
        logo_path = None
        if website_id == 'inventario_oculto':
            logo_path = os.path.join(script_dir, 'logos', 'logo_inventario_oculto.png')
        elif website_id == 'olympus_scan':
            logo_path = os.path.join(script_dir, 'logos', 'logo_olympus_scan.webp')
        elif website_id == 'mangatv':
            logo_path = os.path.join(script_dir, 'logos', 'logo_manga_tv.png')
        elif website_id == 'lectorknight':
            logo_path = os.path.join(script_dir, 'logos', 'logo_knight.png')
        elif website_id == 'zonatmo':
            logo_path = os.path.join(script_dir, 'logos', 'logo_zonatmo.png')
        elif website_id == 'tomosmanga':
            logo_path = os.path.join(script_dir, 'logos', 'logo_tomosmanga.png')
        
        if logo_path and PIL_AVAILABLE and os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                max_size = (80, 50)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                logo_image = ImageTk.PhotoImage(img)
                
                if website_id == 'mangatv':
                    self.logo_label = tk.Label(self.logo_frame, image=logo_image, bg='black')
                    self.logo_label.image = logo_image
                    self.logo_label.pack()
                else:
                    self.logo_label = ttk.Label(self.logo_frame, image=logo_image)
                    self.logo_label.image = logo_image
                    self.logo_label.pack()
            except Exception as e:
                print(f"[ADVERTENCIA] No se pudo cargar logo: {e}")
    
    def on_website_change(self, event=None):
        selected_name = self.selected_website_name.get()
        website_id = self.website_names.get(selected_name, 'inventario_oculto')
        self.selected_website.set(website_id)
        self.update_website_logo()
        volume_label = self.get_volume_label()
        self.volumes_label.config(text=f"{volume_label} Disponibles:")
        self.load_btn.config(text=f"Cargar {volume_label}")
        
        if website_id == 'olympus_scan' or website_id == 'mangatv' or website_id == 'lectorknight' or website_id == 'zonatmo' or website_id == 'tomosmanga':
            self.url_label.config(text="URL del Manga/Manhwa:")
        else:
            self.url_label.config(text="URL del Manga:")
    
    def detect_website_from_url(self, url):
        if not url:
            return None
        
        url_lower = url.lower()
        
        if 'lectorknight.com' in url_lower or 'lectorknight' in url_lower:
            return 'lectorknight'
        elif 'zonatmo.com' in url_lower or 'zonatmo' in url_lower:
            return 'zonatmo'
        elif 'mangatv.net' in url_lower or 'mangatv' in url_lower:
            return 'mangatv'
        elif 'olympusbiblioteca.com' in url_lower or 'olympusbiblioteca' in url_lower:
            return 'olympus_scan'
        elif 'inventariooculto.com' in url_lower or 'inventariooculto' in url_lower:
            return 'inventario_oculto'
        elif 'tomosmanga.com' in url_lower or 'tomosmanga' in url_lower:
            return 'tomosmanga'
        
        return None
    
    def validate_url_length(self, value):
        return len(value) <= 150
    
    def on_paste(self, event=None):
        self.root.after(100, self.validate_pasted_url)
        return None
    
    def validate_pasted_url(self):
        current_text = self.url_entry.get()
        if len(current_text) > 150:
            self.url_entry.delete(150, 'end')
            self.log(f"URL truncada a 150 caracteres (tamaño original: {len(current_text)})")
        self.on_url_change()
    
    def on_url_change(self, event=None):
        url = self.url_entry.get().strip()
        if url:
            detected_website = self.detect_website_from_url(url)
            if detected_website and detected_website != self.selected_website.get():
                website_name = self.website_ids.get(detected_website)
                if website_name:
                    self.selected_website_name.set(website_name)
                    self.selected_website.set(detected_website)
                    self.update_website_logo()
                    volume_label = self.get_volume_label()
                    self.volumes_label.config(text=f"{volume_label} Disponibles:")
                    self.load_btn.config(text=f"Cargar {volume_label}")
                    
                    if detected_website in ['olympus_scan', 'mangatv', 'lectorknight', 'zonatmo']:
                        self.url_label.config(text="URL del Manga/Manhwa:")
                    else:
                        self.url_label.config(text="URL del Manga:")
    
    def cancel_load(self):
        self.is_loading_cancelled = True
        if self.downloader:
            self.downloader.cancelled = True
        self.load_btn.config(state='normal')
        self.cancel_load_btn.config(state='disabled')
        self.url_entry.config(state='normal')
        self.progress_bar.stop()
        self.progress_var.set("Carga cancelada")
        self.log("Carga cancelada por el usuario")
    
    def detect_source_type_from_dir(self, directory):
        if not os.path.exists(directory):
            return None
        
        items = []
        try:
            items = os.listdir(directory)
        except:
            return None
        has_tomos = any('Tomo' in item or 'Volumen' in item for item in items)
        has_capitulos = any(('Capítulo' in item) or ('Capitulo' in item) for item in items)
        if has_capitulos and not has_tomos:
            return 'olympus_scan'
        if has_tomos:
            return 'inventario_oculto'

        metadata = self.generator.load_metadata(directory)
        if metadata:
            source_type = metadata.get('_source_type')
            if source_type:
                return source_type

        try:
            subdirs = [os.path.join(directory, item) for item in items if os.path.isdir(os.path.join(directory, item))]
            for sd in subdirs[:50]:
                try:
                    files = os.listdir(sd)
                except:
                    continue
                if any(f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')) for f in files):
                    return 'olympus_scan'
        except:
            pass
        manga_meta = os.path.join(directory, 'manga_metadata.json')
        manhwa_meta = os.path.join(directory, 'manhwa_metadata.json')
        
        if os.path.exists(manhwa_meta):
            return 'olympus_scan'
        elif os.path.exists(manga_meta):
            return 'inventario_oculto'
        
        return None
    
    def get_title_from_directory(self, directory):
        if not os.path.exists(directory):
            return "Manga"
        metadata = self.generator.load_metadata(directory)
        return self.generator.get_title_from_metadata(directory, metadata)
    
    def load_content_list(self, output_dir):
        if not os.path.exists(output_dir):
            return []
        
        content_list = []
        items_found = os.listdir(output_dir)
        
        root_metadata = self.generator.load_metadata(output_dir)
        if root_metadata:
            source_type = root_metadata.get('_source_type', 'inventario_oculto')
            if 'manhwa_title' in root_metadata:
                title = root_metadata.get('manhwa_title', 'Manhwa')
            else:
                title = root_metadata.get('manga_title', 'Manga')
            content_list.append({
                'title': title,
                'folder': '.',
                'source_type': source_type
            })
            return content_list
        
        for item in items_found:
            item_path = os.path.join(output_dir, item)
            if not os.path.isdir(item_path) or item.endswith('.cbr'):
                continue
            
            source_type = self.detect_source_type_from_dir(item_path)
            if source_type:
                title = self.get_title_from_directory(item_path)
                content_list.append({
                    'title': title,
                    'folder': item,
                    'source_type': source_type
                })
            else:
                has_tomos = any('Tomo' in subitem or 'Volumen' in subitem 
                              for subitem in os.listdir(item_path) 
                              if os.path.isdir(os.path.join(item_path, subitem)))
                if has_tomos:
                    content_list.append({
                        'title': item,
                        'folder': item,
                        'source_type': 'inventario_oculto'
                    })
        
        return content_list
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        mode_frame = ttk.LabelFrame(main_frame, text="Modo de Operación", padding="10")
        mode_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Radiobutton(mode_frame, text="Descargar Manga", variable=self.mode, value="download", command=self.on_mode_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="Crear CBR", variable=self.mode, value="cbr", command=self.on_mode_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="Crear RAR", variable=self.mode, value="rar", command=self.on_mode_change).pack(side=tk.LEFT, padx=10)
        
        self.download_frame = ttk.Frame(main_frame)
        self.download_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.download_frame.columnconfigure(1, weight=1)
        self.download_frame.rowconfigure(4, weight=1, minsize=150)
        
        website_frame = ttk.Frame(self.download_frame)
        website_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        website_frame.columnconfigure(1, weight=1)
        
        ttk.Label(website_frame, text="Sitio Web:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        
        website_combo = ttk.Combobox(website_frame, textvariable=self.selected_website_name, 
                                     values=list(self.website_names.keys()),
                                     state='readonly', width=25)
        website_combo.set('Inventario Oculto')
        website_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        website_combo.bind('<<ComboboxSelected>>', self.on_website_change)
        self.website_combo = website_combo
        
        self.logo_frame = ttk.Frame(website_frame)
        self.logo_frame.grid(row=0, column=2, sticky=tk.E, padx=5, pady=5)
        self.update_website_logo()
        
        self.url_label = ttk.Label(self.download_frame, text="URL del Manga:")
        self.url_label.grid(row=1, column=0, sticky=tk.W, pady=5)
        url_frame = ttk.Frame(self.download_frame)
        url_frame.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        url_frame.columnconfigure(0, weight=1)
        
        vcmd = (self.root.register(self.validate_url_length), '%P')
        self.url_entry = ttk.Entry(url_frame, width=60, validate='key', validatecommand=vcmd)
        self.url_entry.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.url_entry.bind('<KeyRelease>', self.on_url_change)
        self.url_entry.bind('<FocusOut>', self.on_url_change)
        self.url_entry.bind('<Control-v>', self.on_paste)
        self.url_entry.bind('<Button-2>', self.on_paste)
        
        volume_label = self.get_volume_label()
        self.load_btn = ttk.Button(self.download_frame, text=f"Cargar {volume_label}", command=self.load_volumes)
        self.load_btn.grid(row=1, column=2, padx=5, pady=5)
        
        self.cancel_load_btn = ttk.Button(self.download_frame, text="Cancelar Carga", command=self.cancel_load, state='disabled')
        self.cancel_load_btn.grid(row=1, column=3, padx=5, pady=5)
        
        ttk.Label(self.download_frame, text="Título:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.title_label = ttk.Label(self.download_frame, text="", foreground="blue")
        self.title_label.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        self.volumes_label = ttk.Label(self.download_frame, text=f"{volume_label} Disponibles:")
        self.volumes_label.grid(row=3, column=0, sticky=tk.W, pady=5)
        
        list_frame = ttk.Frame(self.download_frame)
        list_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        list_frame.config(height=200)
        
        canvas = tk.Canvas(list_frame, height=200)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        def bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)
        def unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", bind_mousewheel)
        canvas.bind("<Leave>", unbind_mousewheel)
        self.scrollable_frame.bind("<Enter>", bind_mousewheel)
        self.scrollable_frame.bind("<Leave>", unbind_mousewheel)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.volumes_frame = self.scrollable_frame
        
        buttons_frame = ttk.Frame(self.download_frame)
        buttons_frame.grid(row=5, column=0, columnspan=3, pady=10, sticky=(tk.W, tk.E))
        
        self.select_all_btn = ttk.Button(buttons_frame, text="Seleccionar Todos", command=self.select_all)
        self.select_all_btn.pack(side=tk.LEFT, padx=5)
        
        self.deselect_all_btn = ttk.Button(buttons_frame, text="Deseleccionar Todos", command=self.deselect_all)
        self.deselect_all_btn.pack(side=tk.LEFT, padx=5)
        
        self.download_btn = ttk.Button(buttons_frame, text="Descargar Seleccionados", command=self.start_download)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        self.cancel_btn = ttk.Button(buttons_frame, text="Cancelar", command=self.cancel_download, state='disabled')
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
        
        self.cbr_frame = ttk.LabelFrame(main_frame, text="Generar CBRs", padding="10")
        self.cbr_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.cbr_frame.columnconfigure(1, weight=1)
        self.cbr_frame.rowconfigure(2, weight=1)
        
        ttk.Label(self.cbr_frame, text="Manga:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.manga_combo = ttk.Combobox(self.cbr_frame, state='readonly', width=40)
        self.manga_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        self.manga_combo.bind('<<ComboboxSelected>>', self.on_manga_selected)
        
        self.load_mangas_btn = ttk.Button(self.cbr_frame, text="Cargar Mangas", command=self.load_available_mangas)
        self.load_mangas_btn.grid(row=0, column=2, padx=5, pady=5)
        
        ttk.Label(self.cbr_frame, text="Tomos:").grid(row=1, column=0, sticky=tk.W, pady=5)
        
        self.chapters_per_group_frame = ttk.Frame(self.cbr_frame)
        self.chapters_per_group_frame.grid(row=1, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        self.chapters_per_group_frame.grid_remove()
        
        ttk.Label(self.chapters_per_group_frame, text="Capítulos por grupo:").pack(side=tk.LEFT, padx=5)
        self.chapters_per_group_var = tk.IntVar(value=5)
        self.chapters_per_group_spin = ttk.Spinbox(self.chapters_per_group_frame, from_=1, to=100, width=10, textvariable=self.chapters_per_group_var, command=self.update_chapter_groups)
        self.chapters_per_group_spin.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.chapters_per_group_frame, text="Aplicar", command=self.update_chapter_groups).pack(side=tk.LEFT, padx=5)
        
        cbr_list_frame = ttk.Frame(self.cbr_frame)
        cbr_list_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        cbr_list_frame.columnconfigure(0, weight=1)
        cbr_list_frame.rowconfigure(0, weight=1)
        
        cbr_canvas = tk.Canvas(cbr_list_frame, height=100)
        cbr_scrollbar = ttk.Scrollbar(cbr_list_frame, orient="vertical", command=cbr_canvas.yview)
        self.cbr_scrollable_frame = ttk.Frame(cbr_canvas)
        
        self.cbr_scrollable_frame.bind(
            "<Configure>",
            lambda e: cbr_canvas.configure(scrollregion=cbr_canvas.bbox("all"))
        )
        
        cbr_canvas.create_window((0, 0), window=self.cbr_scrollable_frame, anchor="nw")
        cbr_canvas.configure(yscrollcommand=cbr_scrollbar.set)
        
        def on_cbr_mousewheel(event):
            cbr_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        def bind_cbr_mousewheel(event):
            cbr_canvas.bind_all("<MouseWheel>", on_cbr_mousewheel)
        def unbind_cbr_mousewheel(event):
            cbr_canvas.unbind_all("<MouseWheel>")
        cbr_canvas.bind("<Enter>", bind_cbr_mousewheel)
        cbr_canvas.bind("<Leave>", unbind_cbr_mousewheel)
        self.cbr_scrollable_frame.bind("<Enter>", bind_cbr_mousewheel)
        self.cbr_scrollable_frame.bind("<Leave>", unbind_cbr_mousewheel)
        
        cbr_canvas.pack(side="left", fill="both", expand=True)
        cbr_scrollbar.pack(side="right", fill="y")
        
        self.cbr_volumes_frame = self.cbr_scrollable_frame
        
        cbr_buttons_frame = ttk.Frame(self.cbr_frame)
        cbr_buttons_frame.grid(row=3, column=0, columnspan=3, pady=5)
        
        self.select_all_cbr_btn = ttk.Button(cbr_buttons_frame, text="Seleccionar Todos", command=self.select_all_cbr)
        self.select_all_cbr_btn.pack(side=tk.LEFT, padx=5)
        
        self.deselect_all_cbr_btn = ttk.Button(cbr_buttons_frame, text="Deseleccionar Todos", command=self.deselect_all_cbr)
        self.deselect_all_cbr_btn.pack(side=tk.LEFT, padx=5)
        
        self.select_cover_btn = ttk.Button(cbr_buttons_frame, text="Seleccionar Portada", command=self.select_cover_image)
        self.select_cover_btn.pack(side=tk.LEFT, padx=5)
        
        self.generate_cbr_btn = ttk.Button(cbr_buttons_frame, text="Generar CBRs Seleccionados", command=self.generate_cbrs)
        self.generate_cbr_btn.pack(side=tk.LEFT, padx=5)
        
        self.rar_frame = ttk.LabelFrame(main_frame, text="Generar RARs", padding="10")
        self.rar_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.rar_frame.columnconfigure(1, weight=1)
        self.rar_frame.rowconfigure(2, weight=1)
        
        ttk.Label(self.rar_frame, text="Manga:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.rar_manga_combo = ttk.Combobox(self.rar_frame, state='readonly', width=40)
        self.rar_manga_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        self.rar_manga_combo.bind('<<ComboboxSelected>>', self.on_rar_manga_selected)
        
        self.load_rar_mangas_btn = ttk.Button(self.rar_frame, text="Cargar Mangas", command=self.load_rar_mangas)
        self.load_rar_mangas_btn.grid(row=0, column=2, padx=5, pady=5)
        
        ttk.Label(self.rar_frame, text="Tomos por RAR:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.tomos_per_rar_var = tk.StringVar(value="4")
        tomos_spinbox = ttk.Spinbox(self.rar_frame, from_=1, to=20, textvariable=self.tomos_per_rar_var, width=10)
        tomos_spinbox.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        
        ttk.Label(self.rar_frame, text="CBRs:").grid(row=2, column=0, sticky=tk.W, pady=5)
        
        rar_list_frame = ttk.Frame(self.rar_frame)
        rar_list_frame.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        rar_list_frame.columnconfigure(0, weight=1)
        rar_list_frame.rowconfigure(0, weight=1)
        
        rar_canvas = tk.Canvas(rar_list_frame, height=100)
        rar_scrollbar = ttk.Scrollbar(rar_list_frame, orient="vertical", command=rar_canvas.yview)
        self.rar_scrollable_frame = ttk.Frame(rar_canvas)
        
        self.rar_scrollable_frame.bind(
            "<Configure>",
            lambda e: rar_canvas.configure(scrollregion=rar_canvas.bbox("all"))
        )
        
        rar_canvas.create_window((0, 0), window=self.rar_scrollable_frame, anchor="nw")
        rar_canvas.configure(yscrollcommand=rar_scrollbar.set)
        
        def on_rar_mousewheel(event):
            rar_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        def bind_rar_mousewheel(event):
            rar_canvas.bind_all("<MouseWheel>", on_rar_mousewheel)
        def unbind_rar_mousewheel(event):
            rar_canvas.unbind_all("<MouseWheel>")
        rar_canvas.bind("<Enter>", bind_rar_mousewheel)
        rar_canvas.bind("<Leave>", unbind_rar_mousewheel)
        self.rar_scrollable_frame.bind("<Enter>", bind_rar_mousewheel)
        self.rar_scrollable_frame.bind("<Leave>", unbind_rar_mousewheel)
        
        rar_canvas.pack(side="left", fill="both", expand=True)
        rar_scrollbar.pack(side="right", fill="y")
        
        self.rar_cbrs_frame = self.rar_scrollable_frame
        
        rar_buttons_frame = ttk.Frame(self.rar_frame)
        rar_buttons_frame.grid(row=3, column=0, columnspan=3, pady=5)
        
        self.select_all_rar_btn = ttk.Button(rar_buttons_frame, text="Seleccionar Todos", command=self.select_all_rar)
        self.select_all_rar_btn.pack(side=tk.LEFT, padx=5)
        
        self.deselect_all_rar_btn = ttk.Button(rar_buttons_frame, text="Deseleccionar Todos", command=self.deselect_all_rar)
        self.deselect_all_rar_btn.pack(side=tk.LEFT, padx=5)
        
        self.generate_rar_btn = ttk.Button(rar_buttons_frame, text="Generar RARs", command=self.generate_rars)
        self.generate_rar_btn.pack(side=tk.LEFT, padx=5)
        
        main_frame.rowconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        ttk.Label(main_frame, text="Progreso:").grid(row=2, column=0, sticky=tk.W, pady=5)
        
        self.progress_var = tk.StringVar(value="Listo")
        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_var)
        self.progress_label.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress_bar.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), padx=5, pady=5)
        
        self.progress_bar_determinate = None
        
        ttk.Label(main_frame, text="Logs:").grid(row=4, column=0, sticky=tk.W, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(main_frame, height=15, width=80)
        self.log_text.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        main_frame.rowconfigure(5, weight=1)
        
        self.on_mode_change()
    
    def on_mode_change(self):
        mode = self.mode.get()
        if mode == "download":
            self.download_frame.grid()
            self.cbr_frame.grid_remove()
            self.rar_frame.grid_remove()
        elif mode == "cbr":
            self.download_frame.grid_remove()
            self.cbr_frame.grid()
            self.rar_frame.grid_remove()
            if not hasattr(self, 'mangas_data') or not self.mangas_data:
                self.load_available_mangas()
        elif mode == "rar":
            self.download_frame.grid_remove()
            self.cbr_frame.grid_remove()
            self.rar_frame.grid()
            if not hasattr(self, 'rar_mangas_data') or not self.rar_mangas_data:
                self.load_rar_mangas()
    
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def load_volumes(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Por favor ingresa una URL")
            return
        
        self.is_loading_cancelled = False
        self.load_btn.config(state='disabled')
        self.cancel_load_btn.config(state='normal')
        self.url_entry.config(state='disabled')
        volume_label = self.get_volume_label().lower()
        self.progress_var.set(f"Cargando {volume_label}...")
        self.progress_bar.start()
        self.log(f"Cargando información de: {url}")
        
        def load_thread():
            try:
                if self.is_loading_cancelled:
                    return
                
                website_id = self.selected_website.get()
                if website_id == 'olympus_scan':
                    self.downloader = OlympusScanDownloader(url, self.config)
                elif website_id == 'mangatv':
                    self.downloader = MangaTVDownloader(url, self.config)
                elif website_id == 'lectorknight':
                    self.downloader = LectorKnightDownloader(url, self.config)
                elif website_id == 'zonatmo':
                    self.downloader = ZonaTMODownloader(url, self.config)
                elif website_id == 'tomosmanga':
                    self.downloader = TomosMangaDownloader(url, self.config)
                else:
                    self.downloader = MangaDownloader(url, self.config)
                
                if self.is_loading_cancelled:
                    return
                
                html_content = self.downloader.get_page(url, use_selenium=True)
                
                if self.is_loading_cancelled:
                    return
                
                if not html_content:
                    self.root.after(0, lambda: messagebox.showerror("Error", "No se pudo cargar la página"))
                    return
                
                if self.is_loading_cancelled:
                    return
                
                if website_id == 'olympus_scan':
                    self.manga_title = self.downloader.get_manhwa_title(html_content)
                    self.manga_type = "manhwa"
                elif website_id == 'mangatv':
                    self.manga_title = self.downloader.get_manga_title(html_content)
                    self.manga_type = self.downloader.get_manga_type(html_content)
                elif website_id == 'lectorknight':
                    self.manga_title = self.downloader.get_manga_title(html_content)
                    self.manga_type = "manhwa"
                elif website_id == 'zonatmo':
                    self.manga_title = self.downloader.get_manga_title(html_content)
                    self.manga_type = self.downloader.get_manga_type(html_content)
                elif website_id == 'tomosmanga':
                    self.manga_title = self.downloader.get_manga_title(html_content)
                    self.manga_type = "manga"
                else:
                    self.manga_title = self.downloader.get_manga_title(html_content)
                    self.manga_type = "manga"
                
                if self.is_loading_cancelled:
                    return
                
                parse_result = self.downloader.parse_volumes(html_content, debug=False)
                
                if self.is_loading_cancelled:
                    return
                
                if website_id == 'mangatv' or website_id == 'zonatmo':
                    if not parse_result or 'volumes' not in parse_result or not parse_result['volumes']:
                        if not self.is_loading_cancelled:
                            volume_label = self.get_volume_label().lower()
                            self.root.after(0, lambda: messagebox.showerror("Error", f"No se encontraron {volume_label}"))
                        return
                    
                    volumes = parse_result['volumes']
                    common_scanlations = parse_result.get('common_scanlations', {})
                    
                    volumes_with_options = [v for v in volumes if v.get('options')]
                    
                    if self.is_loading_cancelled:
                        return
                    
                    if volumes_with_options and common_scanlations:
                        scanlation_list = list(common_scanlations.keys())
                        self.root.after(0, lambda: self.select_scanlation_dialog(scanlation_list, common_scanlations, volumes_with_options, volumes, parse_result))
                        return
                    elif volumes_with_options:
                        self.root.after(0, lambda: self.select_scanlation_per_chapter(volumes_with_options, volumes, parse_result))
                        return
                    else:
                        sorted_volumes = sorted(volumes, key=lambda v: float(self.downloader.extract_chapter_numbers(v['name'])))
                        if self.manga_type == 'manga':
                            self.root.after(0, lambda: self.create_tomos_dialog(sorted_volumes))
                            return
                        else:
                            self.volumes = sorted_volumes
                else:
                    self.volumes = parse_result
                
                if self.is_loading_cancelled:
                    return
                
                if not self.volumes:
                    volume_label = self.get_volume_label().lower()
                    self.root.after(0, lambda: messagebox.showerror("Error", f"No se encontraron {volume_label}"))
                    return
                
                if website_id != 'olympus_scan' and website_id != 'mangatv' and website_id != 'lectorknight' and website_id != 'tomosmanga':
                    self.volumes.reverse()
                
                if not self.is_loading_cancelled:
                    self.root.after(0, self.update_volumes_list)
                
            except Exception as e:
                if not self.is_loading_cancelled:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error al cargar: {str(e)}"))
                    self.root.after(0, lambda: self.log(f"Error: {str(e)}"))
            finally:
                self.root.after(0, self.load_complete)
        
        self.load_thread = threading.Thread(target=load_thread, daemon=True)
        self.load_thread.start()
    
    def load_complete(self):
        self.load_btn.config(state='normal')
        self.cancel_load_btn.config(state='disabled')
        self.url_entry.config(state='normal')
        self.progress_bar.stop()
        if self.is_loading_cancelled:
            self.progress_var.set("Carga cancelada")
            self.is_loading_cancelled = False
            if self.downloader:
                self.downloader.cancelled = False
        else:
            self.progress_var.set("Listo")
    
    def select_scanlation_dialog(self, scanlation_list, common_scanlations, volumes_with_options, volumes, parse_result):
        dialog = tk.Toplevel(self.root)
        dialog.title("Seleccionar Scanlation Global")
        dialog.geometry("500x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - 500) // 2
        y = (screen_height - 350) // 2
        dialog.geometry(f"500x350+{x}+{y}")
        
        result = [None]
        cancelled = [False]
        
        ttk.Label(dialog, text="Scanlations comunes en todos los capítulos:", font=("Arial", 10, "bold")).pack(pady=10)
        
        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        for idx, scanlation in enumerate(scanlation_list, start=1):
            count = common_scanlations[scanlation]
            btn = ttk.Button(frame, text=f"{idx}. {scanlation} (presente en {count} capítulos)", 
                            command=lambda s=scanlation: [result.__setitem__(0, s), dialog.destroy()])
            btn.pack(fill=tk.X, pady=5)
        
        ttk.Label(dialog, text="O presiona Cancelar para seleccionar por capítulo", font=("Arial", 9)).pack(pady=5)
        
        def on_cancel():
            cancelled[0] = True
            dialog.destroy()
        
        ttk.Button(dialog, text="Cancelar", command=on_cancel).pack(pady=10)
        
        dialog.wait_window()
        
        if cancelled[0]:
            self.select_scanlation_per_chapter(volumes_with_options, volumes, parse_result)
            return
        
        global_scanlation = result[0]
        if global_scanlation:
            processed_volumes = []
            
            for volume in volumes_with_options:
                found = False
                for option in volume.get('options', []):
                    if option['scanlation'] == global_scanlation:
                        volume['chapters'] = [{'name': option['name'], 'url': option['url']}]
                        volume['options'] = None
                        processed_volumes.append(volume)
                        found = True
                        break
                if not found:
                    continue
            
            volumes_without_options_initial = [v for v in volumes if not v.get('options') and v.get('single_scanlation') == global_scanlation]
            all_volumes_combined = volumes_without_options_initial + processed_volumes
            sorted_volumes = sorted(all_volumes_combined, key=lambda v: float(self.downloader.extract_chapter_numbers(v['name'])))
            
            if self.manga_type == 'manga':
                self.root.after(0, lambda: self.create_tomos_dialog(sorted_volumes))
            else:
                self.volumes = sorted_volumes
                self.update_volumes_list()
                self.load_complete()
    
    def group_chapters_by_scanlations(self, volumes):
        sorted_volumes = sorted(volumes, key=lambda v: float(self.downloader.extract_chapter_numbers(v['name'])))
        groups = []
        current_group = None
        
        for volume in sorted_volumes:
            if volume.get('options'):
                scanlations_clean = []
                for opt in volume.get('options', []):
                    scanlation_text = opt['scanlation']
                    if ' | ' in scanlation_text:
                        scanlation_name = scanlation_text.split(' | ')[-1]
                        scanlations_clean.append(scanlation_name)
                    else:
                        scanlations_clean.append(scanlation_text)
                scanlations_list = sorted(set(scanlations_clean))
                scanlations_set = frozenset(scanlations_list)
                scanlations_key = tuple(scanlations_list)
                
                if current_group is None or current_group['scanlations_key'] != scanlations_key:
                    if current_group:
                        groups.append(current_group)
                    current_group = {
                        'scanlations': scanlations_set,
                        'scanlations_key': scanlations_key,
                        'chapters': [volume],
                        'scanlations_list': scanlations_list
                    }
                else:
                    current_group['chapters'].append(volume)
            else:
                if current_group:
                    groups.append(current_group)
                    current_group = None
                scanlation_name = volume.get('single_scanlation', 'Desconocido')
                groups.append({
                    'scanlations': None,
                    'scanlations_key': None,
                    'chapters': [volume],
                    'scanlations_list': [scanlation_name] if scanlation_name != 'Desconocido' else []
                })
        
        if current_group:
            groups.append(current_group)
        
        return groups
    
    def select_scanlation_per_chapter(self, volumes_with_options, volumes, parse_result):
        volumes_without_options = [v for v in volumes if not v.get('options')]
        
        if not volumes_with_options:
            filtered_volumes = [v for v in volumes_without_options if v.get('chapters')]
            sorted_volumes = sorted(filtered_volumes, key=lambda v: float(self.downloader.extract_chapter_numbers(v['name'])))
            if self.manga_type == 'manga':
                self.root.after(0, lambda: self.create_tomos_dialog(sorted_volumes))
            else:
                self.volumes = sorted_volumes
                self.update_volumes_list()
                self.load_complete()
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Seleccionar Scanlation por Grupo")
        dialog.geometry("700x600")
        dialog.transient(self.root)
        dialog.grab_set()
        
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - 700) // 2
        y = (screen_height - 600) // 2
        dialog.geometry(f"700x600+{x}+{y}")
        
        selected_options = {}
        groups = self.group_chapters_by_scanlations(volumes)
        
        scroll_frame = ttk.Frame(dialog)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        canvas = tk.Canvas(scroll_frame)
        scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        scrollable_frame.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        
        for group_idx, group in enumerate(groups):
            first_chapter = group['chapters'][0]
            last_chapter = group['chapters'][-1]
            first_num = self.downloader.extract_chapter_numbers(first_chapter['name'])
            last_num = self.downloader.extract_chapter_numbers(last_chapter['name'])
            
            if first_num == last_num:
                group_label = f"Capítulo {first_num}"
            else:
                group_label = f"Capítulos {first_num} - {last_num}"
            
            chapter_frame = ttk.LabelFrame(scrollable_frame, text=group_label, padding="10")
            chapter_frame.pack(fill=tk.X, pady=5)
            
            if group['scanlations']:
                var = tk.StringVar()
                scanlations_list = group.get('scanlations_list', [])
                unique_scanlations = sorted(set(scanlations_list))
                for scanlation in unique_scanlations:
                    radio = ttk.Radiobutton(chapter_frame, text=scanlation, variable=var, 
                                           value=scanlation)
                    radio.pack(anchor=tk.W, padx=5)
                
                if unique_scanlations:
                    var.set(unique_scanlations[0])
                selected_options[group_idx] = {'var': var, 'group': group}
            else:
                scanlation_name = group.get('scanlations_list', ['Desconocido'])[0] if group.get('scanlations_list') else 'Desconocido'
                ttk.Label(chapter_frame, text=f"Scanlation: {scanlation_name}", foreground="gray").pack(anchor=tk.W, padx=5)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        def apply_selections():
            processed_volumes = []
            for group_idx, group in enumerate(groups):
                if group['scanlations']:
                    group_data = selected_options.get(group_idx)
                    if group_data:
                        var = group_data['var']
                        selected_scanlation = var.get()
                        for volume in group['chapters']:
                            for option in volume.get('options', []):
                                option_scanlation = option['scanlation']
                                if ' | ' in option_scanlation:
                                    option_scanlation_clean = option_scanlation.split(' | ')[-1]
                                else:
                                    option_scanlation_clean = option_scanlation
                                if option_scanlation_clean == selected_scanlation:
                                    volume['chapters'] = [{'name': option['name'], 'url': option['url']}]
                                    volume['options'] = None
                                    processed_volumes.append(volume)
                                    break
                else:
                    processed_volumes.extend(group['chapters'])
            
            sorted_volumes = sorted(processed_volumes, key=lambda v: float(self.downloader.extract_chapter_numbers(v['name'])))
            dialog.destroy()
            
            if self.manga_type == 'manga':
                self.root.after(0, lambda: self.create_tomos_dialog(sorted_volumes))
            else:
                self.volumes = sorted_volumes
                self.update_volumes_list()
                self.load_complete()
        
        ttk.Button(dialog, text="Aplicar", command=apply_selections).pack(pady=10)
    
    def create_tomos_dialog(self, chapters):
        print(f"[DEBUG] create_tomos_dialog llamado con {len(chapters)} capítulos")
        for idx, ch in enumerate(chapters[:5]):
            print(f"[DEBUG]   Capítulo {idx+1}: name={ch.get('name')}, url={ch.get('url', 'SIN URL')}, tiene chapters={ch.get('chapters') is not None}")
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Crear Tomos")
        dialog.geometry("1000x700")
        dialog.transient(self.root)
        dialog.grab_set()
        
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - 1000) // 2
        y = (screen_height - 700) // 2
        dialog.geometry(f"1000x700+{x}+{y}")
        
        self.tomos_structure = []
        tomo_frames = []
        
        available_chapters = []
        for ch in chapters:
            if ch.get('chapters'):
                for sub_ch in ch['chapters']:
                    available_chapters.append(sub_ch)
            else:
                available_chapters.append(ch)
        
        print(f"[DEBUG] Capítulos disponibles para seleccionar: {len(available_chapters)}")
        for idx, ch in enumerate(available_chapters[:5]):
            print(f"[DEBUG]   Capítulo disponible {idx+1}: name={ch.get('name')}, url={ch.get('url', 'SIN URL')}")
        
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(main_frame, text="Organiza los capítulos en tomos (cada tomo puede tener diferente cantidad)", font=("Arial", 10, "bold")).pack(pady=5)
        
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        canvas = tk.Canvas(canvas_frame, height=500)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        scrollable_frame.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        tomos_frame = ttk.LabelFrame(scrollable_frame, text="Tomos", padding="10")
        tomos_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        def add_tomo():
            tomo_num = len(tomo_frames) + 1
            tomo_frame = ttk.Frame(tomos_frame)
            tomo_frame.pack(fill=tk.X, pady=5)
            
            tomo_label = ttk.Label(tomo_frame, text=f"Tomo {tomo_num}:", font=("Arial", 9, "bold"))
            tomo_label.pack(side=tk.LEFT, padx=5)
            
            tomo_chapters_frame = ttk.Frame(tomo_frame)
            tomo_chapters_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            
            selected_label = ttk.Label(tomo_chapters_frame, text="Ningún capítulo seleccionado", foreground="gray")
            selected_label.pack(side=tk.LEFT)
            
            def select_chapters_for_tomo():
                select_dialog = tk.Toplevel(dialog)
                select_dialog.title(f"Seleccionar Capítulos para Tomo {tomo_num}")
                select_dialog.geometry("500x500")
                select_dialog.transient(dialog)
                select_dialog.grab_set()
                
                select_frame = ttk.Frame(select_dialog)
                select_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
                
                ttk.Label(select_frame, text=f"Selecciona los capítulos para Tomo {tomo_num}:", font=("Arial", 10, "bold")).pack(pady=5)
                
                select_canvas = tk.Canvas(select_frame, height=350)
                select_scrollbar = ttk.Scrollbar(select_frame, orient="vertical", command=select_canvas.yview)
                select_scrollable = ttk.Frame(select_canvas)
                
                select_scrollable.bind(
                    "<Configure>",
                    lambda e: select_canvas.configure(scrollregion=select_canvas.bbox("all"))
                )
                
                select_canvas.create_window((0, 0), window=select_scrollable, anchor="nw")
                select_canvas.configure(yscrollcommand=select_scrollbar.set)
                
                select_canvas.bind("<MouseWheel>", lambda e: select_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
                select_scrollable.bind("<MouseWheel>", lambda e: select_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
                
                select_canvas.pack(side="left", fill="both", expand=True)
                select_scrollbar.pack(side="right", fill="y")
                
                tomo_chapter_vars = {}
                for chapter in available_chapters:
                    var = tk.BooleanVar()
                    tomo_chapter_vars[chapter['name']] = var
                    ttk.Checkbutton(select_scrollable, text=chapter['name'], variable=var).pack(anchor=tk.W, padx=5, pady=2)
                
                def apply_tomo_selection():
                    selected_chapters = [ch for ch in available_chapters if tomo_chapter_vars[ch['name']].get()]
                    print(f"[DEBUG] apply_tomo_selection: {len(selected_chapters)} capítulos seleccionados para Tomo {tomo_num}")
                    for idx, ch in enumerate(selected_chapters[:3]):
                        print(f"[DEBUG]   Capítulo seleccionado {idx+1}: name={ch.get('name')}, url={ch.get('url', 'SIN URL')}")
                    if selected_chapters:
                        tomo_data = {
                            'tomo_number': tomo_num,
                            'chapters': selected_chapters
                        }
                        while len(self.tomos_structure) < tomo_num:
                            self.tomos_structure.append({'tomo_number': len(self.tomos_structure) + 1, 'chapters': []})
                        self.tomos_structure[tomo_num - 1] = tomo_data
                        
                        selected_names = [ch['name'] for ch in selected_chapters]
                        if len(selected_names) <= 3:
                            selected_label.config(text=f"{len(selected_names)} capítulos: {', '.join(selected_names)}", foreground="black")
                        else:
                            selected_label.config(text=f"{len(selected_names)} capítulos: {', '.join(selected_names[:3])}...", foreground="black")
                    else:
                        selected_label.config(text="Ningún capítulo seleccionado", foreground="gray")
                    select_dialog.destroy()
                
                ttk.Button(select_frame, text="Aplicar", command=apply_tomo_selection).pack(pady=10)
            
            ttk.Button(tomo_frame, text="Seleccionar Capítulos", command=select_chapters_for_tomo).pack(side=tk.LEFT, padx=5)
            
            def remove_tomo():
                tomo_frame.destroy()
                tomo_frames.remove(tomo_frame)
                if tomo_num <= len(self.tomos_structure):
                    self.tomos_structure.pop(tomo_num - 1)
                for idx, frame in enumerate(tomo_frames):
                    frame.winfo_children()[0].config(text=f"Tomo {idx + 1}:")
                for idx, tomo in enumerate(self.tomos_structure):
                    tomo['tomo_number'] = idx + 1
                for idx, tomo in enumerate(self.tomos_structure):
                    tomo['tomo_number'] = idx + 1
            
            ttk.Button(tomo_frame, text="Eliminar", command=remove_tomo).pack(side=tk.LEFT, padx=5)
            
            tomo_frames.append(tomo_frame)
            self.tomos_structure.append({'tomo_number': tomo_num, 'chapters': []})
        
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(buttons_frame, text="Agregar Tomo", command=add_tomo).pack(side=tk.LEFT, padx=5)
        
        def load_from_json():
            json_path = filedialog.askopenfilename(
                title="Seleccionar archivo JSON",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            
            if not json_path:
                return
            
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                
                if 'tomos' not in json_data:
                    messagebox.showerror("Error", "El archivo JSON no contiene la clave 'tomos'")
                    return
                
                chapters_dict = {ch['name']: ch for ch in available_chapters}
                loaded_tomos = []
                missing_chapters = []
                
                for tomo_data in json_data['tomos']:
                    if 'tomo_number' not in tomo_data or 'chapters' not in tomo_data:
                        continue
                    
                    tomo_chapters = []
                    for chapter_name in tomo_data['chapters']:
                        if chapter_name in chapters_dict:
                            tomo_chapters.append(chapters_dict[chapter_name])
                        else:
                            missing_chapters.append(chapter_name)
                    
                    if tomo_chapters:
                        loaded_tomos.append({
                            'tomo_number': tomo_data['tomo_number'],
                            'chapters': tomo_chapters
                        })
                
                if missing_chapters:
                    missing_list = ', '.join(missing_chapters[:10])
                    if len(missing_chapters) > 10:
                        missing_list += f" ... y {len(missing_chapters) - 10} más"
                    messagebox.showwarning(
                        "Advertencia",
                        f"Los siguientes capítulos del JSON no están disponibles:\n{missing_list}\n\nSe crearán solo los tomos con capítulos disponibles."
                    )
                
                if not loaded_tomos:
                    messagebox.showerror("Error", "No se pudieron crear tomos desde el JSON. Verifica que los nombres de los capítulos coincidan.")
                    return
                
                loaded_tomos.sort(key=lambda x: x['tomo_number'])
                
                for widget in tomos_frame.winfo_children():
                    widget.destroy()
                
                tomo_frames.clear()
                self.tomos_structure = []
                
                for tomo_data in loaded_tomos:
                    tomo_num = tomo_data['tomo_number']
                    tomo_frame = ttk.Frame(tomos_frame)
                    tomo_frame.pack(fill=tk.X, pady=5)
                    
                    tomo_label = ttk.Label(tomo_frame, text=f"Tomo {tomo_num}:", font=("Arial", 9, "bold"))
                    tomo_label.pack(side=tk.LEFT, padx=5)
                    
                    selected_names = [ch['name'] for ch in tomo_data['chapters']]
                    if len(selected_names) <= 3:
                        display_text = f"{len(selected_names)} capítulos: {', '.join(selected_names)}"
                    else:
                        display_text = f"{len(selected_names)} capítulos: {', '.join(selected_names[:3])}..."
                    
                    selected_label = ttk.Label(tomo_frame, text=display_text, foreground="black")
                    selected_label.pack(side=tk.LEFT, padx=5)
                    
                    def remove_tomo_json(tomo_num_to_remove, frame_to_remove):
                        frame_to_remove.destroy()
                        tomo_frames.remove(frame_to_remove)
                        self.tomos_structure = [t for t in self.tomos_structure if t['tomo_number'] != tomo_num_to_remove]
                        for idx, frame in enumerate(tomo_frames):
                            frame.winfo_children()[0].config(text=f"Tomo {idx + 1}:")
                        for idx, tomo in enumerate(self.tomos_structure):
                            tomo['tomo_number'] = idx + 1
                    
                    ttk.Button(tomo_frame, text="Eliminar", command=lambda tn=tomo_num, tf=tomo_frame: remove_tomo_json(tn, tf)).pack(side=tk.LEFT, padx=5)
                    
                    self.tomos_structure.append(tomo_data)
                    tomo_frames.append(tomo_frame)
                
                messagebox.showinfo("Éxito", f"Se cargaron {len(loaded_tomos)} tomos desde el archivo JSON")
                
            except json.JSONDecodeError as e:
                messagebox.showerror("Error", f"Error al leer el archivo JSON: {str(e)}")
            except Exception as e:
                messagebox.showerror("Error", f"Error al cargar el JSON: {str(e)}")
        
        ttk.Button(buttons_frame, text="Cargar desde JSON", command=load_from_json).pack(side=tk.LEFT, padx=5)
        
        def apply_tomos():
            valid_tomos = [tomo for tomo in self.tomos_structure if tomo.get('chapters')]
            if not valid_tomos:
                messagebox.showwarning("Advertencia", "Debes crear al menos un tomo con capítulos seleccionados")
                return
            
            print(f"[DEBUG] apply_tomos: {len(valid_tomos)} tomos válidos")
            used_chapters = set()
            for tomo_idx, tomo in enumerate(valid_tomos):
                print(f"[DEBUG] Tomo {tomo['tomo_number']}: {len(tomo['chapters'])} capítulos")
                for ch_idx, ch in enumerate(tomo['chapters']):
                    print(f"[DEBUG]   Capítulo {ch_idx+1}: name={ch.get('name')}, url={ch.get('url', 'SIN URL')}")
                    if ch['name'] in used_chapters:
                        messagebox.showwarning("Advertencia", f"El capítulo {ch['name']} está asignado a múltiples tomos")
                        return
                    used_chapters.add(ch['name'])
                    if not ch.get('url'):
                        print(f"[ERROR] Capítulo sin URL: {ch}")
                        messagebox.showerror("Error", f"El capítulo {ch['name']} no tiene URL. Por favor, selecciona las scanlations primero.")
                        return
            
            self.volumes = []
            for tomo in valid_tomos:
                tomo_name = f"Tomo {tomo['tomo_number']}"
                print(f"[DEBUG] Creando volumen: {tomo_name} con {len(tomo['chapters'])} capítulos")
                self.volumes.append({
                    'name': tomo_name,
                    'chapters': tomo['chapters']
                })
            
            dialog.destroy()
            self.update_volumes_list()
        
        def cancel_tomos():
            self.tomos_structure = None
            dialog.destroy()
            self.load_complete()
        
        ttk.Button(buttons_frame, text="Aplicar", command=apply_tomos).pack(side=tk.RIGHT, padx=5)
        ttk.Button(buttons_frame, text="Cancelar", command=cancel_tomos).pack(side=tk.RIGHT, padx=5)
        
        add_tomo()
    
    def update_volumes_list(self):
        for widget in self.volumes_frame.winfo_children():
            widget.destroy()
        
        self.checkboxes = []
        self.title_label.config(text=self.manga_title)
        
        website_id = self.selected_website.get()
        if website_id == 'mangatv' and self.manga_type == 'manga' and self.tomos_structure:
            for idx, volume in enumerate(self.volumes, start=1):
                volume_name = volume['name']
                chapters_count = len(volume['chapters'])
                display_text = f"{idx}. {volume_name} ({chapters_count} capítulos)"
                
                var = tk.BooleanVar()
                checkbox = ttk.Checkbutton(
                    self.volumes_frame,
                    text=display_text,
                    variable=var
                )
                checkbox.grid(row=idx-1, column=0, sticky=tk.W, padx=5, pady=2)
                
                self.checkboxes.append({
                    'var': var,
                    'volume': volume,
                    'index': idx-1
                })
            
            self.log(f"Título: {self.manga_title}")
            self.log(f"Tomos creados: {len(self.volumes)}")
            messagebox.showinfo("Éxito", f"Se crearon {len(self.volumes)} tomos")
        elif website_id == 'olympus_scan' or website_id == 'mangatv' or website_id == 'lectorknight' or website_id == 'tomosmanga':
            for idx, volume in enumerate(self.volumes, start=1):
                chapter_name = volume['name']
                display_text = chapter_name
                
                var = tk.BooleanVar()
                checkbox = ttk.Checkbutton(
                    self.volumes_frame,
                    text=display_text,
                    variable=var
                )
                checkbox.grid(row=idx-1, column=0, sticky=tk.W, padx=5, pady=2)
                
                self.checkboxes.append({
                    'var': var,
                    'volume': volume,
                    'index': idx-1
                })
            
            self.log(f"Título: {self.manga_title}")
            self.log(f"Capítulos encontrados: {len(self.volumes)}")
            messagebox.showinfo("Éxito", f"Se encontraron {len(self.volumes)} capítulos")
        else:
            for idx, volume in enumerate(self.volumes, start=1):
                volume_name = volume['name']
                chapters_count = len(volume['chapters'])
                display_text = f"{idx}. {volume_name} ({chapters_count} capítulos)"
                
                var = tk.BooleanVar()
                checkbox = ttk.Checkbutton(
                    self.volumes_frame,
                    text=display_text,
                    variable=var
                )
                checkbox.grid(row=idx-1, column=0, sticky=tk.W, padx=5, pady=2)
                
                self.checkboxes.append({
                    'var': var,
                    'volume': volume,
                    'index': idx-1
                })
            
            self.log(f"Título: {self.manga_title}")
            volume_label = self.get_volume_label().lower()
            self.log(f"{self.get_volume_label()} encontrados: {len(self.volumes)}")
            messagebox.showinfo("Éxito", f"Se encontraron {len(self.volumes)} {volume_label}")
    
    def select_all(self):
        for cb in self.checkboxes:
            cb['var'].set(True)
    
    def deselect_all(self):
        for cb in self.checkboxes:
            cb['var'].set(False)
    
    def start_download(self):
        if self.is_downloading:
            messagebox.showwarning("Advertencia", "Ya hay una descarga en progreso")
            return
        
        selected_volumes = [cb['volume'] for cb in self.checkboxes if cb['var'].get()]
        
        if not selected_volumes:
            volume_label = self.get_volume_label().lower()
            messagebox.showwarning("Advertencia", f"Por favor selecciona al menos un {volume_label[:-1] if volume_label.endswith('s') else volume_label}")
            return
        
        if not self.downloader:
            volume_label = self.get_volume_label().lower()
            messagebox.showerror("Error", f"Primero debes cargar los {volume_label}")
            return
        
        self.is_downloading = True
        self.download_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        self.load_btn.config(state='disabled')
        self.progress_var.set("Descargando...")
        self.progress_bar.config(mode='indeterminate')
        self.progress_bar.start()
        
        def download_thread():
            try:
                output_dir = self.config['output_dir']
                os.makedirs(output_dir, exist_ok=True)
                
                website_id = self.selected_website.get()
                if website_id == 'mangatv':
                    save_metadata_mangatv(self.manga_title, self.volumes, output_dir, manga_type=self.manga_type, tomos_structure=self.tomos_structure)
                elif website_id == 'olympus_scan':
                    save_metadata_olympus(self.manga_title, self.volumes, output_dir)
                elif website_id == 'lectorknight':
                    save_metadata_lectorknight(self.manga_title, self.volumes, output_dir)
                elif website_id == 'zonatmo':
                    save_metadata_zonatmo(self.manga_title, self.volumes, output_dir, self.manga_type, self.tomos_structure if self.tomos_structure else None)
                elif website_id == 'tomosmanga':
                    save_metadata_tomosmanga(self.manga_title, self.volumes, output_dir)
                else:
                    save_metadata(self.manga_title, self.volumes, output_dir)
                
                total_volumes = len(selected_volumes)
                volume_label = self.get_volume_label().lower()
                website_id = self.selected_website.get()
                is_olympus = website_id == 'olympus_scan'
                is_mangatv = website_id == 'mangatv'
                is_lectorknight = website_id == 'lectorknight'
                is_zonatmo = website_id == 'zonatmo'
                is_tomosmanga = website_id == 'tomosmanga'
                
                self.root.after(0, lambda: self.log(f"Iniciando descarga de {total_volumes} {volume_label}..."))
                
                if is_tomosmanga and self.downloader:
                    def on_fireload_progress(current, total, chapter_name):
                        def update_fireload(c=current, t=total, n=chapter_name):
                            status = f"Obteniendo URLs ({c}/{t}): {n}"
                            self.progress_var.set(status)
                        def log_fireload(n=chapter_name):
                            self.log(f"Obteniendo URL: {n}")
                        self.root.after(0, update_fireload)
                        self.root.after(0, log_fireload)
                    
                    def on_download_start(chapter_name, file_size):
                        def update_start(n=chapter_name, fs=file_size):
                            size_mb = (fs / (1024 * 1024)) if fs else 0
                            status = f"Descargando: {n} ({size_mb:.2f} MB)"
                            self.progress_var.set(status)
                        def log_start(n=chapter_name, fs=file_size):
                            size_mb = (fs / (1024 * 1024)) if fs else 0
                            self.log(f"Iniciando descarga: {n} ({size_mb:.2f} MB)")
                        self.root.after(0, update_start)
                        self.root.after(0, log_start)
                    
                    def on_download_progress(chapter_name, percent, speed_mb, downloaded, total):
                        def update_progress(n=chapter_name, p=percent, s=speed_mb, d=downloaded, t=total):
                            downloaded_mb = d / (1024 * 1024)
                            total_mb = t / (1024 * 1024) if t else 0
                            speed_text = f" @ {s:.1f} MB/s" if s > 0 else ""
                            if p > 0 and total_mb > 0:
                                status_text = f"Descargando: {n} - {p:.1f}% ({downloaded_mb:.1f}/{total_mb:.1f} MB){speed_text}"
                            else:
                                status_text = f"Descargando: {n} - ({downloaded_mb:.1f} MB){speed_text}"
                            self.progress_var.set(status_text)
                        self.root.after(0, update_progress)
                    
                    def on_download_complete(chapter_name):
                        self.root.after(0, lambda n=chapter_name: self.log(f"✓ {n} completado"))
                    
                    self.downloader.set_callback('on_fireload_progress', on_fireload_progress)
                    self.downloader.set_callback('on_download_start', on_download_start)
                    self.downloader.set_callback('on_download_progress', on_download_progress)
                    self.downloader.set_callback('on_download_complete', on_download_complete)
                
                parallel_tomos = self.config.get('parallel_tomos', 1)
                
                def download_single_tomo(volume, idx, total):
                    if self.downloader and self.downloader.cancelled:
                        return None
                    if is_olympus or is_mangatv or is_lectorknight or is_zonatmo:
                        volume_label_single = "Capítulo"
                        volume_number = self.downloader.extract_chapter_numbers(volume['name'])
                    elif is_tomosmanga:
                        volume_label_single = "Tomo"
                        volume_number = self.downloader.extract_chapter_numbers(volume['name'])
                    else:
                        volume_label_single = "Tomo"
                        volume_number = self.downloader.extract_tomo_number(volume['name'])
                    
                    self.root.after(0, lambda idx=idx, total=total, vol=volume_number, label=volume_label_single: self.log(f"Procesando {label} {idx}/{total}: {label} {vol}"))
                    
                    is_tomo_structure = ((is_mangatv or is_zonatmo) and self.manga_type == 'manga' and self.tomos_structure)
                    print(f"[DEBUG] Descargando volumen: {volume['name']}, capítulos: {len(volume.get('chapters', []))}")
                    self.root.after(0, lambda v=volume: self.log(f"[DEBUG] Descargando volumen: {v['name']}, capítulos: {len(v.get('chapters', []))}"))
                    if volume.get('chapters'):
                        for ch_idx, ch in enumerate(volume['chapters'][:3]):
                            ch_name = ch.get('name', 'SIN NOMBRE')
                            ch_url = ch.get('url', 'SIN URL')
                            print(f"[DEBUG]   Capítulo {ch_idx+1}: name={ch_name}, url={ch_url}")
                            self.root.after(0, lambda name=ch_name, url=ch_url, idx=ch_idx: self.log(f"[DEBUG]   Capítulo {idx+1}: name={name}, url={url}"))
                    try:
                        if is_tomo_structure:
                            if is_mangatv or is_zonatmo:
                                result = self.downloader.download_volume(volume, self.manga_title, output_dir, selected_option=None, is_tomo_structure=True)
                            else:
                                result = self.downloader.download_volume(volume, self.manga_title, output_dir, is_tomo_structure=True)
                        else:
                            if is_mangatv or is_zonatmo:
                                result = self.downloader.download_volume(volume, self.manga_title, output_dir, selected_option=None)
                            elif is_tomosmanga:
                                result = self.downloader.download_volume(volume, self.manga_title, output_dir)
                            else:
                                result = self.downloader.download_volume(volume, self.manga_title, output_dir)
                    except Exception as e:
                        import traceback
                        error_msg = str(e)
                        error_trace = traceback.format_exc()
                        print(f"[ERROR] Error durante la descarga: {error_msg}")
                        print(f"[ERROR] Traceback:\n{error_trace}")
                        self.root.after(0, lambda e=error_msg: self.log(f"[ERROR] Error durante la descarga: {e}"))
                        self.root.after(0, lambda trace=error_trace: self.log(f"[ERROR] Traceback: {trace}"))
                        return None
                    
                    if result and result.get('dir'):
                        if is_olympus or (is_mangatv and not is_tomo_structure):
                            self.root.after(0, lambda vol=volume_number: self.log(f"Capítulo {vol} descargado correctamente"))
                        else:
                            self.root.after(0, lambda vol=volume_number: self.log(f"Tomo {vol} descargado correctamente"))
                        return {
                            'dir': result['dir'],
                            'tomo_number': volume_number,
                            'failed_chapters': result.get('failed_chapters', [])
                        }
                    return None
                
                all_failed_chapters = []
                
                if parallel_tomos > 1 and total_volumes > 1:
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                    with ThreadPoolExecutor(max_workers=parallel_tomos) as executor:
                        futures = {executor.submit(download_single_tomo, volume, idx+1, total_volumes): idx 
                                  for idx, volume in enumerate(selected_volumes)}
                        
                        for future in as_completed(futures):
                            if self.downloader and self.downloader.cancelled:
                                executor.shutdown(wait=False, cancel_futures=True)
                                self.root.after(0, lambda: self.log("Descarga cancelada por el usuario"))
                                break
                            try:
                                result = future.result()
                                if result and isinstance(result, dict) and 'failed_chapters' in result:
                                    all_failed_chapters.extend(result.get('failed_chapters', []))
                            except Exception as e:
                                self.root.after(0, lambda e=e: self.log(f"Error: {str(e)}"))
                else:
                    for idx, volume in enumerate(selected_volumes, start=1):
                        if self.downloader and self.downloader.cancelled:
                            self.root.after(0, lambda: self.log("Descarga cancelada por el usuario"))
                            break
                        result = download_single_tomo(volume, idx, total_volumes)
                        if result and isinstance(result, dict) and 'failed_chapters' in result:
                            all_failed_chapters.extend(result.get('failed_chapters', []))
                
                if self.downloader and not self.downloader.cancelled:
                    self.root.after(0, lambda total=total_volumes, label=volume_label: self.log(f"Descarga completada: {total} {label}"))
                
                if all_failed_chapters:
                    def get_failed_sort_key(failed):
                        if is_olympus or is_mangatv or is_lectorknight or is_zonatmo or is_tomosmanga:
                            try:
                                chapter_num = float(self.downloader.extract_chapter_numbers(failed.get('chapter_name', '')))
                            except:
                                chapter_num = 0.0
                            return (0, chapter_num)
                        else:
                            try:
                                tomo_num = int(failed.get('tomo_number', 0))
                            except:
                                tomo_num = 0
                            try:
                                chapter_num = float(self.downloader.extract_chapter_numbers(failed.get('chapter_name', '')))
                            except:
                                chapter_num = 0.0
                            return (tomo_num, chapter_num)
                    
                    sorted_failed = sorted(all_failed_chapters, key=get_failed_sort_key)
                    
                    self.root.after(0, lambda: self.log(f"\n{'='*60}"))
                    self.root.after(0, lambda: self.log("RESUMEN DE ERRORES"))
                    self.root.after(0, lambda: self.log(f"{'='*60}"))
                    is_tomo_structure = ((is_mangatv or is_zonatmo) and self.manga_type == 'manga' and self.tomos_structure)
                    for failed in sorted_failed:
                        if is_olympus or (is_mangatv and not is_tomo_structure) or is_lectorknight or is_zonatmo or is_tomosmanga:
                            self.root.after(0, lambda f=failed: self.log(f"Capítulo {f['chapter_name']}: {f['downloaded']}/{f['total']}"))
                        else:
                            tomo_num = failed.get('tomo_number', '?')
                            self.root.after(0, lambda f=failed, tn=tomo_num: self.log(f"Tomo {tn}, {f['chapter_name']}: {f['downloaded']}/{f['total']}"))
                    self.root.after(0, lambda: self.log(f"{'='*60}"))
                
                if self.downloader and not self.downloader.cancelled:
                    self.root.after(0, lambda total=total_volumes, label=volume_label: messagebox.showinfo("Éxito", f"Descarga completada: {total} {label}"))
                else:
                    self.root.after(0, lambda: messagebox.showinfo("Cancelado", "La descarga ha sido cancelada"))
                
            except Exception as e:
                import traceback
                error_msg = str(e)
                error_trace = traceback.format_exc()
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("Error", f"Error durante la descarga: {msg}"))
                self.root.after(0, lambda msg=error_msg: self.log(f"[ERROR] Error durante la descarga: {msg}"))
                self.root.after(0, lambda trace=error_trace: self.log(f"[ERROR] Traceback completo:\n{trace}"))
            finally:
                self.root.after(0, self.download_complete)
        
        self.download_thread = threading.Thread(target=download_thread, daemon=True)
        self.download_thread.start()
    
    def cancel_download(self):
        if self.downloader:
            self.downloader.cancel()
            self.root.after(0, lambda: self.log("Cancelando descarga..."))
            self.progress_var.set("Cancelando...")
    
    def download_complete(self):
        self.is_downloading = False
        self.download_btn.config(state='normal')
        self.cancel_btn.config(state='disabled')
        self.load_btn.config(state='normal')
        self.progress_bar.stop()
        self.progress_var.set("Listo")
    
    def load_available_mangas(self):
        output_dir = self.config['output_dir']
        
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, output_dir)
        
        self.log(f"Buscando contenido en: {output_dir}")
        
        if not os.path.exists(output_dir):
            self.log(f"[ERROR] El directorio no existe: {output_dir}")
            messagebox.showerror("Error", f"El directorio {output_dir} no existe")
            return
        
        content_list = self.load_content_list(output_dir)
        
        if content_list:
            titles = [item['title'] for item in content_list]
            self.manga_combo['values'] = titles
            self.mangas_data = content_list
            self.log(f"Contenido encontrado: {len(content_list)}")
        else:
            self.manga_combo['values'] = []
            self.mangas_data = []
            self.log("[ADVERTENCIA] No se encontró contenido")
            messagebox.showinfo("Info", f"No se encontró contenido en:\n{output_dir}")
    
    def on_manga_selected(self, event=None):
        selected_title = self.manga_combo.get()
        if not selected_title or not hasattr(self, 'mangas_data'):
            return
        
        selected_manga = next((m for m in self.mangas_data if m['title'] == selected_title), None)
        if not selected_manga:
            return
        
        output_dir = self.config['output_dir']
        
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, output_dir)
        
        if selected_manga['folder'] == '.':
            manga_folder = output_dir
        else:
            manga_folder = os.path.join(output_dir, selected_manga['folder'])
        
        self.load_cbr_volumes(manga_folder)
    
    def load_cbr_volumes(self, manga_dir):
        for widget in self.cbr_volumes_frame.winfo_children():
            widget.destroy()
        
        self.cbr_checkboxes = []
        
        if not os.path.exists(manga_dir):
            return
        
        items = []
        for item in os.listdir(manga_dir):
            item_path = os.path.join(manga_dir, item)
            if os.path.isdir(item_path) and not item.endswith('.cbr'):
                items.append(item)
        
        if not items:
            self.log("No se encontraron carpetas en este contenido")
            return
        
        has_tomos = any('Tomo' in item or 'Volumen' in item for item in items)
        has_capitulos = any(('Capítulo' in item) or ('Capitulo' in item) for item in items)
        
        source_type = self.detect_source_type_from_dir(manga_dir)
        
        if source_type is None:
            if has_capitulos and not has_tomos:
                source_type = 'olympus_scan'
            elif has_tomos:
                source_type = 'inventario_oculto'
            else:
                source_type = 'inventario_oculto'
        
        is_chapters_source = (source_type == 'olympus_scan' or source_type == 'mangatv' or source_type == 'lectorknight' or source_type == 'zonatmo')
        
        self.log(f"[DEBUG] Tipo detectado: {source_type}")
        self.log(f"[DEBUG] Items encontrados: {len(items)} (Tomos: {has_tomos}, Capítulos: {has_capitulos})")
        
        filtered_items = []
        for item in items:
            if is_chapters_source and (('Capítulo' in item) or ('Capitulo' in item) or re.search(r'\\d', item)):
                filtered_items.append(item)
            elif not is_chapters_source and ('Tomo' in item or 'Volumen' in item):
                filtered_items.append(item)
        
        items = filtered_items
        
        def get_item_sort_key(item_name):
            if is_chapters_source:
                match = re.search(r'(\d+\.?\d*)', item_name)
                if match:
                    try:
                        return float(match.group(1))
                    except:
                        return 0.0
            else:
                match = re.search(r'(\d+)', item_name)
                if match:
                    return int(match.group(1))
            return 0
        
        items.sort(key=get_item_sort_key)
        
        if not is_chapters_source:
            self._create_inventario_checkboxes(items, manga_dir)
        else:
            self.current_manga_is_olympus = True
            self.all_chapters = items
            self.current_manga_dir = manga_dir
            self.all_chapter_paths = {item: os.path.join(manga_dir, item) for item in items}
            self.chapters_per_group_frame.grid()
            self.update_chapter_groups()
        
        label = "Capítulos" if is_chapters_source else "Tomos"
        if items:
            self.log(f"{label} encontrados: {len(items)}")
        else:
            self.log(f"No se encontraron {label.lower()} en este contenido")
    
    def _create_inventario_checkboxes(self, items, manga_dir):
        for idx, item_name in enumerate(items, start=1):
            var = tk.BooleanVar()
            item_path = os.path.join(manga_dir, item_name)
            item_path_normalized = os.path.normpath(os.path.abspath(item_path))
            
            checkbox_frame = ttk.Frame(self.cbr_volumes_frame)
            checkbox_frame.grid(row=idx-1, column=0, sticky=tk.W, padx=5, pady=2)
            
            checkbox = ttk.Checkbutton(
                checkbox_frame,
                text=item_name,
                variable=var
            )
            checkbox.pack(side=tk.LEFT)
            
            cover_label = ttk.Label(checkbox_frame, text="", foreground="green", font=("Arial", 8))
            cover_label.pack(side=tk.LEFT, padx=(5, 0))
            
            self.cbr_checkboxes.append({
                'var': var,
                'volume_name': item_name,
                'volume_path': item_path,
                'cover_label': cover_label,
                'is_olympus': False
            })
    
    def update_chapter_groups(self):
        if not hasattr(self, 'current_manga_is_olympus') or not self.current_manga_is_olympus:
            return
        
        if not hasattr(self, 'all_chapters') or not self.all_chapters:
            return
        
        for widget in self.cbr_volumes_frame.winfo_children():
            widget.destroy()
        
        self.cbr_checkboxes = []
        
        chapters_per_group = self.chapters_per_group_var.get()
        if chapters_per_group < 1:
            chapters_per_group = 1
        
        def get_chapter_sort_key(chapter_name):
            match = re.search(r'(\d+\.?\d*)', chapter_name)
            if match:
                try:
                    return float(match.group(1))
                except:
                    return 0.0
            return 0.0
        
        sorted_chapters = sorted(self.all_chapters, key=get_chapter_sort_key)
        
        groups = []
        for i in range(0, len(sorted_chapters), chapters_per_group):
            group_chapters = sorted_chapters[i:i + chapters_per_group]
            groups.append(group_chapters)
        
        current_row = 0
        for idx, group in enumerate(groups, start=1):
            first_chapter = group[0]
            last_chapter = group[-1]
            
            first_num = re.search(r'(\d+\.?\d*)', first_chapter)
            last_num = re.search(r'(\d+\.?\d*)', last_chapter)
            
            if first_num and last_num:
                try:
                    first = float(first_num.group(1))
                    last = float(last_num.group(1))
                    group_name = f"Capítulos {first:g}-{last:g}"
                except:
                    group_name = f"{first_chapter} - {last_chapter}"
            else:
                group_name = f"{first_chapter} - {last_chapter}"
            
            group_var = tk.BooleanVar()
            group_paths = [self.all_chapter_paths[ch] for ch in group]
            group_path_normalized = os.path.normpath(os.path.abspath(group_paths[0]))
            
            group_frame = ttk.Frame(self.cbr_volumes_frame)
            group_frame.grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=2)
            current_row += 1
            
            group_checkbox = ttk.Checkbutton(
                group_frame,
                text=group_name,
                variable=group_var,
                command=lambda g=group_name: self.toggle_group(g)
            )
            group_checkbox.pack(side=tk.LEFT)
            
            expand_btn = ttk.Button(
                group_frame,
                text="▼",
                width=3,
                command=lambda g=group_name: self.toggle_group_expand(g)
            )
            expand_btn.pack(side=tk.LEFT, padx=(5, 0))
            
            cover_label = ttk.Label(group_frame, text="", foreground="green", font=("Arial", 8))
            cover_label.pack(side=tk.LEFT, padx=(5, 0))
            
            chapter_frame = ttk.Frame(self.cbr_volumes_frame)
            chapter_frame.grid(row=current_row, column=0, sticky=tk.W, padx=20, pady=2)
            chapter_frame.grid_remove()
            current_row += 1
            
            chapter_vars = []
            for chapter_name in group:
                chapter_var = tk.BooleanVar()
                chapter_path = self.all_chapter_paths[chapter_name]
                
                chapter_checkbox = ttk.Checkbutton(
                    chapter_frame,
                    text=chapter_name,
                    variable=chapter_var
                )
                chapter_checkbox.pack(anchor=tk.W, padx=5, pady=1)
                chapter_vars.append(chapter_var)
            
            self.cbr_checkboxes.append({
                'var': group_var,
                'volume_name': group_name,
                'volume_path': group_paths[0],
                'cover_label': cover_label,
                'is_olympus': True,
                'is_group': True,
                'chapter_paths': group_paths,
                'group_name': group_name,
                'chapter_frame': chapter_frame,
                'expand_btn': expand_btn,
                'chapter_vars': chapter_vars,
                'expanded': False,
                'group_row': current_row - 2
            })
        
        self.log(f"Grupos creados: {len(groups)} (de {chapters_per_group} capítulos cada uno)")
    
    def toggle_group(self, group_name):
        for cb in self.cbr_checkboxes:
            if cb.get('group_name') == group_name and cb.get('is_group', False):
                if cb['var'].get():
                    for chapter_var in cb.get('chapter_vars', []):
                        chapter_var.set(True)
                else:
                    for chapter_var in cb.get('chapter_vars', []):
                        chapter_var.set(False)
                break
    
    def toggle_group_expand(self, group_name):
        for cb in self.cbr_checkboxes:
            if cb.get('group_name') == group_name and cb.get('is_group', False):
                chapter_frame = cb.get('chapter_frame')
                if not chapter_frame:
                    return
                
                if cb.get('expanded', False):
                    chapter_frame.grid_remove()
                    cb['expand_btn'].config(text="▼")
                    cb['expanded'] = False
                else:
                    chapter_frame.grid()
                    cb['expand_btn'].config(text="▲")
                    cb['expanded'] = True
                break
    
    def select_all_cbr(self):
        for cb in self.cbr_checkboxes:
            cb['var'].set(True)
    
    def deselect_all_cbr(self):
        for cb in self.cbr_checkboxes:
            cb['var'].set(False)
    
    def update_cover_indicators(self):
        for cb in self.cbr_checkboxes:
            if 'cover_label' in cb:
                if cb.get('is_group', False):
                    group_key = f"group_{cb['group_name']}"
                    if group_key in self.selected_cover:
                        cb['cover_label'].config(text="✓ Portada")
                    else:
                        cb['cover_label'].config(text="")
                else:
                    volume_path_normalized = os.path.normpath(os.path.abspath(cb['volume_path']))
                    if volume_path_normalized in self.selected_cover:
                        cb['cover_label'].config(text="✓ Portada")
                    else:
                        cb['cover_label'].config(text="")
    
    def select_cover_image(self):
        selected_volumes = [cb for cb in self.cbr_checkboxes if cb['var'].get()]
        
        if not selected_volumes:
            messagebox.showwarning("Advertencia", "Por favor selecciona al menos un tomo")
            return
        
        if not PIL_AVAILABLE:
            messagebox.showerror("Error", "Pillow no está instalado. Instala con: pip install Pillow")
            return
        
        self.cover_selection_queue = selected_volumes.copy()
        self.current_cover_index = 0
        self.process_next_cover()
    
    def process_next_cover(self):
        if self.current_cover_index >= len(self.cover_selection_queue):
            self.update_cover_indicators()
            messagebox.showinfo("Completado", f"Selección de portadas completada para {len(self.cover_selection_queue)} tomo(s)")
            return
        
        volume_data = self.cover_selection_queue[self.current_cover_index]
        volume_path = volume_data['volume_path']
        volume_name = volume_data['volume_name']
        total = len(self.cover_selection_queue)
        current = self.current_cover_index + 1
        
        self.show_cover_selector(volume_path, volume_name, current, total)
    
    def show_cover_selector(self, volume_path, volume_name, current=1, total=1):
        cover_window = tk.Toplevel(self.root)
        cover_window.title(f"Seleccionar Portada - {volume_name} ({current}/{total})")
        cover_window.geometry("900x700")
        
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
        
        image_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
        all_images = []
        
        volume_data = None
        for cb in self.cbr_checkboxes:
            if cb.get('is_group', False) and cb['group_name'] == volume_name:
                volume_data = cb
                break
        
        if volume_data and volume_data.get('is_group', False):
            chapter_paths = volume_data['chapter_paths']
            for chapter_path in chapter_paths:
                chapter_name = os.path.basename(chapter_path)
                for root, dirs, files in os.walk(chapter_path):
                    dirs.sort(key=natural_sort_key)
                    files.sort(key=natural_sort_key)
                    for img_file in files:
                        if img_file.lower().startswith('temp_'):
                            continue
                        if img_file.lower().endswith(image_extensions):
                            img_path = os.path.join(root, img_file)
                            file_rel_path = os.path.relpath(img_path, chapter_path)
                            rel_path = os.path.join(chapter_name, file_rel_path)
                            rel_path_for_sort = rel_path.replace('\\', '/')
                            all_images.append((img_path, rel_path, rel_path_for_sort))
        else:
            for root, dirs, files in os.walk(volume_path):
                dirs.sort(key=natural_sort_key)
                files.sort(key=natural_sort_key)
                for file in files:
                    if file.lower().startswith('temp_'):
                        continue
                    if file.lower().endswith(image_extensions):
                        img_path = os.path.join(root, file)
                        rel_path = os.path.relpath(img_path, volume_path)
                        rel_path_for_sort = rel_path.replace('\\', '/')
                        all_images.append((img_path, rel_path, rel_path_for_sort))
        
        if not all_images:
            messagebox.showinfo("Info", f"No se encontraron imágenes en {volume_name}")
            cover_window.destroy()
            self.current_cover_index += 1
            self.root.after(100, self.process_next_cover)
            return
        
        all_images.sort(key=lambda x: natural_sort_key(x[2]))
        
        main_frame = ttk.Frame(cover_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        info_label = ttk.Label(main_frame, text=f"Tomo: {volume_name} ({current}/{total})", font=("Arial", 10, "bold"))
        info_label.pack(pady=5)
        
        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def on_cover_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        def bind_cover_mousewheel(event):
            canvas.bind_all("<MouseWheel>", on_cover_mousewheel)
        def unbind_cover_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", bind_cover_mousewheel)
        canvas.bind("<Leave>", unbind_cover_mousewheel)
        scrollable_frame.bind("<Enter>", bind_cover_mousewheel)
        scrollable_frame.bind("<Leave>", unbind_cover_mousewheel)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        selected_image = [None]
        status_labels = {}
        preview_images = []
        max_previews = 100
        
        def on_image_select(img_path, img_name, row_frame):
            selected_image[0] = img_path
            for widget in scrollable_frame.winfo_children():
                if isinstance(widget, ttk.Frame):
                    for child in widget.winfo_children():
                        if isinstance(child, ttk.Label) and child.cget('text') == '✓ SELECCIONADA':
                            child.config(text='', foreground='')
            
            status_label = status_labels.get(row_frame)
            if status_label:
                status_label.config(text='✓ SELECCIONADA', foreground='green')
        
        image_list = all_images[:max_previews]
        for idx, img_tuple in enumerate(image_list):
            img_path, rel_path, _ = img_tuple
            
            row_frame = ttk.Frame(scrollable_frame)
            row_frame.grid(row=idx, column=0, sticky=tk.W, pady=5, padx=5)
            
            try:
                img = Image.open(img_path)
                img.thumbnail((150, 200), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                preview_images.append(photo)
                
                preview_label = ttk.Label(row_frame, image=photo)
                preview_label.image = photo
                preview_label.pack(side=tk.LEFT, padx=5)
                
                text_label = ttk.Label(row_frame, text=os.path.basename(rel_path), width=50, anchor=tk.W)
                text_label.pack(side=tk.LEFT, padx=5)
                
                select_btn = ttk.Button(row_frame, text="Seleccionar", 
                                       command=lambda p=img_path, n=rel_path, rf=row_frame: on_image_select(p, n, rf))
                select_btn.pack(side=tk.LEFT, padx=5)
                
                status_label = ttk.Label(row_frame, text="", width=15)
                status_label.pack(side=tk.LEFT, padx=5)
                status_labels[row_frame] = status_label
                
            except Exception as e:
                ttk.Label(row_frame, text=f"Error: {os.path.basename(rel_path)}").pack(side=tk.LEFT)
        
        total_images = len(all_images)
        if total_images > max_previews:
            ttk.Label(scrollable_frame, text=f"... y {total_images - max_previews} imágenes más (mostrando las primeras {max_previews})").grid(row=max_previews, column=0, pady=10)
        
        def confirm_selection():
            if selected_image[0]:
                volume_data = None
                for cb in self.cbr_checkboxes:
                    if cb.get('is_group', False) and cb['group_name'] == volume_name:
                        volume_data = cb
                        break
                
                if volume_data and volume_data.get('is_group', False):
                    group_key = f"group_{volume_name}"
                    abs_path = os.path.abspath(selected_image[0])
                    self.selected_cover[group_key] = abs_path
                    self.log(f"Portada seleccionada para {volume_name}: {os.path.basename(selected_image[0])}")
                else:
                    abs_path = os.path.abspath(selected_image[0])
                    volume_path_normalized = os.path.normpath(os.path.abspath(volume_path))
                    self.selected_cover[volume_path_normalized] = abs_path
                    self.log(f"Portada seleccionada para {volume_name}: {os.path.basename(selected_image[0])}")
            
            cover_window.destroy()
            self.current_cover_index += 1
            self.root.after(100, self.process_next_cover)
        
        def cancel_selection():
            cover_window.destroy()
            self.current_cover_index += 1
            self.root.after(100, self.process_next_cover)
        
        button_frame = ttk.Frame(cover_window)
        button_frame.pack(pady=10)
        
        if current < total:
            confirm_text = f"Confirmar y Continuar ({current}/{total})"
            cancel_text = f"Omitir y Continuar ({current}/{total})"
        else:
            confirm_text = "Confirmar"
            cancel_text = "Cancelar"
        
        ttk.Button(button_frame, text=confirm_text, command=confirm_selection).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=cancel_text, command=cancel_selection).pack(side=tk.LEFT, padx=5)
    
    def generate_cbrs(self):
        selected_volumes = [cb for cb in self.cbr_checkboxes if cb['var'].get()]
        
        if not selected_volumes:
            messagebox.showwarning("Advertencia", "Por favor selecciona al menos un tomo/capítulo")
            return
        
        selected_manga_title = self.manga_combo.get()
        if not selected_manga_title:
            messagebox.showwarning("Advertencia", "Por favor selecciona un manga")
            return
        
        is_olympus = selected_volumes[0].get('is_olympus', False)
        
        self.generate_cbr_btn.config(state='disabled')
        self.progress_var.set("Generando CBRs...")
        self.progress_bar.start()
        
        def generate_thread():
            try:
                output_dir = self.config['output_dir']
                
                if not os.path.isabs(output_dir):
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    output_dir = os.path.join(script_dir, output_dir)
                
                selected_manga = next((m for m in self.mangas_data if m['title'] == selected_manga_title), None)
                if not selected_manga:
                    return
                
                if selected_manga['folder'] == '.':
                    manga_dir = output_dir
                else:
                    manga_dir = os.path.join(output_dir, selected_manga['folder'])
                
                generated_cbrs = []
                
                self.root.after(0, lambda: self.log(f"{'='*60}"))
                self.root.after(0, lambda: self.log("GENERADOR DE CBR"))
                self.root.after(0, lambda: self.log(f"{'='*60}"))
                self.root.after(0, lambda: self.log(f"Manga: {selected_manga_title}"))
                
                metadata = self.generator.load_metadata(manga_dir)
                title = self.get_title_from_directory(manga_dir)
                
                for idx, volume_data in enumerate(selected_volumes, start=1):
                    volume_name = volume_data['volume_name']
                    volume_path_normalized = os.path.normpath(os.path.abspath(volume_data.get('volume_path', '')))
                    
                    if volume_data.get('is_group', False):
                        self.root.after(0, lambda idx=idx, total=len(selected_volumes), name=volume_name: self.log(f"\n[{idx}/{total}] Procesando grupo: {name}"))
                        
                        chapter_dirs = volume_data.get('chapter_paths', [])
                        if not chapter_dirs:
                            continue
                        
                        group_key = f"group_{volume_name}"
                        cover_image = self.selected_cover.get(group_key)
                        if not cover_image:
                            cover_image = self.selected_cover.get(volume_path_normalized)
                        
                        if cover_image:
                            self.root.after(0, lambda cover=os.path.basename(cover_image): self.log(f"Usando portada personalizada: {cover}"))
                        
                        cbr_path = self.generator.generate_cbr_from_multiple_chapters(chapter_dirs, manga_dir, title, cover_image, metadata)
                        
                        if cbr_path:
                            generated_cbrs.append(cbr_path)
                            self.root.after(0, lambda name=os.path.basename(cbr_path): self.log(f"[OK] CBR generado: {name}"))
                    else:
                        self.root.after(0, lambda idx=idx, total=len(selected_volumes), name=volume_name: self.log(f"\n[{idx}/{total}] Procesando: {name}"))
                        
                        volume_path = volume_data['volume_path']
                        cover_image = self.selected_cover.get(volume_path_normalized)
                        if not cover_image:
                            cover_image = self.selected_cover.get(volume_path)
                        
                        if cover_image:
                            self.root.after(0, lambda name=volume_name, cover=os.path.basename(cover_image): self.log(f"Usando portada personalizada: {cover}"))
                        
                        cbr_path = self.generator.generate_cbr_from_folder(volume_path, manga_dir, title, metadata, cover_image)
                        
                        if cbr_path:
                            generated_cbrs.append(cbr_path)
                            self.root.after(0, lambda name=os.path.basename(cbr_path): self.log(f"[OK] CBR generado: {name}"))
                
                if generated_cbrs:
                    self.root.after(0, lambda: self.log(f"\n{'='*60}"))
                    self.root.after(0, lambda count=len(generated_cbrs): self.log(f"GENERACIÓN COMPLETADA ({count} CBRs)"))
                    self.root.after(0, lambda: self.log(f"{'='*60}"))
                    
                    def ask_delete_images():
                        response = messagebox.askyesno(
                            "Eliminar imágenes",
                            f"Se generaron {len(generated_cbrs)} archivos CBR.\n\n¿Deseas eliminar las carpetas de imágenes de los tomos convertidos?",
                            icon='question'
                        )
                        if response:
                            self.delete_image_folders(generated_cbrs, manga_dir)
                    
                    self.root.after(0, lambda count=len(generated_cbrs): messagebox.showinfo("Éxito", f"Se generaron {count} archivos CBR"))
                    self.root.after(0, ask_delete_images)
                else:
                    self.root.after(0, lambda: messagebox.showinfo("Info", "No se generaron archivos CBR"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Error al generar CBRs: {str(e)}"))
                self.root.after(0, lambda e=str(e): self.log(f"Error: {e}"))
            finally:
                self.root.after(0, self.generate_complete)
        
        thread = threading.Thread(target=generate_thread, daemon=True)
        thread.start()
    
    def delete_image_folders(self, generated_cbrs, manga_dir):
        self.progress_var.set("Eliminando imágenes...")
        self.progress_bar.start()
        
        def delete_thread():
            try:
                deleted_folders = []
                
                for cbr_path in generated_cbrs:
                    cbr_name = os.path.basename(cbr_path)
                    
                    import re
                    tomo_match = re.search(r'Tomo\s+(\d+)', cbr_name)
                    if tomo_match:
                        tomo_number = tomo_match.group(1)
                        
                        for item in os.listdir(manga_dir):
                            item_path = os.path.join(manga_dir, item)
                            if os.path.isdir(item_path) and not item.endswith('.cbr'):
                                volume_name = os.path.basename(item_path)
                                
                                volume_tomo_match = re.search(r'Tomo\s+(\d+)', volume_name)
                                if volume_tomo_match:
                                    volume_tomo_number = volume_tomo_match.group(1)
                                    
                                    if tomo_number == volume_tomo_number:
                                        try:
                                            shutil.rmtree(item_path)
                                            deleted_folders.append(volume_name)
                                            self.root.after(0, lambda name=volume_name: self.log(f"[ELIMINADO] {name}"))
                                        except Exception as e:
                                            self.root.after(0, lambda name=volume_name, err=str(e): self.log(f"[ERROR] No se pudo eliminar {name}: {err}"))
                                        break
                
                if deleted_folders:
                    self.root.after(0, lambda count=len(deleted_folders): self.log(f"\n{'='*60}"))
                    self.root.after(0, lambda count=len(deleted_folders): self.log(f"Eliminadas {count} carpetas de imágenes"))
                    self.root.after(0, lambda: self.log(f"{'='*60}"))
                    self.root.after(0, lambda count=len(deleted_folders): messagebox.showinfo("Éxito", f"Se eliminaron {count} carpetas de imágenes"))
                else:
                    self.root.after(0, lambda: self.log("No se encontraron carpetas para eliminar"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Error al eliminar imágenes: {str(e)}"))
                self.root.after(0, lambda e=str(e): self.log(f"Error: {e}"))
            finally:
                self.root.after(0, self.generate_complete)
        
        thread = threading.Thread(target=delete_thread, daemon=True)
        thread.start()
    
    def generate_complete(self):
        self.generate_cbr_btn.config(state='normal')
        self.progress_bar.stop()
        self.progress_var.set("Listo")
    
    def load_rar_mangas(self):
        output_dir = self.config['output_dir']
        
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, output_dir)
        
        self.log(f"Buscando contenido en: {output_dir}")
        
        if not os.path.exists(output_dir):
            self.log(f"[ERROR] El directorio no existe: {output_dir}")
            messagebox.showerror("Error", f"El directorio {output_dir} no existe")
            return
        
        content_list = self.load_content_list(output_dir)
        
        items_found = []
        try:
            items_found = [item for item in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, item)) and not item.endswith('.cbr')]
        except Exception as e:
            self.log(f"[ERROR] Error al listar directorio: {e}")
            return
        
        for item in items_found:
            item_path = os.path.join(output_dir, item)
            if not any(c['folder'] == item for c in content_list):
                has_cbrs = False
                for subitem in os.listdir(item_path):
                    if subitem.lower().endswith('.cbr'):
                        has_cbrs = True
                        break
                    subitem_path = os.path.join(item_path, subitem)
                    if os.path.isdir(subitem_path):
                        for file in os.listdir(subitem_path):
                            if file.lower().endswith('.cbr'):
                                has_cbrs = True
                                break
                if has_cbrs:
                    content_list.append({
                        'title': item,
                        'folder': item,
                        'source_type': 'inventario_oculto'
                    })
        
        if content_list:
            titles = [item['title'] for item in content_list]
            self.rar_manga_combo['values'] = titles
            self.rar_mangas_data = content_list
            self.log(f"Contenido encontrado: {len(content_list)}")
        else:
            self.rar_manga_combo['values'] = []
            self.rar_mangas_data = []
            self.log("[ADVERTENCIA] No se encontró contenido")
            messagebox.showinfo("Info", f"No se encontró contenido en:\n{output_dir}")
    
    def on_rar_manga_selected(self, event=None):
        selected_title = self.rar_manga_combo.get()
        if not selected_title or not hasattr(self, 'rar_mangas_data'):
            return
        
        selected_manga = next((m for m in self.rar_mangas_data if m['title'] == selected_title), None)
        if not selected_manga:
            return
        
        output_dir = self.config['output_dir']
        
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, output_dir)
        
        if selected_manga['folder'] == '.':
            manga_dir = output_dir
        else:
            manga_dir = os.path.join(output_dir, selected_manga['folder'])
        
        cbr_list = []
        for root, dirs, files in os.walk(manga_dir):
            for file in files:
                if file.lower().endswith('.cbr'):
                    cbr_path = os.path.join(root, file)
                    manga_title, tomo_number = extract_manga_title_and_tomo(file)
                    if manga_title and tomo_number:
                        cbr_list.append((tomo_number, cbr_path, file))
                    else:
                        cbr_list.append((999, cbr_path, file))
        
        cbr_list.sort(key=lambda x: x[0])
        
        self.load_rar_cbrs(cbr_list)
    
    def load_rar_cbrs(self, cbr_list):
        for widget in self.rar_cbrs_frame.winfo_children():
            widget.destroy()
        
        self.rar_checkboxes = []
        
        if not cbr_list:
            return
        
        for idx, (tomo_number, cbr_path, cbr_filename) in enumerate(cbr_list, start=1):
            var = tk.BooleanVar()
            
            checkbox = ttk.Checkbutton(
                self.rar_cbrs_frame,
                text=f"Tomo {tomo_number:02d}: {cbr_filename}",
                variable=var
            )
            checkbox.grid(row=idx-1, column=0, sticky=tk.W, padx=5, pady=2)
            
            self.rar_checkboxes.append({
                'var': var,
                'tomo_number': tomo_number,
                'cbr_path': cbr_path,
                'cbr_filename': cbr_filename
            })
    
    def select_all_rar(self):
        for cb in self.rar_checkboxes:
            cb['var'].set(True)
    
    def deselect_all_rar(self):
        for cb in self.rar_checkboxes:
            cb['var'].set(False)
    
    def generate_rars(self):
        selected_cbrs = [cb for cb in self.rar_checkboxes if cb['var'].get()]
        
        if not selected_cbrs:
            messagebox.showwarning("Advertencia", "Por favor selecciona al menos un CBR")
            return
        
        selected_manga_title = self.rar_manga_combo.get()
        if not selected_manga_title:
            messagebox.showwarning("Advertencia", "Por favor selecciona un manga")
            return
        
        try:
            tomo_range = int(self.tomos_per_rar_var.get())
            if tomo_range < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Por favor ingresa un número válido de tomos por RAR (1-20)")
            return
        
        self.generate_rar_btn.config(state='disabled')
        self.progress_var.set("Generando RARs...")
        self.progress_bar.start()
        
        def generate_thread():
            try:
                output_dir = self.config['output_dir']
                
                if not os.path.isabs(output_dir):
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    output_dir = os.path.join(script_dir, output_dir)
                
                selected_manga = next((m for m in self.rar_mangas_data if m['title'] == selected_manga_title), None)
                if not selected_manga:
                    return
                
                if selected_manga['folder'] == '.':
                    manga_dir = output_dir
                else:
                    manga_dir = os.path.join(output_dir, selected_manga['folder'])
                
                self.root.after(0, lambda: self.log(f"{'='*60}"))
                self.root.after(0, lambda: self.log("GENERADOR DE RAR"))
                self.root.after(0, lambda: self.log(f"{'='*60}"))
                self.root.after(0, lambda: self.log(f"Manga: {selected_manga_title}"))
                self.root.after(0, lambda count=len(selected_cbrs): self.log(f"CBRs seleccionados: {count}"))
                self.root.after(0, lambda tr=tomo_range: self.log(f"Tomos por RAR: {tr}"))
                
                selected_cbrs_sorted = sorted(selected_cbrs, key=lambda x: x['tomo_number'])
                
                created_rars = []
                i = 0
                while i < len(selected_cbrs_sorted):
                    group = selected_cbrs_sorted[i:i+tomo_range]
                    first_tomo = group[0]['tomo_number']
                    last_tomo = group[-1]['tomo_number']
                    
                    zip_name = create_zip_name(selected_manga_title, first_tomo, last_tomo)
                    zip_path = os.path.join(manga_dir, zip_name)
                    
                    cbr_files = [cb['cbr_path'] for cb in group]
                    tomo_numbers = [str(cb['tomo_number']) for cb in group]
                    
                    self.root.after(0, lambda name=zip_name, tomos=', '.join(tomo_numbers): self.log(f"\n[INFO] Creando: {name}"))
                    self.root.after(0, lambda tomos=', '.join(tomo_numbers): self.log(f"       Tomos incluidos: {tomos}"))
                    
                    if create_zip_from_cbrs(cbr_files, zip_path):
                        created_rars.append(zip_path)
                        file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
                        self.root.after(0, lambda name=zip_name, size=file_size_mb: self.log(f"[OK] RAR creado: {name} ({size:.2f} MB)"))
                    else:
                        self.root.after(0, lambda name=zip_name: self.log(f"[ERROR] No se pudo crear: {name}"))
                    
                    i += tomo_range
                
                if created_rars:
                    self.root.after(0, lambda: self.log(f"\n{'='*60}"))
                    self.root.after(0, lambda count=len(created_rars): self.log(f"GENERACIÓN COMPLETADA ({count} RARs)"))
                    self.root.after(0, lambda: self.log(f"{'='*60}"))
                    self.root.after(0, lambda: messagebox.showinfo("Completado", f"Se generaron {len(created_rars)} archivos RAR"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("Error", "No se pudieron generar los archivos RAR"))
                
            except Exception as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("Error", f"Error al generar RARs: {err}"))
                self.root.after(0, lambda err=str(e): self.log(f"[ERROR] {err}"))
                import traceback
                self.root.after(0, lambda: self.log(traceback.format_exc()))
            finally:
                self.root.after(0, self.generate_rar_complete)
        
        thread = threading.Thread(target=generate_thread, daemon=True)
        thread.start()
    
    def generate_rar_complete(self):
        self.generate_rar_btn.config(state='normal')
        self.progress_bar.stop()
        self.progress_var.set("Listo")


def select_website_dialog():
    root = tk.Tk()
    root.title("Seleccionar Web")
    root.geometry("600x450")
    root.resizable(False, False)
    
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - 600) // 2
    y = (screen_height - 450) // 2
    root.geometry(f"600x450+{x}+{y}")
    
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)
    
    title_label = ttk.Label(root, text="Selecciona la web de manga:", font=("Arial", 14, "bold"))
    title_label.grid(row=0, column=0, pady=30)
    
    websites_frame = ttk.Frame(root)
    websites_frame.grid(row=1, column=0, padx=40, pady=20, sticky=(tk.W, tk.E))
    websites_frame.columnconfigure(0, weight=1, uniform="websites")
    websites_frame.columnconfigure(1, weight=1, uniform="websites")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    websites = [
        {
            'name': 'Inventario Oculto',
            'id': 'inventario_oculto',
            'logo': os.path.join(script_dir, 'logos', 'logo_inventario_oculto.png')
        },
        {
            'name': 'Olympus Scan',
            'id': 'olympus_scan',
            'logo': os.path.join(script_dir, 'logos', 'logo_olympus_scan.webp')
        }
    ]
    
    selected_website = [None]
    logo_labels = []
    buttons = []
    
    logo_containers = []
    for idx, website in enumerate(websites):
        logo_path = website['logo']
        logo_img = None
        
        if PIL_AVAILABLE and os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                max_size = (220, 160)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                logo_img = img
            except Exception as e:
                print(f"[ADVERTENCIA] No se pudo cargar logo {logo_path}: {e}")
        
        logo_containers.append(logo_img)
    
    max_logo_height = 0
    for logo_img in logo_containers:
        if logo_img and logo_img.height > max_logo_height:
            max_logo_height = logo_img.height
    
    if max_logo_height == 0:
        max_logo_height = 150
    
    button_row_height = 40
    
    for idx, website in enumerate(websites):
        website_frame = ttk.LabelFrame(websites_frame, text=website['name'], padding="15")
        website_frame.grid(row=0, column=idx, padx=15, pady=10, sticky=(tk.W, tk.E, tk.N, tk.S))
        website_frame.columnconfigure(0, weight=1)
        website_frame.rowconfigure(0, weight=0)
        website_frame.rowconfigure(1, minsize=max_logo_height + 30 if max_logo_height > 0 else 180)
        website_frame.rowconfigure(2, minsize=button_row_height)
        
        logo_img = logo_containers[idx]
        logo_label = None
        
        if logo_img:
            try:
                logo_image = ImageTk.PhotoImage(logo_img)
                logo_label = ttk.Label(website_frame, image=logo_image)
                logo_label.image = logo_image
                logo_label.grid(row=1, column=0, pady=15)
            except Exception as e:
                print(f"[ADVERTENCIA] Error al mostrar logo: {e}")
        
        if not logo_label:
            placeholder = ttk.Label(website_frame, text="[Logo no disponible]", font=("Arial", 10), foreground="gray")
            placeholder.grid(row=1, column=0, pady=15)
            logo_label = placeholder
        
        logo_labels.append(logo_label)
        
        def create_select_handler(website_id):
            def handler():
                selected_website[0] = website_id
                root.destroy()
            return handler
        
        select_btn = ttk.Button(website_frame, text="Seleccionar", command=create_select_handler(website['id']), width=20)
        select_btn.grid(row=2, column=0, pady=(15, 0), sticky=(tk.W, tk.E))
        buttons.append(select_btn)
    
    def on_close():
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    
    return selected_website[0]

def main():
    root = tk.Tk()
    app = MangaDownloaderGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()

