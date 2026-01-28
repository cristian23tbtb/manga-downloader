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
from threading import Lock

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import NoSuchWindowException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    NoSuchWindowException = Exception


def load_config():
    config_path = 'config.json'
    default_config = {
        "timeout": 60,
        "retry_attempts": 5,
        "retry_delay": 2,
        "delay_between_chapters": 2,
        "delay_between_volumes": 3,
        "output_dir": "downloads",
        "selenium_wait_time": 30,
        "selenium_extra_wait": 3,
        "parallel_tomos": 1,
        "parallel_chapters": 1,
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
    metadata['_source_type'] = 'tomosmanga'
    for volume in volumes:
        if 'chapters' in volume:
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
        else:
            volume_data = {
                'name': volume['name'],
                'tomo_number': re.search(r'(\d+)', volume['name']).group(1) if re.search(r'(\d+)', volume['name']) else "1",
                'chapters': [{
                    'name': volume['name'],
                    'url': volume.get('url', '')
                }]
            }
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


class TomosMangaDownloader:
    def __init__(self, base_url, config):
        self.base_url = base_url
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.cancelled = False
        self.print_lock = Lock()
        
        self.callbacks = {
            'on_fireload_progress': None,
            'on_download_start': None,
            'on_download_progress': None,
            'on_download_complete': None
        }

    def set_callback(self, name, callback):
        if name in self.callbacks:
            self.callbacks[name] = callback
    
    def cancel(self):
        self.cancelled = True

    def get_page(self, url, use_selenium=False):
        print(f"[TomosManga] Obteniendo página: {url}")
        print(f"[TomosManga] Usando Selenium: {use_selenium}")
        
        if use_selenium and SELENIUM_AVAILABLE:
            html = self.get_page_selenium(url)
            if html:
                try:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_tomosmanga.html')
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(html)
                    print(f"[TomosManga] HTML guardado en: {debug_file}")
                except Exception as e:
                    print(f"[TomosManga] Error al guardar HTML de debug: {e}")
            return html
        
        try:
            print(f"[TomosManga] Usando requests para obtener página")
            response = self.session.get(url, timeout=self.config['timeout'])
            response.raise_for_status()
            html = response.text
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_tomosmanga.html')
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"[TomosManga] HTML guardado en: {debug_file}")
            except Exception as e:
                print(f"[TomosManga] Error al guardar HTML de debug: {e}")
            return html
        except requests.RequestException as e:
            print(f"[TomosManga ERROR] Error al obtener página: {e}")
            return None

    def get_page_selenium(self, url):
        if not SELENIUM_AVAILABLE:
            print(f"[TomosManga ERROR] Selenium no está disponible")
            return None
        if self.cancelled:
            print(f"[TomosManga] Operación cancelada")
            return None
        
        print(f"[TomosManga] Inicializando Selenium...")
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        prefs = {
            'profile.default_content_setting_values': {
                'notifications': 2,
                'geolocation': 2,
            },
            'profile.managed_default_content_settings': {
                'images': 1,
            }
        }
        options.add_experimental_option('prefs', prefs)
        
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = None
        try:
            print(f"[TomosManga] Creando instancia de Brave WebDriver...")
            brave_paths = [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                os.path.expanduser(r"~\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe")
            ]
            
            brave_path = None
            for path in brave_paths:
                if os.path.exists(path):
                    brave_path = path
                    break
            
            if brave_path:
                options.binary_location = brave_path
                print(f"[TomosManga] Usando Brave en: {brave_path}")
            else:
                print(f"[TomosManga] Brave no encontrado en rutas comunes, usando Chrome por defecto")
            
            driver = webdriver.Chrome(options=options)
            print(f"[TomosManga] Navegando a: {url}")
            driver.get(url)
            wait_time = self.config.get('selenium_extra_wait', 3)
            print(f"[TomosManga] Esperando {wait_time} segundos para que cargue la página...")
            time.sleep(wait_time)
            html = driver.page_source
            print(f"[TomosManga] Página cargada, HTML obtenido ({len(html)} caracteres)")
            return html
        except Exception as e:
            print(f"[TomosManga ERROR] Error con Selenium: {e}")
            import traceback
            print(f"[TomosManga ERROR] Traceback: {traceback.format_exc()}")
            return None
        finally:
            if driver:
                print(f"[TomosManga] Cerrando navegador...")
                driver.quit()

    def bypass_ouo_io(self, ouo_url, max_retries=3):
        if not SELENIUM_AVAILABLE:
            print("[TomosManga ERROR] Selenium no está disponible para bypass de ouo.io")
            return None
        
        if self.cancelled:
            print("[TomosManga] Operación cancelada antes de bypass de ouo.io")
            return None
        
        is_shared = False
        
        for attempt in range(1, max_retries + 1):
            print(f"[TomosManga] Iniciando bypass de ouo.io (Intento {attempt}/{max_retries})")
            print(f"[TomosManga] URL de ouo.io: {ouo_url}")
            
            result = self._attempt_bypass_ouo_io(ouo_url, is_shared)
            
            if result is None:
                if attempt < max_retries:
                    print(f"[TomosManga] Bypass falló, reintentando en 3 segundos...")
                    time.sleep(3)
                    continue
                else:
                    print(f"[TomosManga ERROR] Bypass falló después de {max_retries} intentos")
                    return None
            
            if isinstance(result, dict):
                if 'fireload_url' in result:
                    return result
                elif 'url' in result:
                    if self.is_ad_url(result['url']):
                        print(f"[TomosManga ADVERTENCIA] URL detectada como publicidad: {result['url'][:100]}...")
                        if attempt < max_retries:
                            print(f"[TomosManga] Reintentando bypass debido a redirección a publicidad...")
                            time.sleep(3)
                            continue
                        else:
                            print(f"[TomosManga ERROR] Bypass redirigió a publicidad después de {max_retries} intentos")
                            return None
                    else:
                        return result
            
            return result
        
        return None
    
    def _attempt_bypass_ouo_io(self, ouo_url, is_shared):
        
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        prefs = {
            'profile.default_content_setting_values': {
                'notifications': 2,
                'geolocation': 2,
            },
            'profile.managed_default_content_settings': {
                'images': 1,
            },
            'brave.shields.enabled': True,
            'brave.shields.blocked_ads': True,
            'brave.shields.blocked_trackers': True,
            'brave.shields.blocked_scripts': True,
            'brave.shields.blocked_fingerprinting': True,
            'brave.shields.blocked_cookies': True
        }
        options.add_experimental_option('prefs', prefs)
        
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = None
        try:
            print(f"[TomosManga] Inicializando navegador Brave para bypass...")
            brave_paths = [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                os.path.expanduser(r"~\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe")
            ]
            
            brave_path = None
            for path in brave_paths:
                if os.path.exists(path):
                    brave_path = path
                    break
            
            if brave_path:
                options.binary_location = brave_path
                print(f"[TomosManga] Usando Brave en: {brave_path}")
            else:
                print(f"[TomosManga] Brave no encontrado en rutas comunes, usando Chrome por defecto")
            
            driver = webdriver.Chrome(options=options)
            
            if self.cancelled:
                if driver:
                    driver.quit()
                return None
            
            print(f"[TomosManga] Navegando a ouo.io: {ouo_url}")
            driver.get(ouo_url)
            
            if self.cancelled:
                if driver:
                    driver.quit()
                return None
            
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_ouo_io.html')
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                print(f"[TomosManga] HTML de ouo.io guardado en: {debug_file}")
            except Exception as e:
                print(f"[TomosManga] Error al guardar HTML de ouo.io: {e}")
            
            wait = WebDriverWait(driver, self.config.get('selenium_wait_time', 30))
            
            print(f"[TomosManga] Esperando a que la página cargue completamente...")
            time.sleep(2)
            
            original_window = driver.current_window_handle
            print(f"[TomosManga] Ventana original: {original_window}")
            all_windows = [original_window]
            
            try:
                print(f"[TomosManga] Buscando botón 'I'm human' (esperando hasta que esté disponible)...")
                im_human_button = wait.until(
                    EC.presence_of_element_located((By.ID, "btn-main"))
                )
                print(f"[TomosManga] Botón 'I'm human' encontrado (id: btn-main)")
                
                try:
                    print(f"[TomosManga] Intentando hacer clic normal...")
                    im_human_button.click()
                    print(f"[TomosManga] ✓ Botón 'I'm human' presionado (clic normal)")
                except Exception as click_error:
                    print(f"[TomosManga] Clic normal falló: {click_error}")
                    print(f"[TomosManga] Intentando hacer clic con JavaScript...")
                    try:
                        driver.execute_script("arguments[0].click();", im_human_button)
                        print(f"[TomosManga] ✓ Botón 'I'm human' presionado (JavaScript)")
                    except Exception as js_error:
                        print(f"[TomosManga] Clic con JavaScript falló: {js_error}")
                        print(f"[TomosManga] Intentando hacer clic en las coordenadas del botón...")
                        try:
                            actions = ActionChains(driver)
                            actions.move_to_element(im_human_button).click().perform()
                            print(f"[TomosManga] ✓ Botón 'I'm human' presionado (ActionChains)")
                        except Exception as ac_error:
                            print(f"[TomosManga] ActionChains falló: {ac_error}")
                            print(f"[TomosManga] Intentando hacer scroll y clic...")
                            try:
                                driver.execute_script("arguments[0].scrollIntoView(true);", im_human_button)
                                time.sleep(0.5)
                                driver.execute_script("arguments[0].click();", im_human_button)
                                print(f"[TomosManga] ✓ Botón 'I'm human' presionado (scroll + JavaScript)")
                            except Exception as scroll_error:
                                print(f"[TomosManga ERROR] Todos los métodos de clic fallaron: {scroll_error}")
                                raise
                
                print(f"[TomosManga] Esperando 5 segundos después de hacer clic en 'I'm human'...")
                time.sleep(5)
                
                if self.cancelled:
                    if driver:
                        driver.quit()
                    return None
            except Exception as e:
                print(f"[TomosManga ADVERTENCIA] No se encontró botón 'I'm human' por ID, intentando con XPath...")
                try:
                    im_human_button = wait.until(
                        EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'I') and contains(text(), 'human')] | //button[contains(text(), 'Soy') and contains(text(), 'humano')] | //button[@id='btn-main'] | //button[@class='btn btn-main']"))
                    )
                    print(f"[TomosManga] Botón 'I'm human' encontrado por XPath")
                    
                    try:
                        im_human_button.click()
                        print(f"[TomosManga] ✓ Botón 'I'm human' presionado (clic normal)")
                    except Exception as click_error:
                        print(f"[TomosManga] Clic normal falló, usando JavaScript...")
                        driver.execute_script("arguments[0].click();", im_human_button)
                        print(f"[TomosManga] ✓ Botón 'I'm human' presionado (JavaScript)")
                    
                    print(f"[TomosManga] Esperando 5 segundos después de hacer clic en 'I'm human'...")
                    time.sleep(5)
                    
                    if self.cancelled:
                        if driver:
                            driver.quit()
                        return None
                except Exception as e2:
                    print(f"[TomosManga ERROR] No se pudo encontrar el botón 'I'm human': {e2}")
                    current_url_check = driver.current_url
                    if self.is_ad_url(current_url_check):
                        print(f"[TomosManga ADVERTENCIA] Redirigido a publicidad sin botón: {current_url_check[:100]}...")
                        if driver:
                            driver.quit()
                        return None
            
            self._close_non_ouo_windows(driver, original_window)
            
            try:
                print(f"[TomosManga] Buscando botón 'Get Link' (esperando hasta que esté disponible)...")
                get_link_button = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Get Link')] | //button[contains(text(), 'Obtener')] | //a[contains(text(), 'Get Link')] | //a[contains(text(), 'Obtener')] | //button[@id='recaptcha']"))
                )
                print(f"[TomosManga] Botón 'Get Link' encontrado")
                
                try:
                    print(f"[TomosManga] Intentando hacer clic normal...")
                    get_link_button.click()
                    print(f"[TomosManga] ✓ Botón 'Get Link' presionado (clic normal)")
                except Exception as click_error:
                    print(f"[TomosManga] Clic normal falló: {click_error}")
                    print(f"[TomosManga] Intentando hacer clic con JavaScript...")
                    try:
                        driver.execute_script("arguments[0].click();", get_link_button)
                        print(f"[TomosManga] ✓ Botón 'Get Link' presionado (JavaScript)")
                    except Exception as js_error:
                        print(f"[TomosManga] Clic con JavaScript falló: {js_error}")
                        print(f"[TomosManga] Intentando hacer clic en las coordenadas del botón...")
                        actions = ActionChains(driver)
                        actions.move_to_element(get_link_button).click().perform()
                        print(f"[TomosManga] ✓ Botón 'Get Link' presionado (ActionChains)")
                
                print(f"[TomosManga] Esperando 5 segundos después de hacer clic en 'Get Link'...")
                time.sleep(5)
                
                if self.cancelled:
                    if driver:
                        driver.quit()
                    return None
            except Exception as e:
                print(f"[TomosManga ADVERTENCIA] No se encontró botón 'Get Link': {e}")
                # Verificar si la URL cambió a publicidad
                current_url_check = driver.current_url
                if self.is_ad_url(current_url_check):
                    print(f"[TomosManga ADVERTENCIA] Redirigido a publicidad sin botón 'Get Link': {current_url_check[:100]}...")
                    if driver:
                        driver.quit()
                    return None
            
            print(f"[TomosManga] Verificando si se abrió otra nueva ventana después de 'Get Link'...")
            try:
                if original_window in driver.window_handles:
                    driver.switch_to.window(original_window)
                elif driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                    original_window = driver.current_window_handle
                all_windows_after = driver.window_handles
            except NoSuchWindowException:
                if driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                    original_window = driver.current_window_handle
                    all_windows_after = driver.window_handles
                else:
                    print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                    if driver:
                        driver.quit()
                    return None
            
            if len(all_windows_after) > len(all_windows):
                self._close_non_ouo_windows(driver, original_window)
            
            try:
                final_url = driver.current_url
            except NoSuchWindowException:
                if driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                    original_window = driver.current_window_handle
                    final_url = driver.current_url
                else:
                    print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                    if driver:
                        driver.quit()
                    return None
            print(f"[TomosManga] URL después del bypass: {final_url}")
            
            if self.is_ad_url(final_url):
                print(f"[TomosManga ADVERTENCIA] URL detectada como publicidad: {final_url[:100]}...")
                self._close_non_ouo_windows(driver, original_window)
                if not is_shared and driver:
                    driver.quit()
                return None
            
            if 'fireload' in final_url.lower():
                print(f"[TomosManga] ✓ URL de fireload obtenida")
                print(f"[TomosManga] Navegando a fireload para obtener botón de descarga...")
                try:
                    if original_window in driver.window_handles:
                        driver.switch_to.window(original_window)
                    elif driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
                        original_window = driver.current_window_handle
                except NoSuchWindowException:
                    if driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
                        original_window = driver.current_window_handle
                    else:
                        print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                        if driver:
                            driver.quit()
                        return None
                fireload_result = self.get_fireload_download_button(driver, final_url)
                if fireload_result and fireload_result.get('button'):
                    return {
                        'driver': driver, 
                        'download_button': fireload_result['button'], 
                        'fireload_url': final_url, 
                        'tab_handle': original_window, 
                        'is_shared': is_shared,
                        'file_size': fireload_result.get('file_size')
                    }
                if not is_shared and driver:
                    driver.quit()
                return None
            elif 'ouo.io' not in final_url.lower() and 'ouo.press' not in final_url.lower():
                if self.is_ad_url(final_url):
                    print(f"[TomosManga ADVERTENCIA] URL detectada como publicidad: {final_url[:100]}...")
                    self._close_non_ouo_windows(driver, original_window)
                    if not is_shared and driver:
                        driver.quit()
                    return None
                print(f"[TomosManga] ✓ URL final obtenida (ya no es ouo.io)")
                selenium_cookies = driver.get_cookies()
                cookies = {cookie['name']: cookie['value'] for cookie in selenium_cookies}
                if driver:
                    driver.quit()
                return {'url': final_url, 'cookies': cookies}
            else:
                print(f"[TomosManga] URL aún es ouo.io, reintentando buscar botones...")
                max_retries = 5
                retry_count = 0
                
                while retry_count < max_retries:
                    if self.cancelled:
                        if driver:
                            driver.quit()
                        return None
                    
                    try:
                        if original_window in driver.window_handles:
                            driver.switch_to.window(original_window)
                        elif driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            original_window = driver.current_window_handle
                        current_url = driver.current_url
                    except NoSuchWindowException:
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            original_window = driver.current_window_handle
                            current_url = driver.current_url
                        else:
                            print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas durante reintentos")
                            if driver:
                                driver.quit()
                            return None
                    if self.is_ad_url(current_url):
                        print(f"[TomosManga ADVERTENCIA] URL detectada como publicidad durante reintentos: {current_url[:100]}...")
                        self._close_non_ouo_windows(driver, original_window)
                        retry_count += 1
                        if retry_count < max_retries:
                            time.sleep(2)
                            continue
                        else:
                            if not is_shared and driver:
                                driver.quit()
                            return None
                    
                    if 'fireload' in current_url.lower():
                        print(f"[TomosManga] ✓ URL cambió a fireload durante reintentos")
                        fireload_result = self.get_fireload_download_button(driver, current_url)
                        if fireload_result and fireload_result.get('button'):
                            return {
                                'driver': driver, 
                                'download_button': fireload_result['button'], 
                                'fireload_url': current_url, 
                                'tab_handle': original_window, 
                                'is_shared': is_shared,
                                'file_size': fireload_result.get('file_size')
                            }
                        break
                    elif 'ouo.io' not in current_url.lower() and 'ouo.press' not in current_url.lower():
                        if not self.is_ad_url(current_url) and 'fireload' not in current_url.lower():
                            print(f"[TomosManga] ✓ URL cambió durante reintentos: {current_url}")
                            fireload_result = self.get_fireload_download_button(driver, current_url)
                            if fireload_result and fireload_result.get('button'):
                                return {
                                    'driver': driver, 
                                    'download_button': fireload_result['button'], 
                                    'fireload_url': current_url, 
                                    'tab_handle': original_window, 
                                    'is_shared': is_shared,
                                    'file_size': fireload_result.get('file_size')
                                }
                        break
                    
                    retry_count += 1
                    print(f"[TomosManga] Intento {retry_count}/{max_retries} de buscar botones en ouo.io...")
                    
                    try:
                        current_windows = driver.window_handles
                        ouo_window = None
                        for window in current_windows:
                            try:
                                driver.switch_to.window(window)
                                window_url = driver.current_url
                                if 'ouo.io' in window_url.lower() or 'ouo.press' in window_url.lower():
                                    if window == original_window or ouo_window is None:
                                        ouo_window = window
                                else:
                                    if window != original_window:
                                        try:
                                            driver.close()
                                            print(f"[TomosManga] Cerrada ventana que no es ouo.io: {window}")
                                        except NoSuchWindowException:
                                            pass
                            except NoSuchWindowException:
                                print(f"[TomosManga] Ventana {window} ya fue cerrada")
                            except Exception as e:
                                print(f"[TomosManga] Error al verificar ventana {window}: {e}")
                        
                        if ouo_window and ouo_window in driver.window_handles:
                            try:
                                driver.switch_to.window(ouo_window)
                            except NoSuchWindowException:
                                if driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])
                                    original_window = driver.current_window_handle
                        elif original_window in driver.window_handles:
                            try:
                                driver.switch_to.window(original_window)
                            except NoSuchWindowException:
                                if driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])
                                    original_window = driver.current_window_handle
                        elif driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            original_window = driver.current_window_handle
                    except Exception as e:
                        print(f"[TomosManga] Error al manejar ventanas: {e}")
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            original_window = driver.current_window_handle
                        else:
                            print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                            if driver:
                                driver.quit()
                            return None
                    
                    # Buscar botón "Get Link" nuevamente
                    try:
                        wait = WebDriverWait(driver, 10)
                        get_link_button = wait.until(
                            EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Get Link')] | //button[contains(text(), 'Obtener')] | //a[contains(text(), 'Get Link')] | //a[contains(text(), 'Obtener')] | //button[@id='recaptcha']"))
                        )
                        print(f"[TomosManga] Botón 'Get Link' encontrado en reintento {retry_count}")
                        
                        try:
                            driver.execute_script("arguments[0].scrollIntoView(true);", get_link_button)
                            time.sleep(0.5)
                            driver.execute_script("arguments[0].click();", get_link_button)
                            print(f"[TomosManga] ✓ Botón 'Get Link' presionado (reintento {retry_count})")
                        except Exception as e:
                            print(f"[TomosManga] Error al hacer clic en reintento: {e}")
                            try:
                                get_link_button.click()
                                print(f"[TomosManga] ✓ Botón 'Get Link' presionado (clic normal)")
                            except Exception as e2:
                                print(f"[TomosManga] Error en clic normal: {e2}")
                                time.sleep(2)
                                continue
                        
                        print(f"[TomosManga] Esperando 5 segundos después del clic...")
                        time.sleep(5)
                        
                        try:
                            final_url = driver.current_url
                            try:
                                if original_window in driver.window_handles:
                                    driver.switch_to.window(original_window)
                                elif driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])
                                    original_window = driver.current_window_handle
                                final_url = driver.current_url
                            except NoSuchWindowException:
                                if driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])
                                    original_window = driver.current_window_handle
                                final_url = driver.current_url
                        except NoSuchWindowException:
                            if driver.window_handles:
                                driver.switch_to.window(driver.window_handles[0])
                                original_window = driver.current_window_handle
                                final_url = driver.current_url
                            else:
                                print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                                if driver:
                                    driver.quit()
                                return None
                        if 'fireload' in final_url.lower():
                            print(f"[TomosManga] ✓ URL cambió a fireload después del reintento")
                            fireload_result = self.get_fireload_download_button(driver, final_url)
                            if fireload_result and fireload_result.get('button'):
                                return {
                                    'driver': driver, 
                                    'download_button': fireload_result['button'], 
                                    'fireload_url': final_url, 
                                    'tab_handle': original_window, 
                                    'is_shared': is_shared,
                                    'file_size': fireload_result.get('file_size')
                                }
                            break
                        elif 'ouo.io' not in final_url.lower() and 'ouo.press' not in final_url.lower():
                            print(f"[TomosManga] ✓ URL cambió después del reintento: {final_url}")
                            fireload_result = self.get_fireload_download_button(driver, final_url)
                            if fireload_result and fireload_result.get('button'):
                                return {
                                    'driver': driver, 
                                    'download_button': fireload_result['button'], 
                                    'fireload_url': final_url, 
                                    'tab_handle': original_window, 
                                    'is_shared': is_shared,
                                    'file_size': fireload_result.get('file_size')
                                }
                            break
                        
                        # Verificar nuevas ventanas después del clic
                        new_windows = driver.window_handles
                        if len(new_windows) > len(current_windows):
                            print(f"[TomosManga] Nueva ventana detectada después del clic en reintento...")
                            windows_to_close = []
                            for window in new_windows:
                                if window not in current_windows:
                                    try:
                                        driver.switch_to.window(window)
                                        new_url = driver.current_url
                                        print(f"[TomosManga] Nueva ventana {window}: {new_url[:80]}...")
                                        if 'fireload' in new_url.lower():
                                            driver.switch_to.window(window)
                                            fireload_result = self.get_fireload_download_button(driver, new_url)
                                            if fireload_result and fireload_result.get('button'):
                                                return {
                                                    'driver': driver, 
                                                    'download_button': fireload_result['button'], 
                                                    'fireload_url': new_url, 
                                                    'tab_handle': window, 
                                                    'is_shared': is_shared,
                                                    'file_size': fireload_result.get('file_size')
                                                }
                                            break
                                        elif 'ouo.io' in new_url.lower() or 'ouo.press' in new_url.lower():
                                            continue
                                        else:
                                            windows_to_close.append(window)
                                    except Exception as e:
                                        print(f"[TomosManga] Error al verificar nueva ventana {window}: {e}")
                            
                            for window in windows_to_close:
                                try:
                                    if window in driver.window_handles:
                                        driver.switch_to.window(window)
                                        driver.close()
                                        print(f"[TomosManga] ✓ Ventana no deseada cerrada: {window}")
                                except NoSuchWindowException:
                                    print(f"[TomosManga] Ventana {window} ya fue cerrada")
                                except Exception as e:
                                    print(f"[TomosManga] Error al cerrar ventana {window}: {e}")
                            
                            try:
                                target_window = ouo_window if ouo_window and ouo_window in driver.window_handles else original_window
                                if target_window in driver.window_handles:
                                    driver.switch_to.window(target_window)
                                elif driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])
                                    original_window = driver.current_window_handle
                            except NoSuchWindowException:
                                if driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])
                                    original_window = driver.current_window_handle
                            
                    except Exception as e:
                        print(f"[TomosManga] Error en reintento {retry_count}: {e}")
                        time.sleep(2)
                        continue
                    
                    time.sleep(2)
                
                try:
                    if original_window in driver.window_handles:
                        driver.switch_to.window(original_window)
                    elif driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
                        original_window = driver.current_window_handle
                    final_url = driver.current_url
                except NoSuchWindowException:
                    if driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
                        original_window = driver.current_window_handle
                        final_url = driver.current_url
                    else:
                        print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                        if driver:
                            driver.quit()
                        return None
                if 'fireload' in final_url.lower():
                    print(f"[TomosManga] ✓ URL de fireload obtenida después de reintentos")
                    fireload_result = self.get_fireload_download_button(driver, final_url)
                    if fireload_result and fireload_result.get('button'):
                        return {
                            'driver': driver, 
                            'download_button': fireload_result['button'], 
                            'fireload_url': final_url, 
                            'tab_handle': original_window, 
                            'is_shared': is_shared,
                            'file_size': fireload_result.get('file_size')
                        }
                else:
                    print(f"[TomosManga ERROR] No se pudo obtener URL de fireload después de {max_retries} reintentos")
                    if not is_shared and driver:
                        driver.quit()
                    return None
                
        except Exception as e:
            print(f"[TomosManga ERROR] Error en bypass_ouo_io: {e}")
            import traceback
            print(f"[TomosManga ERROR] Traceback: {traceback.format_exc()}")
            if driver:
                try:
                    print(f"[TomosManga] URL actual en navegador: {driver.current_url}")
                    try:
                        script_dir = os.path.dirname(os.path.abspath(__file__))
                        debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_ouo_io_error.html')
                        with open(debug_file, 'w', encoding='utf-8') as f:
                            f.write(driver.page_source)
                        print(f"[TomosManga] HTML de error guardado en: {debug_file}")
                    except:
                        pass
                    if driver:
                        try:
                            if driver.window_handles:
                                driver.switch_to.window(driver.window_handles[0])
                            fireload_url = driver.current_url
                        except NoSuchWindowException:
                            if driver.window_handles:
                                driver.switch_to.window(driver.window_handles[0])
                                fireload_url = driver.current_url
                            else:
                                fireload_url = ""
                except Exception as e:
                    print(f"[TomosManga] Error al obtener URL de error: {e}")
                    fireload_url = ""
                
                if fireload_url and 'fireload' in fireload_url.lower():
                    fireload_result = self.get_fireload_download_button(driver, fireload_url)
                    if fireload_result and fireload_result.get('button'):
                        try:
                            tab_handle = driver.current_window_handle if driver.window_handles else None
                        except:
                            tab_handle = None
                        return {
                            'driver': driver, 
                            'download_button': fireload_result['button'], 
                            'fireload_url': fireload_url, 
                            'tab_handle': tab_handle, 
                            'is_shared': is_shared,
                            'file_size': fireload_result.get('file_size')
                        }
                
                if fireload_url and fireload_url != "":
                    fireload_result = self.get_fireload_download_button(driver, fireload_url)
                    if fireload_result and fireload_result.get('button'):
                        try:
                            tab_handle = driver.current_window_handle if driver.window_handles else None
                        except:
                            tab_handle = None
                        return {
                            'driver': driver, 
                            'download_button': fireload_result['button'], 
                            'fireload_url': fireload_url, 
                            'tab_handle': tab_handle, 
                            'is_shared': is_shared,
                            'file_size': fireload_result.get('file_size')
                        }
                
                if not is_shared and driver:
                    driver.quit()
                return None
            return None
        finally:
            pass
    
    def _close_non_ouo_windows(self, driver, original_window):
        try:
            all_windows = driver.window_handles
            if len(all_windows) > 1:
                print(f"[TomosManga] Se detectaron {len(all_windows)} ventanas, cerrando las que NO sean ouo.io...")
                ouo_window = None
                windows_to_close = []
                
                for window in all_windows:
                    try:
                        driver.switch_to.window(window)
                        current_url = driver.current_url
                        print(f"[TomosManga] Ventana {window}: {current_url[:80]}...")
                        if 'ouo.io' in current_url.lower() or 'ouo.press' in current_url.lower():
                            if window == original_window or ouo_window is None:
                                ouo_window = window
                            print(f"[TomosManga] ✓ Encontrada ventana con ouo.io: {window}")
                        else:
                            if window != original_window:
                                windows_to_close.append(window)
                                print(f"[TomosManga] Ventana que NO es ouo.io, será cerrada: {window}")
                    except NoSuchWindowException:
                        print(f"[TomosManga] Ventana {window} ya fue cerrada")
                    except Exception as e:
                        print(f"[TomosManga] Error al verificar ventana {window}: {e}")
                
                for window in windows_to_close:
                    try:
                        if window in driver.window_handles:
                            driver.switch_to.window(window)
                            driver.close()
                            print(f"[TomosManga] ✓ Ventana cerrada: {window}")
                    except NoSuchWindowException:
                        print(f"[TomosManga] Ventana {window} ya fue cerrada")
                    except Exception as e:
                        print(f"[TomosManga] Error al cerrar ventana {window}: {e}")
                
                if ouo_window and ouo_window in driver.window_handles:
                    try:
                        driver.switch_to.window(ouo_window)
                        print(f"[TomosManga] Cambiado a ventana con ouo.io: {ouo_window}")
                    except NoSuchWindowException:
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            print(f"[TomosManga] Ventana ouo.io cerrada, usando primera ventana disponible")
                elif original_window in driver.window_handles:
                    try:
                        driver.switch_to.window(original_window)
                        print(f"[TomosManga] No se encontró ventana con ouo.io, usando la ventana original")
                    except NoSuchWindowException:
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            print(f"[TomosManga] Ventana original cerrada, usando primera ventana disponible")
                elif driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                    print(f"[TomosManga] Usando primera ventana disponible")
            else:
                print(f"[TomosManga] No se abrió nueva ventana, usando la actual")
        except Exception as e:
            print(f"[TomosManga] Error en _close_non_ouo_windows: {e}")
            if driver.window_handles:
                try:
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    pass
    
    def is_ad_url(self, url):
        if not url:
            return True
        url_lower = url.lower()
        ad_keywords = [
            'ads', 'advertisement', 'advertising', 'popup', 'pop-up', 'redirect', 'click', 
            'offer', 'promo', 'promotion', 'banner', 'sponsor', 'affiliate', 'tracking', 
            'analytics', 'doubleclick', 'googleads', 'adservice', 'casino', 'bet', 'gambling',
            'jugabet', 'voluum', 'utm_campaign', 'utm_source', 'utm_medium', 'clickid',
            'campaignid', 'offerid', 'win.', 'bet.', 'casino.', 'game.', 'slot.',
            'subid=', 'target_id=', 'affid=', 'voluum_clickid', 'voluum_campaignid'
        ]
        for keyword in ad_keywords:
            if keyword in url_lower:
                return True
        suspicious_domains = [
            'jugabet', 'casino', 'bet', 'gambling', 'slot', 'poker',
            'javsecrets.com', 'porngo.xxx', 'hurlybegaud.top', 'qeloviro.com',
            'turnhub.net', 'tuberel.com', 'tuberl.com', 'admeking.com',
            'redirect.admeking.com', 'win.jugabet'
        ]
        parsed_url = urlparse(url_lower)
        domain = parsed_url.netloc
        for suspicious in suspicious_domains:
            if suspicious in domain:
                return True
        return False
    
    def get_fireload_download_button(self, driver, fireload_url):
        if self.cancelled:
            return None
        
        if not driver:
            print(f"[TomosManga ERROR] No hay navegador disponible para obtener botón de descarga")
            return None
        
        if self.is_ad_url(fireload_url):
            print(f"[TomosManga ERROR] URL de fireload es publicidad: {fireload_url[:100]}...")
            return None
        
        if 'fireload' not in fireload_url.lower():
            print(f"[TomosManga ERROR] URL no es de fireload: {fireload_url[:100]}...")
            return None
        
        try:
            print(f"[TomosManga] Navegando a fireload: {fireload_url}")
            
            if self.cancelled:
                return None
            try:
                original_window = driver.current_window_handle
                if driver.current_url != fireload_url:
                    driver.get(fireload_url)
            except NoSuchWindowException:
                if driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                    original_window = driver.current_window_handle
                    if driver.current_url != fireload_url:
                        driver.get(fireload_url)
                else:
                    print(f"[TomosManga ERROR] Todas las ventanas fueron cerradas")
                    return None
            
            print(f"[TomosManga] Esperando a que fireload cargue...")
            time.sleep(3)
            
            if self.cancelled:
                return None
            
            if len(driver.window_handles) > 1:
                print(f"[TomosManga] Detectadas {len(driver.window_handles)} ventanas, verificando...")
                windows_to_close = []
                fireload_window = None
                
                for window in driver.window_handles:
                    try:
                        driver.switch_to.window(window)
                        window_url = driver.current_url
                        if self.is_ad_url(window_url):
                            if window != original_window:
                                windows_to_close.append(window)
                                print(f"[TomosManga] Ventana de publicidad detectada: {window}")
                        elif 'fireload' in window_url.lower():
                            fireload_window = window
                            print(f"[TomosManga] ✓ Ventana con fireload encontrada: {window}")
                    except Exception as e:
                        print(f"[TomosManga] Error al verificar ventana {window}: {e}")
                
                for window in windows_to_close:
                    try:
                        if window in driver.window_handles:
                            driver.switch_to.window(window)
                            driver.close()
                            print(f"[TomosManga] ✓ Ventana de publicidad cerrada: {window}")
                    except Exception as e:
                        print(f"[TomosManga] Error al cerrar ventana {window}: {e}")
                
                if fireload_window and fireload_window in driver.window_handles:
                    try:
                        driver.switch_to.window(fireload_window)
                        original_window = fireload_window
                        print(f"[TomosManga] Cambiado a ventana con fireload")
                    except Exception as e:
                        print(f"[TomosManga] Error al cambiar a ventana fireload: {e}")
                elif original_window in driver.window_handles:
                    try:
                        driver.switch_to.window(original_window)
                    except Exception as e:
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            original_window = driver.current_window_handle
                elif driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                    original_window = driver.current_window_handle
            
            current_url_after_cleanup = driver.current_url
            max_reload_attempts = 3
            reload_attempt = 0
            
            if self.is_ad_url(current_url_after_cleanup):
                print(f"[TomosManga ADVERTENCIA] Fireload redirigió a publicidad: {current_url_after_cleanup[:100]}...")
                
                if len(driver.window_handles) == 1:
                    try:
                        driver.back()
                        time.sleep(2)
                        if not self.is_ad_url(driver.current_url):
                            print(f"[TomosManga] ✓ Vuelto atrás exitosamente de publicidad")
                        else:
                            print(f"[TomosManga] Aún es publicidad después de back(), recargando fireload...")
                            while reload_attempt < max_reload_attempts and self.is_ad_url(driver.current_url):
                                driver.get(fireload_url)
                                time.sleep(3)
                                reload_attempt += 1
                                if not self.is_ad_url(driver.current_url):
                                    print(f"[TomosManga] ✓ Fireload recargado exitosamente (intento {reload_attempt})")
                                    break
                                elif reload_attempt < max_reload_attempts:
                                    print(f"[TomosManga] Aún es publicidad, reintentando recarga... (intento {reload_attempt + 1}/{max_reload_attempts})")
                            
                            if self.is_ad_url(driver.current_url):
                                print(f"[TomosManga ERROR] No se pudo cargar fireload después de {max_reload_attempts} intentos")
                                return None
                    except Exception as e:
                        print(f"[TomosManga] Error al volver atrás: {e}, recargando fireload directamente...")
                        driver.get(fireload_url)
                        time.sleep(3)
                        
                        if self.is_ad_url(driver.current_url):
                            print(f"[TomosManga ERROR] No se pudo cargar fireload después de recargar")
                            return None
                else:
                    found_valid_window = False
                    for window in driver.window_handles:
                        try:
                            driver.switch_to.window(window)
                            if not self.is_ad_url(driver.current_url):
                                original_window = window
                                found_valid_window = True
                                print(f"[TomosManga] ✓ Cambiado a ventana válida: {window}")
                                break
                        except Exception as e:
                            print(f"[TomosManga] Error al verificar ventana {window}: {e}")
                    
                    if not found_valid_window:
                        print(f"[TomosManga] Todas las ventanas son publicidad, cerrando extras y recargando fireload...")
                        while len(driver.window_handles) > 1:
                            try:
                                for window in list(driver.window_handles)[1:]:
                                    driver.switch_to.window(window)
                                    driver.close()
                            except Exception:
                                break
                        
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                            original_window = driver.current_window_handle
                            driver.get(fireload_url)
                            time.sleep(3)
                            
                            if self.is_ad_url(driver.current_url):
                                print(f"[TomosManga ERROR] No se pudo cargar fireload después de limpiar ventanas")
                                return None
            
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_file = os.path.join(script_dir, 'resources', 'debug', 'debug_html_fireload.html')
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                print(f"[TomosManga] HTML de fireload guardado en: {debug_file}")
            except Exception as e:
                print(f"[TomosManga] Error al guardar HTML de fireload: {e}")
            
            wait = WebDriverWait(driver, self.config.get('selenium_wait_time', 30))
            
            print(f"[TomosManga] Buscando botón 'Download' en fireload...")
            download_button = None
            
            try:
                download_button = wait.until(
                    EC.presence_of_element_located((By.ID, "downloadButton"))
                )
                print(f"[TomosManga] Botón 'Download' encontrado por ID")
            except Exception as e:
                print(f"[TomosManga ADVERTENCIA] No se encontró botón por ID 'downloadButton': {e}")
                try:
                    download_button = wait.until(
                        EC.presence_of_element_located((By.XPATH, "//a[@id='downloadButton'] | //a[contains(@class, 'download-button')] | //a[contains(@data-dlink-value, 'fireload')] | //a[contains(text(), 'Download File')]"))
                    )
                    print(f"[TomosManga] Botón 'Download' encontrado por XPath")
                except Exception as e2:
                    print(f"[TomosManga ADVERTENCIA] No se encontró botón por XPath: {e2}")
                    print(f"[TomosManga] Buscando enlaces de descarga directa...")
                    try:
                        download_links = driver.find_elements(By.TAG_NAME, "a")
                        for link in download_links:
                            href = link.get_attribute('href') or ''
                            data_dlink = link.get_attribute('data-dlink-value') or ''
                            text = link.text.lower()
                            if (('download' in text or 'descargar' in text) and not self.is_ad_url(href)) or ('fireload' in data_dlink.lower()):
                                download_button = link
                                print(f"[TomosManga] Enlace de descarga encontrado: {text[:50]}")
                                break
                    except Exception as e3:
                        print(f"[TomosManga ERROR] Error al buscar enlaces: {e3}")
            
            if not download_button:
                print(f"[TomosManga ERROR] No se encontró botón de descarga en fireload")
                return None
            
            file_size_bytes = None
            try:
                size_element = driver.find_element(By.CSS_SELECTOR, "span.item-size")
                size_text = size_element.text.strip()
                print(f"[TomosManga] Tamaño del archivo encontrado: {size_text}")
                
                size_match = re.search(r'([\d.]+)\s*(MB|GB|KB)', size_text, re.IGNORECASE)
                if size_match:
                    size_value = float(size_match.group(1))
                    size_unit = size_match.group(2).upper()
                    
                    if size_unit == 'KB':
                        file_size_bytes = int(size_value * 1024)
                    elif size_unit == 'MB':
                        file_size_bytes = int(size_value * 1024 * 1024)
                    elif size_unit == 'GB':
                        file_size_bytes = int(size_value * 1024 * 1024 * 1024)
                    
                    print(f"[TomosManga] Tamaño convertido: {file_size_bytes / (1024 * 1024):.2f} MB")
            except Exception as e:
                print(f"[TomosManga ADVERTENCIA] No se pudo obtener el tamaño del archivo: {e}")
            
            return {'button': download_button, 'file_size': file_size_bytes}
                
        except Exception as e:
            print(f"[TomosManga ERROR] Error al obtener botón de descarga de fireload: {e}")
            import traceback
            print(f"[TomosManga ERROR] Traceback: {traceback.format_exc()}")
            return None
    
    def download_file_with_selenium(self, driver, download_button, download_dir, expected_filename, total_size=None, chapter_name=None):
        if not driver or not download_button:
            print(f"[TomosManga ERROR] No hay navegador o botón disponible para descargar")
            return False
        
        try:
            os.makedirs(download_dir, exist_ok=True)
            
            try:
                driver.execute_cdp_cmd('Page.setDownloadBehavior', {
                    'behavior': 'allow',
                    'downloadPath': os.path.abspath(download_dir)
                })
            except Exception:
                pass
            
            files_before = set(os.listdir(download_dir)) if os.path.exists(download_dir) else set()
            
            download_url = download_button.get_attribute('data-dlink-value') or download_button.get_attribute('href')
            if download_url and download_url.startswith('javascript:'):
                download_url = None
            
            time.sleep(2)
            
            initial_button_text = download_button.text.strip().lower()
            
            current_window_before = driver.current_window_handle
            all_windows_before = driver.window_handles
            
            # Intentar hacer clic múltiples veces si es necesario
            max_click_attempts = 5
            click_attempt = 0
            download_started = False
            
            while click_attempt < max_click_attempts and not download_started:
                click_attempt += 1
                
                try:
                    wait = WebDriverWait(driver, 10)
                    download_button = wait.until(
                        EC.presence_of_element_located((By.ID, "downloadButton"))
                    )
                except:
                    try:
                        download_button = driver.find_element(By.XPATH, "//a[@id='downloadButton'] | //a[contains(@class, 'download-button')] | //a[contains(@data-dlink-value, 'fireload')] | //a[contains(text(), 'Download File')]")
                    except:
                        print(f"[TomosManga] No se pudo encontrar el botón en intento {click_attempt}")
                        if click_attempt < max_click_attempts:
                            time.sleep(3)
                            continue
                        else:
                            return False
                
                try:
                    driver.execute_script("arguments[0].scrollIntoView(true);", download_button)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", download_button)
                except Exception as e:
                    print(f"[TomosManga] Clic con JavaScript falló: {e}, intentando clic normal...")
                    try:
                        download_button.click()
                    except Exception as e2:
                        print(f"[TomosManga] Clic normal también falló: {e2}")
                        if click_attempt < max_click_attempts:
                            time.sleep(3)
                            continue
                        else:
                            return False
                
                # Monitorear cambios en el botón y archivos nuevos
                button_changed = False
                files_changed = False
                
                # Esperar hasta 20 segundos para detectar inicio de descarga
                for check in range(20):
                    if self.cancelled:
                        return False
                    
                    time.sleep(1)
                    
                    # Verificar cambio en el botón
                    try:
                        current_text = download_button.text.strip().lower()
                        if current_text != initial_button_text:
                            if 'starting' in current_text or 'iniciando' in current_text or 'download' in current_text or 'descarga' in current_text or 'wait' in current_text or 'espera' in current_text:
                                button_changed = True
                                download_started = True
                                break
                    except Exception as e:
                        pass
                    
                    if os.path.exists(download_dir):
                        files_after_check = set(os.listdir(download_dir))
                        new_files_check = files_after_check - files_before
                        if new_files_check:
                            for filename in new_files_check:
                                filepath = os.path.join(download_dir, filename)
                                if os.path.isfile(filepath):
                                    try:
                                        file_size = os.path.getsize(filepath)
                                        if file_size > 0:
                                            files_changed = True
                                            download_started = True
                                            break
                                    except:
                                        pass
                        if files_changed:
                            break
                
                if download_started:
                    break
                else:
                    if click_attempt < max_click_attempts:
                        time.sleep(3)
                        try:
                            wait = WebDriverWait(driver, 5)
                            download_button = wait.until(
                                EC.presence_of_element_located((By.ID, "downloadButton"))
                            )
                            print(f"[TomosManga] Botón encontrado nuevamente, continuando monitoreo...")
                        except:
                            print(f"[TomosManga] No se pudo encontrar el botón, pero continuando monitoreo de archivos...")
            
            all_windows_after = driver.window_handles
            
            if len(all_windows_after) > len(all_windows_before):
                    print(f"[TomosManga] Se detectaron nuevas ventanas, cerrando ventanas de publicidad...")
                    windows_to_close = []
                    for window in all_windows_after:
                        if window not in all_windows_before:
                            try:
                                driver.switch_to.window(window)
                                new_url = driver.current_url
                                print(f"[TomosManga] Nueva ventana {window}: {new_url[:80]}...")
                                if self.is_ad_url(new_url):
                                    windows_to_close.append(window)
                                    print(f"[TomosManga] Ventana de publicidad detectada, será cerrada...")
                                else:
                                    print(f"[TomosManga] Ventana válida, manteniendo abierta...")
                            except Exception as e:
                                print(f"[TomosManga] Error al verificar ventana {window}: {e}")
                    
                    for window in windows_to_close:
                        try:
                            if window in driver.window_handles:
                                driver.switch_to.window(window)
                                driver.close()
                                print(f"[TomosManga] ✓ Ventana de publicidad cerrada: {window}")
                        except NoSuchWindowException:
                            print(f"[TomosManga] Ventana {window} ya fue cerrada")
                        except Exception as e:
                            print(f"[TomosManga] Error al cerrar ventana {window}: {e}")
                    
                    try:
                        if current_window_before in driver.window_handles:
                            driver.switch_to.window(current_window_before)
                        elif driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                    except NoSuchWindowException:
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
            
            waited = 0
            downloaded_file = None
            last_size = 0
            stable_count = 0
            temp_file = None
            max_stable_checks = 10
            previous_sizes = []
            size_history_window = 10
            last_callback_time = 0
            callback_interval = 2
            
            pbar = None
            if total_size and total_size > 0:
                pbar = tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024, desc=f"  {expected_filename}", leave=True, ncols=100, miniters=1024*1024, mininterval=0.5, file=sys.stdout)
            
            while True:
                if self.cancelled:
                    if pbar:
                        pbar.close()
                    print(f"[TomosManga] Descarga cancelada")
                    if temp_file and os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except:
                            pass
                    return False
                
                time.sleep(1)
                waited += 1
                
                if not os.path.exists(download_dir):
                    continue
                
                if temp_file and os.path.exists(temp_file) and self.callbacks['on_download_progress'] and (waited - last_callback_time) >= callback_interval:
                    try:
                        current_check_size = os.path.getsize(temp_file)
                        if current_check_size > 0:
                            percent = 0
                            speed_mb = 0
                            if total_size and total_size > 0:
                                percent = (current_check_size / total_size) * 100
                                if len(previous_sizes) >= 2:
                                    time_diff = waited - previous_sizes[-1][0] if previous_sizes else 1
                                    size_diff = current_check_size - previous_sizes[-1][1] if previous_sizes else current_check_size
                                    if time_diff > 0:
                                        speed_mb = (size_diff / (1024 * 1024)) / time_diff
                            self.callbacks['on_download_progress'](chapter_name or expected_filename, percent, speed_mb, current_check_size, total_size or current_check_size)
                            last_callback_time = waited
                    except:
                        pass
                
                    
                files_after = set(os.listdir(download_dir))
                new_files = files_after - files_before
                
                if new_files:
                    for filename in new_files:
                        filepath = os.path.join(download_dir, filename)
                        if os.path.isfile(filepath):
                            try:
                                file_size = os.path.getsize(filepath)
                                if file_size > 0:
                                    if filename.endswith('.tmp') or filename.endswith('.crdownload'):
                                        temp_file = filepath
                                        if file_size != last_size:
                                            if pbar and file_size > last_size:
                                                pbar.update(file_size - last_size)
                                                pbar.refresh()
                                            
                                            if self.callbacks['on_download_progress']:
                                                try:
                                                    percent = 0
                                                    speed_mb = 0
                                                    if total_size and total_size > 0:
                                                        percent = (file_size / total_size) * 100
                                                        if len(previous_sizes) >= 2:
                                                            time_diff = waited - previous_sizes[-1][0] if previous_sizes else 1
                                                            size_diff = file_size - previous_sizes[-1][1] if previous_sizes else file_size
                                                            if time_diff > 0:
                                                                speed_mb = (size_diff / (1024 * 1024)) / time_diff
                                                    self.callbacks['on_download_progress'](chapter_name or expected_filename, percent, speed_mb, file_size, total_size or file_size)
                                                except Exception as e:
                                                    print(f"[DEBUG] Error en callback on_download_progress: {e}")
                                            
                                            last_size = file_size
                                            stable_count = 0
                                            if len(previous_sizes) >= size_history_window:
                                                previous_sizes.pop(0)
                                            previous_sizes.append((waited, file_size))
                                        else:
                                            stable_count += 1
                                        
                                        if stable_count >= max_stable_checks:
                                            if pbar:
                                                pbar.n = total_size if total_size else file_size
                                                pbar.refresh()
                                                pbar.close()
                                            base_name = os.path.basename(temp_file).rsplit('.', 1)[0]
                                            if download_url:
                                                if '.rar' in download_url.lower():
                                                    final_name = base_name + '.rar'
                                                elif '.zip' in download_url.lower():
                                                    final_name = base_name + '.zip'
                                                else:
                                                    final_name = base_name + '.rar'
                                            else:
                                                final_name = base_name + '.rar'
                                            final_path = os.path.join(download_dir, final_name)
                                            if not os.path.exists(final_path):
                                                os.rename(temp_file, final_path)
                                                print(f"[TomosManga] ✓ Archivo completado y renombrado: {final_name} ({file_size / (1024 * 1024):.2f} MB)")
                                                return final_path
                                    else:
                                        downloaded_file = filepath
                                        if pbar:
                                            pbar.n = total_size if total_size else file_size
                                            pbar.refresh()
                                            pbar.close()
                                        print(f"[TomosManga] ✓ Archivo descargado encontrado: {filename} ({file_size / (1024 * 1024):.2f} MB)")
                                        time.sleep(2)
                                        final_size = os.path.getsize(downloaded_file)
                                        if final_size == file_size:
                                            print(f"[TomosManga] ✓ Descarga completada: {os.path.basename(downloaded_file)}")
                                            return downloaded_file
                            except Exception as e:
                                continue
                
                
                if temp_file and os.path.exists(temp_file):
                    try:
                        current_size = os.path.getsize(temp_file)
                        if current_size != last_size:
                            if pbar and current_size > last_size:
                                pbar.update(current_size - last_size)
                                pbar.refresh()
                            
                            if self.callbacks['on_download_progress']:
                                try:
                                    percent = 0
                                    speed_mb = 0
                                    if total_size and total_size > 0:
                                        percent = (current_size / total_size) * 100
                                        if len(previous_sizes) >= 2:
                                            time_diff = waited - previous_sizes[-1][0] if previous_sizes else 1
                                            size_diff = current_size - previous_sizes[-1][1] if previous_sizes else current_size
                                            if time_diff > 0:
                                                speed_mb = (size_diff / (1024 * 1024)) / time_diff
                                    self.callbacks['on_download_progress'](chapter_name or expected_filename, percent, speed_mb, current_size, total_size or current_size)
                                except Exception as e:
                                    print(f"[DEBUG] Error en callback on_download_progress: {e}")
                            
                            last_size = current_size
                            if len(previous_sizes) >= size_history_window:
                                previous_sizes.pop(0)
                            previous_sizes.append((waited, current_size))
                            stable_count = 0
                        elif current_size > 0 and current_size == last_size:
                            if stable_count >= max_stable_checks:
                                if pbar:
                                    pbar.n = total_size if total_size else current_size
                                    pbar.refresh()
                                    pbar.close()
                                base_name = os.path.basename(temp_file).rsplit('.', 1)[0]
                                if download_url:
                                    if '.rar' in download_url.lower():
                                        final_name = base_name + '.rar'
                                    elif '.zip' in download_url.lower():
                                        final_name = base_name + '.zip'
                                    else:
                                        final_name = base_name + '.rar'
                                else:
                                    final_name = base_name + '.rar'
                                final_path = os.path.join(download_dir, final_name)
                                if not os.path.exists(final_path):
                                    os.rename(temp_file, final_path)
                                    if not pbar:
                                        print(f"[TomosManga] ✓ Archivo descargado completamente: {final_name} ({current_size / (1024 * 1024):.2f} MB)")
                                    return final_path
                    except:
                        pass
            
            if pbar:
                pbar.close()
            
            if downloaded_file:
                if not pbar:
                    print(f"[TomosManga] ✓ Archivo descargado: {os.path.basename(downloaded_file)}")
                return downloaded_file
            elif temp_file and os.path.exists(temp_file):
                try:
                    base_name = os.path.basename(temp_file).rsplit('.', 1)[0]
                    final_name = base_name + ('.rar' if download_url and '.rar' in download_url.lower() else '.zip')
                    final_path = os.path.join(download_dir, final_name)
                    if not os.path.exists(final_path):
                        os.rename(temp_file, final_path)
                        if not pbar:
                            print(f"[TomosManga] ✓ Archivo renombrado al finalizar: {final_name}")
                        return final_path
                except Exception as e:
                    pass
            
            if not downloaded_file and not temp_file:
                if pbar:
                    pbar.close()
                print(f"[TomosManga ERROR] No se detectó ningún archivo descargado")
                return False
                
        except Exception as e:
            print(f"[TomosManga ERROR] Error al descargar archivo con Selenium: {e}")
            import traceback
            print(f"[TomosManga ERROR] Traceback: {traceback.format_exc()}")
            return False

    def download_file(self, url, filepath, cookies=None):
        print(f"[TomosManga] Iniciando descarga de archivo...")
        print(f"[TomosManga] URL: {url}")
        print(f"[TomosManga] Guardando en: {filepath}")
        
        try:
            print(f"[TomosManga] Enviando solicitud HTTP...")
            if cookies:
                print(f"[TomosManga] Usando {len(cookies)} cookies del navegador")
                response = self.session.get(url, stream=True, timeout=self.config['timeout'], cookies=cookies)
            else:
                response = self.session.get(url, stream=True, timeout=self.config['timeout'])
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            if total_size > 0:
                size_mb = total_size / (1024 * 1024)
                print(f"[TomosManga] Tamaño del archivo: {size_mb:.2f} MB")
            else:
                print(f"[TomosManga] Tamaño del archivo: desconocido")
            
            print(f"[TomosManga] Descargando archivo...")
            with open(filepath, 'wb') as f:
                if total_size == 0:
                    f.write(response.content)
                    print(f"[TomosManga] Archivo descargado (sin tamaño conocido)")
                else:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.cancelled:
                            print(f"[TomosManga] Descarga cancelada")
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                if downloaded % (1024 * 1024) == 0:
                                    print(f"[TomosManga] Progreso: {percent:.1f}% ({downloaded / (1024 * 1024):.2f} MB / {total_size / (1024 * 1024):.2f} MB)")
            
            file_size = os.path.getsize(filepath)
            if file_size > 0:
                print(f"[TomosManga] ✓ Archivo descargado correctamente ({file_size / (1024 * 1024):.2f} MB)")
                return True
            else:
                print(f"[TomosManga ERROR] Archivo descargado está vacío")
                return False
        except Exception as e:
            print(f"[TomosManga ERROR] Error al descargar archivo: {e}")
            import traceback
            print(f"[TomosManga ERROR] Traceback: {traceback.format_exc()}")
            return False

    def get_manga_title(self, html_content):
        print(f"[TomosManga] Extrayendo título del manga...")
        soup = BeautifulSoup(html_content, 'html.parser')
        title_elem = soup.find('h1', class_='entry-title') or soup.find('h1')
        if title_elem:
            raw_title = title_elem.get_text(strip=True)
            parts = re.split(r'\btomos\b', raw_title, flags=re.IGNORECASE)
            title = parts[0].strip() if parts else raw_title
            if not title:
                title = raw_title
            print(f"[TomosManga] Título encontrado: {title}")
            return title
        print(f"[TomosManga ADVERTENCIA] No se encontró título, usando 'Manga' por defecto")
        return "Manga"

    def parse_volumes(self, html_content, debug=False):
        print(f"[TomosManga] Parseando tomos desde HTML...")
        soup = BeautifulSoup(html_content, 'html.parser')
        volumes = []
        
        print(f"[TomosManga] Buscando enlaces de ouo.io/ouo.press...")
        download_links = soup.find_all('a', href=re.compile(r'ouo\.io|ouo\.press'))
        print(f"[TomosManga] Encontrados {len(download_links)} enlaces con ouo.io/ouo.press")
        
        for link in download_links:
            link_text = link.get_text(strip=True)
            link_url = link.get('href', '')
            
            if not link_url.startswith('http'):
                link_url = urljoin(self.base_url, link_url)
            
            tomo_match = re.search(r'\[(\d+)\s*-\s*(\d+)\](?:\s*\+\s*(.+))?', link_text, re.IGNORECASE)
            if tomo_match:
                start_num = tomo_match.group(1)
                end_num = tomo_match.group(2)
                extra_text = tomo_match.group(3) if tomo_match.group(3) else ""
                
                if start_num == end_num:
                    chapter_name = f"Tomo {start_num}"
                    chapter_num = start_num
                else:
                    range_text = f"{start_num}-{end_num}"
                    if extra_text:
                        chapter_name = f"Tomo {range_text} + {extra_text.strip()}"
                    else:
                        chapter_name = f"Tomo {range_text}"
                    chapter_num = start_num
            else:
                chapter_match = re.search(r'cap[íi]tulo\s*([\d\s\-]+)', link_text, re.IGNORECASE)
                if not chapter_match:
                    chapter_match = re.search(r'\[(\d+)\s*-\s*(\d+)\]', link_text)
                    if chapter_match:
                        start_num = chapter_match.group(1)
                        end_num = chapter_match.group(2)
                        if start_num == end_num:
                            chapter_name = f"Tomo {start_num}"
                            chapter_num = start_num
                        else:
                            chapter_name = f"Tomo {start_num}-{end_num}"
                            chapter_num = start_num
                    else:
                        chapter_match = re.search(r'(\d+)', link_text)
                        if chapter_match:
                            chapter_num = chapter_match.group(1)
                            chapter_name = f"Tomo {chapter_num}"
                        else:
                            chapter_num = "1"
                            chapter_name = "Tomo 1"
                else:
                    chapter_text = chapter_match.group(1).strip()
                    chapter_num = re.search(r'(\d+)', chapter_text).group(1) if re.search(r'(\d+)', chapter_text) else "1"
                    if ' - ' in chapter_text or (len(chapter_text) > 2 and '-' in chapter_text and not chapter_text.startswith('-')):
                        chapter_name = f"Tomo {chapter_text}"
                    else:
                        chapter_name = f"Tomo {chapter_num}"
            
            volumes.append({
                'name': chapter_name,
                'url': link_url,
                'chapter_number': chapter_num
            })
            print(f"[TomosManga] Tomo encontrado: {chapter_name} -> {link_url}")
        
        if not volumes:
            print(f"[TomosManga] No se encontraron enlaces directos, buscando en secciones de descarga...")
            download_sections = soup.find_all(['div', 'section'], class_=re.compile(r'download|descarga', re.I))
            for section in download_sections:
                links = section.find_all('a', href=re.compile(r'ouo\.io|ouo\.press'))
                for link in links:
                    link_text = link.get_text(strip=True)
                    link_url = link.get('href', '')
                    
                    if not link_url.startswith('http'):
                        link_url = urljoin(self.base_url, link_url)
                    
                    tomo_match = re.search(r'\[(\d+)\s*-\s*(\d+)\](?:\s*\+\s*(.+))?', link_text, re.IGNORECASE)
                    if tomo_match:
                        start_num = tomo_match.group(1)
                        end_num = tomo_match.group(2)
                        extra_text = tomo_match.group(3) if tomo_match.group(3) else ""
                        
                        if start_num == end_num:
                            chapter_name = f"Tomo {start_num}"
                            chapter_num = start_num
                        else:
                            range_text = f"{start_num}-{end_num}"
                            if extra_text:
                                chapter_name = f"Tomo {range_text} + {extra_text.strip()}"
                            else:
                                chapter_name = f"Tomo {range_text}"
                            chapter_num = start_num
                    else:
                        chapter_match = re.search(r'cap[íi]tulo\s*([\d\s\-]+)', link_text, re.IGNORECASE)
                        if not chapter_match:
                            chapter_match = re.search(r'\[(\d+)\s*-\s*(\d+)\]', link_text)
                            if chapter_match:
                                start_num = chapter_match.group(1)
                                end_num = chapter_match.group(2)
                                if start_num == end_num:
                                    chapter_name = f"Tomo {start_num}"
                                    chapter_num = start_num
                                else:
                                    chapter_name = f"Tomo {start_num}-{end_num}"
                                    chapter_num = start_num
                            else:
                                chapter_match = re.search(r'(\d+)', link_text)
                                if chapter_match:
                                    chapter_num = chapter_match.group(1)
                                    chapter_name = f"Tomo {chapter_num}"
                                else:
                                    chapter_num = "1"
                                    chapter_name = "Tomo 1"
                        else:
                            chapter_text = chapter_match.group(1).strip()
                            chapter_num = re.search(r'(\d+)', chapter_text).group(1) if re.search(r'(\d+)', chapter_text) else "1"
                            if ' - ' in chapter_text or (len(chapter_text) > 2 and '-' in chapter_text and not chapter_text.startswith('-')):
                                chapter_name = f"Tomo {chapter_text}"
                            else:
                                chapter_name = f"Tomo {chapter_num}"
                    
                    volumes.append({
                        'name': chapter_name,
                        'url': link_url,
                        'chapter_number': chapter_num
                    })
        
        if volumes:
            print(f"[TomosManga] Ordenando {len(volumes)} tomos por número...")
            volumes.sort(key=lambda x: float(re.search(r'(\d+\.?\d*)', x['chapter_number']).group(1)) if re.search(r'(\d+\.?\d*)', x['chapter_number']) else 0)
            print(f"[TomosManga] ✓ {len(volumes)} tomos parseados y ordenados")
        else:
            print(f"[TomosManga ERROR] No se encontraron tomos en la página")
        
        return volumes
    
    def extract_chapter_numbers(self, chapter_name):
        match = re.search(r'Tomo\s*(\d+)\s*-\s*(\d+)', chapter_name, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'Tomo\s*(\d+\.?\d*)', chapter_name, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'\[(\d+)\s*-\s*(\d+)\]', chapter_name)
        if match:
            return match.group(1)
        match = re.search(r'(\d+\.?\d*)', chapter_name)
        if match:
            return match.group(1)
        return "0"

    def _get_single_fireload_url(self, volume, idx, total):
        if self.cancelled:
            return {
                'chapter_name': volume['name'],
                'fireload_url': None,
                'driver': None,
                'download_button': None,
                'tab_handle': None,
                'index': idx - 1
            }
        
        chapter_name = volume['name']
        chapter_url = volume['url']
        
        with self.print_lock:
            print(f"[{idx}/{total}] Obteniendo URL de fireload para: {chapter_name}")
        
        if self.callbacks['on_fireload_progress']:
            try:
                self.callbacks['on_fireload_progress'](idx, total, chapter_name)
            except:
                pass
        
        result = self.bypass_ouo_io(chapter_url)
        
        if self.cancelled:
            if result and result.get('driver'):
                try:
                    result['driver'].quit()
                except:
                    pass
            return {
                'chapter_name': chapter_name,
                'fireload_url': None,
                'driver': None,
                'download_button': None,
                'tab_handle': None,
                'index': idx - 1
            }
        
        if result and result.get('fireload_url') and result.get('driver') and result.get('download_button'):
            with self.print_lock:
                print(f"[TomosManga] ✓ URL de fireload obtenida para {chapter_name}")
            return {
                'chapter_name': chapter_name,
                'fireload_url': result['fireload_url'],
                'driver': result['driver'],
                'download_button': result['download_button'],
                'tab_handle': result.get('tab_handle'),
                'file_size': result.get('file_size'),
                'index': idx - 1
            }
        else:
            with self.print_lock:
                print(f"[TomosManga ERROR] No se pudo obtener URL de fireload para {chapter_name}")
            return {
                'chapter_name': chapter_name,
                'fireload_url': None,
                'driver': None,
                'download_button': None,
                'tab_handle': None,
                'index': idx - 1
            }
    
    def get_fireload_urls(self, volumes):
        print(f"\n{'='*60}")
        print(f"[TomosManga] Obteniendo URLs de fireload para {len(volumes)} tomos...")
        print(f"{'='*60}\n")
        
        parallel_tomos = self.config.get('parallel_tomos', 1)
        fireload_data = [None] * len(volumes)
        
        if self.callbacks['on_fireload_progress']:
            try:
                self.callbacks['on_fireload_progress'](0, len(volumes), "Iniciando...")
            except:
                pass
        
        if parallel_tomos > 1 and len(volumes) > 1:
            with self.print_lock:
                print(f"[TomosManga] Obteniendo URLs en paralelo (máximo {parallel_tomos} simultáneos)")
            with ThreadPoolExecutor(max_workers=parallel_tomos) as executor:
                futures = {executor.submit(self._get_single_fireload_url, volume, idx, len(volumes)): idx 
                          for idx, volume in enumerate(volumes, start=1)}
                
                for future in as_completed(futures):
                    if self.cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        for result in fireload_data:
                            if result and result.get('driver'):
                                try:
                                    result['driver'].quit()
                                except:
                                    pass
                        break
                    try:
                        result = future.result()
                        if result:
                            fireload_data[result['index']] = result
                    except Exception as e:
                        idx = futures[future]
                        with self.print_lock:
                            print(f"[TomosManga ERROR] Error al obtener URL para tomo {idx}: {e}")
                        fireload_data[idx - 1] = {
                            'chapter_name': volumes[idx - 1]['name'],
                            'fireload_url': None,
                            'driver': None,
                            'download_button': None,
                            'tab_handle': None,
                            'index': idx - 1
                        }
        else:
            for idx, volume in enumerate(volumes, start=1):
                if self.cancelled:
                    for result in fireload_data:
                        if result and result.get('driver'):
                            try:
                                result['driver'].quit()
                            except:
                                pass
                    break
                result = self._get_single_fireload_url(volume, idx, len(volumes))
                if result:
                    fireload_data[result['index']] = result
                if idx < len(volumes):
                    time.sleep(self.config.get('delay_between_chapters', 2))
        
        if self.cancelled:
            for result in fireload_data:
                if result and result.get('driver'):
                    try:
                        result['driver'].quit()
                    except:
                        pass
        
        return fireload_data
    
    def download_chapter(self, chapter_name, fireload_data, output_dir):
        if self.cancelled:
            print(f"[TomosManga] Descarga cancelada para: {chapter_name}")
            if fireload_data and fireload_data.get('driver'):
                try:
                    fireload_data['driver'].quit()
                except:
                    pass
            return ([], 0, 0, [])
        
        if not fireload_data or not fireload_data.get('fireload_url') or not fireload_data.get('driver') or not fireload_data.get('download_button'):
            print(f"[TomosManga ERROR] No hay datos de fireload para: {chapter_name}")
            if fireload_data and fireload_data.get('driver'):
                try:
                    fireload_data['driver'].quit()
                except:
                    pass
            return ([], 0, 0, [{'url': '', 'error': "No hay datos de fireload", 'index': -1}])
        
        safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '_', chapter_name)
        os.makedirs(output_dir, exist_ok=True)
        
        driver = fireload_data['driver']
        download_button = fireload_data['download_button']
        
        url_ext = '.zip'
        archive_path = os.path.join(output_dir, f"{safe_chapter_name}{url_ext}")
        
        if os.path.exists(archive_path) and not self.config.get('force_redownload', False):
            file_size = os.path.getsize(archive_path) / (1024 * 1024)
            print(f"[TomosManga] ✓ Archivo ya existe: {archive_path} ({file_size:.2f} MB)")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            return ([archive_path], 1, 1, [])
        
        temp_download_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "downloads", "temp", safe_chapter_name)
        )
        os.makedirs(temp_download_dir, exist_ok=True)
        
        file_size = fireload_data.get('file_size')
        if file_size:
            size_mb = file_size / (1024 * 1024)
            print(f"[{safe_chapter_name}] Iniciando descarga ({size_mb:.2f} MB)...")
        
        if self.callbacks['on_download_start']:
            try:
                self.callbacks['on_download_start'](chapter_name, file_size)
            except:
                pass
        
        downloaded_file = None
        try:
            downloaded_file = self.download_file_with_selenium(driver, download_button, temp_download_dir, safe_chapter_name, total_size=file_size, chapter_name=chapter_name)
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        if self.cancelled:
            if downloaded_file and os.path.exists(downloaded_file):
                try:
                    os.remove(downloaded_file)
                except:
                    pass
            return ([], 0, 0, [])
        
        if not downloaded_file:
            print(f"[TomosManga ERROR] Error al descargar archivo")
            return ([], 0, 0, [{'url': fireload_data['fireload_url'], 'error': "Error al descargar archivo", 'index': -1}])
        
        print(f"[TomosManga] Moviendo archivo descargado a destino final...")
        try:
            if os.path.exists(archive_path):
                os.remove(archive_path)
            os.rename(downloaded_file, archive_path)
            print(f"[TomosManga] ✓ Archivo movido exitosamente")
        except Exception as e:
            print(f"[TomosManga ERROR] Error al mover archivo: {e}")
            import shutil
            try:
                shutil.copy2(downloaded_file, archive_path)
                print(f"[TomosManga] ✓ Archivo copiado exitosamente")
            except Exception as e2:
                print(f"[TomosManga ERROR] Error al copiar archivo: {e2}")
                return ([], 0, 0, [{'url': fireload_data['fireload_url'], 'error': f"Error al mover archivo: {e2}", 'index': -1}])
        
        file_size = os.path.getsize(archive_path) / (1024 * 1024)
        print(f"[TomosManga] ✓ Archivo descargado exitosamente: {os.path.basename(archive_path)} ({file_size:.2f} MB)")
        print(f"{'='*60}\n")
        
        if self.callbacks['on_download_complete']:
            try:
                self.callbacks['on_download_complete'](chapter_name)
            except:
                pass
        
        return ([archive_path], 1, 1, [])
    
    def download_volume(self, volume, manga_title, output_dir):
        print(f"[TomosManga] download_volume llamado para: {volume.get('name', 'Tomo')}")
        
        if not volume.get('url'):
            print(f"[TomosManga ERROR] El volumen no tiene URL")
            return {'dir': None, 'failed_chapters': []}
        
        chapter_name = volume.get('name', 'Tomo')
        chapter_url = volume['url']
        
        safe_manga_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
        manga_dir = os.path.join(output_dir, safe_manga_title)
        os.makedirs(manga_dir, exist_ok=True)
        print(f"[TomosManga] Directorio del manga: {manga_dir}")
        
        if self.callbacks['on_fireload_progress']:
            try:
                self.callbacks['on_fireload_progress'](1, 1, chapter_name)
            except:
                pass
        
        result = self.bypass_ouo_io(chapter_url)
        
        if not result or not result.get('fireload_url') or not result.get('driver') or not result.get('download_button'):
            print(f"[TomosManga ERROR] No se pudo obtener botón de descarga")
            return {'dir': None, 'failed_chapters': [{'chapter_name': chapter_name, 'downloaded': 0, 'total': 1}]}
        
        fireload_data = {
            'chapter_name': chapter_name,
            'fireload_url': result['fireload_url'],
            'driver': result['driver'],
            'download_button': result['download_button'],
            'tab_handle': result.get('tab_handle'),
            'file_size': result.get('file_size')
        }
        
        downloaded, total, success, failed = self.download_chapter(chapter_name, fireload_data, manga_dir)
        
        failed_chapters = []
        if failed:
            for fail_item in failed:
                failed_chapters.append({
                    'chapter_name': chapter_name,
                    'downloaded': 0,
                    'total': 1
                })
        elif success == 0:
            failed_chapters.append({
                'chapter_name': chapter_name,
                'downloaded': 0,
                'total': 1
            })
        
        if success > 0:
            print(f"[TomosManga] ✓ Tomo descargado exitosamente en: {manga_dir}")
            return {'dir': manga_dir, 'failed_chapters': failed_chapters}
        else:
            print(f"[TomosManga ERROR] No se pudo descargar el tomo")
            return {'dir': None, 'failed_chapters': failed_chapters}


def main():
    print("="*60)
    print("DESCARGADOR DE MANGA - TOMOSMANGA.COM")
    print("="*60)
    
    config = load_config()
    
    url = input("\nIngresa la URL del manga: ").strip()
    if not url:
        print("Error: Debes proporcionar una URL")
        sys.exit(1)
    
    downloader = TomosMangaDownloader(url, config)
    
    print(f"\nDescargando información de: {url}")
    
    html_content = downloader.get_page(url, use_selenium=True)
    if not html_content:
        print("Error: No se pudo descargar la página")
        sys.exit(1)
    
    manga_title = downloader.get_manga_title(html_content)
    print(f"Título del manga: {manga_title}")
    
    print("Parseando tomos...")
    volumes = downloader.parse_volumes(html_content)
    
    if not volumes:
        print("Error: No se encontraron tomos")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"TOMOS DETECTADOS: {len(volumes)}")
    print(f"{'='*60}")
    for idx, volume in enumerate(volumes, start=1):
        print(f"{idx}. {volume['name']}")
    
    print(f"\n{'='*60}")
    print("Opciones de selección:")
    print("  - Un tomo: 1")
    print("  - Varios tomos: 1,3,5 o 1-5")
    print("  - Todos los tomos: all")
    print(f"{'='*60}")
    
    selection = input("\nSelecciona los tomos a descargar: ").strip().lower()
    
    selected_volumes = []
    if selection == 'all':
        selected_volumes = volumes
    else:
        for part in selection.split(','):
            part = part.strip()
            if '-' in part:
                start, end = part.split('-')
                try:
                    start_idx = int(start.strip()) - 1
                    end_idx = int(end.strip())
                    selected_volumes.extend(volumes[start_idx:end_idx])
                except:
                    print(f"[ERROR] Rango inválido: {part}")
            else:
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(volumes):
                        selected_volumes.append(volumes[idx])
                except:
                    print(f"[ERROR] Índice inválido: {part}")
    
    if not selected_volumes:
        print("Error: No se seleccionaron tomos")
        sys.exit(1)
    
    output_dir = config['output_dir']
    safe_manga_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
    manga_dir = os.path.join(output_dir, safe_manga_title)
    os.makedirs(manga_dir, exist_ok=True)
    
    save_metadata(manga_title, [{'name': v['name'], 'chapters': [{'name': v['name'], 'url': v['url']}]} for v in volumes], manga_dir)
    
    print(f"\n{'='*60}")
    print("OBTENIENDO URLs DE FIRELOAD")
    print(f"{'='*60}\n")
    
    fireload_data_list = downloader.get_fireload_urls(selected_volumes)
    
    print(f"\n{'='*60}")
    print("INICIANDO DESCARGA")
    print(f"{'='*60}\n")
    
    parallel_chapters = config.get('parallel_chapters', 1)
    
    def download_single_chapter(idx, volume, fireload_data):
        downloaded, total, success, failed = downloader.download_chapter(
            volume['name'], fireload_data, manga_dir
        )
        return {
            'index': idx - 1,
            'success': success > 0,
            'volume_name': volume['name']
        }
    
    if parallel_chapters > 1 and len(selected_volumes) > 1:
        with downloader.print_lock:
            print(f"[TomosManga] Descargando en paralelo (máximo {parallel_chapters} simultáneos)")
        with ThreadPoolExecutor(max_workers=parallel_chapters) as executor:
            futures = {executor.submit(download_single_chapter, idx, volume, fireload_data): idx 
                      for idx, (volume, fireload_data) in enumerate(zip(selected_volumes, fireload_data_list), start=1)}
            
            for future in as_completed(futures):
                if downloader.cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    result = future.result()
                    with downloader.print_lock:
                        if result['success']:
                            print(f"[OK] Archivo descargado: {result['volume_name']}")
                        else:
                            print(f"[ERROR] No se pudo descargar el archivo: {result['volume_name']}")
                except Exception as e:
                    idx = futures[future]
                    with downloader.print_lock:
                        print(f"[ERROR] Error al descargar tomo {idx}: {e}")
    else:
        for idx, (volume, fireload_data) in enumerate(zip(selected_volumes, fireload_data_list), start=1):
            if downloader.cancelled:
                break
            result = download_single_chapter(idx, volume, fireload_data)
            if result['success']:
                print(f"[OK] Archivo descargado")
            else:
                print(f"[ERROR] No se pudo descargar el archivo")
            
            if idx < len(selected_volumes):
                time.sleep(config['delay_between_chapters'])
    
    print(f"\n{'='*60}")
    print("DESCARGA COMPLETADA")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
