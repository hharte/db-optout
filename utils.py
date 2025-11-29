import json
import os
import sys
import csv
import requests

def _load_json_file(config_path):
    """
    Helper to read and parse the JSON file.
    """
    if not os.path.exists(config_path):
        print(f"# Error: Configuration file '{config_path}' not found.")
        sys.exit(1)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"# Error: Failed to parse '{config_path}'. Please ensure it is valid JSON.")
        sys.exit(1)

def list_available_profiles(config_path):
    """
    Reads the config file and prints all available profile keys.
    """
    data = _load_json_file(config_path)
    
    if 'profiles' not in data or not data['profiles']:
        print(f"# No profiles found in '{config_path}'.")
        return

    print(f"{'Available Profiles':<20}")
    print("-" * 30)
    for profile in data['profiles']:
        print(f"- {profile}")
    print("-" * 30)

def load_profile_config(config_path, profile_name):
    """
    Loads a specific profile from the configuration JSON file.
    """
    data = _load_json_file(config_path)
    
    # Validate structure
    if 'profiles' not in data:
        print(f"# Error: 'profiles' key missing in '{config_path}'. Please update JSON structure.")
        sys.exit(1)

    if profile_name not in data['profiles']:
        print(f"# Error: Profile '{profile_name}' not found in '{config_path}'.")
        print(f"# Available profiles: {list(data['profiles'].keys())}")
        sys.exit(1)

    config = data['profiles'][profile_name]
    
    # Validate required keys common to both scripts
    # Note: 'user_details' is only strictly required for sending, but good to have.
    required_keys = ['gmail_user', 'gmail_app_password']
    for key in required_keys:
        if key not in config:
            print(f"# Error: Missing required key '{key}' in profile '{profile_name}'.")
            sys.exit(1)
            
    return config

def download_csv_if_missing(file_path, url):
    """
    Checks if the CSV file exists. If not, downloads it from the specified URL.
    """
    if os.path.exists(file_path):
        return

    print(f"# File '{file_path}' not found. Attempting to download from GitHub...")
    
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    try:
        response = requests.get(url)
        response.raise_for_status()
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
            
        print(f"# Successfully downloaded '{file_path}'.")
        
    except requests.exceptions.RequestException as e:
        print(f"# Error downloading file: {e}")
        sys.exit(1)

def get_valid_brokers_list(file_path):
    """
    Reads the CSV and returns a list of dictionaries for rows with valid emails.
    Filters out duplicate email addresses.
    """
    valid_brokers = []
    seen_emails = set() # Set to track unique emails

    try:
        with open(file_path, mode='r', encoding='utf-8', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                broker_name = row.get('title', 'Unknown Broker').strip()
                broker_email = row.get('email', '').strip()

                if broker_email and '@' in broker_email:
                    # Check for duplicates
                    if broker_email not in seen_emails:
                        valid_brokers.append({'name': broker_name, 'email': broker_email})
                        seen_emails.add(broker_email)
        
        return valid_brokers

    except FileNotFoundError:
        print(f"# Error: Could not find file at {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"# Error reading CSV file: {e}")
        sys.exit(1)
