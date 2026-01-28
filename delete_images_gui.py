import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import hashlib
from pathlib import Path
from collections import defaultdict
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False

class DeleteImagesGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Eliminar Imágenes por Contenido")
        self.root.geometry("1000x700")
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_downloads = os.path.join(script_dir, "downloads")
        
        self.reference_image_paths = []
        self.manga_folder_path = tk.StringVar(value=default_downloads if os.path.exists(default_downloads) else "")
        self.matching_images = []
        self.image_vars = {}
        self.thumbnail_images = []
        self.selected_preview_images = []
        self.search_thread = None
        self.is_searching = False
        self.progress_var = tk.StringVar(value="Listo")
        
        self.setup_ui()
        
        if self.manga_folder_path.get() and os.path.exists(self.manga_folder_path.get()):
            self.add_ref_btn.config(state="normal")
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(top_frame, text="Carpeta de manga:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Entry(top_frame, textvariable=self.manga_folder_path, width=50, state="readonly").grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(top_frame, text="Seleccionar", command=self.select_manga_folder).grid(row=0, column=2, padx=(0, 10))
        
        ref_header_frame = ttk.Frame(top_frame)
        ref_header_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
        
        ttk.Label(ref_header_frame, text="Imágenes de referencia:").pack(side=tk.LEFT, padx=(0, 10))
        ref_btn_frame = ttk.Frame(ref_header_frame)
        ref_btn_frame.pack(side=tk.LEFT)
        self.add_ref_btn = ttk.Button(ref_btn_frame, text="Agregar", command=self.add_reference_image, state="disabled")
        self.add_ref_btn.pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(ref_btn_frame, text="Quitar", command=self.remove_reference_image).pack(side=tk.LEFT)
        
        ref_frame = ttk.Frame(ref_header_frame)
        ref_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.reference_listbox = tk.Listbox(ref_frame, height=3)
        self.reference_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ref_scroll = ttk.Scrollbar(ref_frame, orient=tk.VERTICAL, command=self.reference_listbox.yview)
        ref_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.reference_listbox.config(yscrollcommand=ref_scroll.set)
        
        top_frame.columnconfigure(1, weight=1)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.search_btn = ttk.Button(button_frame, text="Buscar Imágenes Similares", command=self.search_similar_images)
        self.search_btn.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Seleccionar Todas", command=self.select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Deseleccionar Todas", command=self.deselect_all).pack(side=tk.LEFT, padx=(0, 5))
        delete_btn = ttk.Button(button_frame, text="Eliminar Seleccionadas", command=self.delete_selected)
        delete_btn.pack(side=tk.LEFT)
        
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 5))
        info_label = ttk.Label(info_frame, text="Imágenes encontradas: 0", font=("Arial", 10, "bold"))
        info_label.pack(side=tk.LEFT)
        progress_label = ttk.Label(info_frame, textvariable=self.progress_var, font=("Arial", 9))
        progress_label.pack(side=tk.LEFT, padx=(10, 0))
        self.progress_bar = ttk.Progressbar(info_frame, mode='indeterminate')
        self.progress_bar.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
        self.info_label = info_label
        
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        results_frame = ttk.Frame(notebook)
        notebook.add(results_frame, text="Imágenes Encontradas")
        
        selected_frame = ttk.Frame(notebook)
        notebook.add(selected_frame, text="Seleccionadas para Eliminar (0)")
        
        selected_info_frame = ttk.Frame(selected_frame)
        selected_info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        info_left_frame = ttk.Frame(selected_info_frame)
        info_left_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        selected_info_label = ttk.Label(info_left_frame, text="0 imágenes seleccionadas", font=("Arial", 10, "bold"))
        selected_info_label.pack(side=tk.LEFT)
        self.selected_info_label = selected_info_label
        
        info_right_frame = ttk.Frame(selected_info_frame)
        info_right_frame.pack(side=tk.RIGHT)
        ttk.Label(info_right_frame, text="Imágenes de referencia:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=(20, 5))
        
        canvas_frame = ttk.Frame(results_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(canvas_frame, bg="white")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        def update_scrollregion(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        scrollable_frame.bind("<Configure>", update_scrollregion)
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        def unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
        
        canvas.bind("<Enter>", bind_mousewheel)
        canvas.bind("<Leave>", unbind_mousewheel)
        scrollable_frame.bind("<Enter>", bind_mousewheel)
        scrollable_frame.bind("<Leave>", unbind_mousewheel)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.canvas = canvas
        self.scrollable_frame = scrollable_frame
        self.update_scrollregion = update_scrollregion
        
        selected_canvas_frame = ttk.Frame(selected_frame)
        selected_canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        selected_canvas = tk.Canvas(selected_canvas_frame, bg="white")
        selected_scrollbar = ttk.Scrollbar(selected_canvas_frame, orient="vertical", command=selected_canvas.yview)
        selected_scrollable_frame = ttk.Frame(selected_canvas)
        
        def update_selected_scrollregion(event=None):
            selected_canvas.configure(scrollregion=selected_canvas.bbox("all"))
        
        selected_scrollable_frame.bind("<Configure>", update_selected_scrollregion)
        
        selected_canvas.create_window((0, 0), window=selected_scrollable_frame, anchor="nw")
        selected_canvas.configure(yscrollcommand=selected_scrollbar.set)
        
        def on_selected_mousewheel(event):
            selected_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def bind_selected_mousewheel(event):
            selected_canvas.bind_all("<MouseWheel>", on_selected_mousewheel)
        
        def unbind_selected_mousewheel(event):
            selected_canvas.unbind_all("<MouseWheel>")
        
        selected_canvas.bind("<Enter>", bind_selected_mousewheel)
        selected_canvas.bind("<Leave>", unbind_selected_mousewheel)
        selected_scrollable_frame.bind("<Enter>", bind_selected_mousewheel)
        selected_scrollable_frame.bind("<Leave>", unbind_selected_mousewheel)
        
        selected_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        selected_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.selected_canvas = selected_canvas
        self.selected_scrollable_frame = selected_scrollable_frame
        self.update_selected_scrollregion = update_selected_scrollregion
        self.selected_info_label = None
    
    def add_reference_image(self):
        manga_path = self.manga_folder_path.get()
        if not manga_path or not os.path.exists(manga_path):
            messagebox.showerror("Error", "Por favor selecciona primero una carpeta de manga")
            return
        
        file_paths = filedialog.askopenfilenames(
            title="Seleccionar Imagen(es) de Referencia",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.webp *.gif"), ("Todos los archivos", "*.*")]
        )
        for file_path in file_paths:
            if file_path not in self.reference_image_paths:
                self.reference_image_paths.append(file_path)
                self.reference_listbox.insert(tk.END, os.path.basename(file_path))
        if file_paths:
            self.matching_images = []
            self.image_vars = {}
            self.clear_preview()
            self.update_selected_preview()
    
    def remove_reference_image(self):
        selection = self.reference_listbox.curselection()
        if selection:
            idx = selection[0]
            self.reference_listbox.delete(idx)
            self.reference_image_paths.pop(idx)
            self.matching_images = []
            self.image_vars = {}
            self.clear_preview()
            self.update_selected_preview()
    
    def select_manga_folder(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_path = os.path.join(script_dir, "downloads")
        initial_dir = default_path if os.path.exists(default_path) else script_dir
        
        folder_path = filedialog.askdirectory(title="Seleccionar Carpeta de Manga", initialdir=initial_dir)
        if folder_path:
            self.manga_folder_path.set(folder_path)
            self.add_ref_btn.config(state="normal")
            self.matching_images = []
            self.image_vars = {}
            self.clear_preview()
    
    
    def calculate_file_hash(self, file_path):
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"Error al calcular hash de {file_path}: {e}")
            return None
    
    def calculate_image_hash(self, file_path):
        if not PIL_AVAILABLE:
            return None
        
        try:
            img = Image.open(file_path)
            img = img.convert('RGB')
            
            if IMAGEHASH_AVAILABLE:
                img_hash = imagehash.phash(img, hash_size=8)
                return str(img_hash)
            else:
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
                pixels = list(img.getdata())
                pixel_hash = hashlib.md5(str(pixels).encode()).hexdigest()
                return pixel_hash
        except Exception as e:
            print(f"Error al calcular hash perceptual de {file_path}: {e}")
            return None
    
    def search_similar_images(self):
        if self.is_searching:
            messagebox.showinfo("Buscando", "Ya hay una búsqueda en progreso")
            return
        
        if not self.reference_image_paths:
            messagebox.showerror("Error", "Por favor selecciona al menos una imagen de referencia")
            return
        
        manga_path = self.manga_folder_path.get()
        if not manga_path or not os.path.exists(manga_path):
            messagebox.showerror("Error", "Por favor selecciona una carpeta de manga válida")
            return
        
        self.clear_preview()
        self.is_searching = True
        self.search_btn.config(state="disabled")
        self.progress_var.set("Calculando hashes de referencia...")
        self.progress_bar.start()
        
        def search_thread():
            try:
                reference_hashes = []
                for ref_path in self.reference_image_paths:
                    if not os.path.exists(ref_path):
                        continue
                    ref_hash = self.calculate_image_hash(ref_path)
                    if ref_hash:
                        reference_hashes.append(ref_hash)
                
                if not reference_hashes:
                    self.root.after(0, lambda: messagebox.showerror("Error", "No se pudieron calcular los hashes de las imágenes de referencia"))
                    self.root.after(0, self.search_complete)
                    return
                
                hash_type = "perceptual (pHash)" if IMAGEHASH_AVAILABLE else "píxeles normalizados"
                self.root.after(0, lambda: self.progress_var.set(f"Buscando imágenes similares ({hash_type}, {len(reference_hashes)} referencias)..."))
                
                base = Path(manga_path)
                image_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
                all_images = []
                for ext in image_extensions:
                    all_images.extend(base.glob(f"**/*{ext}"))
                    all_images.extend(base.glob(f"**/*{ext.upper()}"))
                
                all_images = [img for img in all_images if img.is_file()]
                
                self.root.after(0, lambda: self.progress_var.set(f"Calculando hashes perceptuales de {len(all_images)} imágenes..."))
                
                matching_images = []
                processed = 0
                similarity_threshold = 5
                
                with ThreadPoolExecutor(max_workers=4) as executor:
                    future_to_image = {executor.submit(self.calculate_image_hash, str(img_path)): img_path for img_path in all_images}
                    
                    for future in as_completed(future_to_image):
                        img_path = future_to_image[future]
                        processed += 1
                        
                        if processed % 50 == 0:
                            self.root.after(0, lambda p=processed, t=len(all_images): self.progress_var.set(f"Procesadas {p}/{t} imágenes..."))
                        
                        try:
                            file_hash = future.result()
                            if not file_hash:
                                continue
                            
                            is_match = False
                            if IMAGEHASH_AVAILABLE:
                                img_hash1 = imagehash.hex_to_hash(file_hash)
                                for ref_hash_str in reference_hashes:
                                    img_hash2 = imagehash.hex_to_hash(ref_hash_str)
                                    hash_distance = img_hash1 - img_hash2
                                    if hash_distance <= similarity_threshold:
                                        is_match = True
                                        break
                            else:
                                if file_hash in reference_hashes:
                                    is_match = True
                            
                            if is_match:
                                matching_images.append(str(img_path))
                        except Exception as e:
                            print(f"Error procesando {img_path}: {e}")
                
                self.matching_images = matching_images
                self.root.after(0, self.update_preview)
                self.root.after(0, lambda: self.progress_var.set(f"Encontradas {len(matching_images)} imágenes similares"))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Error durante la búsqueda: {str(e)}"))
            finally:
                self.root.after(0, self.search_complete)
        
        self.search_thread = threading.Thread(target=search_thread, daemon=True)
        self.search_thread.start()
    
    def search_complete(self):
        self.is_searching = False
        self.search_btn.config(state="normal")
        self.progress_bar.stop()
    
    def clear_preview(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.thumbnail_images = []
        self.image_vars = {}
        self.info_label.config(text="Imágenes encontradas: 0")
    
    def update_preview(self):
        self.clear_preview()
        
        if not self.matching_images:
            ttk.Label(self.scrollable_frame, text="No se encontraron imágenes con el mismo contenido").pack(pady=20)
            return
        
        self.info_label.config(text=f"Imágenes encontradas: {len(self.matching_images)}")
        
        if not PIL_AVAILABLE:
            for img_path in self.matching_images:
                if not os.path.exists(img_path):
                    continue
                var = tk.BooleanVar(value=True)
                self.image_vars[img_path] = var
                frame = ttk.Frame(self.scrollable_frame)
                frame.pack(fill=tk.X, padx=5, pady=2)
                checkbox = ttk.Checkbutton(frame, text=img_path, variable=var, command=self.update_selected_preview)
                checkbox.pack(side=tk.LEFT, padx=5)
            self.update_scrollregion()
            return
        
        cols = 4
        for col_idx in range(cols):
            self.scrollable_frame.columnconfigure(col_idx, weight=1, uniform="img_col")
        
        for idx, img_path in enumerate(self.matching_images):
            if not os.path.exists(img_path):
                continue
                
            var = tk.BooleanVar(value=True)
            self.image_vars[img_path] = var
            
            row = idx // cols
            col = idx % cols
            
            item_frame = ttk.Frame(self.scrollable_frame, relief=tk.RAISED, borderwidth=1)
            item_frame.grid(row=row, column=col, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
            
            try:
                img = Image.open(img_path)
                img.thumbnail((150, 200), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.thumbnail_images.append(photo)
                
                preview_label = ttk.Label(item_frame, image=photo)
                preview_label.image = photo
                preview_label.pack(pady=5)
                
                rel_path = os.path.relpath(img_path, self.manga_folder_path.get())
                path_label = ttk.Label(item_frame, text=rel_path, wraplength=150)
                path_label.pack(pady=2)
                
                checkbox = ttk.Checkbutton(item_frame, text="Eliminar", variable=var, command=self.update_selected_preview)
                checkbox.pack(pady=2)
                
            except Exception as e:
                frame = ttk.Frame(self.scrollable_frame)
                frame.grid(row=row, column=col, padx=5, pady=5)
                checkbox = ttk.Checkbutton(frame, text=f"Error: {os.path.basename(img_path)}", variable=var, command=self.update_selected_preview)
                checkbox.pack()
        
        self.update_scrollregion()
    
    def select_all(self):
        for var in self.image_vars.values():
            var.set(True)
        self.update_selected_preview()
    
    def deselect_all(self):
        for var in self.image_vars.values():
            var.set(False)
        self.update_selected_preview()
    
    def update_selected_preview(self):
        for widget in self.selected_scrollable_frame.winfo_children():
            widget.destroy()
        self.selected_preview_images = []
        
        selected = [img_path for img_path, var in self.image_vars.items() if var.get()]
        
        if self.selected_info_label:
            self.selected_info_label.config(text=f"{len(selected)} imagen(es) seleccionada(s)")
            notebook = self.selected_scrollable_frame.master.master.master
            for i in range(notebook.index("end")):
                if notebook.tab(i, "text").startswith("Seleccionadas"):
                    notebook.tab(i, text=f"Seleccionadas para Eliminar ({len(selected)})")
                    break
        
        if not PIL_AVAILABLE:
            if selected:
                ttk.Label(self.selected_scrollable_frame, text="Imágenes seleccionadas para eliminar:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=5, pady=(5, 2))
                for img_path in selected:
                    if not os.path.exists(img_path):
                        continue
                    frame = ttk.Frame(self.selected_scrollable_frame)
                    frame.pack(fill=tk.X, padx=5, pady=2)
                    ttk.Label(frame, text=img_path).pack(side=tk.LEFT, padx=5)
            
            if self.reference_image_paths:
                ttk.Label(self.selected_scrollable_frame, text="Imágenes de referencia:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=5, pady=(20, 2))
                for img_path in self.reference_image_paths:
                    if not os.path.exists(img_path):
                        continue
                    frame = ttk.Frame(self.selected_scrollable_frame)
                    frame.pack(fill=tk.X, padx=5, pady=2)
                    ttk.Label(frame, text=img_path).pack(side=tk.LEFT, padx=5)
            
            if not selected and not self.reference_image_paths:
                ttk.Label(self.selected_scrollable_frame, text="No hay imágenes seleccionadas").pack(pady=20)
            
            self.update_selected_scrollregion()
            return
        
        current_row = 0
        
        if selected:
            ttk.Label(self.selected_scrollable_frame, text="Imágenes seleccionadas para eliminar:", font=("Arial", 10, "bold")).grid(row=current_row, column=0, columnspan=4, sticky=tk.W, padx=5, pady=(5, 10))
            current_row += 1
            
            cols = 4
            for col_idx in range(cols):
                self.selected_scrollable_frame.columnconfigure(col_idx, weight=1, uniform="sel_col")
            
            for idx, img_path in enumerate(selected):
                if not os.path.exists(img_path):
                    continue
                
                row = current_row + (idx // cols)
                col = idx % cols
                
                item_frame = ttk.Frame(self.selected_scrollable_frame, relief=tk.RAISED, borderwidth=1)
                item_frame.grid(row=row, column=col, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
                
                try:
                    img = Image.open(img_path)
                    img.thumbnail((150, 200), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self.selected_preview_images.append(photo)
                    
                    preview_label = ttk.Label(item_frame, image=photo)
                    preview_label.image = photo
                    preview_label.pack(pady=5)
                    
                    rel_path = os.path.relpath(img_path, self.manga_folder_path.get())
                    path_label = ttk.Label(item_frame, text=rel_path, wraplength=150)
                    path_label.pack(pady=2)
                    
                except Exception as e:
                    ttk.Label(item_frame, text=f"Error: {os.path.basename(img_path)}").pack(pady=5)
            
            if selected:
                current_row = row + 1
        
        if self.reference_image_paths:
            ttk.Label(self.selected_scrollable_frame, text="Imágenes de referencia:", font=("Arial", 10, "bold")).grid(row=current_row, column=0, columnspan=4, sticky=tk.W, padx=5, pady=(20, 10))
            current_row += 1
            
            cols = 4
            for idx, img_path in enumerate(self.reference_image_paths):
                if not os.path.exists(img_path):
                    continue
                
                row = current_row + (idx // cols)
                col = idx % cols
                
                item_frame = ttk.Frame(self.selected_scrollable_frame, relief=tk.RAISED, borderwidth=1, style="Accent.TFrame")
                item_frame.grid(row=row, column=col, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
                
                try:
                    img = Image.open(img_path)
                    img.thumbnail((150, 200), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self.selected_preview_images.append(photo)
                    
                    preview_label = ttk.Label(item_frame, image=photo)
                    preview_label.image = photo
                    preview_label.pack(pady=5)
                    
                    filename = os.path.basename(img_path)
                    path_label = ttk.Label(item_frame, text=filename, wraplength=150)
                    path_label.pack(pady=2)
                    
                except Exception as e:
                    ttk.Label(item_frame, text=f"Error: {os.path.basename(img_path)}").pack(pady=5)
        
        if not selected and not self.reference_image_paths:
            ttk.Label(self.selected_scrollable_frame, text="No hay imágenes seleccionadas").pack(pady=20)
        
        self.update_selected_scrollregion()
    
    def delete_selected(self):
        selected = [img_path for img_path, var in self.image_vars.items() if var.get()]
        
        if not selected:
            messagebox.showwarning("Advertencia", "No hay imágenes seleccionadas para eliminar")
            return
        
        confirm = messagebox.askyesno(
            "Confirmar Eliminación",
            f"¿Estás seguro de que deseas eliminar {len(selected)} imagen(es)?\n\nEsta acción no se puede deshacer."
        )
        
        if not confirm:
            return
        
        deleted_count = 0
        errors = []
        deleted_paths = set()
        
        for img_path in selected:
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
                    deleted_count += 1
                    deleted_paths.add(img_path)
            except Exception as e:
                errors.append(f"{os.path.basename(img_path)}: {str(e)}")
        
        if errors:
            error_msg = f"Eliminadas: {deleted_count}\n\nErrores:\n" + "\n".join(errors)
            messagebox.showwarning("Eliminación Parcial", error_msg)
        else:
            messagebox.showinfo("Éxito", f"Se eliminaron {deleted_count} imagen(es) correctamente")
        
        self.matching_images = [img for img in self.matching_images if img not in deleted_paths and os.path.exists(img)]
        
        refs_to_remove = []
        for idx, ref_path in enumerate(self.reference_image_paths):
            if ref_path in deleted_paths or not os.path.exists(ref_path):
                refs_to_remove.append(idx)
        
        for idx in reversed(refs_to_remove):
            self.reference_image_paths.pop(idx)
            self.reference_listbox.delete(idx)
        
        self.update_preview()
        self.update_selected_preview()

def main():
    root = tk.Tk()
    app = DeleteImagesGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
