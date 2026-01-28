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
    
    metadata['_source_type'] = 'zonatmo'
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
    else:
        metadata_path = os.path.join(manga_dir, 'manga_metadata.json')
    
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    title_path = os.path.join(manga_dir, 'manga_title.txt')
    with open(title_path, 'w', encoding='utf-8') as f:
        f.write(manga_title)


class ZonaTMODownloader:
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
            driver.get(url)
            
            if not self._sleep_with_cancel(self.config.get('selenium_wait_time', 10)):
                if driver:
                    driver.quit()
                return None
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scrolls = 10
            
            while scroll_attempts < max_scrolls:
                if self.cancelled:
                    if driver:
                        driver.quit()
                    return None
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                
                if not self._sleep_with_cancel(2):
                    if driver:
                        driver.quit()
                    return None
                
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                scroll_attempts += 1
            
            if not self._sleep_with_cancel(2):
                if driver:
                    driver.quit()
                return None
            
            try:
                show_all_btn = driver.find_element(By.ID, "show-chapters")
                if show_all_btn:
                    print(f"[ZonaTMO] Botón 'Ver todo' encontrado, haciendo click...")
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", show_all_btn)
                    if not self._sleep_with_cancel(1):
                        if driver:
                            driver.quit()
                        return None
                    driver.execute_script("arguments[0].click();", show_all_btn)
                    if not self._sleep_with_cancel(2):
                        if driver:
                            driver.quit()
                        return None
            except Exception as e:
                print(f"[ZonaTMO] Botón 'Ver todo' no disponible o no necesario: {e}")
            
            try:
                show_all_result = driver.execute_script("""
                    if (typeof showAllChapters === 'function') {
                        showAllChapters();
                        return true;
                    }
                    return false;
                """)
                
                if show_all_result:
                    print(f"[ZonaTMO] Ejecutado showAllChapters()")
                    if not self._sleep_with_cancel(2):
                        if driver:
                            driver.quit()
                        return None
                
                result = driver.execute_script(r"""
                    var result = {clicked: 0, expanded: 0, total: 0};
                    
                    var collapsedDiv = document.getElementById('chapters-collapsed');
                    if (collapsedDiv) {
                        result.collapsedDivFound = true;
                        var style = window.getComputedStyle(collapsedDiv);
                        if (style.display === 'none') {
                            collapsedDiv.style.display = 'block';
                            result.collapsedExpanded = true;
                        }
                    }
                    
                    var collapseButtons = document.querySelectorAll('a.btn-collapse, a[class*="btn-collapse"]');
                    result.totalButtons = collapseButtons.length;
                    
                    for (var i = 0; i < collapseButtons.length; i++) {
                        var btn = collapseButtons[i];
                        var onclick = btn.getAttribute('onclick') || '';
                        if (onclick.indexOf('collapseChapter') !== -1) {
                            try {
                                var collapsibleId = onclick.match(/collapseChapter\('([^']+)'\)/);
                                if (collapsibleId) {
                                    var targetDiv = document.getElementById(collapsibleId[1]);
                                    if (targetDiv) {
                                        var style = window.getComputedStyle(targetDiv);
                                        if (style.display === 'none') {
                                            btn.click();
                                            result.clicked++;
                                        }
                                    }
                                }
                            } catch(e) {
                            }
                        }
                    }
                    
                    var collapsibleDivs = document.querySelectorAll('div[id^="collapsible"]');
                    result.total = collapsibleDivs.length;
                    for (var i = 0; i < collapsibleDivs.length; i++) {
                        var div = collapsibleDivs[i];
                        var style = window.getComputedStyle(div);
                        if (style.display === 'none') {
                            div.style.display = 'block';
                            div.setAttribute('style', 'display: block !important');
                            result.expanded++;
                        }
                    }
                    
                    return result;
                """)
                
                if result:
                    print(f"[ZonaTMO] Clicked en {result.get('clicked', 0)} botones de {result.get('totalButtons', 0)}")
                    print(f"[ZonaTMO] Expandidos manualmente {result.get('expanded', 0)} divs de {result.get('total', 0)} totales")
                
                if not self._sleep_with_cancel(2):
                    if driver:
                        driver.quit()
                    return None
                
                try:
                    chapters_element = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.ID, "chapters"))
                    )
                    print(f"[ZonaTMO] div#chapters encontrado después de expansión")
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'start'});", chapters_element)
                    if not self._sleep_with_cancel(2):
                        if driver:
                            driver.quit()
                        return None
                except Exception:
                    try:
                        chapters_element = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div.chapters, div[class*='chapters']"))
                        )
                        print(f"[ZonaTMO] div.chapters encontrado después de expansión (por CSS)")
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'start'});", chapters_element)
                        if not self._sleep_with_cancel(2):
                            if driver:
                                driver.quit()
                            return None
                    except Exception as e:
                        print(f"[ZonaTMO] No se encontró div#chapters después de expansión, intentando con JavaScript: {e}")
                        try:
                            driver.execute_script("""
                                var chaptersDiv = document.getElementById('chapters');
                                if (!chaptersDiv) {
                                    chaptersDiv = document.querySelector('div.chapters, div[class*="chapters"]');
                                }
                                if (chaptersDiv) {
                                    chaptersDiv.scrollIntoView({behavior: 'smooth', block: 'start'});
                                }
                            """)
                        except:
                            pass
                
                if not self._sleep_with_cancel(1):
                    if driver:
                        driver.quit()
                    return None
                
                last_count = 0
                for scroll_attempt in range(3):
                    chapters_check = driver.execute_script("""
                        var chaptersDiv = document.getElementById('chapters');
                        if (!chaptersDiv) return {found: false, count: 0};
                        
                        var listGroup = chaptersDiv.querySelector('ul.list-group, ul[class*="list-group"]');
                        var uploadLinks = [];
                        if (listGroup) {
                            uploadLinks = Array.from(listGroup.querySelectorAll('li.upload-link, li[class*="upload-link"]'));
                        }
                        
                        var collapsedDiv = document.getElementById('chapters-collapsed');
                        var collapsedLinks = [];
                        if (collapsedDiv) {
                            collapsedLinks = Array.from(collapsedDiv.querySelectorAll('li.upload-link, li[class*="upload-link"]'));
                        }
                        
                        return {
                            found: true, 
                            mainCount: uploadLinks.length,
                            collapsedCount: collapsedLinks.length,
                            total: uploadLinks.length + collapsedLinks.length
                        };
                    """)
                    
                    if chapters_check:
                        current_total = chapters_check.get('total', 0)
                        print(f"[ZonaTMO] Verificación {scroll_attempt + 1}: main={chapters_check.get('mainCount', 0)}, collapsed={chapters_check.get('collapsedCount', 0)}, total={current_total}")
                        
                        if current_total > 0 and current_total == last_count:
                            break
                        last_count = current_total
                    
                    if scroll_attempt < 2:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        if not self._sleep_with_cancel(1):
                            if driver:
                                driver.quit()
                            return None
                    
            except Exception as e:
                print(f"[ZonaTMO] Error al expandir capítulos: {e}")
            
            html_content = driver.page_source
            
            if driver:
                driver.quit()
            
            return html_content
        except Exception as e:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            return None

    def get_manga_title(self, html_content):
        soup = BeautifulSoup(html_content, 'lxml')
        
        h1_element_title = soup.find('h1', class_='element-title')
        if h1_element_title:
            title_text = h1_element_title.get_text(strip=True)
            if title_text:
                small_tag = h1_element_title.find('small')
                if small_tag:
                    title_text = title_text.replace(small_tag.get_text(strip=True), '').strip()
                return title_text
        
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title.get('content').strip()
        
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True)
        
        return "Manga"

    def get_manga_type(self, html_content):
        if '/manhwa/' in self.base_url.lower():
            return 'manhwa'
        if '/manga/' in self.base_url.lower():
            return 'manga'
        
        soup = BeautifulSoup(html_content, 'lxml')
        
        breadcrumb = soup.find('nav', class_='breadcrumb') or soup.find('ol', class_='breadcrumb')
        if breadcrumb:
            breadcrumb_text = breadcrumb.get_text().lower()
            if 'manhwa' in breadcrumb_text:
                return 'manhwa'
            if 'manga' in breadcrumb_text:
                return 'manga'
        
        return 'manga'

    def extract_chapter_numbers(self, text):
        if not text:
            return "0"
        m = re.search(r'(\d+(?:\.\d+)?)', text)
        if m:
            return m.group(1)
        m = re.search(r'/chapter[_-]?(\d+(?:\.\d+)?)/', text, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r'/capitulo[_-]?(\d+(?:\.\d+)?)/', text, re.IGNORECASE)
        if m:
            return m.group(1)
        return "0"

    def parse_volumes(self, html_content, debug=False):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        try:
            debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_zonatmo.html')
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(html_content or '')
        except Exception as e:
            pass
        
        print(f"[ZonaTMO] Iniciando parseo de capítulos...")
        print(f"[ZonaTMO] Tamaño del HTML: {len(html_content)} caracteres")
        
        if not html_content or len(html_content) < 100:
            print(f"[ZonaTMO ERROR] HTML vacío o muy corto")
            return {'volumes': [], 'common_scanlations': {}}
        
        soup = BeautifulSoup(html_content, 'lxml')
        
        chapters_container = soup.find('div', id='chapters')
        if not chapters_container:
            chapters_container = soup.find('div', class_=lambda x: x and ('chapters' in ' '.join(x) if isinstance(x, list) else 'chapters' in str(x)) if x else False)
        
        if not chapters_container:
            print(f"[ZonaTMO ERROR] No se encontró div#chapters")
            return {'volumes': [], 'common_scanlations': {}}
        
        print(f"[ZonaTMO] Contenedor div#chapters encontrado")
        
        all_upload_links = []
        
        def has_upload_link_class(classes):
            if not classes:
                return False
            if isinstance(classes, list):
                classes_str = ' '.join(classes)
            else:
                classes_str = str(classes)
            return 'upload-link' in classes_str
        
        def is_chapter_li(tag):
            if tag.name != 'li':
                return False
            classes = tag.get('class', [])
            classes_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
            has_upload_link = 'upload-link' in classes_str
            has_data_index = tag.get('data-index') is not None
            has_btn_collapse = tag.find('a', class_='btn-collapse') is not None
            return has_upload_link or (has_data_index and has_btn_collapse)
        
        list_group = chapters_container.find('ul', class_=lambda x: x and ('list-group' in (' '.join(x) if isinstance(x, list) else str(x))) if x else False)
        if list_group:
            upload_links = list_group.find_all(is_chapter_li)
            all_upload_links.extend(upload_links)
            print(f"[ZonaTMO] Encontrados {len(upload_links)} capítulos en ul principal dentro de div#chapters")
        
        if not all_upload_links:
            upload_links_direct = chapters_container.find_all(is_chapter_li)
            all_upload_links.extend(upload_links_direct)
            print(f"[ZonaTMO] Buscando directamente: encontrados {len(upload_links_direct)} capítulos en div#chapters")
        
        chapters_collapsed = soup.find('div', id='chapters-collapsed')
        if chapters_collapsed:
            collapsed_style = chapters_collapsed.get('style', '')
            collapsed_upload_links = chapters_collapsed.find_all(is_chapter_li)
            if collapsed_upload_links:
                all_upload_links.extend(collapsed_upload_links)
                print(f"[ZonaTMO] Encontrados {len(collapsed_upload_links)} capítulos adicionales en div#chapters-collapsed")
            else:
                print(f"[ZonaTMO] div#chapters-collapsed encontrado pero sin capítulos (style: {collapsed_style})")
        
        upload_links = all_upload_links
        print(f"[ZonaTMO] Total de capítulos encontrados: {len(upload_links)}")
        
        if len(upload_links) == 0:
            print(f"[ZonaTMO ERROR] No se encontraron capítulos. Buscando todos los li dentro del contenedor...")
            all_lis = chapters_container.find_all('li')
            print(f"[ZonaTMO] Total de <li> encontrados en div#chapters: {len(all_lis)}")
            for idx, li in enumerate(all_lis[:5]):
                classes = li.get('class', [])
                classes_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                btn_collapse = li.find('a', class_='btn-collapse')
                print(f"[ZonaTMO]   li[{idx}]: classes={classes_str}, data-index={li.get('data-index', 'N/A')}, tiene btn-collapse={btn_collapse is not None}")
            
            all_lis_with_btn = chapters_container.find_all('li')
            found_by_btn = []
            for li in all_lis_with_btn:
                if li.find('a', class_='btn-collapse'):
                    found_by_btn.append(li)
                    if len(found_by_btn) <= 3:
                        print(f"[ZonaTMO]   Capítulo encontrado por btn-collapse: {li.find('a', class_='btn-collapse').get_text(strip=True)[:50]}")
            
            if found_by_btn:
                upload_links = found_by_btn
                print(f"[ZonaTMO] Total encontrados por btn-collapse: {len(upload_links)}")
            else:
                print(f"[ZonaTMO] No se encontraron capítulos incluso buscando por btn-collapse")
                return {'volumes': [], 'common_scanlations': {}}
        
        chapters_by_number = {}
        processed_count = 0
        skipped_count = 0
        
        for idx, li in enumerate(upload_links[:10], 1):
            if self.cancelled:
                break
            
            chapter_link = li.find('a', class_='btn-collapse')
            if not chapter_link:
                skipped_count += 1
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] No se encontró a.btn-collapse")
                continue
            
            chapter_text = chapter_link.get_text(strip=True)
            if not chapter_text:
                skipped_count += 1
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] Texto vacío en a.btn-collapse")
                continue
            
            if idx <= 3:
                print(f"[ZonaTMO] [{idx}] Procesando: '{chapter_text}'")
            
            chapter_num_match = re.search(r'Capítulo\s*(\d+\.?\d*)', chapter_text, re.IGNORECASE)
            if not chapter_num_match:
                chapter_num_match = re.search(r'(\d+\.?\d*)', chapter_text)
            
            if chapter_num_match:
                try:
                    chapter_num = float(chapter_num_match.group(1))
                except:
                    chapter_num = 0.0
            else:
                skipped_count += 1
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] No se pudo extraer número del capítulo")
                continue
            
            chapter_name = f"Capítulo {chapter_num:g}" if chapter_num % 1 == 0 else f"Capítulo {chapter_num}"
            
            onclick_attr = chapter_link.get('onclick', '')
            collapsible_id = None
            if onclick_attr:
                match = re.search(r"collapseChapter\('([^']+)'\)", onclick_attr)
                if match:
                    collapsible_id = match.group(1)
            
            if not collapsible_id:
                collapsible_id = f"collapsible{chapter_num}"
            
            if idx <= 3:
                print(f"[ZonaTMO] [{idx}] Buscando collapsible_id: '{collapsible_id}' dentro del li")
            
            collapsible_div = li.find('div', id=collapsible_id)
            if not collapsible_div:
                all_divs_in_li = li.find_all('div', id=True)
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] No encontrado por id exacto. Divs con id en este li: {[d.get('id') for d in all_divs_in_li[:3]]}")
                collapsible_div = li.find('div', id=lambda x: x and 'collapsible' in str(x) if x else False)
            
            if not collapsible_div:
                skipped_count += 1
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] No se encontró div collapsible dentro del li")
                continue
            
            if idx <= 3:
                print(f"[ZonaTMO] [{idx}] ✓ Div collapsible encontrado: id='{collapsible_div.get('id')}', style='{collapsible_div.get('style', '')}'")
            
            chapter_list_element = collapsible_div.find('div', class_='chapter-list-element')
            if not chapter_list_element:
                chapter_list_element = collapsible_div.find('div', class_=lambda x: x and ('chapter-list-element' in ' '.join(x) if isinstance(x, list) else 'chapter-list-element' in str(x)) if x else False)
            
            if chapter_list_element:
                chapter_list_ul = chapter_list_element.find('ul', class_='chapter-list')
            else:
                chapter_list_ul = None
            
            if not chapter_list_ul:
                chapter_list_ul = collapsible_div.find('ul', class_='chapter-list')
            
            if not chapter_list_ul:
                chapter_list_ul = collapsible_div.find('ul', class_=lambda x: x and ('chapter-list' in ' '.join(x) if isinstance(x, list) else 'chapter-list' in str(x)) if x else False)
            
            if not chapter_list_ul:
                skipped_count += 1
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] No se encontró ul.chapter-list dentro del collapsible")
                    all_uls_in_collapsible = collapsible_div.find_all('ul')
                    print(f"[ZonaTMO] [{idx}]   Uls encontrados en collapsible: {len(all_uls_in_collapsible)}, classes: {[ul.get('class', []) for ul in all_uls_in_collapsible]}")
                continue
            
            scanlation_options = []
            scanlation_items = chapter_list_ul.find_all('li', class_='list-group-item')
            
            if idx <= 3:
                print(f"[ZonaTMO] [{idx}] Encontrados {len(scanlation_items)} items de scanlation")
            
            for item in scanlation_items:
                group_link = item.find('a', href=re.compile(r'/groups/\d+/'))
                if not group_link:
                    continue
                
                scanlation_name = group_link.get_text(strip=True)
                if not scanlation_name:
                    continue
                
                upload_link = item.find('a', href=re.compile(r'/view_uploads/\d+'))
                if not upload_link:
                    continue
                
                chapter_url = upload_link.get('href')
                if not chapter_url:
                    continue
                
                if not chapter_url.startswith('http'):
                    chapter_url = urljoin(self.base_url, chapter_url)
                
                scanlation_options.append({
                    'name': chapter_name,
                    'scanlation': scanlation_name,
                    'url': chapter_url,
                    'number': chapter_num
                })
            
            if not scanlation_options:
                skipped_count += 1
                if idx <= 3:
                    print(f"[ZonaTMO] [{idx}] No se encontraron opciones de scanlation válidas")
                continue
            
            processed_count += 1
            
            if idx <= 3:
                print(f"[ZonaTMO] [{idx}] ✓ Capítulo {chapter_num} procesado con {len(scanlation_options)} opciones")
            
            if chapter_num not in chapters_by_number:
                chapters_by_number[chapter_num] = []
            
            chapters_by_number[chapter_num].extend(scanlation_options)
        
        for idx, li in enumerate(upload_links[10:], 11):
            if self.cancelled:
                break
            
            chapter_link = li.find('a', class_='btn-collapse')
            if not chapter_link:
                skipped_count += 1
                continue
            
            chapter_text = chapter_link.get_text(strip=True)
            if not chapter_text:
                skipped_count += 1
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
                skipped_count += 1
                continue
            
            chapter_name = f"Capítulo {chapter_num:g}" if chapter_num % 1 == 0 else f"Capítulo {chapter_num}"
            
            onclick_attr = chapter_link.get('onclick', '')
            collapsible_id = None
            if onclick_attr:
                match = re.search(r"collapseChapter\('([^']+)'\)", onclick_attr)
                if match:
                    collapsible_id = match.group(1)
            
            if not collapsible_id:
                collapsible_id = f"collapsible{chapter_num}"
            
            collapsible_div = li.find('div', id=collapsible_id)
            if not collapsible_div:
                collapsible_div = li.find('div', id=lambda x: x and 'collapsible' in str(x) if x else False)
            
            if not collapsible_div:
                skipped_count += 1
                continue
            
            chapter_list_element = collapsible_div.find('div', class_='chapter-list-element')
            if not chapter_list_element:
                chapter_list_element = collapsible_div.find('div', class_=lambda x: x and ('chapter-list-element' in ' '.join(x) if isinstance(x, list) else 'chapter-list-element' in str(x)) if x else False)
            
            if chapter_list_element:
                chapter_list_ul = chapter_list_element.find('ul', class_='chapter-list')
            else:
                chapter_list_ul = None
            
            if not chapter_list_ul:
                chapter_list_ul = collapsible_div.find('ul', class_='chapter-list')
            
            if not chapter_list_ul:
                chapter_list_ul = collapsible_div.find('ul', class_=lambda x: x and ('chapter-list' in ' '.join(x) if isinstance(x, list) else 'chapter-list' in str(x)) if x else False)
            
            if not chapter_list_ul:
                skipped_count += 1
                continue
            
            scanlation_options = []
            scanlation_items = chapter_list_ul.find_all('li', class_='list-group-item')
            
            for item in scanlation_items:
                group_link = item.find('a', href=re.compile(r'/groups/\d+/'))
                if not group_link:
                    continue
                
                scanlation_name = group_link.get_text(strip=True)
                if not scanlation_name:
                    continue
                
                upload_link = item.find('a', href=re.compile(r'/view_uploads/\d+'))
                if not upload_link:
                    continue
                
                chapter_url = upload_link.get('href')
                if not chapter_url:
                    continue
                
                if not chapter_url.startswith('http'):
                    chapter_url = urljoin(self.base_url, chapter_url)
                
                scanlation_options.append({
                    'name': chapter_name,
                    'scanlation': scanlation_name,
                    'url': chapter_url,
                    'number': chapter_num
                })
            
            if not scanlation_options:
                skipped_count += 1
                continue
            
            processed_count += 1
            
            if chapter_num not in chapters_by_number:
                chapters_by_number[chapter_num] = []
            
            chapters_by_number[chapter_num].extend(scanlation_options)
        
        print(f"[ZonaTMO] Procesados: {processed_count}, omitidos: {skipped_count}")
        print(f"[ZonaTMO] Capítulos únicos encontrados: {len(chapters_by_number)}")
        
        if chapters_by_number:
            sorted_sample = sorted(chapters_by_number.keys(), reverse=False)[:3]
            for chapter_num in sorted_sample:
                options = chapters_by_number[chapter_num]
                scanlations = [opt['scanlation'] for opt in options]
                print(f"[ZonaTMO] Capítulo {chapter_num:g}: {len(options)} opción(es) - {', '.join(scanlations[:3])}")
        
        all_scanlations = set()
        for chapter_num, options in chapters_by_number.items():
            for option in options:
                all_scanlations.add(option['scanlation'])
        
        print(f"[ZonaTMO] Scanlations únicos: {len(all_scanlations)}")
        
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
        
        print(f"[ZonaTMO] Generando {len(sorted_numbers)} volúmenes...")
        
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
        
        try:
            debug_links_file = os.path.join(script_dir, 'resources', 'debug', 'debug_links_zonatmo.json')
            with open(debug_links_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'total_upload_links': len(upload_links),
                    'processed_chapters': processed_count,
                    'skipped_count': skipped_count,
                    'final_chapters_count': len(chapters_by_number),
                    'all_scanlations': sorted(list(all_scanlations)),
                    'common_scanlations': common_scanlations,
                    'chapters_by_number': {str(k): [{'scanlation': opt['scanlation'], 'url': opt['url']} for opt in v] for k, v in list(chapters_by_number.items())[:20]}
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ZonaTMO ERROR] No se pudo guardar debug JSON: {e}")
        
        volumes_with_options = [v for v in volumes if v.get('options')]
        print(f"[ZonaTMO] ✓ Procesamiento completado: {len(volumes)} volúmenes ({len(volumes_with_options)} con opciones)")
        
        result = {
            'volumes': volumes,
            'common_scanlations': common_scanlations
        }
        
        return result

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
        current_url = chapter_url
        
        try:
            print(f"[ZonaTMO] URL original del capítulo: {chapter_url}")
            
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            driver = webdriver.Chrome(options=options)
            
            print(f"[ZonaTMO] Accediendo a URL con Selenium: {chapter_url}")
            driver.get(chapter_url)
            
            if not self._sleep_with_cancel(2):
                if driver:
                    driver.quit()
                return ([], 0, 0, [], 0)
            
            try:
                print(f"[ZonaTMO] Esperando a que la URL contenga '/viewer/' (timeout: 10s)...")
                WebDriverWait(driver, 10).until(EC.url_contains("/viewer/"))
                final_url = driver.current_url
                print(f"[ZonaTMO] ✓ Redirección 302 detectada y confirmada:")
                print(f"[ZonaTMO]   URL original: {chapter_url}")
                print(f"[ZonaTMO]   URL final: {final_url}")
                current_url = final_url
            except Exception as e:
                selenium_url = driver.current_url
                print(f"[ZonaTMO] No se detectó URL con '/viewer/' después de 10s")
                print(f"[ZonaTMO] URL actual en navegador: {selenium_url}")
                
                if selenium_url != chapter_url:
                    print(f"[ZonaTMO] ✓ URL cambió (redirección detectada):")
                    print(f"[ZonaTMO]   URL original: {chapter_url}")
                    print(f"[ZonaTMO]   URL final: {selenium_url}")
                    current_url = selenium_url
                else:
                    print(f"[ZonaTMO] URL no cambió, usando URL original")
                    current_url = chapter_url
                    
                    try:
                        print(f"[ZonaTMO] Intentando obtener header Location con requests...")
                        response_no_redirect = self.session.get(chapter_url, allow_redirects=False, timeout=self.config['timeout'])
                        
                        if response_no_redirect.status_code in [301, 302, 303, 307, 308]:
                            location = response_no_redirect.headers.get('Location', '')
                            if location:
                                if location.startswith('/'):
                                    current_url = urljoin(chapter_url, location)
                                elif location.startswith('http'):
                                    current_url = location
                                else:
                                    current_url = urljoin(chapter_url, '/' + location.lstrip('/'))
                                print(f"[ZonaTMO] ✓ Redirección 302 detectada en header Location: {current_url}")
                                driver.get(current_url)
                                if not self._sleep_with_cancel(2):
                                    if driver:
                                        driver.quit()
                                    return ([], 0, 0, [], 0)
                    except Exception as req_e:
                        print(f"[ZonaTMO] Error al intentar obtener Location header: {req_e}")
            
            page_title = driver.title
            print(f"[ZonaTMO] Título de la página: {page_title}")
            print(f"[ZonaTMO] URL final después de redirección: {driver.current_url}")
            
            if not self._sleep_with_cancel(2):
                if driver:
                    driver.quit()
                return ([], 0, 0, [], 0)
            
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "img"))
                )
                print(f"[ZonaTMO] Imágenes encontradas en la página")
            except Exception as e:
                print(f"[ZonaTMO] Advertencia: No se encontraron imágenes inmediatamente: {e}")
            
            if not self._sleep_with_cancel(self.config.get('selenium_extra_wait', 5)):
                if driver:
                    driver.quit()
                return ([], 0, 0, [], 0)
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scrolls = 10
            
            while scroll_attempts < max_scrolls:
                if self.cancelled:
                    if driver:
                        driver.quit()
                    return ([], 0, 0, [], 0)
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                
                if not self._sleep_with_cancel(2):
                    if driver:
                        driver.quit()
                    return ([], 0, 0, [], 0)
                
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                scroll_attempts += 1
            
            driver.execute_script("window.scrollTo(0, 0);")
            if not self._sleep_with_cancel(1):
                if driver:
                    driver.quit()
                return ([], 0, 0, [], 0)
            
            html_content = driver.page_source
            
            js_images = driver.execute_script("""
                var images = [];
                var readerArea = document.querySelector('.reading-content, .reader-area, #readerarea, .chapter-content, .manga-reader, .viewer-content, [class*="viewer"], [class*="reader"]');
                if (!readerArea) {
                    readerArea = document.body;
                }
                var imgs = readerArea.getElementsByTagName('img');
                for (var i = 0; i < imgs.length; i++) {
                    var src = imgs[i].src || imgs[i].getAttribute('data-src') || imgs[i].getAttribute('data-lazy-src') || imgs[i].getAttribute('data-original') || imgs[i].getAttribute('data-url') || imgs[i].getAttribute('data-srcset');
                    if (src && src.trim() && !src.includes('logo') && !src.includes('avatar') && !src.includes('icon') && !src.includes('banner')) {
                        if (src.startsWith('//')) {
                            src = 'https:' + src;
                        }
                        if (!src.startsWith('http')) {
                            src = window.location.origin + src;
                        }
                        if (images.indexOf(src) === -1 && (src.includes('jpg') || src.includes('jpeg') || src.includes('png') || src.includes('webp') || src.includes('image'))) {
                            images.push(src);
                        }
                    }
                }
                return images;
            """)
            
            if js_images:
                for img_url in js_images:
                    if img_url and img_url not in images:
                        images.append(img_url)
            
            if not images:
                soup = BeautifulSoup(html_content, 'lxml')
                reader_area = soup.find('div', class_=['reading-content', 'reader-area']) or soup.find('div', id='readerarea') or soup.find('div', class_='chapter-content') or soup.find('div', class_='viewer-content') or soup.find('div', class_=lambda x: x and ('viewer' in (' '.join(x) if isinstance(x, list) else str(x))) if x else False)
                
                if reader_area:
                    img_tags = reader_area.find_all('img')
                else:
                    img_tags = soup.find_all('img')
                
                for img_tag in img_tags:
                    img_url = img_tag.get('src', '') or img_tag.get('data-src', '') or img_tag.get('data-lazy-src', '') or img_tag.get('data-original', '') or img_tag.get('data-url', '') or img_tag.get('data-srcset', '')
                    if img_url and 'logo' not in img_url.lower() and 'avatar' not in img_url.lower() and 'icon' not in img_url.lower() and 'banner' not in img_url.lower():
                        if not img_url.startswith('http'):
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            else:
                                img_url = urljoin(current_url, img_url)
                        if img_url not in images and ('.jpg' in img_url.lower() or '.jpeg' in img_url.lower() or '.png' in img_url.lower() or '.webp' in img_url.lower() or '/image' in img_url.lower()):
                            images.append(img_url)
        
        except Exception as e:
            import traceback
            print(f"[ZonaTMO ERROR] Error al descargar imágenes del capítulo: {e}")
            print(f"[ZonaTMO ERROR] Traceback: {traceback.format_exc()}")
            return ([], 0, 0, [{'url': chapter_url, 'error': f"Error al obtener HTML: {str(e)}", 'index': -1}], 0)
        finally:
            if driver:
                driver.quit()
        
        if not images:
            print(f"[ZonaTMO] No se encontraron imágenes en: {chapter_url}")
            return ([], 0, 0, [{'url': chapter_url, 'error': "No se encontraron imágenes", 'index': -1}], 0)
        
        print(f"[ZonaTMO] Encontradas {len(images)} imágenes para {chapter_name}")
        
        safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter_name)
        output_basename = os.path.basename(output_dir)
        safe_output_basename = re.sub(r'[<>:"/\\|?*]', '_', output_basename)
        
        if safe_output_basename == safe_chapter_name or output_basename.startswith('Tomo '):
            chapter_dir = output_dir
        else:
            chapter_dir = os.path.join(output_dir, safe_chapter_name)
            os.makedirs(chapter_dir, exist_ok=True)
        
        output_dir_abs = os.path.abspath(chapter_dir)
        
        downloaded_files = []
        failed_downloads = []
        
        def prepare_download(img_url, index):
            if self.cancelled:
                return None
            
            url_ext = os.path.splitext(urlparse(img_url).path)[1].lower() or '.jpg'
            if url_ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                url_ext = '.jpg'
            
            original_filename = f"img_{index:04d}{url_ext}"
            if url_ext == '.webp':
                original_filename = f"img_{index:04d}-webp{url_ext}"
            
            filepath = os.path.join(output_dir_abs, original_filename)
            
            if os.path.exists(filepath) and not self.config.get('force_redownload', False):
                if url_ext == '.webp':
                    jpg_path = filepath.replace('-webp.webp', '.jpg').replace('.webp', '.jpg')
                    if os.path.exists(jpg_path):
                        return None
            
            return (img_url, filepath, index)
        
        download_tasks = []
        for idx, img_url in enumerate(images, start=1):
            if self.cancelled:
                break
            task = prepare_download(img_url, idx)
            if task:
                download_tasks.append(task)
        
        if not download_tasks:
            existing_files = [f for f in os.listdir(output_dir_abs) if os.path.isfile(os.path.join(output_dir_abs, f)) and f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
            if existing_files:
                return (existing_files, len(existing_files), sum(os.path.getsize(os.path.join(output_dir_abs, f)) for f in existing_files), [], len(existing_files))
            return ([], 0, 0, [], 0)
        
        with ThreadPoolExecutor(max_workers=self.config.get('parallel_images', 8)) as executor:
            futures = {executor.submit(self.download_image_with_semaphore, img_url, filepath, idx, len(download_tasks), referer_url=current_url): (img_url, filepath, idx) for img_url, filepath, idx in download_tasks}
            
            for future in as_completed(futures):
                if self.cancelled:
                    break
                
                img_url, filepath, idx = futures[future]
                try:
                    result_index, success, file_size, returned_filepath = future.result()
                    if success and returned_filepath:
                        downloaded_files.append(returned_filepath)
                    else:
                        failed_downloads.append({'url': img_url, 'error': 'Falló la descarga', 'index': idx})
                except Exception as e:
                    failed_downloads.append({'url': img_url, 'error': str(e), 'index': idx})
        
        downloaded_files.sort()
        
        for idx, old_path in enumerate(downloaded_files, start=1):
            if self.cancelled:
                break
            
            ext = os.path.splitext(old_path)[1].lower()
            if ext == '.webp':
                ext = '.jpg'
            
            new_name = f"{idx:03d}{ext}"
            new_path = os.path.join(output_dir_abs, new_name)
            
            if old_path != new_path:
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(old_path, new_path)
                except Exception as e:
                    pass
        
        final_files = [f for f in os.listdir(output_dir_abs) if os.path.isfile(os.path.join(output_dir_abs, f)) and f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        final_files.sort()
        
        total_size = sum(os.path.getsize(os.path.join(output_dir_abs, f)) for f in final_files)
        
        return (final_files, len(final_files), total_size, failed_downloads, len(images))

    def sort_chapters_by_number(self, chapters):
        return sorted(chapters, key=lambda x: float(self.extract_chapter_numbers(x.get('name', x.get('url', '0')))))

    def check_volume_complete(self, volume_dir):
        if not os.path.exists(volume_dir):
            return False
        
        image_files = [f for f in os.listdir(volume_dir) if os.path.isfile(os.path.join(volume_dir, f)) and f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        return len(image_files) > 0

    def download_volume(self, volume_data, manga_title, output_dir='downloads', selected_option=None, is_tomo_structure=False):
        if self.cancelled:
            return {'dir': None, 'failed_chapters': []}
        
        volume_name = volume_data['name']
        chapters = volume_data.get('chapters', [])
        
        if not chapters:
            return {'dir': None, 'failed_chapters': []}
        
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
        
        all_images = []
        chapter_stats = []
        failed_chapters = []
        
        parallel_chapters = self.config.get('parallel_chapters', 1)
        
        def download_single_chapter(chapter, idx, total):
            if self.cancelled:
                return ({'name': chapter['name'], 'total_found': 0, 'total_downloaded': 0, 'failed': 0, 'skipped': 0}, [])
            try:
                if not chapter.get('url'):
                    return ({'name': chapter.get('name', 'Desconocido'), 'total_found': 0, 'total_downloaded': 0, 'failed': 0, 'skipped': 0}, [])
                
                chapter_dir = volume_dir
                if is_tomo_structure:
                    safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter['name'])
                    chapter_dir = os.path.join(volume_dir, safe_chapter_name)
                    os.makedirs(chapter_dir, exist_ok=True)
                
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
                
                return (stat, images)
            except Exception as e:
                return ({'name': chapter.get('name', 'Desconocido'), 'total_found': 0, 'total_downloaded': 0, 'failed': 1, 'skipped': 0}, [])
        
        if parallel_chapters > 1 and len(chapters) > 1:
            with ThreadPoolExecutor(max_workers=parallel_chapters) as executor:
                futures = {executor.submit(download_single_chapter, chapter, idx, len(chapters)): (idx, chapter) for idx, chapter in enumerate(chapters, start=1)}
                
                for future in as_completed(futures):
                    if self.cancelled:
                        break
                    
                    idx, chapter = futures[future]
                    try:
                        stat, images = future.result()
                        chapter_stats.append(stat)
                        all_images.extend(images)
                    except Exception as e:
                        chapter_stats.append({'name': chapter.get('name', 'Desconocido'), 'total_found': 0, 'total_downloaded': 0, 'failed': 1, 'skipped': 0})
        else:
            for idx, chapter in enumerate(chapters, start=1):
                if self.cancelled:
                    break
                stat, images = download_single_chapter(chapter, idx, len(chapters))
                chapter_stats.append(stat)
                all_images.extend(images)
        
        for stat in chapter_stats:
            total_found = stat.get('total_found', 0)
            total_downloaded = stat.get('total_downloaded', 0)
            
            if total_downloaded < total_found:
                failed_chapter_data = {
                    'chapter_name': stat['name'],
                    'downloaded': total_downloaded,
                    'total': total_found
                }
                if is_tomo_structure:
                    tomo_number_match = re.search(r'Tomo\s+(\d+)', volume_name)
                    if tomo_number_match:
                        failed_chapter_data['tomo_number'] = int(tomo_number_match.group(1))
                failed_chapters.append(failed_chapter_data)
        
        return {
            'dir': volume_dir,
            'failed_chapters': failed_chapters
        }


def main():
    config = load_config()
    
    url = input("URL de la serie: ").strip()
    
    if not url:
        print("URL no proporcionada")
        return
    
    downloader = ZonaTMODownloader(url, config)
    
    print("Obteniendo información de la serie...")
    html_content = downloader.get_page_selenium(url)
    
    if not html_content:
        print("Error al obtener el contenido de la página")
        return
    
    manga_title = downloader.get_manga_title(html_content)
    manga_type = downloader.get_manga_type(html_content)
    
    print(f"Título: {manga_title}")
    print(f"Tipo: {manga_type}")
    
    parse_result = downloader.parse_volumes(html_content, debug=True)
    
    if not parse_result or 'volumes' not in parse_result or not parse_result['volumes']:
        print("No se encontraron capítulos")
        return
    
    volumes = parse_result['volumes']
    print(f"\nSe encontraron {len(volumes)} capítulos")
    
    output_dir = config.get('output_dir', 'downloads')
    
    for volume in volumes:
        print(f"\nDescargando: {volume['name']}")
        result = downloader.download_volume(volume, manga_title, output_dir)
        
        if result and result.get('success'):
            print(f"  ✓ Descargado correctamente")
        else:
            print(f"  ✗ Error en la descarga")


if __name__ == '__main__':
    main()
