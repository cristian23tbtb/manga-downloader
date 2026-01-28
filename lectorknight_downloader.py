import os
import sys
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Semaphore

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def load_config():
    config_path = 'config.json'
    default_config = {
        "timeout": 30,
        "retry_attempts": 5,
        "retry_delay": 2,
        "delay_between_images": 0.1,
        "delay_between_chapters": 0.5,
        "delay_between_volumes": 1,
        "min_file_size": 0,
        "output_dir": "downloads",
        "selenium_wait_time": 10,
        "selenium_extra_wait": 2,
        "parallel_tomos": 3,
        "parallel_chapters": 2,
        "parallel_images": 8,
        "retry_failed_images": 5,
        "force_redownload": False
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        except:
            pass
    return default_config


def save_metadata(manga_title, volumes, output_dir):
    metadata = {
        'manga_title': manga_title,
        'url': '',
        'volumes': []
    }
    metadata['_source_type'] = 'lectorknight'
    for volume in volumes:
        volume_data = {
            'name': volume['name'],
            'tomo_number': re.search(r'(\d+)', volume['name']).group(1) if re.search(r'(\d+)', volume['name']) else "1",
            'chapters': []
        }
        for chapter in volume['chapters']:
            volume_data['chapters'].append({
                'name': chapter['name'],
                'url': chapter['url']
            })
        metadata['volumes'].append(volume_data)
    safe_manga_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
    manga_dir = os.path.join(output_dir, safe_manga_title)
    os.makedirs(manga_dir, exist_ok=True)
    metadata_path = os.path.join(manga_dir, 'manga_metadata.json')
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    title_path = os.path.join(manga_dir, 'manga_title.txt')
    with open(title_path, 'w', encoding='utf-8') as f:
        f.write(manga_title)


class LectorKnightDownloader:
    def __init__(self, base_url, config):
        self.base_url = base_url
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        max_connections = config.get('parallel_tomos', 1) * config.get('parallel_chapters', 1) * config.get('parallel_images', 1)
        self.connection_semaphore = Semaphore(min(max_connections, 50))
        self.print_lock = Lock()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def _sleep_with_cancel(self, seconds):
        end = time.time() + max(0, float(seconds))
        while time.time() < end:
            if self.cancelled:
                return False
            time.sleep(min(0.1, end - time.time()))
        return not self.cancelled

    def get_page(self, url, use_selenium=False):
        if use_selenium and SELENIUM_AVAILABLE:
            return self.get_page_selenium(url)
        try:
            response = self.session.get(url, timeout=self.config['timeout'])
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            return None

    def get_page_selenium(self, url):
        if not SELENIUM_AVAILABLE:
            return None
        if self.cancelled:
            return None
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-cache')
        options.add_argument('--disable-application-cache')
        options.add_argument('--disable-offline-load-stale-cache')
        options.add_argument('--disk-cache-size=0')
        options.add_argument('--media-cache-size=0')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        prefs = {
            "profile.default_content_setting_values": {
                "images": 2
            },
            "profile.managed_default_content_settings": {
                "images": 2
            }
        }
        options.add_experimental_option("prefs", prefs)
        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            try:
                driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': True})
            except:
                pass
            driver.get(url)
            if self.cancelled:
                return None
            try:
                WebDriverWait(driver, self.config['selenium_wait_time']).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/capitulo-'], .wp-manga-chapter, .listing-chapters_wrap"))
                )
            except:
                pass
            if self.cancelled:
                return None
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            if not self._sleep_with_cancel(1.5):
                return None
            driver.execute_script("window.scrollTo(0, 0);")
            if not self._sleep_with_cancel(0.8):
                return None
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            if not self._sleep_with_cancel(self.config.get('selenium_extra_wait', 2)):
                return None
            return driver.page_source
        except Exception:
            return None
        finally:
            try:
                if driver:
                    driver.quit()
            except:
                pass

    def get_manga_title(self, html_content):
        soup = BeautifulSoup(html_content, 'lxml')
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title.get('content').split('-')[0].strip()
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
            if title:
                return title
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True).split('-')[0].strip()
        return "Manga"

    def extract_chapter_numbers(self, text):
        if not text:
            return "0"
        m = re.search(r'(\d+(?:\.\d+)?)', text)
        if m:
            return m.group(1)
        m = re.search(r'/capitulo-(\d+(?:\.\d+)?)/', text)
        if m:
            return m.group(1)
        return "0"

    def parse_volumes(self, html_content, debug=False):
        if debug:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_lectorknight.html')
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html_content or '')
            except:
                pass
        soup = BeautifulSoup(html_content, 'lxml')
        primary_links = soup.select("li.wp-manga-chapter a")
        links = primary_links if primary_links else soup.select("a")
        rows = []
        for a in links:
            href = (a.get('href') or '').strip()
            text = a.get_text(" ", strip=True)
            if not href and not text:
                continue
            if text and not re.search(r'^cap', text, re.IGNORECASE):
                continue
            num = None
            if text:
                m = re.search(r'(\d+(?:\.\d+)?)', text)
                if m:
                    num = m.group(1)
            if not num and href:
                m = re.search(r'/capitulo-(\d+(?:\.\d+)?)/', href)
                if m:
                    num = m.group(1)
            if not num:
                continue
            full_href = urljoin(self.base_url, href) if href else ''
            if '/n-a/' in (full_href or ''):
                pass
            elif full_href and '/capitulo-' not in full_href:
                full_href = urljoin(self.base_url if self.base_url.endswith('/') else self.base_url + '/', f"capitulo-{num}/")
            if not full_href or ('/capitulo-' not in full_href and '/n-a/' not in full_href):
                continue
            name = text if text else f"Capítulo {num}"
            if not re.search(r'cap', name, re.IGNORECASE):
                name = f"Capítulo {num}"
            rows.append({'num': num, 'name': name, 'url': full_href})
        if debug:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_links_lectorknight.json')
                with open(debug_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'total_anchors': len(soup.select('a')),
                        'wp_manga_chapter_anchors': len(primary_links),
                        'rows': rows[:300]
                    }, f, ensure_ascii=False, indent=2)
            except:
                pass
        by_num = {}
        for r in rows:
            k = r['num']
            existing = by_num.get(k)
            if not existing:
                by_num[k] = r
                continue
            if '/n-a/' in existing.get('url', '') and '/n-a/' not in r.get('url', ''):
                by_num[k] = r
        items = list(by_num.values())
        def key_fn(it):
            try:
                return float(self.extract_chapter_numbers(it['name'] + " " + it['url']))
            except:
                return 0.0
        items_sorted = sorted(items, key=key_fn)
        volumes = []
        for ch in items_sorted:
            volumes.append({
                'name': ch['name'],
                'chapters': [{'name': ch['name'], 'url': ch['url']}]
            })
        return volumes

    def convert_webp_to_jpg(self, webp_path, jpg_path, quality=95):
        try:
            if not PIL_AVAILABLE:
                return False
            img = Image.open(webp_path)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(jpg_path, 'JPEG', quality=quality, optimize=True)
            return True
        except Exception:
            return False

    def download_image_with_retry(self, img_url, filepath, max_retries=None, referer_url=None):
        if max_retries is None:
            max_retries = self.config['retry_attempts']
        headers = {}
        if referer_url:
            headers['Referer'] = referer_url
        
        filename = os.path.basename(filepath)
        for attempt in range(max_retries):
            if self.cancelled:
                print(f"[LectorKnight] Descarga cancelada para: {filename}")
                return False, 0, filepath
            try:
                if attempt > 0:
                    print(f"[LectorKnight] Reintentando descarga ({attempt+1}/{max_retries}): {filename} - {img_url[:80]}")
                
                response = self.session.get(img_url, timeout=self.config['timeout'], headers=headers)
                response.raise_for_status()
                content = response.content
                file_size = len(content)
                
                if file_size == 0:
                    raise ValueError("Archivo vacío")
                
                with open(filepath, 'wb') as f:
                    f.write(content)
                
                original_ext = os.path.splitext(filepath)[1].lower()
                if original_ext == '.webp' and PIL_AVAILABLE:
                    base_name = os.path.basename(filepath)
                    if '-webp' in base_name:
                        jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
                    else:
                        jpg_filename = base_name.replace('.webp', '.jpg')
                    jpg_filepath = os.path.join(os.path.dirname(filepath), jpg_filename)
                    if self.convert_webp_to_jpg(filepath, jpg_filepath, quality=95):
                        try:
                            os.remove(filepath)
                        except:
                            pass
                        filepath = jpg_filepath
                        file_size = os.path.getsize(filepath)
                        print(f"[LectorKnight] WebP convertido a JPG: {filename} -> {jpg_filename} ({file_size} bytes)")
                
                if attempt > 0:
                    print(f"[LectorKnight] Descarga exitosa en intento {attempt+1}: {filename} ({file_size} bytes)")
                return True, file_size, filepath
            except Exception as e:
                error_msg = str(e)
                if attempt < max_retries - 1:
                    print(f"[LectorKnight] Error descargando {filename} (intento {attempt+1}/{max_retries}): {error_msg}")
                    time.sleep(self.config['retry_delay'])
                else:
                    print(f"[LectorKnight ERROR] Falló descarga después de {max_retries} intentos: {filename} - {error_msg}")
                    return False, 0, filepath
        return False, 0, filepath

    def download_image_with_semaphore(self, img_url, filepath, img_index, total, referer_url=None):
        with self.connection_semaphore:
            if self.cancelled:
                return (img_index, False, None, filepath)
            success, file_size, returned_filepath = self.download_image_with_retry(img_url, filepath, referer_url=referer_url)
            if success and file_size > 0:
                return (img_index, True, file_size, returned_filepath)
            return (img_index, False, None, filepath)

    def download_chapter_images(self, chapter_url, chapter_name, output_dir):
        print(f"[LectorKnight] Iniciando descarga de capítulo: {chapter_name}")
        print(f"[LectorKnight] URL del capítulo: {chapter_url}")
        
        if not SELENIUM_AVAILABLE:
            print(f"[LectorKnight ERROR] Selenium no está disponible")
            return ([], 0, 0, [{'url': chapter_url, 'error': "Selenium no disponible", 'index': -1}], 0)
        if self.cancelled:
            print(f"[LectorKnight] Descarga cancelada para: {chapter_name}")
            return ([], 0, 0, [], 0)
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, output_dir)
        safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter_name)
        output_basename = os.path.basename(output_dir)
        safe_output_basename = re.sub(r'[<>:"/\\|?*]', '_', output_basename)
        if safe_output_basename == safe_chapter_name:
            chapter_dir = output_dir
        else:
            chapter_dir = os.path.join(output_dir, safe_chapter_name)
        print(f"[LectorKnight] Directorio del capítulo: {chapter_dir}")
        os.makedirs(chapter_dir, exist_ok=True)
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-cache')
        options.add_argument('--disable-application-cache')
        options.add_argument('--disable-offline-load-stale-cache')
        options.add_argument('--disk-cache-size=0')
        options.add_argument('--media-cache-size=0')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        prefs = {
            "profile.default_content_setting_values": {
                "images": 2
            },
            "profile.managed_default_content_settings": {
                "images": 2
            }
        }
        options.add_experimental_option("prefs", prefs)
        driver = None
        images = []
        try:
            if self.cancelled:
                print(f"[LectorKnight] Operación cancelada antes de iniciar Selenium para: {chapter_name}")
                return ([], 0, 0, [], 0)
            
            print(f"[LectorKnight] Inicializando Selenium para: {chapter_name}")
            driver = webdriver.Chrome(options=options)
            try:
                driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': True})
                print(f"[LectorKnight] Cache deshabilitado")
            except Exception as e:
                print(f"[LectorKnight] No se pudo deshabilitar cache: {e}")
            
            print(f"[LectorKnight] Cargando URL: {chapter_url}")
            driver.get(chapter_url)
            
            current_url = driver.current_url
            print(f"[LectorKnight] URL actual después de cargar: {current_url}")
            
            if self.cancelled:
                print(f"[LectorKnight] Operación cancelada después de cargar página para: {chapter_name}")
                return ([], 0, 0, [], 0)
            
            print(f"[LectorKnight] Esperando a que la página cargue completamente...")
            if not self._sleep_with_cancel(3):
                return ([], 0, 0, [], 0)
            
            print(f"[LectorKnight] Verificando si el contenido está cargado...")
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                print(f"[LectorKnight] Página completamente cargada")
            except:
                print(f"[LectorKnight] Timeout esperando readyState, continuando...")
            
            print(f"[LectorKnight] Esperando contenedor de contenido...")
            container_selectors = [
                "div.reading-content",
                "div.chapter-images",
                "div.entry-content",
                "div.read-container"
            ]
            
            container_found = False
            for container_selector in container_selectors:
                try:
                    WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, container_selector))
                    )
                    print(f"[LectorKnight] Contenedor encontrado: {container_selector}")
                    container_found = True
                    if not self._sleep_with_cancel(2):
                        return ([], 0, 0, [], 0)
                    break
                except:
                    continue
            
            if not container_found:
                print(f"[LectorKnight] No se encontró contenedor, esperando tiempo adicional y verificando...")
                for attempt in range(3):
                    if not self._sleep_with_cancel(2):
                        return ([], 0, 0, [], 0)
                    check_result = driver.execute_script("""
                        return {
                            readingContent: document.querySelector('div.reading-content') !== null,
                            chapterImages: document.querySelector('div.chapter-images') !== null,
                            entryContent: document.querySelector('div.entry-content') !== null,
                            readContainer: document.querySelector('div.read-container') !== null
                        };
                    """)
                    print(f"[LectorKnight] Intento {attempt + 1}: reading-content={check_result.get('readingContent')}, chapter-images={check_result.get('chapterImages')}, entry-content={check_result.get('entryContent')}, read-container={check_result.get('readContainer')}")
                    if any(check_result.values()):
                        container_found = True
                        break
            
            print(f"[LectorKnight] Haciendo scroll para cargar contenido dinámico...")
            for i in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                if not self._sleep_with_cancel(1.5):
                    return ([], 0, 0, [], 0)
                driver.execute_script("window.scrollTo(0, 0);")
                if not self._sleep_with_cancel(1):
                    return ([], 0, 0, [], 0)
            
            print(f"[LectorKnight] Esperando elementos de imagen (timeout: {self.config['selenium_wait_time']}s)")
            selectors = [
                "div.chapter-images img",
                ".wp-manga-chapter-img",
                "div.reading-content img",
                "div.page-break img",
                "div.reading-content .chapter-images img"
            ]
            
            found_selector = None
            for selector in selectors:
                try:
                    WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    img_count = driver.execute_script(f"return document.querySelectorAll('{selector}').length;")
                    if img_count > 0:
                        found_selector = selector
                        print(f"[LectorKnight] Elementos de imagen encontrados con selector '{selector}': {img_count} imágenes")
                        break
                except:
                    continue
            
            if not found_selector:
                print(f"[LectorKnight] No se encontraron elementos con ningún selector, buscando información de debug...")
                try:
                    img_count = driver.execute_script("return document.querySelectorAll('img').length;")
                    print(f"[LectorKnight] Debug: Total de imágenes en página: {img_count}")
                    
                    reading_content = driver.execute_script("return document.querySelectorAll('div.reading-content').length;")
                    chapter_images = driver.execute_script("return document.querySelectorAll('div.chapter-images').length;")
                    wp_manga_imgs = driver.execute_script("return document.querySelectorAll('.wp-manga-chapter-img').length;")
                    page_break = driver.execute_script("return document.querySelectorAll('div.page-break').length;")
                    
                    print(f"[LectorKnight] Debug: div.reading-content: {reading_content}")
                    print(f"[LectorKnight] Debug: div.chapter-images: {chapter_images}")
                    print(f"[LectorKnight] Debug: .wp-manga-chapter-img: {wp_manga_imgs}")
                    print(f"[LectorKnight] Debug: div.page-break: {page_break}")
                    
                    debug_info = driver.execute_script("""
                        const divs = Array.from(document.querySelectorAll('div.reading-content, div.chapter-images, div.page-break'));
                        return divs.slice(0, 10).map(div => ({
                            tag: div.tagName,
                            classes: div.className || '',
                            id: div.id || '',
                            imgCount: div.querySelectorAll('img').length
                        }));
                    """)
                    print(f"[LectorKnight] Debug: Contenedores encontrados:")
                    for idx, info in enumerate(debug_info, 1):
                        print(f"[LectorKnight]   {idx}. {info['tag']} - clases: {info['classes'][:80]} - imgs: {info['imgCount']}")
                except Exception as debug_e:
                    print(f"[LectorKnight] Error en debug: {debug_e}")
            
            if self.cancelled:
                print(f"[LectorKnight] Operación cancelada después de esperar imágenes para: {chapter_name}")
                return ([], 0, 0, [], 0)
            
            extra_wait = self.config.get('selenium_extra_wait', 2)
            print(f"[LectorKnight] Esperando {extra_wait}s adicionales para asegurar carga completa")
            if not self._sleep_with_cancel(extra_wait):
                print(f"[LectorKnight] Cancelado durante espera adicional")
                return ([], 0, 0, [], 0)
            
            print(f"[LectorKnight] Extrayendo URLs de imágenes")
            urls = driver.execute_script(r"""
                const selectors = [
                    'div.chapter-images img',
                    '.wp-manga-chapter-img',
                    'div.reading-content div.chapter-images img',
                    'div.page-break img',
                    'div.reading-content img'
                ];
                
                let allImgs = [];
                for (const selector of selectors) {
                    const imgs = Array.from(document.querySelectorAll(selector));
                    if (imgs.length > 0) {
                        allImgs = imgs;
                        console.log('Selector que funcionó:', selector, '- Imágenes:', imgs.length);
                        break;
                    }
                }
                
                if (allImgs.length === 0) {
                    console.log('No se encontraron imágenes con selectores específicos, buscando todas...');
                    allImgs = Array.from(document.querySelectorAll('img'));
                    console.log('Total de imágenes en página:', allImgs.length);
                }
                
                const excludeKeywords = ['logo_knight', 'tumblr', 'discord2'];
                const imageData = allImgs.map((img, index) => {
                    let src = img.getAttribute('data-src') || 
                             img.getAttribute('data-lazy-src') || 
                             img.getAttribute('data-original') || 
                             img.src || '';
                    if (src) {
                        src = src.trim();
                    }
                    const imgId = img.id || '';
                    const idMatch = imgId.match(/image-(\d+)/);
                    const idNum = idMatch ? parseInt(idMatch[1]) : (999 + index);
                    const className = img.className || '';
                    const hasWPmangaClass = className.includes('wp-manga-chapter-img') || className.includes('knsexc');
                    
                    return { src: src, id: idNum, imgId: imgId, className: className, hasWPmangaClass: hasWPmangaClass, originalIndex: index };
                }).filter(item => {
                    if (!item.src) return false;
                    
                    const lowerSrc = item.src.toLowerCase();
                    
                    if (item.hasWPmangaClass || /\/WP-manga\/|\/wp-manga\//i.test(item.src)) {
                        if (!item.src.startsWith('http') && !item.src.startsWith('//')) {
                            return false;
                        }
                        const isExcluded = excludeKeywords.some(keyword => lowerSrc.includes(keyword));
                        return !isExcluded;
                    }
                    
                    return false;
                }).sort((a, b) => {
                    if (a.id < 999 && b.id < 999) {
                        return a.id - b.id;
                    }
                    if (a.id < 999) return -1;
                    if (b.id < 999) return 1;
                    const numA = parseInt(a.src.match(/\/(\d{2})\.(jpg|jpeg|png|webp|gif)/i)?.[1] || '999');
                    const numB = parseInt(b.src.match(/\/(\d{2})\.(jpg|jpeg|png|webp|gif)/i)?.[1] || '999');
                    if (numA !== 999 && numB !== 999) {
                        return numA - numB;
                    }
                    return a.originalIndex - b.originalIndex;
                });
                
                const imageUrls = imageData.map(item => item.src);
                
                console.log('URLs extraídas después de filtrar:', imageUrls.length);
                if (imageUrls.length > 0) {
                    console.log('Primera URL:', imageUrls[0].substring(0, 100));
                    console.log('Última URL:', imageUrls[imageUrls.length - 1].substring(0, 100));
                } else {
                    console.log('DEBUG: No se encontraron URLs. Total de imágenes procesadas:', allImgs.length);
                    if (allImgs.length > 0) {
                        console.log('DEBUG: Primeras 5 imágenes encontradas:');
                        allImgs.slice(0, 5).forEach((img, idx) => {
                            const src = (img.src || img.getAttribute('data-src') || '').trim();
                            const id = img.id || '';
                            const cls = img.className || '';
                            const hasWP = cls.includes('wp-manga-chapter-img') || cls.includes('knsexc');
                            const isWPmanga = /\/WP-manga\/|\/wp-manga\//i.test(src);
                            console.log(`  ${idx + 1}. id=${id}, class=${cls.substring(0, 40)}, hasWPmangaClass=${hasWP}, isWPmangaPath=${isWPmanga}, src=${src.substring(0, 90)}`);
                        });
                    }
                }
                return imageUrls;
            """)
            
            print(f"[LectorKnight] URLs extraídas del JavaScript: {len(urls) if urls else 0}")
            
            if urls:
                seen = set()
                for u in urls:
                    if not u:
                        continue
                    if not u.startswith('http'):
                        u = urljoin(chapter_url, u)
                    if u in seen:
                        continue
                    seen.add(u)
                    images.append(u)
                print(f"[LectorKnight] URLs únicas de imágenes: {len(images)}")
                if len(images) > 0:
                    print(f"[LectorKnight] Primera URL: {images[0]}")
                    if len(images) > 1:
                        print(f"[LectorKnight] Última URL: {images[-1]}")
            else:
                print(f"[LectorKnight] ADVERTENCIA: No se encontraron URLs de imágenes")
                
                try:
                    debug_all = driver.execute_script("""
                        const result = {
                            allImgs: [],
                            chapterImagesDiv: null,
                            readingContentDiv: null
                        };
                        
                        const chapterImagesDiv = document.querySelector('div.chapter-images');
                        if (chapterImagesDiv) {
                            result.chapterImagesDiv = {
                                exists: true,
                                imgCount: chapterImagesDiv.querySelectorAll('img').length,
                                innerHTML: chapterImagesDiv.innerHTML.substring(0, 500)
                            };
                        }
                        
                        const readingContentDiv = document.querySelector('div.reading-content');
                        if (readingContentDiv) {
                            result.readingContentDiv = {
                                exists: true,
                                imgCount: readingContentDiv.querySelectorAll('img').length
                            };
                        }
                        
                        const wpMangaImgs = Array.from(document.querySelectorAll('.wp-manga-chapter-img'));
                        result.wpMangaImgCount = wpMangaImgs.length;
                        
                        const allImgs = Array.from(document.querySelectorAll('img'));
                        result.allImgs = allImgs.slice(0, 10).map(img => ({
                            id: img.id || '',
                            src: (img.src || '').trim().substring(0, 100),
                            dataSrc: (img.getAttribute('data-src') || '').trim().substring(0, 100),
                            classes: img.className || '',
                            parent: img.parentElement ? img.parentElement.className : 'none'
                        }));
                        
                        return result;
                    """)
                    
                    print(f"[LectorKnight] Debug detallado:")
                    print(f"[LectorKnight]   div.chapter-images: {'existe' if debug_all.get('chapterImagesDiv') else 'NO existe'}")
                    if debug_all.get('chapterImagesDiv'):
                        print(f"[LectorKnight]     - Imágenes dentro: {debug_all['chapterImagesDiv'].get('imgCount', 0)}")
                    print(f"[LectorKnight]   div.reading-content: {'existe' if debug_all.get('readingContentDiv') else 'NO existe'}")
                    if debug_all.get('readingContentDiv'):
                        print(f"[LectorKnight]     - Imágenes dentro: {debug_all['readingContentDiv'].get('imgCount', 0)}")
                    print(f"[LectorKnight]   .wp-manga-chapter-img: {debug_all.get('wpMangaImgCount', 0)} imágenes")
                    print(f"[LectorKnight]   Primeras 10 imágenes encontradas:")
                    for idx, img_info in enumerate(debug_all.get('allImgs', []), 1):
                        print(f"[LectorKnight]     {idx}. id={img_info.get('id', 'sin id')}, classes={img_info.get('classes', '')[:50]}")
                        print(f"[LectorKnight]        src={img_info.get('src', 'vacío')[:100]}")
                        print(f"[LectorKnight]        parent={img_info.get('parent', 'none')[:50]}")
                except Exception as debug_e:
                    print(f"[LectorKnight] Error al obtener debug de imágenes: {debug_e}")
                    import traceback
                    traceback.print_exc()
                    
        except Exception as e:
            print(f"[LectorKnight ERROR] Excepción durante extracción de imágenes para {chapter_name}: {e}")
            import traceback
            traceback.print_exc()
            return ([], 0, 0, [{'url': chapter_url, 'error': f"{str(e)}", 'index': -1}], 0)
        finally:
            try:
                if driver:
                    driver.quit()
            except:
                pass
        total_found = len(images)
        print(f"[LectorKnight] Total de imágenes encontradas: {total_found}")
        if total_found == 0:
            print(f"[LectorKnight ERROR] No se encontraron imágenes para: {chapter_name}")
            return ([], 0, 0, [], 0)
        
        downloaded_files = [None] * total_found
        failed_downloads = []
        skipped_files = 0
        parallel_images = self.config.get('parallel_images', 1)
        print(f"[LectorKnight] Preparando descarga de {total_found} imágenes (paralelo: {parallel_images})")

        def prepare_download(img_index, img_url):
            parsed_url = urlparse(img_url)
            filename = os.path.basename(parsed_url.path)
            if not filename or '.' not in filename:
                path_part = parsed_url.path
                if '.' in path_part:
                    ext = path_part.split('.')[-1].lower()
                    if ext in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
                        filename = f"{img_index+1:03d}-webp.{ext}" if ext == 'webp' else f"{img_index+1:03d}.{ext}"
                    else:
                        filename = f"{img_index+1:03d}.jpg"
                else:
                    filename = f"{img_index+1:03d}.jpg"
            else:
                ext = filename.split('.')[-1].lower()
                if ext not in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
                    ext = 'jpg'
                filename = f"{img_index+1:03d}-webp.{ext}" if ext == 'webp' else f"{img_index+1:03d}.{ext}"
            if '?' in filename:
                filename = filename.split('?')[0]
            filepath = os.path.join(chapter_dir, filename)
            return (img_index, img_url, filepath)

        download_tasks = []
        print(f"[LectorKnight] Preparando tareas de descarga para {total_found} imágenes")
        for img_index, img_url in enumerate(images):
            img_index, img_url, filepath = prepare_download(img_index, img_url)
            base_name = os.path.basename(filepath)
            jpg_filepath = None
            if '-webp' in base_name:
                jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
                jpg_filepath = os.path.join(chapter_dir, jpg_filename)
            if jpg_filepath and os.path.exists(jpg_filepath) and os.path.getsize(jpg_filepath) > 0:
                downloaded_files[img_index] = jpg_filepath
                skipped_files += 1
                continue
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                downloaded_files[img_index] = filepath
                skipped_files += 1
                continue
            download_tasks.append((img_index, img_url, filepath))
        
        print(f"[LectorKnight] Tareas de descarga: {len(download_tasks)} nuevas, {skipped_files} omitidas")

        if download_tasks:
            print(f"[LectorKnight] Iniciando descarga de {len(download_tasks)} imágenes")
            if parallel_images > 1:
                with ThreadPoolExecutor(max_workers=parallel_images) as executor:
                    futures = {executor.submit(self.download_image_with_semaphore, img_url, filepath, idx, total_found, chapter_url): (idx, img_url)
                               for idx, img_url, filepath in download_tasks}
                    for future in tqdm(as_completed(futures), total=len(download_tasks), desc=f"  {safe_chapter_name}", leave=False, unit="img"):
                        if self.cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            print(f"[LectorKnight] Descarga cancelada durante paralelo")
                            return ([], total_found, 0, [], 0)
                        idx, img_url = futures[future]
                        try:
                            img_index, success, result, filepath = future.result()
                            if success:
                                downloaded_files[img_index] = filepath
                            else:
                                print(f"[LectorKnight ERROR] Falló descarga imagen {img_index+1}/{total_found}: {img_url[:80]}")
                                failed_downloads.append({'url': img_url, 'error': 'Falló descarga', 'index': img_index})
                        except Exception as e:
                            print(f"[LectorKnight ERROR] Excepción descargando imagen {idx+1}/{total_found}: {e}")
                            failed_downloads.append({'url': img_url, 'error': str(e), 'index': idx})
            else:
                for img_index, img_url, filepath in tqdm(download_tasks, desc=f"  {safe_chapter_name}", leave=False, unit="img"):
                    if self.cancelled:
                        print(f"[LectorKnight] Descarga cancelada durante secuencial")
                        return ([], total_found, 0, [], 0)
                    print(f"[LectorKnight] Descargando imagen {img_index+1}/{len(download_tasks)}: {img_url[:80]}")
                    success, file_size, returned_filepath = self.download_image_with_retry(img_url, filepath, referer_url=chapter_url)
                    if success:
                        downloaded_files[img_index] = returned_filepath
                        print(f"[LectorKnight] Imagen {img_index+1} descargada: {returned_filepath} ({file_size} bytes)")
                    else:
                        print(f"[LectorKnight ERROR] Falló descarga imagen {img_index+1}/{len(download_tasks)}: {img_url[:80]}")
                        failed_downloads.append({'url': img_url, 'error': 'Falló descarga', 'index': img_index})
                    time.sleep(self.config.get('delay_between_images', 0.1))
        else:
            print(f"[LectorKnight] No hay tareas de descarga (todas omitidas)")

        files_with_index = []
        for idx, filepath in enumerate(downloaded_files):
            if filepath is not None and os.path.exists(filepath):
                files_with_index.append((idx, filepath))
        files_with_index.sort(key=lambda x: x[0])
        renamed_files = []
        for original_idx, old_filepath in files_with_index:
            if not os.path.exists(old_filepath):
                continue
            file_ext = os.path.splitext(old_filepath)[1].lower()
            if not file_ext or file_ext not in ['.png', '.jpg', '.jpeg', '.webp', '.gif']:
                file_ext = '.jpg'
            seq_num = original_idx + 1
            new_filename = f"{seq_num:03d}{file_ext}"
            new_filepath = os.path.join(chapter_dir, new_filename)
            if old_filepath != new_filepath:
                if os.path.exists(new_filepath):
                    temp_name = f"temp_{seq_num:03d}_{hash(old_filepath) % 10000}{file_ext}"
                    temp_filepath = os.path.join(chapter_dir, temp_name)
                    try:
                        os.rename(old_filepath, temp_filepath)
                        old_filepath = temp_filepath
                    except Exception:
                        renamed_files.append(old_filepath)
                        continue
                try:
                    os.rename(old_filepath, new_filepath)
                    renamed_files.append(new_filepath)
                except Exception:
                    renamed_files.append(old_filepath)
            else:
                renamed_files.append(new_filepath)
        downloaded_files = renamed_files
        total_downloaded = len(downloaded_files)
        
        print(f"[LectorKnight] Limpiando archivos temporales en: {chapter_dir}")
        for file in os.listdir(chapter_dir):
            file_path = os.path.join(chapter_dir, file)
            if not os.path.isfile(file_path):
                continue
            file_lower = file.lower()
            if not file_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                continue
            base_name = os.path.splitext(file)[0]
            if not re.match(r'^\d{3}$', base_name):
                try:
                    os.remove(file_path)
                except:
                    pass
        
        print(f"[LectorKnight] Resumen para {chapter_name}:")
        print(f"[LectorKnight]   - Imágenes encontradas: {total_found}")
        print(f"[LectorKnight]   - Imágenes descargadas: {total_downloaded}")
        print(f"[LectorKnight]   - Imágenes omitidas: {skipped_files}")
        print(f"[LectorKnight]   - Descargas fallidas: {len(failed_downloads)}")
        if failed_downloads:
            print(f"[LectorKnight]   - Errores:")
            for failed in failed_downloads[:5]:
                print(f"[LectorKnight]     * Imagen {failed.get('index', '?')+1}: {failed.get('error', 'Desconocido')}")
        
        return (downloaded_files, total_found, total_downloaded, failed_downloads, skipped_files)

    def sort_chapters_by_number(self, chapters):
        def get_chapter_sort_key(chapter):
            chapter_num = self.extract_chapter_numbers(chapter.get('name', '') + " " + chapter.get('url', ''))
            try:
                return float(chapter_num)
            except:
                return 0.0
        return sorted(chapters, key=get_chapter_sort_key)

    def check_volume_complete(self, volume_dir, chapters):
        complete_chapters = 0
        total_chapters = len(chapters)
        for chapter in chapters:
            safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter['name'])
            chapter_dir = os.path.join(volume_dir, safe_chapter_name)
            if os.path.exists(chapter_dir):
                images = [f for f in os.listdir(chapter_dir) if re.match(r'^\d{3}\.(jpg|jpeg|png|webp|gif)$', f.lower())]
                if len(images) > 0:
                    complete_chapters += 1
        is_complete = (complete_chapters == total_chapters and total_chapters > 0)
        return is_complete, complete_chapters, total_chapters

    def download_volume(self, volume_data, manga_title, output_dir='downloads'):
        print(f"[LectorKnight] ========================================")
        print(f"[LectorKnight] INICIANDO DESCARGA DE VOLUMEN")
        print(f"[LectorKnight] ========================================")
        print(f"[LectorKnight] Título del manga: {manga_title}")
        print(f"[LectorKnight] Nombre del volumen: {volume_data['name']}")
        print(f"[LectorKnight] Capítulos en volumen: {len(volume_data['chapters'])}")
        
        if self.cancelled:
            print(f"[LectorKnight] Operación cancelada antes de iniciar descarga de volumen")
            return {'dir': None, 'failed_chapters': []}
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, output_dir)
        volume_name = volume_data['name']
        chapters = volume_data['chapters']
        print(f"[LectorKnight] Ordenando capítulos por número")
        chapters = self.sort_chapters_by_number(chapters)
        print(f"[LectorKnight] Capítulos ordenados. Lista:")
        for idx, ch in enumerate(chapters, 1):
            print(f"[LectorKnight]   {idx}. {ch['name']} - {ch['url']}")
        
        safe_manga_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
        manga_dir = os.path.join(output_dir, safe_manga_title)
        os.makedirs(manga_dir, exist_ok=True)
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', volume_name)
        volume_dir = os.path.join(manga_dir, safe_name)
        print(f"[LectorKnight] Directorio del volumen: {volume_dir}")
        os.makedirs(volume_dir, exist_ok=True)
        force_redownload = self.config.get('force_redownload', False)
        if not force_redownload:
            print(f"[LectorKnight] Verificando si el volumen ya está completo")
            is_complete, complete_chapters, total_chapters = self.check_volume_complete(volume_dir, chapters)
            print(f"[LectorKnight] Volumen completo: {is_complete} ({complete_chapters}/{total_chapters} capítulos)")
            if is_complete:
                print(f"[LectorKnight] Volumen ya está completo, omitiendo descarga")
                return {'dir': volume_dir, 'failed_chapters': []}
        all_images = []
        chapter_stats = []
        parallel_chapters = self.config.get('parallel_chapters', 1)

        def download_single_chapter(chapter, idx, total):
            print(f"[LectorKnight] ========== Descargando capítulo {idx}/{total}: {chapter['name']} ==========")
            print(f"[LectorKnight] URL del capítulo: {chapter['url']}")
            if self.cancelled:
                print(f"[LectorKnight] Operación cancelada para: {chapter['name']}")
                return ({'name': chapter['name'], 'total_found': 0, 'total_downloaded': 0, 'failed': 0, 'skipped': 0}, [])
            try:
                result = self.download_chapter_images(chapter['url'], chapter['name'], volume_dir)
                if len(result) == 5:
                    images, total_found, total_downloaded, failed, skipped = result
                else:
                    images, total_found, total_downloaded, failed = result
                    skipped = 0
                stat = {
                    'name': chapter['name'],
                    'total_found': total_found,
                    'total_downloaded': total_downloaded,
                    'failed': len(failed),
                    'skipped': skipped
                }
                print(f"[LectorKnight] ========== Finalizado capítulo {idx}/{total}: {chapter['name']} ==========")
                print(f"[LectorKnight]   Resultado: {total_downloaded}/{total_found} descargadas, {len(failed)} fallidas")
                time.sleep(self.config['delay_between_chapters'])
                return (stat, images)
            except Exception as e:
                print(f"[LectorKnight ERROR] Excepción descargando capítulo {chapter['name']}: {e}")
                import traceback
                traceback.print_exc()
                return ({
                    'name': chapter['name'],
                    'total_found': 0,
                    'total_downloaded': 0,
                    'failed': 1,
                    'skipped': 0
                }, [])

        if parallel_chapters > 1 and len(chapters) > 1:
            with ThreadPoolExecutor(max_workers=parallel_chapters) as executor:
                futures = {executor.submit(download_single_chapter, chapter, idx+1, len(chapters)): idx
                           for idx, chapter in enumerate(chapters)}
                for future in as_completed(futures):
                    if self.cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    try:
                        stat, images = future.result()
                        chapter_stats.append(stat)
                        all_images.extend(images)
                    except Exception:
                        pass
        else:
            print(f"[LectorKnight] Descarga secuencial de {len(chapters)} capítulos")
            for idx, chapter in enumerate(tqdm(chapters, desc=volume_name, unit="img"), start=1):
                if self.cancelled:
                    print(f"[LectorKnight] Operación cancelada durante descarga secuencial")
                    break
                try:
                    print(f"[LectorKnight] ========== Descargando capítulo {idx}/{len(chapters)}: {chapter['name']} ==========")
                    print(f"[LectorKnight] URL del capítulo: {chapter['url']}")
                    result = self.download_chapter_images(chapter['url'], chapter['name'], volume_dir)
                    if len(result) == 5:
                        images, total_found, total_downloaded, failed, skipped = result
                    else:
                        images, total_found, total_downloaded, failed = result
                        skipped = 0
                    all_images.extend(images)
                    chapter_stats.append({
                        'name': chapter['name'],
                        'total_found': total_found,
                        'total_downloaded': total_downloaded,
                        'failed': len(failed),
                        'skipped': skipped
                    })
                    print(f"[LectorKnight] ========== Finalizado capítulo {idx}/{len(chapters)}: {chapter['name']} ==========")
                    print(f"[LectorKnight]   Resultado: {total_downloaded}/{total_found} descargadas, {len(failed)} fallidas")
                    time.sleep(self.config['delay_between_chapters'])
                except Exception as e:
                    print(f"[LectorKnight ERROR] Excepción descargando capítulo {chapter['name']}: {e}")
                    import traceback
                    traceback.print_exc()
                    chapter_stats.append({
                        'name': chapter['name'],
                        'total_found': 0,
                        'total_downloaded': 0,
                        'failed': 1,
                        'skipped': 0
                    })
        print(f"[LectorKnight] ========================================")
        print(f"[LectorKnight] RESUMEN DE DESCARGA DE VOLUMEN")
        print(f"[LectorKnight] ========================================")
        print(f"[LectorKnight] Capítulos procesados: {len(chapter_stats)}")
        
        failed_chapters = []
        for stat in chapter_stats:
            print(f"[LectorKnight]   - {stat['name']}: {stat['total_downloaded']}/{stat['total_found']} descargadas, {stat['failed']} fallidas, {stat['skipped']} omitidas")
            if stat['failed'] > 0 or stat['total_downloaded'] < stat['total_found']:
                failed_chapters.append({
                    'chapter_name': stat['name'],
                    'downloaded': stat['total_downloaded'],
                    'total': stat['total_found']
                })
        
        if failed_chapters:
            print(f"[LectorKnight] Capítulos con problemas: {len(failed_chapters)}")
            for failed in failed_chapters:
                print(f"[LectorKnight]   - {failed['chapter_name']}: {failed['downloaded']}/{failed['total']}")
        else:
            print(f"[LectorKnight] Todos los capítulos descargados correctamente")
        
        print(f"[LectorKnight] ========================================")
        return {'dir': volume_dir, 'failed_chapters': failed_chapters}


def main():
    print("="*60)
    print("DESCARGADOR - LECTORKNIGHT")
    print("="*60)
    config = load_config()
    url = input("URL de la serie: ").strip()
    if not url:
        print("URL inválida")
        return
    downloader = LectorKnightDownloader(url, config)
    html = downloader.get_page(url, use_selenium=True)
    if not html:
        print("No se pudo cargar la página")
        return
    title = downloader.get_manga_title(html)
    volumes = downloader.parse_volumes(html, debug=False)
    print(f"Título: {title}")
    print(f"Capítulos: {len(volumes)}")
    output_dir = config['output_dir']
    os.makedirs(output_dir, exist_ok=True)
    save_metadata(title, volumes, output_dir)
    sel = input("Selecciona capítulo (1..N) o 'all': ").strip().lower()
    if sel == 'all':
        selected = list(range(len(volumes)))
    else:
        try:
            i = int(sel) - 1
            selected = [i] if 0 <= i < len(volumes) else []
        except:
            selected = []
    for idx in selected:
        v = volumes[idx]
        print(f"Descargando: {v['name']}")
        downloader.download_volume(v, title, output_dir)
        time.sleep(config.get('delay_between_volumes', 1))
    print("Listo")


if __name__ == '__main__':
    main()

