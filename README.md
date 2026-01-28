<<<<<<< HEAD
# manga-downloader
Herramienta para descargar manga desde ciertas webs en particular
=======
# Manga Downloader - Generador CBR

Herramienta completa en Python para descargar manga desde múltiples sitios web y generar archivos CBR (Comic Book Archive) para lectores de cómics.

## Características

- **Múltiples fuentes:** Soporta descarga desde varios sitios de manga
  - Inventario Oculto
  - MangaTV
  - Tomos Manga
  - Lecktor Knight
  - Olympus Scan
  - Zona TMO
  - Y más...
- **Detección automática:** Identifica volúmenes y capítulos disponibles
- **Descarga inteligente:** Descarga todas las imágenes en orden
- **Generador CBR:** Crea archivos CBR listos para visores de cómics
- **Interfaz GUI:** Versión con interfaz gráfica para mayor comodidad
- **CLI:** Herramientas de línea de comandos para automatización
- **Utilidades:** Scripts para organizar, eliminar y procesar imágenes

## Scripts Disponibles

| Script | Descripción |
|--------|-------------|
| `manga_downloader.py` | Descargador principal desde Inventario Oculto |
| `manga_downloader_gui.py` | Versión con interfaz gráfica |
| `mangatv_downloader.py` | Descargador de MangaTV |
| `tomosmanga_downloader.py` | Descargador de TomosManga |
| `lectorknight_downloader.py` | Descargador de Lecktor Knight |
| `olympus_scan_downloader.py` | Descargador de Olympus Scan |
| `zonatmo_downloader.py` | Descargador de Zona TMO |
| `cbr_generator.py` | Generador de archivos CBR desde carpetas |
| `delete_images_gui.py` | Eliminador de imágenes con interfaz gráfica |
| `delete_001_images.py` | Elimina imágenes 001 de series |
| `create_rar.py` | Crea archivos RAR |

## Requisitos Previos

- **Python 3.7+** o superior
- **Chrome/Chromium** instalado en el sistema (para Selenium)
- **pip** (gestor de paquetes de Python)
- Windows, Linux o macOS

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/manga-downloader.git
cd manga-downloader
```

### 2. Crear entorno virtual

```bash
python -m venv venv
```

### 3. Activar el entorno virtual

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/macOS:**
```bash
source venv/bin/activate
```

### 4. Instalar dependencias

```bash
pip install -r requirements.txt
```

## Uso

### Opción 1: Interfaz Gráfica (Recomendado)

```bash
python manga_downloader_gui.py
```

Simple e intuitiva, ideal para usuarios sin experiencia en CLI.

### Opción 2: Línea de Comandos

**Descargador principal:**
```bash
python manga_downloader.py
```

O con URL directa:
```bash
python manga_downloader.py "https://inventariooculto.com/manga/soul-eater/"
```

Con opciones de depuración:
```bash
python manga_downloader.py "https://inventariooculto.com/manga/soul-eater/" --debug
```

### Opción 3: Generar CBR desde carpeta

Si ya tienes las imágenes descargadas:
```bash
python cbr_generator.py
```

## Selección de Volúmenes

El programa soporta varias formas de seleccionar volúmenes:

- `1` - Solo el volumen 1
- `1,3,5` - Volúmenes 1, 3 y 5
- `1-5` - Volúmenes del 1 al 5 (inclusivo)
- `all` - Todos los volúmenes disponibles

## Estructura del Proyecto

```
manga-downloader/
├── manga_downloader.py
├── manga_downloader_gui.py
├── mangatv_downloader.py
├── tomosmanga_downloader.py
├── lectorknight_downloader.py
├── olympus_scan_downloader.py
├── zonatmo_downloader.py
├── cbr_generator.py
├── delete_images_gui.py
├── delete_001_images.py
├── create_rar.py
├── requirements.txt
├── README.md
├── .gitignore
├── config.json
├── downloads/
├── resources/
├── logos/
└── venv/
```

## Configuración

Edita `config.json` para personalizar:

```json
{
  "chrome_path": "ruta/a/chrome",
  "timeout": 30,
  "delay": 1,
  "output_format": "cbr"
}
```

## Dependencias

- `requests` - Peticiones HTTP
- `beautifulsoup4` - Parsing HTML
- `lxml` - Parser XML
- `selenium` - Automatización web y JavaScript
- `tqdm` - Barras de progreso
- `Pillow` - Procesamiento de imágenes

## Notas Importantes

- Los archivos CBR se guardan en `downloads/`
- El programa incluye pausas entre descargas para no sobrecargar servidores
- Los nombres de archivo se limpian automáticamente
- Compatible con lectores de cómics: MangaStorm, ComiXology, etc.
- Requiere conexión a internet
- Respeta los términos de servicio de los sitios web

## Solución de Problemas

### ChromeDriver no encontrado
```bash
pip install --upgrade webdriver-manager
```

### Errores de conexión
Verifica tu conexión a internet y que el sitio web funcione correctamente.

### Archivos incompletos
Reinicia la descarga; el programa reanudará desde donde se detuvo.

## Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está bajo la licencia MIT. Ver [LICENSE](LICENSE) para más detalles.

## Aviso Legal

Esta herramienta está diseñada con propósitos educativos. El usuario es responsable de verificar que tiene los derechos para descargar el contenido. Respeta siempre los términos de servicio de los sitios web.

## Contacto

Para reportar bugs o sugerencias, abre un [Issue](../../issues) en el repositorio.

---

Hecho para los amantes del manga

>>>>>>> dd3621e (Initial commit)
