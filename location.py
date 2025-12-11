import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import time
import re
import os
import traceback
import logging
import subprocess
import webbrowser
import tempfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Setup logging to file and console
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('location_tracker.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def find_msedgedriver():
    """Find msedgedriver.exe on the system"""
    # Get the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Common locations for Edge WebDriver
    possible_paths = [
        # Same folder as this script (PRIORITY)
        os.path.join(script_dir, "msedgedriver.exe"),
        # Check PATH
        "msedgedriver.exe",
        # Current working directory
        os.path.join(os.getcwd(), "msedgedriver.exe"),
        # Default Edge driver locations
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge SxS\Application\msedgedriver.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedgedriver.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedgedriver.exe"),
        # User profile
        os.path.expanduser(r"~\msedgedriver.exe"),
        os.path.expanduser(r"~\Downloads\msedgedriver.exe"),
        os.path.expanduser(r"~\Desktop\msedgedriver.exe"),
    ]
    
    # Check each location
    for path in possible_paths:
        expanded_path = os.path.expandvars(path)
        if os.path.exists(expanded_path):
            logger.info(f"Found msedgedriver at: {expanded_path}")
            return expanded_path
    
    # Check if msedgedriver is in PATH using 'where' command
    try:
        result = subprocess.run(["where", "msedgedriver"], capture_output=True, text=True)
        if result.returncode == 0:
            path = result.stdout.strip().split('\n')[0]
            if os.path.exists(path):
                logger.info(f"Found msedgedriver in PATH: {path}")
                return path
    except:
        pass
    
    return None

class LocationTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Google Location Tracker")
        self.root.geometry("800x600")
        
        self.tracking = False
        self.locations = []
        self.driver = None
        self.update_interval = 30  # seconds between updates
        
        self.setup_ui()
    
    def setup_ui(self):
        # Control Frame
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Google Maps Shared Link Input
        ttk.Label(control_frame, text="Shared Google Maps Link:").grid(row=0, column=0, sticky=tk.W)
        self.link_entry = ttk.Entry(control_frame, width=60)
        self.link_entry.grid(row=0, column=1, padx=5)
        
        # Tracking Controls
        ttk.Button(control_frame, text="Start Tracking", 
                  command=self.start_tracking).grid(row=1, column=0, pady=10)
        ttk.Button(control_frame, text="Stop Tracking", 
                  command=self.stop_tracking).grid(row=1, column=1, pady=10)
        ttk.Button(control_frame, text="Export Data", 
                  command=self.export_data).grid(row=1, column=2, pady=10)
        ttk.Button(control_frame, text="Show Map", 
                  command=self.show_map).grid(row=1, column=3, pady=10)
        
        # Status Display
        self.status_label = ttk.Label(control_frame, text="Status: Ready")
        self.status_label.grid(row=2, column=0, columnspan=4, pady=5)
        
        # Current Location Display
        location_info_frame = ttk.LabelFrame(self.root, text="Current Location", padding="10")
        location_info_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)
        
        ttk.Label(location_info_frame, text="Latitude:").grid(row=0, column=0, sticky=tk.W)
        self.lat_label = ttk.Label(location_info_frame, text="--", font=('Arial', 12, 'bold'))
        self.lat_label.grid(row=0, column=1, sticky=tk.W, padx=10)
        
        ttk.Label(location_info_frame, text="Longitude:").grid(row=0, column=2, sticky=tk.W, padx=20)
        self.lng_label = ttk.Label(location_info_frame, text="--", font=('Arial', 12, 'bold'))
        self.lng_label.grid(row=0, column=3, sticky=tk.W, padx=10)
        
        ttk.Button(location_info_frame, text="Open in Browser", 
                  command=self.open_in_browser).grid(row=0, column=4, padx=20)
        
        # Log Display
        display_frame = ttk.Frame(self.root, padding="10")
        display_frame.grid(row=2, column=0, sticky=(tk.N, tk.S, tk.W, tk.E))
        
        self.location_text = scrolledtext.ScrolledText(display_frame, width=80, height=15)
        self.location_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        
        # Store current coordinates
        self.current_lat = None
        self.current_lng = None
    
    def open_in_browser(self):
        """Open current location in default browser"""
        if self.current_lat and self.current_lng:
            url = f"https://www.google.com/maps?q={self.current_lat},{self.current_lng}"
            webbrowser.open(url)
        else:
            messagebox.showwarning("No Location", "No location data available yet")
    
    def show_map(self):
        """Show all tracked locations on an interactive map"""
        if not self.locations:
            messagebox.showwarning("No Data", "No location data to display")
            return
        
        # Create HTML map with all locations
        html_content = self._generate_map_html()
        
        # Save to temp file and open in browser
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            temp_path = f.name
        
        webbrowser.open(f'file://{temp_path}')
        self.log(f"Map opened in browser with {len(self.locations)} location(s)")
    
    def _generate_map_html(self):
        """Generate HTML with OpenStreetMap showing all tracked locations"""
        # Get the latest location for centering
        latest = self.locations[-1] if self.locations else {'latitude': 0, 'longitude': 0}
        center_lat = latest['latitude']
        center_lng = latest['longitude']
        
        # Build markers JavaScript
        markers_js = ""
        for i, loc in enumerate(self.locations):
            markers_js += f"""
            L.marker([{loc['latitude']}, {loc['longitude']}])
                .addTo(map)
                .bindPopup('<b>Location #{i+1}</b><br>Time: {loc['timestamp']}<br>Lat: {loc['latitude']}<br>Lng: {loc['longitude']}');
            """
        
        # Build path if multiple locations
        path_js = ""
        if len(self.locations) > 1:
            coords = ", ".join([f"[{loc['latitude']}, {loc['longitude']}]" for loc in self.locations])
            path_js = f"""
            var path = L.polyline([{coords}], {{color: 'blue', weight: 3}}).addTo(map);
            """
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Location Tracker Map</title>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                body {{ margin: 0; padding: 0; }}
                #map {{ width: 100%; height: 100vh; }}
                .info-box {{
                    position: absolute;
                    top: 10px;
                    right: 10px;
                    z-index: 1000;
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                    font-family: Arial, sans-serif;
                }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <div class="info-box">
                <h3>Location Tracker</h3>
                <p><strong>Total Locations:</strong> {len(self.locations)}</p>
                <p><strong>Latest:</strong><br>
                Lat: {center_lat}<br>
                Lng: {center_lng}</p>
            </div>
            <script>
                var map = L.map('map').setView([{center_lat}, {center_lng}], 15);
                
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors'
                }}).addTo(map);
                
                {markers_js}
                {path_js}
            </script>
        </body>
        </html>
        """
        return html
    
    def start_tracking(self):
        shared_link = self.link_entry.get().strip()
        
        # Use default link if none provided
        if not shared_link:
            shared_link = "https://www.google.com/maps/@-1.3297194,37.9910964,807m/data=!3m2!1e3!4b1!4m4!7m3!1m1!1s109269683512603548875!2e2?authuser=0&entry=ttu&g_ep=EgoyMDI1MTIwOC4wIKXMDSoASAFQAw%3D%3D"
            self.link_entry.insert(0, shared_link)
        
        if not self.tracking:
            self.tracking = True
            self.status_label.config(text="Status: Initializing browser...")
            self.location_text.insert(tk.END, f"\n{'='*70}\n")
            self.location_text.insert(tk.END, f"Starting tracking at {datetime.now()}\n")
            self.location_text.insert(tk.END, f"Link: {shared_link}\n")
            self.location_text.insert(tk.END, f"{'='*70}\n\n")
            
            # Start tracking in separate thread
            thread = threading.Thread(target=self.track_location, args=(shared_link,))
            thread.daemon = True
            thread.start()
    
    def stop_tracking(self):
        self.tracking = False
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
        self.status_label.config(text="Status: Stopped")
        self.location_text.insert(tk.END, f"\n{'='*70}\n")
        self.location_text.insert(tk.END, f"Tracking stopped at {datetime.now()}\n")
        self.location_text.insert(tk.END, f"{'='*70}\n\n")
    
    def log(self, message, level="INFO"):
        """Log to both file and UI"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_message = f"[{timestamp}] {message}"
        
        if level == "DEBUG":
            logger.debug(message)
        elif level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)
        
        # Update UI
        self.root.after(0, lambda: self.location_text.insert(tk.END, log_message + "\n"))
        self.root.after(0, lambda: self.location_text.see(tk.END))
    
    def track_location(self, shared_link):
        try:
            self.log("=" * 50)
            self.log("TRACKING SESSION STARTED")
            self.log("=" * 50)
            
            # Validate URL format
            original_link = shared_link
            if not shared_link.startswith(('http://', 'https://')):
                shared_link = 'https://' + shared_link
            self.log(f"Original URL: {original_link}")
            self.log(f"Processed URL: {shared_link}")
            
            # Setup Edge options (Edge comes pre-installed on Windows)
            self.log("Configuring Edge browser options...")
            edge_options = Options()
            # edge_options.add_argument('--headless')  # Disabled for debugging
            edge_options.add_argument('--no-sandbox')
            edge_options.add_argument('--disable-dev-shm-usage')
            edge_options.add_argument('--disable-gpu')
            edge_options.add_argument('--ignore-certificate-errors')
            edge_options.add_argument('--disable-blink-features=AutomationControlled')
            edge_options.add_argument('--remote-debugging-port=9222')
            edge_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0')
            self.log("Edge options configured")
            
            # Initialize driver
            self.root.after(0, lambda: self.status_label.config(text="Status: Starting Edge browser..."))
            self.log("Looking for Edge WebDriver...")
            
            # Try to find existing driver first
            driver_path = find_msedgedriver()
            
            if driver_path:
                self.log(f"Found existing WebDriver at: {driver_path}")
            else:
                # Try webdriver-manager as fallback
                self.log("No local driver found, trying to download...")
                try:
                    from webdriver_manager.microsoft import EdgeChromiumDriverManager
                    driver_path = EdgeChromiumDriverManager().install()
                    self.log(f"Downloaded WebDriver to: {driver_path}")
                except Exception as e:
                    self.log(f"Could not download WebDriver: {e}", "ERROR")
                    self.log("Trying to use Edge without explicit driver path...", "INFO")
                    driver_path = None
            
            self.log("Creating Edge WebDriver service...")
            
            try:
                if driver_path:
                    service = Service(driver_path)
                    self.driver = webdriver.Edge(service=service, options=edge_options)
                else:
                    # Let Selenium find the driver automatically
                    self.driver = webdriver.Edge(options=edge_options)
                self.log("Edge browser started successfully")
            except Exception as e:
                self.log(f"ERROR starting Edge browser: {str(e)}", "ERROR")
                self.log(f"Traceback: {traceback.format_exc()}", "ERROR")
                self.log("\n" + "="*50, "ERROR")
                self.log("SOLUTION: Download Edge WebDriver manually:", "ERROR")
                self.log("1. Check your Edge version: edge://version", "ERROR")
                self.log("2. Download matching driver from: https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/", "ERROR")
                self.log("3. Extract msedgedriver.exe to a folder in your PATH", "ERROR")
                self.log("   (e.g., C:\\Windows or the same folder as this script)", "ERROR")
                self.log("="*50 + "\n", "ERROR")
                raise
            
            self.driver.set_page_load_timeout(60)
            self.log("Page load timeout set to 60 seconds")
            
            # Load the shared location page
            self.root.after(0, lambda: self.status_label.config(text="Status: Loading shared location..."))
            self.log(f"Navigating to URL: {shared_link}")
            
            try:
                self.driver.get(shared_link)
                self.log("Navigation initiated")
            except Exception as e:
                self.log(f"ERROR during navigation: {str(e)}", "ERROR")
                self.log(f"Traceback: {traceback.format_exc()}", "ERROR")
                raise
            
            self.log("Waiting 5 seconds for page load and redirects...")
            time.sleep(5)
            
            # Log the final URL after redirects
            final_url = self.driver.current_url
            self.log(f"Final URL after redirect: {final_url}")
            
            # Log page title
            try:
                page_title = self.driver.title
                self.log(f"Page title: {page_title}")
            except:
                self.log("Could not get page title")
            
            self.root.after(0, lambda: self.status_label.config(text="Status: Tracking active"))
            self.log("Tracking loop started")
            self.log("-" * 50)
            
            while self.tracking:
                try:
                    self.log("Extracting location data...")
                    
                    # Extract location data from URL or page elements
                    current_url = self.driver.current_url
                    self.log(f"Current URL: {current_url}", "DEBUG")
                    
                    # Try to extract coordinates from URL
                    coords = self.extract_coordinates_from_url(current_url)
                    self.log(f"Coordinates from URL: {coords}", "DEBUG")
                    
                    if not coords:
                        # Try to extract from page source
                        self.log("Trying to extract from page source...", "DEBUG")
                        coords = self.extract_coordinates_from_page()
                        self.log(f"Coordinates from page: {coords}", "DEBUG")
                    
                    if coords:
                        location_data = {
                            'timestamp': datetime.now().isoformat(),
                            'latitude': coords['lat'],
                            'longitude': coords['lng'],
                            'url': current_url
                        }
                        
                        self.locations.append(location_data)
                        
                        # Store current coordinates
                        self.current_lat = coords['lat']
                        self.current_lng = coords['lng']
                        
                        # Update location labels in UI
                        self.root.after(0, lambda lat=coords['lat']: self.lat_label.config(text=str(lat)))
                        self.root.after(0, lambda lng=coords['lng']: self.lng_label.config(text=str(lng)))
                        
                        # Update display
                        self.log(f"LOCATION FOUND:")
                        self.log(f"  Latitude:  {coords['lat']}")
                        self.log(f"  Longitude: {coords['lng']}")
                        self.log(f"  Google Maps: https://www.google.com/maps?q={coords['lat']},{coords['lng']}")
                        
                        # Update status
                        status_text = f"Status: Tracking | Last update: {datetime.now().strftime('%H:%M:%S')} | Total: {len(self.locations)}"
                        self.root.after(0, lambda text=status_text: self.status_label.config(text=text))
                    else:
                        self.log("Unable to extract coordinates from URL or page")
                        # Log page source snippet for debugging
                        try:
                            page_source = self.driver.page_source[:2000]
                            self.log(f"Page source preview (first 2000 chars):\n{page_source}", "DEBUG")
                        except Exception as e:
                            self.log(f"Could not get page source: {e}", "DEBUG")
                    
                    # Refresh page to get updated location
                    if self.tracking:
                        self.log(f"Waiting {self.update_interval} seconds before next update...")
                        time.sleep(self.update_interval)
                        self.log("Refreshing page...")
                        self.driver.refresh()
                        time.sleep(3)
                        self.log("-" * 30)
                
                except Exception as e:
                    self.log(f"Error in tracking loop: {str(e)}", "ERROR")
                    self.log(f"Traceback: {traceback.format_exc()}", "ERROR")
                    time.sleep(self.update_interval)
        
        except Exception as e:
            error_msg = f"Failed to initialize tracking: {str(e)}"
            self.log(error_msg, "ERROR")
            self.log(f"Full traceback:\n{traceback.format_exc()}", "ERROR")
            self.root.after(0, lambda: messagebox.showerror("Tracking Error", error_msg))
            self.root.after(0, lambda: self.status_label.config(text="Status: Error"))
            self.tracking = False
        
        finally:
            self.log("Cleaning up...")
            if self.driver:
                try:
                    self.driver.quit()
                    self.log("Browser closed")
                except Exception as e:
                    self.log(f"Error closing browser: {e}", "ERROR")
    
    def extract_coordinates_from_url(self, url):
        """Extract coordinates from Google Maps URL"""
        # Pattern 1: @lat,lng,zoom
        pattern1 = r'@(-?\d+\.\d+),(-?\d+\.\d+)'
        match1 = re.search(pattern1, url)
        if match1:
            return {'lat': float(match1.group(1)), 'lng': float(match1.group(2))}
        
        # Pattern 2: /maps/place/@lat,lng
        pattern2 = r'/maps/.*?@(-?\d+\.\d+),(-?\d+\.\d+)'
        match2 = re.search(pattern2, url)
        if match2:
            return {'lat': float(match2.group(1)), 'lng': float(match2.group(2))}
        
        # Pattern 3: ?q=lat,lng
        pattern3 = r'\?q=(-?\d+\.\d+),(-?\d+\.\d+)'
        match3 = re.search(pattern3, url)
        if match3:
            return {'lat': float(match3.group(1)), 'lng': float(match3.group(2))}
        
        return None
    
    def extract_coordinates_from_page(self):
        """Extract coordinates from page source"""
        try:
            # Try to find coordinates in page source
            page_source = self.driver.page_source
            
            # Look for coordinate patterns in the page
            patterns = [
                r'"lat":(-?\d+\.\d+).*?"lng":(-?\d+\.\d+)',
                r'\[(-?\d+\.\d+),(-?\d+\.\d+)\]',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, page_source)
                if match:
                    return {'lat': float(match.group(1)), 'lng': float(match.group(2))}
            
            return None
        except:
            return None
    
    def export_data(self):
        if self.locations:
            filename = f"location_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(self.locations, f, indent=2, default=str)
            messagebox.showinfo("Export Successful", f"Data exported to {filename}")
            self.status_label.config(text=f"Status: Data exported ({len(self.locations)} locations)")
        else:
            messagebox.showwarning("No Data", "No location data to export")

# Run the application
if __name__ == "__main__":
    root = tk.Tk()
    app = LocationTrackerApp(root)
    root.mainloop()