import os
import sys
import subprocess
import requests
import tempfile
import time

class Updater:
    VERSION = "0.9.0"
    REPO_URL = "https://api.github.com/repos/ReiKatari/STORM_TRANSLATOR/releases/latest"

    @staticmethod
    def check_for_updates():
        try:
            response = requests.get(Updater.REPO_URL, timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get('tag_name', '')
                if latest_version and latest_version != Updater.VERSION:
                    return latest_version
        except Exception as e:
            print(f"Update check failed: {e}")
        return None

    @staticmethod
    def start_update(new_version):
        try:
            response = requests.get(Updater.REPO_URL, timeout=10)
            if response.status_code != 200:
                return False
            
            data = response.json()
            assets = data.get('assets', [])
            if not assets:
                return False
            
            # Find common executable or zip/py file
            asset = assets[0] # Simplification: pick first asset
            download_url = asset.get('browser_download_url')
            
            temp_dir = tempfile.gettempdir()
            new_file_path = os.path.join(temp_dir, asset.get('name'))
            
            # Download
            res = requests.get(download_url, stream=True)
            with open(new_file_path, 'wb') as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Create .bat for self-replacement
            app_path = os.path.abspath(sys.argv[0])
            app_dir = os.path.dirname(app_path)
            bat_path = os.path.join(temp_dir, "storm_update.bat")
            
            # Wait 2 seconds for app to close, copy, then restart
            bat_content = f"""
@echo off
timeout /t 2 /nobreak > nul
copy /y "{new_file_path}" "{app_path}"
start "" "{app_path}"
del "%~f0"
"""
            with open(bat_path, 'w', encoding='cp866') as f:
                f.write(bat_content)
                
            subprocess.Popen([bat_path], shell=True)
            return True
        except Exception as e:
            print(f"Update failed: {e}")
            return False
