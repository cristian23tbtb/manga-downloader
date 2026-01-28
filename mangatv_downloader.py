import os
import sys
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import base64
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


def save_metadata(manga_title, volumes, output_dir, manga_type='manga', tomos_structure=None):
    if manga_type == 'manhwa':
        metadata = {
            'manhwa_title': manga_title,
            'url': '',
            'volumes': []
        }
    else:
        metadata = {
            'manga_title': manga_title,
            'url': '',
            'volumes': []
        }
    
    metadata['_source_type'] = 'mangatv'
    metadata['_manga_type'] = manga_type
    
    if tomos_structure and manga_type == 'manga':
        metadata['_tomos_structure'] = tomos_structure
    
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
    
    if manga_type == 'manhwa':
        metadata_path = os.path.join(manga_dir, 'manhwa_metadata.json')
        title_path = os.path.join(manga_dir, 'manhwa_title.txt')
    else:
        metadata_path = os.path.join(manga_dir, 'manga_metadata.json')
        title_path = os.path.join(manga_dir, 'manga_title.txt')
    
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    with open(title_path, 'w', encoding='utf-8') as f:
        f.write(manga_title)


class MangaTVDownloader:
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
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
    
    def get_page(self, url, use_selenium=False):
        if use_selenium and SELENIUM_AVAILABLE:
            return self.get_page_selenium(url)
        
        try:
            response = self.session.get(url, timeout=self.config['timeout'])
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error al descargar la página: {e}")
            return None
    
    def get_page_selenium(self, url):
        if not SELENIUM_AVAILABLE:
            print("[ERROR] Selenium no esta disponible. Instala con: pip install selenium")
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
            driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': True})
            driver.get(url)
            
            try:
                WebDriverWait(driver, self.config['selenium_wait_time']).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except:
                pass
            
            time.sleep(self.config.get('selenium_extra_wait', 2))
            
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except:
                pass
            
            html = driver.page_source
            return html
        except Exception as e:
            print(f"Error con Selenium: {e}")
            return None
        finally:
            if driver:
                driver.quit()
    
    def get_manga_title(self, html_content):
        soup = BeautifulSoup(html_content, 'lxml')
        
        h1_tag = soup.find('h1', class_='entry-title')
        if h1_tag:
            title = h1_tag.get_text(strip=True)
            return title
        
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '').strip()
            if ' | ' in title:
                title = title.split(' | ')[0].strip()
            return title
        
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            if ' | ' in title:
                title = title.split(' | ')[0].strip()
            return title
        
        return "Manga"
    
    def get_manga_type(self, html_content):
        soup = BeautifulSoup(html_content, 'lxml')
        
        imptdt_divs = soup.find_all('div', class_='imptdt')
        for div in imptdt_divs:
            text = div.get_text(strip=True)
            if text.startswith('Tipo'):
                tipo_link = div.find('a')
                if tipo_link:
                    tipo = tipo_link.get_text(strip=True)
                    if tipo.lower() in ['manhwa', 'manhua']:
                        return 'manhwa'
                    elif tipo.lower() == 'manga':
                        return 'manga'
                break
        
        return 'manga'
    
    def extract_chapter_numbers(self, chapter_name):
        match = re.search(r'Capítulo\s*(\d+\.?\d*)', chapter_name, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'(\d+\.?\d*)', chapter_name)
        if match:
            return match.group(1)
        return "0"
    
    def parse_volumes(self, html_content, debug=False):
        soup = BeautifulSoup(html_content, 'lxml')
        
        if debug:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_mangatv.html')
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("\n=== MODO DEPURACIÓN ===")
            print(f"Tamaño del HTML: {len(html_content)} caracteres")
            print(f"  HTML guardado en '{debug_file}' para inspección")
        
        chapter_list = soup.find('div', class_='eplister', id='chapterlist')
        if not chapter_list:
            if debug:
                print("\n[ERROR] No se encontró div.eplister#chapterlist")
                all_eplisters = soup.find_all('div', class_='eplister')
                print(f"  Total de div.eplister encontrados: {len(all_eplisters)}")
                for idx, div in enumerate(all_eplisters[:5]):
                    div_id = div.get('id', 'sin id')
                    print(f"    {idx+1}. id={div_id}, clases={div.get('class', [])}")
                
                divs_with_id = soup.find_all('div', id=True)
                chapterlist_divs = [div for div in divs_with_id if 'chapter' in div.get('id', '').lower()]
                print(f"  Total de divs con 'chapter' en id: {len(chapterlist_divs)}")
                for idx, div in enumerate(chapterlist_divs[:5]):
                    print(f"    {idx+1}. id={div.get('id')}, clases={div.get('class', [])}")
            return {'volumes': [], 'common_scanlations': {}}
        
        if debug:
            print(f"\n[OK] div.eplister#chapterlist encontrado")
        
        ul = chapter_list.find('ul', class_='clstyle')
        if not ul:
            if debug:
                print("\n[ERROR] No se encontró ul.clstyle dentro de chapter_list")
                all_uls = chapter_list.find_all('ul')
                print(f"  Total de <ul> dentro de chapter_list: {len(all_uls)}")
                for idx, ul_elem in enumerate(all_uls[:5]):
                    print(f"    {idx+1}. clases={ul_elem.get('class', [])}")
                
                all_uls_doc = soup.find_all('ul', class_='clstyle')
                print(f"  Total de ul.clstyle en todo el documento: {len(all_uls_doc)}")
            return {'volumes': [], 'common_scanlations': {}}
        
        if debug:
            print(f"[OK] ul.clstyle encontrado")
        
        chapters_by_number = {}
        
        all_lis = ul.find_all('li')
        if debug:
            print(f"  Total de <li> encontrados: {len(all_lis)}")
        
        processed_count = 0
        skipped_count = 0
        
        for li in all_lis:
            chbox = li.find('div', class_='chbox')
            if not chbox:
                skipped_count += 1
                continue
            
            link = chbox.find('div', class_='dt').find('a', class_='dload') if chbox.find('div', class_='dt') else None
            if not link or not link.get('href'):
                skipped_count += 1
                continue
            
            chapter_url = link.get('href')
            if not chapter_url.startswith('http'):
                chapter_url = urljoin(self.base_url, chapter_url)
            
            eph_num = chbox.find('div', class_='eph-num')
            if not eph_num:
                skipped_count += 1
                continue
            
            chapternum_spans = eph_num.find_all('span', class_='chapternum')
            if len(chapternum_spans) < 2:
                skipped_count += 1
                continue
            
            processed_count += 1
            
            chapter_number_text = chapternum_spans[0].get_text(strip=True)
            scanlation_text = chapternum_spans[1].get_text(strip=True)
            
            chapter_num_match = re.search(r'Capítulo\s*(\d+\.?\d*)', chapter_number_text, re.IGNORECASE)
            if not chapter_num_match:
                chapter_num_match = re.search(r'(\d+\.?\d*)', chapter_number_text)
            
            if chapter_num_match:
                try:
                    chapter_num = float(chapter_num_match.group(1))
                except:
                    chapter_num = 0.0
            else:
                chapter_num = 0.0
            
            chapter_name = f"Capítulo {chapter_num:g}" if chapter_num % 1 == 0 else f"Capítulo {chapter_num}"
            
            if chapter_num not in chapters_by_number:
                chapters_by_number[chapter_num] = []
            
            chapters_by_number[chapter_num].append({
                'name': chapter_name,
                'scanlation': scanlation_text,
                'url': chapter_url,
                'number': chapter_num
            })
        
        if debug:
            print(f"\n[DEBUG] Capítulos procesados: {processed_count}, omitidos: {skipped_count}")
            print(f"  Capítulos únicos encontrados: {len(chapters_by_number)}")
            if chapters_by_number:
                print(f"  Primeros 3 capítulos encontrados:")
                sorted_sample = sorted(chapters_by_number.keys(), reverse=False)[:3]
                for chapter_num in sorted_sample:
                    options = chapters_by_number[chapter_num]
                    scanlations = [opt['scanlation'] for opt in options]
                    print(f"    - Capítulo {chapter_num:g}: {len(options)} opción(es) - {', '.join(scanlations)}")
        
        all_scanlations = set()
        for chapter_num, options in chapters_by_number.items():
            for option in options:
                all_scanlations.add(option['scanlation'])
        
        if debug:
            print(f"  Scanlations únicos encontrados: {len(all_scanlations)}")
            for scan in sorted(all_scanlations):
                print(f"    - {scan}")
        
        common_scanlations = {}
        total_chapters = len(chapters_by_number)
        for scanlation in all_scanlations:
            count = 0
            for chapter_num, options in chapters_by_number.items():
                has_scanlation = any(opt['scanlation'] == scanlation for opt in options)
                if has_scanlation:
                    count += 1
            if count > 0 and count == total_chapters:
                common_scanlations[scanlation] = count
        
        volumes = []
        sorted_numbers = sorted(chapters_by_number.keys(), reverse=False)
        if debug:
            print(f"\n[DEBUG] Generando lista de volúmenes")
            print(f"  Total de capítulos únicos a procesar: {len(sorted_numbers)}")
        
        for chapter_num in sorted_numbers:
            options = chapters_by_number[chapter_num]
            if len(options) == 1:
                volumes.append({
                    'name': options[0]['name'],
                    'chapters': [{'name': options[0]['name'], 'url': options[0]['url']}],
                    'options': None,
                    'scanlations': None,
                    'single_scanlation': options[0]['scanlation']
                })
            else:
                volumes.append({
                    'name': options[0]['name'],
                    'chapters': [{'name': options[0]['name'], 'url': options[0]['url']}],
                    'options': options,
                    'scanlations': [opt['scanlation'] for opt in options]
                })
        
        if debug:
            print(f"\n[OK] Procesamiento completado")
            print(f"  Total de volúmenes generados: {len(volumes)}")
            volumes_with_options = [v for v in volumes if v.get('options')]
            print(f"  Volúmenes con múltiples opciones: {len(volumes_with_options)}")
            print(f"  Scanlations comunes encontrados: {len(common_scanlations)}")
            if common_scanlations:
                for scan, count in sorted(common_scanlations.items(), key=lambda x: x[1], reverse=True):
                    print(f"    - {scan}: presente en {count} capítulos")
        
        result = {
            'volumes': volumes,
            'common_scanlations': common_scanlations
        }
        
        return result
    
    def select_chapter_option(self, chapter_name, options):
        print(f"\n{'='*60}")
        print(f"Múltiples opciones encontradas para {chapter_name}:")
        print(f"{'='*60}")
        
        for idx, option in enumerate(options, start=1):
            print(f"{idx}. {option['scanlation']}")
        
        while True:
            try:
                selection = input(f"\nSelecciona una opción (1-{len(options)}): ").strip()
                option_idx = int(selection) - 1
                if 0 <= option_idx < len(options):
                    selected = options[option_idx]
                    print(f"[OK] Opción seleccionada: {selected['scanlation']}")
                    return selected
                else:
                    print(f"Por favor, ingresa un número entre 1 y {len(options)}")
            except ValueError:
                print("Por favor, ingresa un número válido")
            except KeyboardInterrupt:
                return None
    
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
        except Exception as e:
            return False
    
    def download_image_with_retry(self, img_url, filepath, max_retries=None, referer_url=None):
        if max_retries is None:
            max_retries = self.config['retry_attempts']
        
        headers = {}
        if referer_url:
            headers['Referer'] = referer_url
        
        for attempt in range(max_retries):
            if self.cancelled:
                return False, 0, filepath
            
            try:
                response = self.session.get(img_url, timeout=self.config['timeout'], headers=headers)
                response.raise_for_status()
                
                content = response.content
                file_size = len(content)
                
                if file_size == 0:
                    raise ValueError(f"Archivo vacío: {file_size} bytes")
                
                original_ext = os.path.splitext(filepath)[1].lower()
                
                with open(filepath, 'wb') as f:
                    f.write(content)
                
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
                
                return True, file_size, filepath
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(self.config['retry_delay'])
                else:
                    return False, 0, filepath
        
        return False, 0, filepath
    
    def download_image_with_semaphore(self, img_url, filepath, img_index, total, referer_url=None):
        with self.connection_semaphore:
            if self.cancelled:
                return (img_index, False, None, filepath)
            
            success, file_size, returned_filepath = self.download_image_with_retry(img_url, filepath, referer_url=referer_url)
            
            if success and file_size > 0:
                return (img_index, True, file_size, returned_filepath)
            else:
                return (img_index, False, None, filepath)
    
    def download_chapter_images(self, chapter_url, chapter_name, output_dir):
        if self.cancelled:
            return ([], 0, 0, [], 0)
        
        if not SELENIUM_AVAILABLE:
            return ([], 0, 0, [{'url': chapter_url, 'error': "Selenium no está disponible", 'index': -1}], 0)
        
        driver = None
        images = []
        
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            driver = webdriver.Chrome(options=options)
            driver.get(chapter_url)
            
            try:
                WebDriverWait(driver, self.config['selenium_wait_time']).until(
                    EC.presence_of_element_located((By.ID, "readerarea"))
                )
            except:
                pass
            
            time.sleep(self.config.get('selenium_extra_wait', 3))
            
            html_content = driver.page_source
            
            base64_pattern = r'Ly9[a-zA-Z0-9+/=]{60,}'
            base64_strings = re.findall(base64_pattern, html_content)
            
            base64_images = []
            for b64 in base64_strings:
                try:
                    if len(b64) % 4 != 0:
                        padding = 4 - (len(b64) % 4)
                        b64 = b64 + '=' * padding
                    decoded_url = base64.b64decode(b64).decode('utf-8')
                    
                    if decoded_url.startswith('//') and ('mangatv.net' in decoded_url or 'library' in decoded_url):
                        if not decoded_url.startswith('http'):
                            decoded_url = 'https:' + decoded_url
                        if decoded_url not in base64_images:
                            base64_images.append(decoded_url)
                except:
                    continue
            
            if base64_images:
                base64_images.reverse()
                images.extend(base64_images)
            
            if not images:
                try:
                    js_images = driver.execute_script("""
                        var images = [];
                        var readerArea = document.getElementById('readerarea');
                        if (readerArea) {
                            var imgs = readerArea.getElementsByTagName('img');
                            for (var i = 0; i < imgs.length; i++) {
                                var src = imgs[i].src || imgs[i].getAttribute('data-src') || imgs[i].getAttribute('data-lazy-src') || imgs[i].getAttribute('data-original');
                                if (src && src.trim()) {
                                    images.push(src);
                                }
                            }
                        }
                        return images;
                    """)
                    if js_images:
                        for img_url in js_images:
                            if not img_url.startswith('http'):
                                img_url = urljoin(chapter_url, img_url)
                            if img_url not in images:
                                images.append(img_url)
                except:
                    pass
            
            if not images:
                soup = BeautifulSoup(html_content, 'lxml')
                reader_area = soup.find('div', id='readerarea')
                
                if reader_area:
                    img_tags = reader_area.find_all('img')
                    for img_tag in img_tags:
                        img_url = img_tag.get('src', '') or img_tag.get('data-src', '') or img_tag.get('data-lazy-src', '') or img_tag.get('data-original', '')
                        if img_url:
                            if not img_url.startswith('http'):
                                img_url = urljoin(chapter_url, img_url)
                            if img_url not in images:
                                images.append(img_url)
            
        except Exception as e:
            return ([], 0, 0, [{'url': chapter_url, 'error': f"Error al obtener HTML: {str(e)}", 'index': -1}], 0)
        finally:
            if driver:
                driver.quit()
        
        safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter_name)
        output_basename = os.path.basename(output_dir)
        safe_output_basename = re.sub(r'[<>:"/\\|?*]', '_', output_basename)
        
        if safe_output_basename == safe_chapter_name or output_basename.startswith('Tomo '):
            chapter_dir = output_dir
        else:
            chapter_dir = os.path.join(output_dir, safe_chapter_name)
        os.makedirs(chapter_dir, exist_ok=True)
        
        total_found = len(images)
        if total_found == 0:
            return ([], 0, 0, [], 0)
        
        downloaded_files = [None] * total_found
        failed_downloads = []
        skipped_files = 0
        
        parallel_images = self.config.get('parallel_images', 1)
        
        def prepare_download(img_index, img_url):
            parsed_url = urlparse(img_url)
            filename = os.path.basename(parsed_url.path)
            
            if not filename or '.' not in filename:
                path_part = parsed_url.path
                if '.' in path_part:
                    ext = path_part.split('.')[-1].lower()
                    if ext in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
                        filename = f"{img_index+1:03d}-webp.{ext}"
                    else:
                        filename = f"{img_index+1:03d}-webp.webp"
                else:
                    filename = f"{img_index+1:03d}-webp.webp"
            else:
                ext = filename.split('.')[-1].lower()
                if ext not in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
                    ext = 'webp'
                filename = f"{img_index+1:03d}-webp.{ext}"
            
            if '?' in filename:
                filename = filename.split('?')[0]
            
            filepath = os.path.join(chapter_dir, filename)
            return (img_index, img_url, filepath)
        
        download_tasks = []
        for idx, img_url in enumerate(images):
            img_index, img_url, filepath = prepare_download(idx, img_url)
            
            base_name = os.path.basename(filepath)
            if '-webp' in base_name:
                jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
            else:
                jpg_filename = base_name.replace('.webp', '.jpg') if filepath.endswith('.webp') else base_name
            jpg_filepath = os.path.join(chapter_dir, jpg_filename)
            
            if os.path.exists(jpg_filepath) and os.path.getsize(jpg_filepath) > 0:
                downloaded_files[img_index] = jpg_filepath
                skipped_files += 1
            elif os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                if filepath.endswith('.webp') and PIL_AVAILABLE:
                    if self.convert_webp_to_jpg(filepath, jpg_filepath, quality=95):
                        try:
                            os.remove(filepath)
                        except:
                            pass
                        downloaded_files[img_index] = jpg_filepath
                        skipped_files += 1
                else:
                    downloaded_files[img_index] = filepath
                    skipped_files += 1
            else:
                download_tasks.append((img_index, img_url, filepath))
        
        if download_tasks:
            if parallel_images > 1:
                with ThreadPoolExecutor(max_workers=parallel_images) as executor:
                    futures = {executor.submit(self.download_image_with_semaphore, img_url, filepath, idx, total_found, chapter_url): (idx, img_url) 
                              for idx, img_url, filepath in download_tasks}
                    
                    for future in tqdm(as_completed(futures), total=len(download_tasks), desc=f"  {safe_chapter_name}", leave=False, unit="img"):
                        if self.cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            return ([], total_found, 0, [], 0)
                        idx, img_url = futures[future]
                        try:
                            img_index, success, result, filepath = future.result()
                            if success:
                                downloaded_files[img_index] = filepath
                            else:
                                failed_downloads.append({'url': img_url, 'error': 'Falló descarga', 'index': img_index})
                        except Exception as e:
                            failed_downloads.append({'url': img_url, 'error': str(e), 'index': img_index})
            else:
                for img_index, img_url, filepath in tqdm(download_tasks, desc=f"  {safe_chapter_name}", leave=False, unit="img"):
                    if self.cancelled:
                        return ([], total_found, 0, [], 0)
                    success, file_size, returned_filepath = self.download_image_with_retry(img_url, filepath, referer_url=chapter_url)
                    if success:
                        downloaded_files[img_index] = returned_filepath
                    else:
                        failed_downloads.append({'url': img_url, 'error': 'Falló descarga', 'index': img_index})
        
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
                    except Exception as e:
                        renamed_files.append(old_filepath)
                        continue
                
                try:
                    os.rename(old_filepath, new_filepath)
                    renamed_files.append(new_filepath)
                except Exception as e:
                    renamed_files.append(old_filepath)
            else:
                renamed_files.append(new_filepath)
        
        downloaded_files = renamed_files
        total_downloaded = len(downloaded_files)
        
        for file in os.listdir(chapter_dir):
            file_path = os.path.join(chapter_dir, file)
            if not os.path.isfile(file_path):
                continue
            
            file_lower = file.lower()
            if not file_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                continue
            
            base_name = os.path.splitext(file)[0]
            if not re.match(r'^\d{3}$', base_name):
                if file.startswith('temp_'):
                    try:
                        os.remove(file_path)
                    except:
                        pass
        
        return (downloaded_files, total_found, total_downloaded, failed_downloads, skipped_files)
    
    def sort_chapters_by_number(self, chapters):
        def get_sort_key(chapter):
            chapter_num = self.extract_chapter_numbers(chapter['name'])
            try:
                return float(chapter_num)
            except:
                return 0.0
        
        return sorted(chapters, key=get_sort_key)
    
    def download_volume(self, volume_data, manga_title, output_dir='downloads', selected_option=None, is_tomo_structure=False):
        if self.cancelled:
            return {'dir': None, 'failed_chapters': []}
        
        volume_name = volume_data['name']
        chapters = volume_data.get('chapters', [])
        
        if not chapters:
            print(f"[ERROR] El volumen {volume_name} no tiene capítulos")
            return {'dir': None, 'failed_chapters': []}
        
        print(f"[DEBUG] Volumen: {volume_name}, Capítulos: {len(chapters)}")
        for idx, ch in enumerate(chapters[:3]):
            print(f"[DEBUG]   Capítulo {idx+1}: name={ch.get('name')}, url={ch.get('url', 'SIN URL')}")
        
        if selected_option and volume_data.get('options'):
            chapters = [{'name': selected_option['name'], 'url': selected_option['url']}]
        
        chapters = self.sort_chapters_by_number(chapters)
        
        safe_manga_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
        manga_dir = os.path.join(output_dir, safe_manga_title)
        os.makedirs(manga_dir, exist_ok=True)
        
        if is_tomo_structure:
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', volume_name)
            volume_dir = os.path.join(manga_dir, safe_name)
            os.makedirs(volume_dir, exist_ok=True)
        else:
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', volume_name)
            volume_dir = os.path.join(manga_dir, safe_name)
            os.makedirs(volume_dir, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"Descargando: {volume_name}")
        print(f"{'='*60}\n")
        
        all_images = []
        chapter_stats = []
        
        parallel_chapters = self.config.get('parallel_chapters', 1)
        
        def download_single_chapter(chapter, idx, total):
            if self.cancelled:
                return ({'name': chapter['name'], 'total_found': 0, 'total_downloaded': 0, 'failed': 0, 'skipped': 0}, [])
            try:
                if not chapter.get('url'):
                    with self.print_lock:
                        print(f"\n[ERROR] Capítulo {chapter.get('name', 'Desconocido')} no tiene URL")
                    return ({'name': chapter.get('name', 'Desconocido'), 'total_found': 0, 'total_downloaded': 0, 'failed': 0, 'skipped': 0}, [])
                
                with self.print_lock:
                    print(f"\n[{idx}/{total}] Procesando: {chapter['name']}")
                    print(f"[DEBUG] URL del capítulo: {chapter['url']}")
                
                chapter_dir = volume_dir
                if is_tomo_structure:
                    safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter['name'])
                    chapter_dir = os.path.join(volume_dir, safe_chapter_name)
                    os.makedirs(chapter_dir, exist_ok=True)
                    print(f"[DEBUG] Creando subcarpeta para capítulo: {chapter_dir}")
                
                result = self.download_chapter_images(chapter['url'], chapter['name'], chapter_dir)
                
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
                
                if total_found > 0:
                    if total_downloaded == total_found:
                        with self.print_lock:
                            print(f"  [OK] {chapter['name']}: {total_downloaded}/{total_found} imágenes")
                    else:
                        with self.print_lock:
                            print(f"  [ADVERTENCIA] {chapter['name']}: {total_downloaded}/{total_found} imágenes ({total_found - total_downloaded} fallaron)")
                else:
                    with self.print_lock:
                        print(f"  [ADVERTENCIA] {chapter['name']}: No se encontraron imágenes")
                
                time.sleep(self.config['delay_between_chapters'])
                return (stat, images)
            except Exception as e:
                with self.print_lock:
                    print(f"  [ERROR] Error en capítulo {chapter['name']}: {str(e)}")
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
                    idx = futures[future]
                    try:
                        stat, images = future.result()
                        chapter_stats.append(stat)
                        all_images.extend(images)
                    except Exception as e:
                        with self.print_lock:
                            print(f"[ERROR] Error al procesar capítulo: {e}")
        else:
            for idx, chapter in enumerate(chapters, start=1):
                if self.cancelled:
                    break
                stat, images = download_single_chapter(chapter, idx, len(chapters))
                chapter_stats.append(stat)
                all_images.extend(images)
        
        if all_images:
            print(f"\n{'='*60}")
            print(f"RESUMEN: {volume_name}")
            print(f"{'='*60}")
            
            def get_chapter_sort_key(stat):
                chapter_num = self.extract_chapter_numbers(stat['name'])
                try:
                    return float(chapter_num)
                except:
                    return 0.0
            
            sorted_stats = sorted(chapter_stats, key=get_chapter_sort_key)
            
            failed_chapters = []
            tomo_number = None
            if is_tomo_structure:
                tomo_match = re.search(r'Tomo\s+(\d+)', volume_name)
                if tomo_match:
                    tomo_number = int(tomo_match.group(1))
            
            for stat in sorted_stats:
                total_found = stat.get('total_found', 0)
                total_downloaded = stat.get('total_downloaded', 0)
                status_icon = "[OK]" if total_downloaded == total_found and total_found > 0 else "[ERROR]"
                print(f"{status_icon} {stat['name']}: {total_downloaded}/{total_found}")
                
                if total_downloaded < total_found:
                    failed_dict = {
                        'chapter_name': stat['name'],
                        'downloaded': total_downloaded,
                        'total': total_found
                    }
                    if tomo_number is not None:
                        failed_dict['tomo_number'] = tomo_number
                    failed_chapters.append(failed_dict)
            
            print(f"{'='*60}")
            print(f"\n[OK] Descarga completada: {os.path.abspath(volume_dir)}")
            return {
                'dir': volume_dir,
                'failed_chapters': failed_chapters
            }
        else:
            print("\n[ERROR] No se descargaron imágenes")
            return {
                'dir': None,
                'failed_chapters': []
            }


def main():
    print("="*60)
    print("DESCARGADOR DE MANGA - MANGATV")
    print("="*60)
    
    config = load_config()
    
    debug_mode = '--debug' in sys.argv or '-d' in sys.argv
    
    url_args = [arg for arg in sys.argv[1:] if arg not in ['--debug', '-d']]
    
    if url_args:
        url = url_args[0]
    else:
        url = input("\nIngresa la URL del manga: ").strip()
    
    if not url:
        print("Error: Debes proporcionar una URL")
        sys.exit(1)
    
    downloader = MangaTVDownloader(url, config)
    
    print(f"\nDescargando información de: {url}")
    
    use_selenium = True
    
    if not SELENIUM_AVAILABLE:
        print("[ERROR] Selenium no está disponible.")
        print("  Instala Selenium con: pip install selenium")
        print("  También necesitas tener Chrome/Chromium instalado")
        sys.exit(1)
    
    html_content = downloader.get_page(url, use_selenium=use_selenium)
    
    if not html_content:
        print("Error: No se pudo cargar la página con Selenium")
        print("  Verifica que Chrome/Chromium esté instalado")
        sys.exit(1)
    
    manga_title = downloader.get_manga_title(html_content)
    manga_type = downloader.get_manga_type(html_content)
    tipo_label = "manhwa" if manga_type == 'manhwa' else "manga"
    print(f"Título del {tipo_label}: {manga_title}")
    print(f"Tipo: {tipo_label.capitalize()}")
    
    print("Parseando capítulos...")
    parse_result = downloader.parse_volumes(html_content, debug=debug_mode)
    
    if not parse_result or 'volumes' not in parse_result or not parse_result['volumes']:
        print("Error: No se encontraron capítulos en la página")
        sys.exit(1)
    
    volumes = parse_result['volumes']
    common_scanlations = parse_result.get('common_scanlations', {})
    
    volumes_with_options = []
    volumes_without_options = []
    
    for volume in volumes:
        if volume.get('options'):
            volumes_with_options.append(volume)
        else:
            volumes_without_options.append(volume)
    
    global_scanlation = None
    
    if volumes_with_options and common_scanlations:
        print(f"\n{'='*60}")
        print(f"SCANLATIONS COMUNES EN TODOS LOS CAPÍTULOS:")
        print(f"{'='*60}")
        
        scanlation_list = list(common_scanlations.keys())
        for idx, scanlation in enumerate(scanlation_list, start=1):
            count = common_scanlations[scanlation]
            print(f"{idx}. {scanlation} (presente en {count} capítulos)")
        
        print(f"\n¿Deseas seleccionar un scanlation global para todos los capítulos?")
        print(f"  - Selecciona un número para usar el mismo scanlation en todos")
        print(f"  - Presiona Enter para seleccionar por capítulo")
        
        try:
            selection = input("\nOpción: ").strip()
            if selection:
                scanlation_idx = int(selection) - 1
                if 0 <= scanlation_idx < len(scanlation_list):
                    global_scanlation = scanlation_list[scanlation_idx]
                    print(f"\n[OK] Scanlation global seleccionado: {global_scanlation}")
        except (ValueError, KeyboardInterrupt):
            print("\nContinuando con selección individual...")
    
    if volumes_with_options and not global_scanlation:
        print(f"\n{'='*60}")
        print(f"CAPÍTULOS CON MÚLTIPLES OPCIONES: {len(volumes_with_options)}")
        print(f"{'='*60}")
        
        selected_options = {}
        for volume in volumes_with_options:
            selected = downloader.select_chapter_option(volume['name'], volume['options'])
            if selected:
                selected_options[volume['name']] = selected
            else:
                print("[CANCELADO] Operación cancelada por el usuario")
                sys.exit(0)
        
        for volume in volumes_with_options:
            if volume['name'] in selected_options:
                volume['chapters'] = [{'name': selected_options[volume['name']]['name'], 'url': selected_options[volume['name']]['url']}]
                volume['options'] = None
    elif global_scanlation:
        for volume in volumes_with_options:
            for option in volume.get('options', []):
                if option['scanlation'] == global_scanlation:
                    volume['chapters'] = [{'name': option['name'], 'url': option['url']}]
                    volume['options'] = None
                    break
    
    all_volumes = volumes_without_options + volumes_with_options
    
    print(f"\n{'='*60}")
    print(f"CAPÍTULOS DETECTADOS: {len(all_volumes)}")
    print(f"{'='*60}")
    for idx, volume in enumerate(all_volumes, start=1):
        print(f"{idx}. {volume['name']}")
    
    print(f"\n{'='*60}")
    print("Opciones de selección:")
    print("  - Un capítulo: 1")
    print("  - Varios capítulos: 1,3,5 o 1-5")
    print("  - Todos los capítulos: all")
    print(f"{'='*60}")
    
    selected_indices = []
    while not selected_indices:
        try:
            selection = input("\nSelecciona los capítulos a descargar: ").strip()
            
            if selection.lower() == 'all':
                selected_indices = list(range(len(all_volumes)))
                print(f"\n[OK] Todos los capítulos seleccionados ({len(selected_indices)} capítulos)")
                break
            elif ',' in selection:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                valid_indices = [idx for idx in indices if 0 <= idx < len(all_volumes)]
                if valid_indices:
                    selected_indices = valid_indices
                    chapter_names = [all_volumes[idx]['name'] for idx in selected_indices]
                    print(f"\n[OK] Capítulos seleccionados: {', '.join(chapter_names)}")
                else:
                    print(f"Por favor, ingresa números entre 1 y {len(all_volumes)}")
                    continue
            elif '-' in selection:
                parts = selection.split('-')
                if len(parts) == 2:
                    start = int(parts[0].strip()) - 1
                    end = int(parts[1].strip()) - 1
                    if 0 <= start <= end < len(all_volumes):
                        selected_indices = list(range(start, end + 1))
                        chapter_names = [all_volumes[idx]['name'] for idx in selected_indices]
                        print(f"\n[OK] Capítulos seleccionados: {', '.join(chapter_names)}")
                    else:
                        print(f"Por favor, ingresa un rango válido (1-{len(all_volumes)})")
                        continue
                else:
                    print("Formato de rango inválido. Usa: 1-5")
                    continue
            else:
                volume_idx = int(selection) - 1
                if 0 <= volume_idx < len(all_volumes):
                    selected_indices = [volume_idx]
                    chapter_name = all_volumes[volume_idx]['name']
                    print(f"\n[OK] Capítulo seleccionado: {chapter_name}")
                else:
                    print(f"Por favor, ingresa un número entre 1 y {len(all_volumes)}")
                    continue
            
            if selected_indices:
                break
            else:
                print("No se seleccionaron capítulos válidos")
        except ValueError:
            print("Por favor, ingresa una selección válida")
        except KeyboardInterrupt:
            print("\n[CANCELADO] Operación cancelada por el usuario")
            sys.exit(0)
        except Exception as e:
            print(f"Error al procesar la selección: {e}")
    
    output_dir = config['output_dir']
    os.makedirs(output_dir, exist_ok=True)
    
    manga_type = downloader.get_manga_type(html_content)
    save_metadata(manga_title, all_volumes, output_dir, manga_type=manga_type)
    
    downloaded_dirs = []
    total_chapters = len(selected_indices)
    
    parallel_tomos = config.get('parallel_tomos', 1)
    
    def download_single_chapter(volume_idx, idx, total):
        selected_volume = all_volumes[volume_idx]
        chapter_name = selected_volume['name']
        
        with downloader.print_lock:
            print(f"\n{'='*60}")
            print(f"PROCESANDO CAPÍTULO {idx}/{total}: {chapter_name}")
            print(f"{'='*60}")
        
        result = downloader.download_volume(selected_volume, manga_title, output_dir)
        
        if result and result.get('dir'):
            return {
                'dir': result['dir'],
                'volume_name': selected_volume['name'],
                'chapters': selected_volume['chapters'],
                'failed_chapters': result.get('failed_chapters', [])
            }
        return None
    
    try:
        if parallel_tomos > 1 and total_chapters > 1:
            with ThreadPoolExecutor(max_workers=parallel_tomos) as executor:
                futures = {executor.submit(download_single_chapter, volume_idx, idx+1, total_chapters): volume_idx 
                          for idx, volume_idx in enumerate(selected_indices)}
                
                for future in as_completed(futures):
                    if downloader.cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    volume_idx = futures[future]
                    try:
                        result = future.result()
                        if result:
                            downloaded_dirs.append(result)
                    except Exception as e:
                        with downloader.print_lock:
                            print(f"[ERROR] Error al descargar capítulo: {e}")
        else:
            for idx, volume_idx in enumerate(selected_indices, start=1):
                if downloader.cancelled:
                    break
                result = download_single_chapter(volume_idx, idx, total_chapters)
                if result:
                    downloaded_dirs.append(result)
    except KeyboardInterrupt:
        print("\n\n[CANCELADO] Descarga cancelada por el usuario")
        downloader.cancel()
        sys.exit(0)
    
    if downloaded_dirs:
        print(f"\n{'='*60}")
        print("DESCARGA COMPLETADA")
        print(f"{'='*60}\n")
        
        all_failed_chapters = []
        for result in downloaded_dirs:
            all_failed_chapters.extend(result.get('failed_chapters', []))
        
        if all_failed_chapters:
            print(f"{'='*60}")
            print("RESUMEN DE ERRORES")
            print(f"{'='*60}")
            
            def get_failed_sort_key(failed):
                chapter_num = downloader.extract_chapter_numbers(failed['chapter_name'])
                try:
                    return float(chapter_num)
                except:
                    return 0.0
            
            sorted_failed = sorted(all_failed_chapters, key=get_failed_sort_key)
            
            for failed in sorted_failed:
                print(f"Capítulo {failed['chapter_name']}: {failed['downloaded']}/{failed['total']}")
            
            print(f"{'='*60}\n")
        
        print(f"Total de capítulos descargados: {len(downloaded_dirs)}")
        print(f"Directorio: {os.path.abspath(output_dir)}")
    else:
        print("\n[ERROR] No se descargaron capítulos")


if __name__ == '__main__':
    main()

