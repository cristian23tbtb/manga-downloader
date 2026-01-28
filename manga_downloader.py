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


class MangaDownloader:
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
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".page-content-listing, .listing-chapters_wrap, ul.version-chap"))
                )
            except:
                pass
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(self.config['selenium_extra_wait'])
            
            driver.execute_script("""
                var volumes = document.querySelectorAll('li.parent.has-child a.has-child');
                volumes.forEach(function(vol) {
                    var subList = vol.closest('li').querySelector('ul.sub-chap.list-chap');
                    if (subList && subList.style.display === 'none') {
                        vol.click();
                    }
                });
            """)
            time.sleep(2)
            
            html = driver.page_source
            return html
        except Exception as e:
            print(f"Error con Selenium: {e}")
            return None
        finally:
            if driver:
                driver.quit()
    
    def get_chapters_ajax(self, manga_id, debug=False):
        from urllib.parse import urlparse
        parsed = urlparse(self.base_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        ajax_url = f"{base_url}/wp-admin/admin-ajax.php"
        
        rest_url = f"{base_url}/wp-json/wp-manga/v1/chapters/{manga_id}"
        try:
            if debug:
                print(f"  Intentando API REST: {rest_url}")
            response = self.session.get(rest_url, timeout=self.config['timeout'])
            if response.status_code == 200:
                content = response.text
                if debug:
                    print(f"  [OK] API REST devolvio contenido")
                return content
        except Exception as e:
            if debug:
                print(f"  Error con API REST: {e}")
        
        actions = [
            ('manga_get_chapters', {'action': 'manga_get_chapters', 'manga': manga_id}),
            ('wp_manga_get_chapters', {'action': 'wp_manga_get_chapters', 'manga_id': manga_id}),
            ('get_manga_chapters', {'action': 'get_manga_chapters', 'manga_id': manga_id}),
            ('manga_chapters', {'action': 'manga_chapters', 'manga': manga_id, 'manga_id': manga_id}),
        ]
        
        for action_name, data in actions:
            try:
                if debug:
                    print(f"  Intentando accion: {action_name}")
                response = self.session.post(ajax_url, data=data, timeout=self.config['timeout'])
                if response.status_code == 200:
                    content = response.text
                    if debug:
                        print(f"  Respuesta (primeros 500 chars): {content[:500]}")
                    
                    if 'version-chap' in content or 'volumns' in content or 'wp-manga-chapter' in content or len(content) > 100:
                        if debug:
                            print(f"  [OK] Accion '{action_name}' devolvio contenido valido")
                        return content
            except requests.RequestException as e:
                if debug:
                    print(f"  Error con accion '{action_name}': {e}")
                continue
        
        return None
    
    def get_manga_title(self, html_content):
        soup = BeautifulSoup(html_content, 'lxml')
        
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
        
        return "Manga"
    
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
        
        manga_id = None
        chapters_holder = soup.find('div', id='manga-chapters-holder')
        if chapters_holder:
            manga_id = chapters_holder.get('data-id')
        
        if not manga_id:
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'manga_id' in script.string:
                    match = re.search(r'"manga_id"\s*:\s*"(\d+)"', script.string)
                    if match:
                        manga_id = match.group(1)
                        break
        
        if debug:
            print("\n=== MODO DEPURACIÓN ===")
            print(f"Tamaño del HTML: {len(html_content)} caracteres")
            
            all_uls = soup.find_all('ul')
            print(f"\nTotal de elementos <ul> encontrados: {len(all_uls)}")
            for ul in all_uls[:10]:
                classes = ul.get('class', [])
                print(f"  - <ul> con clases: {classes}")
            
            page_content = soup.find('div', class_='page-content-listing')
            if page_content:
                print("\n[OK] Encontrado div.page-content-listing")
                print(f"  Contenido interno (primeros 500 chars): {str(page_content)[:500]}")
            else:
                print("\n[ERROR] No se encontro div.page-content-listing")
            
            vol_uls = soup.find_all('ul', class_=lambda x: x and ('volumns' in ' '.join(x) or 'version-chap' in ' '.join(x)))
            print(f"\nElementos <ul> con 'volumns' o 'version-chap': {len(vol_uls)}")
            for ul in vol_uls:
                print(f"  - Clases: {ul.get('class', [])}")
        
        volume_container = soup.find('ul', class_='main version-chap volumns active')
        if not volume_container:
            volume_container = soup.find('ul', class_='main version-chap volumns')
        
        if not volume_container:
            volume_container = soup.find('ul', class_=lambda x: x and 'volumns' in ' '.join(x))
        
        if not volume_container:
            page_content = soup.find('div', class_='page-content-listing')
            if page_content:
                volume_container = page_content.find('ul', class_=lambda x: x and 'volumns' in ' '.join(x) if x else False)
        
        if not volume_container and manga_id:
            if debug:
                print(f"\n[INFO] Intentando cargar capitulos mediante AJAX (manga_id: {manga_id})")
            
            ajax_content = self.get_chapters_ajax(manga_id, debug=debug)
            if ajax_content:
                ajax_soup = BeautifulSoup(ajax_content, 'lxml')
                volume_container = ajax_soup.find('ul', class_='main version-chap volumns active')
                if not volume_container:
                    volume_container = ajax_soup.find('ul', class_='main version-chap volumns')
                if not volume_container:
                    volume_container = ajax_soup.find('ul', class_=lambda x: x and 'volumns' in ' '.join(x) if x else False)
                
                if volume_container:
                    if debug:
                        print("[OK] Contenedor encontrado mediante AJAX")
                    soup = ajax_soup
        
        if not volume_container:
            if debug:
                print("\n[ERROR] No se encontro el contenedor de volumenes")
                print(f"  Manga ID encontrado: {manga_id}")
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html.html')
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"  HTML guardado en '{debug_file}' para inspeccion")
                
                all_divs = soup.find_all('div', class_=lambda x: x and ('listing' in ' '.join(x) or 'chapter' in ' '.join(x) or 'volume' in ' '.join(x).lower()))
                print(f"\nDivs con 'listing', 'chapter' o 'volume': {len(all_divs)}")
                for div in all_divs[:5]:
                    print(f"  - Clases: {div.get('class', [])}")
                    uls_inside = div.find_all('ul')
                    print(f"    Uls dentro: {len(uls_inside)}")
                    for ul in uls_inside:
                        print(f"      - Ul clases: {ul.get('class', [])}")
            else:
                print("No se encontró el contenedor de volúmenes")
            return volumes
        
        if debug:
            print(f"\n[OK] Contenedor encontrado: {volume_container.get('class', [])}")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html.html')
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"  HTML guardado en '{debug_file}' para inspeccion")
        
        volume_items = volume_container.find_all('li', class_=lambda x: x and 'parent' in x and 'has-child' in x)
        
        if debug:
            print(f"\n[DEBUG] Elementos 'li.parent has-child' encontrados: {len(volume_items)}")
        
        for item in volume_items:
            volume_link = item.find('a', class_='has-child')
            if volume_link:
                volume_name = volume_link.get_text(strip=True)
                
                chapters = []
                sub_chap_list = item.find('ul', class_='sub-chap list-chap')
                if sub_chap_list:
                    sub_chap_list_inner = sub_chap_list.find('ul', class_='sub-chap-list')
                    if sub_chap_list_inner:
                        chapter_links = sub_chap_list_inner.find_all('a', href=True)
                    else:
                        chapter_links = sub_chap_list.find_all('a', href=True)
                    
                    for chapter_link in chapter_links:
                        chapter_url = chapter_link.get('href')
                        chapter_name = chapter_link.get_text(strip=True)
                        if chapter_url and chapter_url != 'javascript:void(0)':
                            chapters.append({
                                'name': chapter_name,
                                'url': chapter_url
                            })
                
                if debug:
                    print(f"  [DEBUG] Volumen encontrado: {volume_name} - Capítulos: {len(chapters)}")
                
                if chapters:
                    volumes.append({
                        'name': volume_name,
                        'chapters': chapters
                    })
                else:
                    if debug:
                        print(f"  [ADVERTENCIA] Volumen '{volume_name}' sin capítulos, se omite")
        
        if debug:
            print(f"\n[DEBUG] Total de volúmenes con capítulos: {len(volumes)}")
        
        return volumes
    
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
                
                with open(filepath, 'wb') as f:
                    f.write(content)
                
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
            
            image_divs = soup.find_all('div', class_='page-break')
            
            for div in image_divs:
                img_tag = div.find('img', class_='wp-manga-chapter-img')
                if img_tag:
                    img_url = None
                    
                    for attr in ['data-src', 'data-full-url', 'data-original', 'data-lazy-src', 'src']:
                        if img_tag.get(attr):
                            img_url = img_tag.get(attr).strip()
                            break
                    
                    if img_tag.get('srcset'):
                        srcset = img_tag.get('srcset', '')
                        if srcset:
                            srcset_parts = [s.strip() for s in srcset.split(',')]
                            largest_url = None
                            largest_size = 0
                            for part in srcset_parts:
                                if ' ' in part:
                                    url_part, size_part = part.rsplit(' ', 1)
                                    try:
                                        if size_part.endswith('w'):
                                            size = int(size_part[:-1])
                                        elif size_part.endswith('x'):
                                            size = float(size_part[:-1]) * 1000
                                        else:
                                            size = 0
                                        
                                        if size > largest_size:
                                            largest_size = size
                                            largest_url = url_part.strip()
                                    except:
                                        pass
                            
                            if largest_url:
                                img_url = largest_url
                    
                    if img_url:
                        img_url = re.sub(r'\s+', '', img_url)
                        
                        parsed = urlparse(img_url)
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        img_url = clean_url
                        
                        if not img_url.startswith('http'):
                            img_url = urljoin(chapter_url, img_url)
                        
                        images.append(img_url)
        except Exception as e:
            return ([], 0, 0, [{'url': chapter_url, 'error': f"Error al parsear HTML: {str(e)}", 'index': -1}])
        
        def extract_number(url):
            match = re.search(r'(\d+)\.\d+-(\d+)', url)
            if match:
                return (int(match.group(1)), int(match.group(2)))
            match = re.search(r'(\d+)', url.split('/')[-1])
            if match:
                return (0, int(match.group(1)))
            return (0, 0)
        
        images.sort(key=extract_number)
        
        safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter_name)
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
                        filename = f"image_{img_index:04d}_{hash(img_url) % 10000}.{ext}"
                    else:
                        filename = f"image_{img_index:04d}_{hash(img_url) % 10000}.png"
                else:
                    filename = f"image_{img_index:04d}_{hash(img_url) % 10000}.png"
            
            if '?' in filename:
                filename = filename.split('?')[0]
            
            filepath = os.path.join(chapter_dir, filename)
            return (img_index, img_url, filepath)
        
        download_tasks = []
        for idx, img_url in enumerate(images):
            img_index, img_url, filepath = prepare_download(idx, img_url)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
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
            if file.lower().startswith('temp_') and file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                temp_file_path = os.path.join(chapter_dir, file)
                try:
                    os.remove(temp_file_path)
                except Exception as e:
                    print(f"[ADVERTENCIA] No se pudo eliminar archivo temporal {file}: {e}")
        
        return (downloaded_files, total_found, total_downloaded, failed_downloads, skipped_files)
    
    def get_chapter_image_count(self, chapter_url):
        try:
            html_content = self.get_page(chapter_url)
            if not html_content:
                return 0
            
            soup = BeautifulSoup(html_content, 'lxml')
            image_divs = soup.find_all('div', class_='page-break')
            images = []
            
            for div in image_divs:
                img_tag = div.find('img', class_='wp-manga-chapter-img')
                if img_tag:
                    img_url = None
                    for attr in ['data-src', 'data-full-url', 'data-original', 'data-lazy-src', 'src']:
                        if img_tag.get(attr):
                            img_url = img_tag.get(attr).strip()
                            break
                    if img_url:
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
    
    def download_volume(self, volume_data, manga_title, output_dir='downloads'):
        if self.cancelled:
            return {'dir': None, 'failed_chapters': []}
        
        volume_name = volume_data['name']
        chapters = volume_data['chapters']
        
        chapters = self.sort_chapters_by_number(chapters)
        
        tomo_number = self.extract_tomo_number(volume_name)
        
        safe_manga_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
        manga_dir = os.path.join(output_dir, safe_manga_title)
        os.makedirs(manga_dir, exist_ok=True)
        
        volume_name_tomo = volume_name.replace('Volumen', 'Tomo').replace('volumen', 'Tomo')
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', volume_name_tomo)
        volume_dir = os.path.join(manga_dir, safe_name)
        os.makedirs(volume_dir, exist_ok=True)
        
        force_redownload = self.config.get('force_redownload', False)
        
        if not force_redownload:
            is_complete, complete_chapters, total_chapters = self.check_volume_complete(volume_dir, chapters)
            
            if is_complete:
                with self.print_lock:
                    print(f"\n{'='*60}")
                    print(f"Tomo {tomo_number} ya está completo ({complete_chapters}/{total_chapters} capítulos)")
                    print(f"Omitiendo descarga. Usa 'force_redownload: true' en config.json para forzar re-descarga")
                    print(f"{'='*60}\n")
                return {
                    'dir': volume_dir,
                    'failed_chapters': []
                }
        
        print(f"\n{'='*60}")
        print(f"Descargando: Tomo {tomo_number}")
        print(f"Capítulos encontrados: {len(chapters)}")
        print(f"{'='*60}\n")
        
        all_images = []
        chapter_stats = []
        
        parallel_chapters = self.config.get('parallel_chapters', 1)
        
        def download_single_chapter(chapter, idx, total):
            if self.cancelled:
                return ({'name': chapter['name'], 'total_found': 0, 'total_downloaded': 0, 'failed': 0, 'skipped': 0}, [])
            try:
                with self.print_lock:
                    print(f"\n[Tomo {tomo_number}] [{idx}/{total}] Procesando: {chapter['name']}")
                
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
            for idx, chapter in enumerate(tqdm(chapters, desc=f"Tomo {tomo_number}", unit="cap"), start=1):
                if self.cancelled:
                    break
                try:
                    print(f"\n[Tomo {tomo_number}] [{idx}/{len(chapters)}] Procesando: {chapter['name']}")
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
            print(f"RESUMEN - Tomo {tomo_number}")
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
                print(f"{status_icon} Tomo {tomo_number}, {stat['name']}: {total_downloaded}/{total_found}")
                
                if total_downloaded < total_found:
                    failed_chapters.append({
                        'tomo_number': tomo_number,
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
    print("DESCARGADOR DE MANGA - GENERADOR DE CBR")
    print("="*60)
    
    config = load_config()
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("\nIngresa la URL del manga: ").strip()
    
    if not url:
        print("Error: Debes proporcionar una URL")
        sys.exit(1)
    
    downloader = MangaDownloader(url, config)
    
    print(f"\nDescargando información de: {url}")
    
    debug_mode = '--debug' in sys.argv or '-d' in sys.argv
    
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
    
    manga_title = downloader.get_manga_title(html_content)
    print(f"Título del manga: {manga_title}")
    
    print("Parseando tomos...")
    volumes = downloader.parse_volumes(html_content, debug=debug_mode)
    
    if not volumes:
        print("Error: No se encontraron tomos en la página")
        sys.exit(1)
    
    volumes.reverse()
    
    print(f"\n{'='*60}")
    print(f"TOMOS DETECTADOS: {len(volumes)}")
    print(f"{'='*60}")
    for idx, volume in enumerate(volumes, start=1):
        print(f"{idx}. {volume['name']} ({len(volume['chapters'])} capítulos)")
    
    print(f"\n{'='*60}")
    print("Opciones de selección:")
    print("  - Un tomo: 1")
    print("  - Varios tomos: 1,3,5 o 1-5")
    print("  - Todos los tomos: all")
    print(f"{'='*60}")
    
    while True:
        try:
            selection = input(f"\nSelecciona el tomo(s) (1-{len(volumes)}) o 'q' para salir: ").strip()
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
                        print(f"[ADVERTENCIA] Tomo {part} fuera de rango, se omitirá")
                selected_indices = sorted(set(selected_indices))
                print(f"\n[OK] Tomos seleccionados: {len(selected_indices)} tomos")
            elif '-' in selection:
                parts = selection.split('-')
                if len(parts) == 2:
                    start = int(parts[0].strip()) - 1
                    end = int(parts[1].strip()) - 1
                    if 0 <= start < len(volumes) and 0 <= end < len(volumes) and start <= end:
                        selected_indices = list(range(start, end + 1))
                        print(f"\n[OK] Rango de tomos seleccionado: {len(selected_indices)} tomos")
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
                    tomo_number = downloader.extract_tomo_number(volumes[volume_idx]['name'])
                    print(f"\n[OK] Tomo seleccionado: Tomo {tomo_number}")
                    print(f"     Capítulos: {len(volumes[volume_idx]['chapters'])}")
                else:
                    print(f"Por favor, ingresa un número entre 1 y {len(volumes)}")
                    continue
            
            if selected_indices:
                break
            else:
                print("No se seleccionaron tomos válidos")
        except ValueError:
            print("Por favor, ingresa una selección válida")
        except Exception as e:
            print(f"Error al procesar la selección: {e}")
    
    output_dir = config['output_dir']
    os.makedirs(output_dir, exist_ok=True)
    
    save_metadata(manga_title, volumes, output_dir)
    
    downloaded_dirs = []
    total_tomos = len(selected_indices)
    
    parallel_tomos = config.get('parallel_tomos', 1)
    
    def download_single_tomo(volume_idx, idx, total):
        selected_volume = volumes[volume_idx]
        tomo_number = downloader.extract_tomo_number(selected_volume['name'])
        
        with downloader.print_lock:
            print(f"\n{'='*60}")
            print(f"PROCESANDO TOMO {idx}/{total}: Tomo {tomo_number}")
            print(f"{'='*60}")
        
        result = downloader.download_volume(selected_volume, manga_title, output_dir)
        
        if result and result.get('dir'):
            return {
                'dir': result['dir'],
                'volume_name': selected_volume['name'],
                'tomo_number': tomo_number,
                'chapters': selected_volume['chapters'],
                'failed_chapters': result.get('failed_chapters', [])
            }
        return None
    
    try:
        if parallel_tomos > 1 and total_tomos > 1:
            print(f"\n[INFO] Descargando {total_tomos} tomos en paralelo (máximo {parallel_tomos} simultáneos)")
            print("[INFO] Presiona Ctrl+C para cancelar la descarga")
            with ThreadPoolExecutor(max_workers=parallel_tomos) as executor:
                futures = {executor.submit(download_single_tomo, volume_idx, idx+1, total_tomos): (volume_idx, idx+1) 
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
                            tomo_number = downloader.extract_tomo_number(volumes[volume_idx]['name'])
                            with downloader.print_lock:
                                print(f"\n[OK] Tomo {tomo_number} descargado: {os.path.basename(result['dir'])}")
                    except Exception as e:
                        tomo_number = downloader.extract_tomo_number(volumes[volume_idx]['name'])
                        with downloader.print_lock:
                            print(f"\n[ERROR] Error al descargar Tomo {tomo_number}: {e}")
                        downloaded_dirs.append({
                            'dir': None,
                            'volume_name': volumes[volume_idx]['name'],
                            'tomo_number': tomo_number,
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
                tomo_number = downloader.extract_tomo_number(selected_volume['name'])
                
                print(f"\n{'='*60}")
                print(f"PROCESANDO TOMO {idx}/{total_tomos}: Tomo {tomo_number}")
                print(f"{'='*60}")
                
                result = downloader.download_volume(selected_volume, manga_title, output_dir)
                
                if result and result.get('dir'):
                    downloaded_dirs.append({
                        'dir': result['dir'],
                        'volume_name': selected_volume['name'],
                        'tomo_number': tomo_number,
                        'chapters': selected_volume['chapters'],
                        'failed_chapters': result.get('failed_chapters', [])
                    })
                    print(f"\n[OK] Tomo {tomo_number} descargado: {os.path.basename(result['dir'])}")
                else:
                    print(f"\n[ERROR] No se pudieron descargar las imágenes para el Tomo {tomo_number}")
                
                if idx < total_tomos:
                    time.sleep(config['delay_between_volumes'])
    except KeyboardInterrupt:
        print("\n[INFO] Descarga cancelada por el usuario (Ctrl+C)")
        downloader.cancel()
    
    if downloaded_dirs:
        def get_tomo_sort_key(item):
            tomo_num = downloader.extract_tomo_number(item['volume_name'])
            try:
                return int(tomo_num)
            except:
                return 0
        
        sorted_dirs = sorted(downloaded_dirs, key=get_tomo_sort_key)
        
        all_failed_chapters = []
        for item in downloaded_dirs:
            if 'failed_chapters' in item:
                all_failed_chapters.extend(item['failed_chapters'])
        
        print(f"\n{'='*60}")
        print(f"¡DESCARGA COMPLETADA! ({len(downloaded_dirs)}/{total_tomos} tomos)")
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
                    tomo_num = int(failed['tomo_number'])
                except:
                    tomo_num = 0
                try:
                    chapter_num = float(downloader.extract_chapter_numbers(failed['chapter_name']))
                except:
                    chapter_num = 0.0
                return (tomo_num, chapter_num)
            
            sorted_failed = sorted(all_failed_chapters, key=get_failed_sort_key)
            
            print(f"\n{'='*60}")
            print("RESUMEN DE ERRORES")
            print(f"{'='*60}")
            for failed in sorted_failed:
                print(f"Tomo {failed['tomo_number']}, {failed['chapter_name']}: {failed['downloaded']}/{failed['total']}")
            print(f"{'='*60}\n")
        else:
            print("\n")
    else:
        print("\n[ERROR] No se pudieron descargar las imágenes")


if __name__ == '__main__':
    main()
