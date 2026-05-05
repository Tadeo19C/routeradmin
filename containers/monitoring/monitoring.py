import requests
import time
from datetime import datetime
from subprocess import Popen, PIPE
import os
import uuid
import re

DEBUG = False
API_ADDRESS = "http://routerfleet:8001"

HOST_LIST_URL = f"{API_ADDRESS}/monitoring/export_router_list/"
UPDATE_STATUS_URL = f"{API_ADDRESS}/monitoring/update_router_status/"
CONFIG_TIMESTAMP_URL = f"{API_ADDRESS}/monitoring/router_config_timestamp/"
UPDATE_HOST_LIST_INTERVAL = 600  # How often to update the router list in seconds
MONITOR_INTERVAL = 60  # How often to monitor each router in seconds
MAX_NOTIFICATIONS_PER_MONITOR_INTERVAL = 50  # Throttle the number of notifications sent to the remote API
MIN_SLEEP_INTERVAL = 0.1  # Avoid CPU spikes if there are too many routers

# Global variables
host_list = []
host_list_update_timestamp = 0
notification_count = 0
current_router_config_timestamp = ''
remote_router_config_timestamp = ''
api_key = ''

def is_valid_address(address):
    """Basic validation for IP or domain name to prevent command injection."""
    if not address or len(address) > 255:
        return False
    # Only allow alphanumeric, dots, hyphens
    return bool(re.match(r"^[a-zA-Z0-9\.-]+$", address))

def safe_request(method, url, **kwargs):
    """Wrapper for requests with basic backoff and error handling."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, timeout=10, **kwargs)
            if response.status_code == 200:
                return response
            elif response.status_code == 403:
                print(f"{datetime.now()} - Auth Error (403). Waiting...")
            else:
                print(f"{datetime.now()} - HTTP {response.status_code} on {url}. Retrying {attempt+1}/{max_retries}...")
        except Exception as e:
            print(f"{datetime.now()} - Request Exception: {e}. Retrying {attempt+1}/{max_retries}...")
        
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Simple exponential backoff: 1, 2, 4s
    return None

def get_verbose_status(status):
    return "online" if status else "offline"

def get_api_key():
    api_key_temp = None
    api_file_path = "/app_secrets/monitoring_key"

    if os.path.exists(api_file_path) and os.path.isfile(api_file_path):
        with open(api_file_path, 'r') as api_file:
            api_file_content = api_file.read().strip()
            try:
                uuid_test = uuid.UUID(api_file_content)
                if str(uuid_test) == api_file_content:
                    api_key_temp = str(uuid_test)
            except:
                pass
    return api_key_temp

def update_router_config_timestamp():
    global remote_router_config_timestamp, api_key
    response = safe_request('GET', f"{CONFIG_TIMESTAMP_URL}?key={api_key}")
    if response:
        try:
            remote_router_config_timestamp_temp = response.json()['router_config']
            if remote_router_config_timestamp_temp != remote_router_config_timestamp:
                remote_router_config_timestamp = remote_router_config_timestamp_temp
                print(f"{datetime.now()} - Router config timestamp updated: {remote_router_config_timestamp}")
            else:
                print(f"{datetime.now()} - Router config timestamp unchanged: {remote_router_config_timestamp}")
        except Exception as e:
             print(f"{datetime.now()} - Error parsing config timestamp: {e}")
    return

def fetch_host_list():
    global host_list_update_timestamp, current_router_config_timestamp, remote_router_config_timestamp, api_key
    response = safe_request('GET', f"{HOST_LIST_URL}?key={api_key}")
    if response:
        try:
            host_list_update_timestamp = time.time()
            remote_router_config_timestamp = response.json()['router_config']
            current_router_config_timestamp = remote_router_config_timestamp
            return response.json()['router_list'], True
        except Exception as e:
            print(f"{datetime.now()} - Error parsing host list: {e}")
    return [], False

def update_host_status(uuid, status):
    global notification_count, api_key
    if notification_count >= MAX_NOTIFICATIONS_PER_MONITOR_INTERVAL:
        print(f"{datetime.now()} - Notification limit reached. Skipping Remote API update.")
        return
    
    response = safe_request('GET', f"{UPDATE_STATUS_URL}?key={api_key}&uuid={uuid}&status={get_verbose_status(status)}")
    if response:
        print(f"{datetime.now()} - Remote API Status updated for {uuid} to {get_verbose_status(status)}")
        notification_count += 1
        if uuid in host_list:
            host_list[uuid]['online'] = status

def check_host_status(host_uuid):
    address = host_list[host_uuid]['address']
    
    if not is_valid_address(address):
        print(f"{datetime.now()} - Security Alert: Invalid host address '{address}'. Skipping.")
        return

    command = ["fping", address]
    process = Popen(command, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    current_online = True if process.returncode == 0 else False
    
    if DEBUG:
        print(f"{datetime.now()} - {address} is {get_verbose_status(current_online)}")
    
    if current_online != host_list[host_uuid]['online']:
        print(f"{datetime.now()} - Status changed for {address} to {get_verbose_status(current_online)}")
        update_host_status(host_uuid, current_online)

def update_and_monitor():
    global host_list, host_list_update_timestamp, notification_count, current_router_config_timestamp, remote_router_config_timestamp, api_key
    api_key = get_api_key()
    if not api_key:
        print(f"{datetime.now()} - Monitoring key not found or invalid. Exiting...")
        exit(1)

    while True:
        update_router_config_timestamp()
        current_time = time.time()
        notification_count = 0
        update_required = False

        if not current_router_config_timestamp or current_router_config_timestamp != remote_router_config_timestamp:
            update_required = True
        if current_time - host_list_update_timestamp > UPDATE_HOST_LIST_INTERVAL:
            update_required = True

        if update_required:
            print(f"{datetime.now()} - Update required. Fetching host list...")
            new_host_list, fetch_host_list_success = fetch_host_list()
            if fetch_host_list_success:
                host_list = new_host_list
                print(f"{datetime.now()} - host list updated.")

        if host_list:
            # CPU Spike Protection
            interval = max(MIN_SLEEP_INTERVAL, MONITOR_INTERVAL / len(host_list))
            if DEBUG:
                print(f"{datetime.now()} - Monitoring hosts... Interval: {interval}s")
            
            for host_uuid in host_list:
                check_host_status(host_uuid)
                time.sleep(interval)
        else:
            print(f"{datetime.now()} - No hosts to monitor.")
            time.sleep(MONITOR_INTERVAL)

if __name__ == "__main__":
    print(f"{datetime.now()} - Monitoring container started, waiting for routerfleet container to start...")
    if not DEBUG:
        time.sleep(30)
    print(f"{datetime.now()} - Starting monitoring service...")
    update_and_monitor()


