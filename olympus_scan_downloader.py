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


def save_metadata(manhwa_title, volumes, output_dir):
    metadata = {
        'manhwa_title': manhwa_title,
        'url': '',
        'volumes': []
    }
    
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
    
    safe_manhwa_title = re.sub(r'[<>:"/\\|?*]', '_', manhwa_title)
    manhwa_dir = os.path.join(output_dir, safe_manhwa_title)
    os.makedirs(manhwa_dir, exist_ok=True)
    
    metadata_path = os.path.join(manhwa_dir, 'manhwa_metadata.json')
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    title_path = os.path.join(manhwa_dir, 'manhwa_title.txt')
    with open(title_path, 'w', encoding='utf-8') as f:
        f.write(manhwa_title)


class OlympusScanDownloader:
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
            
            time.sleep(2)
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scroll_attempts = 50
            no_change_count = 0
            
            while scroll_attempts < max_scroll_attempts:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)
                
                new_height = driver.execute_script("return document.body.scrollHeight")
                
                if new_height == last_height:
                    no_change_count += 1
                    if no_change_count >= 3:
                        break
                else:
                    no_change_count = 0
                
                last_height = new_height
                scroll_attempts += 1
            
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            
            html = driver.page_source
            return html
        except Exception as e:
            print(f"Error con Selenium: {e}")
            return None
        finally:
            if driver:
                driver.quit()
    
    def get_manhwa_title(self, html_content):
        soup = BeautifulSoup(html_content, 'lxml')
        
        h1_tag = soup.find('h1')
        if h1_tag:
            title = h1_tag.get_text(strip=True)
            return title
        
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '').strip()
            if ' - ' in title:
                title = title.split(' - ')[0].strip()
            return title
        
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            if ' - ' in title:
                title = title.split(' - ')[0].strip()
            return title
        
        return "Manhwa"
    
    def extract_tomo_number(self, volume_name):
        match = re.search(r'(\d+)', volume_name)
        if match:
            return match.group(1)
        return "1"
    
    def extract_chapter_numbers(self, chapter_name):
        match = re.search(r'Capítulo\s*(\d+\.?\d*)', chapter_name, re.IGNORECASE)
        if not match:
            match = re.search(r'(\d+\.?\d*)', chapter_name)
        if match:
            return match.group(1)
        return "0"
    
    def sort_chapters_by_number(self, chapters):
        def get_chapter_sort_key(chapter):
            chapter_num = self.extract_chapter_numbers(chapter['name'])
            try:
                return float(chapter_num)
            except:
                return 0.0
        
        return sorted(chapters, key=get_chapter_sort_key)
    
    def parse_volumes(self, html_content, debug=False):
        soup = BeautifulSoup(html_content, 'lxml')
        volumes = []
        
        if debug:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_olympus.html')
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("\n=== MODO DEPURACIÓN ===")
            print(f"Tamaño del HTML: {len(html_content)} caracteres")
            print(f"  HTML guardado en '{debug_file}' para inspeccion")
        
        section = soup.find('section')
        if not section:
            if debug:
                print("[DEBUG] No se encontró la sección de capítulos")
                all_sections = soup.find_all('section')
                print(f"  Total de <section> encontrados: {len(all_sections)}")
                for idx, sec in enumerate(all_sections[:3]):
                    classes = sec.get('class', [])
                    print(f"    Sección {idx+1}: clases={classes}")
            return volumes
        
        if debug:
            section_classes = section.get('class', [])
            print(f"[DEBUG] Sección encontrada: clases={section_classes}")
        
        chapter_links = section.find_all('a', href=re.compile(r'/capitulo/\d+'))
        
        if not chapter_links:
            chapter_links = soup.find_all('a', href=re.compile(r'/capitulo/\d+'))
            if debug:
                print("[DEBUG] No se encontraron enlaces en la sección, buscando en todo el documento")
        
        if not chapter_links:
            if debug:
                print("[DEBUG] No se encontraron enlaces de capítulos")
                all_links = soup.find_all('a', href=True)
                print(f"  Total de enlaces <a> encontrados: {len(all_links)}")
                capitulo_links = [link for link in all_links if 'capitulo' in link.get('href', '').lower()]
                print(f"  Enlaces con 'capitulo' en href: {len(capitulo_links)}")
                for idx, link in enumerate(capitulo_links[:5]):
                    print(f"    {idx+1}. href={link.get('href', '')[:100]}")
            return volumes
        
        if debug:
            print(f"[DEBUG] Encontrados {len(chapter_links)} enlaces de capítulos")
            print(f"  Primeros 3 enlaces:")
            for idx, link in enumerate(chapter_links[:3]):
                href = link.get('href', '')
                print(f"    {idx+1}. href={href[:80]}")
                chapter_name_div = link.find('div', class_=lambda x: x and 'chapter-name' in ' '.join(x) if x else False)
                if chapter_name_div:
                    print(f"       chapter-name encontrado: {chapter_name_div.get_text(strip=True)[:50]}")
                else:
                    print(f"       chapter-name NO encontrado, texto completo: {link.get_text(strip=True)[:50]}")
        
        chapters_dict = {}
        skipped_count = 0
        for link in chapter_links:
            chapter_url = link.get('href', '')
            if not chapter_url:
                skipped_count += 1
                if debug and skipped_count <= 3:
                    print(f"[DEBUG] Enlace sin href, saltando...")
                continue
            
            if not chapter_url.startswith('http'):
                chapter_url = urljoin(self.base_url, chapter_url)
            
            chapter_name_div = link.find('div', class_=lambda x: x and 'chapter-name' in ' '.join(x) if x else False)
            if chapter_name_div:
                chapter_text = chapter_name_div.get_text(strip=True)
                if debug and len(chapters_dict) < 3:
                    print(f"[DEBUG] Capítulo {len(chapters_dict)+1}: Usando chapter-name div: '{chapter_text}'")
            else:
                chapter_text = link.get_text(strip=True)
                time_tag = link.find('time')
                if time_tag:
                    time_text = time_tag.get_text(strip=True)
                    if time_text in chapter_text:
                        chapter_text = chapter_text.replace(time_text, '').strip()
                
                por_div = link.find('div', string=re.compile(r'Por\s+', re.IGNORECASE))
                if por_div:
                    por_text = por_div.get_text(strip=True)
                    if por_text in chapter_text:
                        chapter_text = chapter_text.replace(por_text, '').strip()
                
                if 'Por' in chapter_text:
                    parts = chapter_text.split('Por')
                    if parts:
                        chapter_text = parts[0].strip()
                
                chapter_text = re.sub(r'\s+Por\s+[^\n]*', '', chapter_text, flags=re.IGNORECASE).strip()
                
                if debug and len(chapters_dict) < 3:
                    print(f"[DEBUG] Capítulo {len(chapters_dict)+1}: Usando texto completo del enlace (limpiado): '{chapter_text[:50]}'")
            
            if not chapter_text:
                skipped_count += 1
                if debug and skipped_count <= 3:
                    print(f"[DEBUG] Capítulo sin texto, saltando...")
                continue
            
            chapter_num_match = re.search(r'Capítulo\s*(\d+\.?\d*)', chapter_text, re.IGNORECASE)
            if not chapter_num_match:
                chapter_num_match = re.search(r'(\d+\.?\d*)', chapter_text)
            
            if chapter_num_match:
                try:
                    chapter_num = float(chapter_num_match.group(1))
                except:
                    chapter_num = 0.0
            else:
                chapter_num = 0.0
                if debug and len(chapters_dict) < 3:
                    print(f"[DEBUG] No se pudo extraer número del capítulo: '{chapter_text}'")
            
            if chapter_url not in chapters_dict:
                chapters_dict[chapter_url] = {
                    'name': chapter_text,
                    'url': chapter_url,
                    'number': chapter_num
                }
        
        if debug and skipped_count > 0:
            print(f"[DEBUG] Total de enlaces saltados: {skipped_count}")
        
        if not chapters_dict:
            if debug:
                print("[DEBUG] No se encontraron capítulos válidos después del procesamiento")
            return volumes
        
        all_chapters = sorted(chapters_dict.values(), key=lambda x: x['number'])
        
        if debug:
            print(f"[DEBUG] Capítulos procesados: {len(all_chapters)}")
            for ch in all_chapters[:5]:
                print(f"  - {ch['name']} (número: {ch['number']})")
        
        for ch in all_chapters:
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
        except Exception as e:
            print(f"[ERROR] Error al convertir WebP a JPG: {e}")
            return False
    
    def download_image_with_retry(self, img_url, filepath, max_retries=None):
        if max_retries is None:
            max_retries = self.config['retry_attempts']
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(img_url, timeout=self.config['timeout'])
                response.raise_for_status()
                
                content = response.content
                file_size = len(content)
                
                if file_size == 0:
                    raise ValueError(f"Archivo vacío: {file_size} bytes")
                
                temp_filepath = filepath
                original_ext = os.path.splitext(filepath)[1].lower()
                
                with open(temp_filepath, 'wb') as f:
                    f.write(content)
                
                if original_ext == '.webp' and PIL_AVAILABLE:
                    base_name = os.path.basename(filepath)
                    if '-webp' in base_name:
                        jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
                    else:
                        jpg_filename = base_name.replace('.webp', '.jpg')
                    jpg_filepath = os.path.join(os.path.dirname(filepath), jpg_filename)
                    
                    if self.convert_webp_to_jpg(temp_filepath, jpg_filepath, quality=95):
                        try:
                            os.remove(temp_filepath)
                        except:
                            pass
                        filepath = jpg_filepath
                        file_size = os.path.getsize(filepath)
                    else:
                        if temp_filepath != filepath:
                            os.rename(temp_filepath, filepath)
                
                return True, file_size
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(self.config['retry_delay'])
                else:
                    return False, str(e)
        
        return False, "Max retries exceeded"
    
    def download_image_with_semaphore(self, img_url, filepath, img_index, total_images):
        with self.connection_semaphore:
            success, result = self.download_image_with_retry(img_url, filepath)
            return (img_index, success, result, filepath)
    
    def download_chapter_images(self, chapter_url, chapter_name, output_dir):
        try:
            html_content = self.get_page(chapter_url)
            if not html_content:
                return ([], 0, 0, [])
        except Exception as e:
            return ([], 0, 0, [{'url': chapter_url, 'error': f"Error al obtener HTML: {str(e)}", 'index': -1}])
        
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            images = []
            
            section = soup.find('section')
            if section:
                img_divs = section.find_all('div', class_=lambda x: x and 'relative' in x)
                for div in img_divs:
                    img_tag = div.find('img')
                    if img_tag:
                        img_url = img_tag.get('src', '')
                        if not img_url:
                            continue
                        
                        if not img_url.startswith('http'):
                            img_url = urljoin(chapter_url, img_url)
                        
                        if img_url not in images:
                            images.append(img_url)
            
            if not images:
                img_tags = soup.find_all('img', src=re.compile(r'\.webp'))
                for img_tag in img_tags:
                    img_url = img_tag.get('src', '')
                    if not img_url:
                        continue
                    
                    if not img_url.startswith('http'):
                        img_url = urljoin(chapter_url, img_url)
                    
                    if img_url not in images:
                        images.append(img_url)
        except Exception as e:
            return ([], 0, 0, [{'url': chapter_url, 'error': f"Error al parsear HTML: {str(e)}", 'index': -1}])
        
        def extract_number(url):
            filename = os.path.basename(urlparse(url).path)
            match = re.search(r'(\d+)', filename)
            if match:
                return int(match.group(1))
            return 0
        
        images.sort(key=extract_number)
        
        safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter_name)
        output_basename = os.path.basename(output_dir)
        safe_output_basename = re.sub(r'[<>:"/\\|?*]', '_', output_basename)
        
        if safe_output_basename == safe_chapter_name:
            chapter_dir = output_dir
        else:
            chapter_dir = os.path.join(output_dir, safe_chapter_name)
        os.makedirs(chapter_dir, exist_ok=True)
        
        total_found = len(images)
        if total_found == 0:
            return ([], 0, 0, [])
        
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
                    futures = {executor.submit(self.download_image_with_semaphore, img_url, filepath, idx, total_found): (idx, img_url) 
                              for idx, img_url, filepath in download_tasks}
                    
                    for future in tqdm(as_completed(futures), total=len(download_tasks), desc=f"  {safe_chapter_name}", leave=False, unit="img"):
                        if self.cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            return ([], total_found, 0, [])
                        idx, img_url = futures[future]
                        try:
                            img_index, success, result, filepath = future.result()
                            if success:
                                base_name = os.path.basename(filepath)
                                if '-webp' in base_name:
                                    jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
                                else:
                                    jpg_filename = base_name.replace('.webp', '.jpg') if filepath.endswith('.webp') else base_name
                                jpg_filepath = os.path.join(chapter_dir, jpg_filename)
                                
                                if os.path.exists(jpg_filepath):
                                    downloaded_files[img_index] = jpg_filepath
                                else:
                                    downloaded_files[img_index] = filepath
                            else:
                                failed_downloads.append({'url': img_url, 'error': result, 'index': img_index, 'filepath': filepath})
                        except Exception as e:
                            failed_downloads.append({'url': img_url, 'error': str(e), 'index': idx, 'filepath': filepath})
            else:
                for idx, img_url, filepath in tqdm(download_tasks, desc=f"  {safe_chapter_name}", leave=False, unit="img"):
                    if self.cancelled:
                        return ([], total_found, 0, [])
                    try:
                        success, result = self.download_image_with_retry(img_url, filepath)
                        if success:
                            base_name = os.path.basename(filepath)
                            if '-webp' in base_name:
                                jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
                            else:
                                jpg_filename = base_name.replace('.webp', '.jpg') if filepath.endswith('.webp') else base_name
                            jpg_filepath = os.path.join(chapter_dir, jpg_filename)
                            
                            if os.path.exists(jpg_filepath):
                                downloaded_files[idx] = jpg_filepath
                            else:
                                downloaded_files[idx] = filepath
                        else:
                            failed_downloads.append({'url': img_url, 'error': result, 'index': idx, 'filepath': filepath})
                        time.sleep(self.config['delay_between_images'])
                    except Exception as e:
                        failed_downloads.append({'url': img_url, 'error': str(e), 'index': idx, 'filepath': filepath})
        
        if failed_downloads:
            retry_attempts = self.config.get('retry_failed_images', 2)
            if retry_attempts > 0:
                for retry in range(retry_attempts):
                    if not failed_downloads:
                        break
                    
                    retry_failed = failed_downloads.copy()
                    failed_downloads = []
                    
                    for failed in retry_failed:
                        if 'filepath' in failed:
                            try:
                                success, result = self.download_image_with_retry(failed['url'], failed['filepath'], max_retries=3)
                                if success:
                                    base_name = os.path.basename(failed['filepath'])
                                    if '-webp' in base_name:
                                        jpg_filename = base_name.replace('-webp', '').replace('.webp', '.jpg')
                                    else:
                                        jpg_filename = base_name.replace('.webp', '.jpg') if failed['filepath'].endswith('.webp') else base_name
                                    jpg_filepath = os.path.join(chapter_dir, jpg_filename)
                                    
                                    if os.path.exists(jpg_filepath):
                                        downloaded_files[failed['index']] = jpg_filepath
                                    else:
                                        downloaded_files[failed['index']] = failed['filepath']
                                else:
                                    failed_downloads.append(failed)
                            except Exception as e:
                                failed_downloads.append(failed)
        
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
                        print(f"[ADVERTENCIA] No se pudo crear archivo temporal: {e}")
                        renamed_files.append(old_filepath)
                        continue
                
                try:
                    os.rename(old_filepath, new_filepath)
                    renamed_files.append(new_filepath)
                except Exception as e:
                    print(f"[ADVERTENCIA] No se pudo renombrar {os.path.basename(old_filepath)}: {e}")
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
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"[ADVERTENCIA] No se pudo eliminar archivo {file}: {e}")
        
        return (downloaded_files, total_found, total_downloaded, failed_downloads, skipped_files)
    
    def get_chapter_image_count(self, chapter_url):
        try:
            html_content = self.get_page(chapter_url)
            if not html_content:
                return 0
            
            soup = BeautifulSoup(html_content, 'lxml')
            images = []
            
            section = soup.find('section')
            if section:
                img_divs = section.find_all('div', class_=lambda x: x and 'relative' in x)
                for div in img_divs:
                    img_tag = div.find('img')
                    if img_tag:
                        img_url = img_tag.get('src', '')
                        if img_url and img_url not in images:
                            images.append(img_url)
            
            if not images:
                img_tags = soup.find_all('img', src=re.compile(r'\.webp'))
                for img_tag in img_tags:
                    img_url = img_tag.get('src', '')
                    if img_url and img_url not in images:
                        images.append(img_url)
            
            return len(images)
        except:
            return 0
    
    def check_volume_complete(self, volume_dir, chapters):
        if not os.path.exists(volume_dir):
            return False, 0, 0
        
        total_chapters = len(chapters)
        complete_chapters = 0
        
        for chapter in chapters:
            safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter['name'])
            chapter_dir = os.path.join(volume_dir, safe_chapter_name)
            
            if os.path.exists(chapter_dir):
                image_files = [f for f in os.listdir(chapter_dir) 
                             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif'))]
                downloaded_count = len(image_files)
                
                if downloaded_count > 0:
                    expected_count = self.get_chapter_image_count(chapter['url'])
                    
                    if expected_count > 0:
                        if downloaded_count >= expected_count:
                            complete_chapters += 1
                    else:
                        if downloaded_count >= 5:
                            complete_chapters += 1
        
        is_complete = complete_chapters == total_chapters and total_chapters > 0
        return is_complete, complete_chapters, total_chapters
    
    def download_volume(self, volume_data, manhwa_title, output_dir='downloads'):
        if self.cancelled:
            return {'dir': None, 'failed_chapters': []}
        
        volume_name = volume_data['name']
        chapters = volume_data['chapters']
        
        chapters = self.sort_chapters_by_number(chapters)
        
        safe_manhwa_title = re.sub(r'[<>:"/\\|?*]', '_', manhwa_title)
        manhwa_dir = os.path.join(output_dir, safe_manhwa_title)
        os.makedirs(manhwa_dir, exist_ok=True)
        
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', volume_name)
        volume_dir = os.path.join(manhwa_dir, safe_name)
        os.makedirs(volume_dir, exist_ok=True)
        
        force_redownload = self.config.get('force_redownload', False)
        
        if not force_redownload:
            is_complete, complete_chapters, total_chapters = self.check_volume_complete(volume_dir, chapters)
            
            if is_complete:
                with self.print_lock:
                    print(f"\n{'='*60}")
                    print(f"Capítulo ya está completo ({complete_chapters}/{total_chapters} imágenes)")
                    print(f"Omitiendo descarga. Usa 'force_redownload: true' en config.json para forzar re-descarga")
                    print(f"{'='*60}\n")
                return {
                    'dir': volume_dir,
                    'failed_chapters': []
                }
        
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
                with self.print_lock:
                    print(f"\n[{idx}/{total}] Procesando: {chapter['name']}")
                
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
                            print(f"  [ERROR] Error en capítulo: {e}")
        else:
            for idx, chapter in enumerate(tqdm(chapters, desc=volume_name, unit="img"), start=1):
                if self.cancelled:
                    break
                try:
                    print(f"\n[{idx}/{len(chapters)}] Procesando: {chapter['name']}")
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
                    
                    if total_found > 0:
                        if total_downloaded == total_found:
                            print(f"  [OK] Verificación: {total_downloaded}/{total_found} imágenes descargadas correctamente")
                        else:
                            print(f"  [ADVERTENCIA] Verificación: {total_downloaded}/{total_found} imágenes descargadas ({total_found - total_downloaded} fallaron)")
                            if failed:
                                print(f"  [ERROR] URLs que fallaron: {len(failed)}")
                    else:
                        print(f"  [ADVERTENCIA] No se encontraron imágenes en este capítulo")
                except Exception as e:
                    print(f"  [ERROR] Error al procesar capítulo {chapter['name']}: {str(e)}")
                    chapter_stats.append({
                        'name': chapter['name'],
                        'total_found': 0,
                        'total_downloaded': 0,
                        'failed': 1,
                        'skipped': 0
                    })
                
                time.sleep(self.config['delay_between_chapters'])
        
        if all_images or any(stat.get('total_downloaded', 0) > 0 for stat in chapter_stats):
            print(f"\n{'='*60}")
            print(f"RESUMEN - {volume_name}")
            print(f"{'='*60}")
            
            def get_chapter_sort_key(stat):
                chapter_num = self.extract_chapter_numbers(stat['name'])
                try:
                    return float(chapter_num)
                except:
                    return 0.0
            
            sorted_stats = sorted(chapter_stats, key=get_chapter_sort_key)
            
            failed_chapters = []
            for stat in sorted_stats:
                total_found = stat.get('total_found', 0)
                total_downloaded = stat.get('total_downloaded', 0)
                status_icon = "[OK]" if total_downloaded == total_found and total_found > 0 else "[ERROR]"
                print(f"{status_icon} {stat['name']}: {total_downloaded}/{total_found}")
                
                if total_downloaded < total_found:
                    failed_chapters.append({
                        'chapter_name': stat['name'],
                        'downloaded': total_downloaded,
                        'total': total_found
                    })
            
            print(f"{'='*60}")
            print(f"\n[OK] Descarga completada: {os.path.abspath(volume_dir)}")
            return {
                'dir': volume_dir,
                'failed_chapters': failed_chapters
            }
        else:
            print("\n[ERROR] No se descargaron imagenes")
            return {
                'dir': None,
                'failed_chapters': []
            }


def main():
    print("="*60)
    print("DESCARGADOR DE MANHWA - OLYMPUS SCAN")
    print("="*60)
    
    config = load_config()
    
    debug_mode = '--debug' in sys.argv or '-d' in sys.argv
    
    url_args = [arg for arg in sys.argv[1:] if arg not in ['--debug', '-d']]
    
    if url_args:
        url = url_args[0]
    else:
        url = input("\nIngresa la URL del manhwa: ").strip()
    
    if not url:
        print("Error: Debes proporcionar una URL")
        sys.exit(1)
    
    downloader = OlympusScanDownloader(url, config)
    
    print(f"\nDescargando información de: {url}")
    
    use_selenium = True
    
    if not SELENIUM_AVAILABLE:
        print("[ERROR] Selenium no esta disponible.")
        print("  Instala Selenium con: pip install selenium")
        print("  Tambien necesitas tener Chrome/Chromium instalado")
        sys.exit(1)
    
    html_content = downloader.get_page(url, use_selenium=use_selenium)
    
    if not html_content:
        print("Error: No se pudo descargar la página con Selenium")
        print("  Verifica que Chrome/Chromium esté instalado")
        print("  ChromeDriver se descarga automáticamente en versiones recientes de Selenium")
        sys.exit(1)
    
    manhwa_title = downloader.get_manhwa_title(html_content)
    print(f"Título del manhwa: {manhwa_title}")
    
    print("Parseando capítulos...")
    volumes = downloader.parse_volumes(html_content, debug=debug_mode)
    
    if not volumes:
        print("Error: No se encontraron capítulos en la página")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"CAPÍTULOS DETECTADOS: {len(volumes)}")
    print(f"{'='*60}")
    for idx, volume in enumerate(volumes, start=1):
        print(f"{idx}. {volume['name']}")
    
    print(f"\n{'='*60}")
    print("Opciones de selección:")
    print("  - Un capítulo: 1")
    print("  - Varios capítulos: 1,3,5 o 1-5")
    print("  - Todos los capítulos: all")
    print(f"{'='*60}")
    
    while True:
        try:
            selection = input(f"\nSelecciona el capítulo(s) (1-{len(volumes)}) o 'q' para salir: ").strip()
            if selection.lower() == 'q':
                print("Saliendo...")
                sys.exit(0)
            
            selected_indices = []
            
            if selection.lower() == 'all':
                selected_indices = list(range(len(volumes)))
                print(f"\n[OK] Todos los tomos seleccionados: {len(volumes)} tomos")
            elif ',' in selection:
                parts = [p.strip() for p in selection.split(',')]
                for part in parts:
                    idx = int(part) - 1
                    if 0 <= idx < len(volumes):
                        selected_indices.append(idx)
                    else:
                        print(f"[ADVERTENCIA] Capítulo {part} fuera de rango, se omitirá")
                selected_indices = sorted(set(selected_indices))
                print(f"\n[OK] Capítulos seleccionados: {len(selected_indices)} capítulos")
            elif '-' in selection:
                parts = selection.split('-')
                if len(parts) == 2:
                    start = int(parts[0].strip()) - 1
                    end = int(parts[1].strip()) - 1
                    if 0 <= start < len(volumes) and 0 <= end < len(volumes) and start <= end:
                        selected_indices = list(range(start, end + 1))
                        print(f"\n[OK] Rango de capítulos seleccionado: {len(selected_indices)} capítulos")
                    else:
                        print(f"Por favor, ingresa un rango válido (1-{len(volumes)})")
                        continue
                else:
                    print("Formato de rango inválido. Usa: 1-5")
                    continue
            else:
                volume_idx = int(selection) - 1
                if 0 <= volume_idx < len(volumes):
                    selected_indices = [volume_idx]
                    chapter_name = volumes[volume_idx]['name']
                    print(f"\n[OK] Capítulo seleccionado: {chapter_name}")
                else:
                    print(f"Por favor, ingresa un número entre 1 y {len(volumes)}")
                    continue
            
            if selected_indices:
                break
            else:
                print("No se seleccionaron capítulos válidos")
        except ValueError:
            print("Por favor, ingresa una selección válida")
        except Exception as e:
            print(f"Error al procesar la selección: {e}")
    
    output_dir = config['output_dir']
    os.makedirs(output_dir, exist_ok=True)
    
    save_metadata(manhwa_title, volumes, output_dir)
    
    downloaded_dirs = []
    total_chapters = len(selected_indices)
    
    parallel_chapters = config.get('parallel_tomos', 1)
    
    def download_single_chapter(volume_idx, idx, total):
        selected_volume = volumes[volume_idx]
        chapter_name = selected_volume['name']
        
        with downloader.print_lock:
            print(f"\n{'='*60}")
            print(f"PROCESANDO CAPÍTULO {idx}/{total}: {chapter_name}")
            print(f"{'='*60}")
        
        result = downloader.download_volume(selected_volume, manhwa_title, output_dir)
        
        if result and result.get('dir'):
            return {
                'dir': result['dir'],
                'volume_name': selected_volume['name'],
                'chapters': selected_volume['chapters'],
                'failed_chapters': result.get('failed_chapters', [])
            }
        return None
    
    try:
        if parallel_chapters > 1 and total_chapters > 1:
            print(f"\n[INFO] Descargando {total_chapters} capítulos en paralelo (máximo {parallel_chapters} simultáneos)")
            print("[INFO] Presiona Ctrl+C para cancelar la descarga")
            with ThreadPoolExecutor(max_workers=parallel_chapters) as executor:
                futures = {executor.submit(download_single_chapter, volume_idx, idx+1, total_chapters): (volume_idx, idx+1) 
                         for idx, volume_idx in enumerate(selected_indices)}
                
                for future in as_completed(futures):
                    if downloader.cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        print("\n[INFO] Descarga cancelada por el usuario")
                        break
                    volume_idx, idx = futures[future]
                    try:
                        result = future.result()
                        if result:
                            downloaded_dirs.append(result)
                            chapter_name = volumes[volume_idx]['name']
                            with downloader.print_lock:
                                print(f"\n[OK] Capítulo {chapter_name} descargado: {os.path.basename(result['dir'])}")
                    except Exception as e:
                        chapter_name = volumes[volume_idx]['name']
                        with downloader.print_lock:
                            print(f"\n[ERROR] Error al descargar capítulo {chapter_name}: {e}")
                        downloaded_dirs.append({
                            'dir': None,
                            'volume_name': volumes[volume_idx]['name'],
                            'chapters': volumes[volume_idx]['chapters'],
                            'failed_chapters': []
                        })
        else:
            print("[INFO] Presiona Ctrl+C para cancelar la descarga")
            for idx, volume_idx in enumerate(selected_indices, start=1):
                if downloader.cancelled:
                    print("\n[INFO] Descarga cancelada por el usuario")
                    break
                selected_volume = volumes[volume_idx]
                chapter_name = selected_volume['name']
                
                print(f"\n{'='*60}")
                print(f"PROCESANDO CAPÍTULO {idx}/{total_chapters}: {chapter_name}")
                print(f"{'='*60}")
                
                result = downloader.download_volume(selected_volume, manhwa_title, output_dir)
                
                if result and result.get('dir'):
                    downloaded_dirs.append({
                        'dir': result['dir'],
                        'volume_name': selected_volume['name'],
                        'chapters': selected_volume['chapters'],
                        'failed_chapters': result.get('failed_chapters', [])
                    })
                    print(f"\n[OK] Capítulo {chapter_name} descargado: {os.path.basename(result['dir'])}")
                else:
                    print(f"\n[ERROR] No se pudieron descargar las imágenes para el capítulo {chapter_name}")
    except KeyboardInterrupt:
        print("\n[INFO] Descarga cancelada por el usuario (Ctrl+C)")
        downloader.cancel()
    
    if downloaded_dirs:
        def get_chapter_sort_key(item):
            chapter_name = item['volume_name']
            chapter_num = downloader.extract_chapter_numbers(chapter_name)
            try:
                return float(chapter_num)
            except:
                return 0.0
        
        sorted_dirs = sorted(downloaded_dirs, key=get_chapter_sort_key)
        
        all_failed_chapters = []
        for item in downloaded_dirs:
            if 'failed_chapters' in item:
                all_failed_chapters.extend(item['failed_chapters'])
        
        print(f"\n{'='*60}")
        print(f"¡DESCARGA COMPLETADA! ({len(downloaded_dirs)}/{total_chapters} capítulos)")
        print(f"{'='*60}")
        print("\nCarpetas de imágenes descargadas:")
        for item in sorted_dirs:
            if item.get('dir'):
                print(f"  - {os.path.basename(item['dir'])}")
        print(f"\nUbicación: {os.path.abspath(output_dir)}")
        print(f"\n[INFO] Para generar los archivos CBR, ejecuta: python cbr_generator.py")
        print(f"{'='*60}")
        
        if all_failed_chapters:
            def get_failed_sort_key(failed):
                try:
                    chapter_num = float(downloader.extract_chapter_numbers(failed.get('chapter_name', '')))
                except:
                    chapter_num = 0.0
                return chapter_num
            
            sorted_failed = sorted(all_failed_chapters, key=get_failed_sort_key)
            
            print(f"\n{'='*60}")
            print("RESUMEN DE ERRORES")
            print(f"{'='*60}")
            for failed in sorted_failed:
                print(f"Capítulo {failed.get('chapter_name', 'Desconocido')}: {failed.get('downloaded', 0)}/{failed.get('total', 0)}")
            print(f"{'='*60}\n")
        else:
            print("\n")
    else:
        print("\n[ERROR] No se pudieron descargar las imágenes")


if __name__ == '__main__':
    main()

