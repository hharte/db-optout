import smtplib
import time
import argparse
import sys
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Import shared utilities
from utils import list_available_profiles, load_profile_config, download_csv_if_missing, get_valid_brokers_list

# Configuration
CSV_FILE_PATH = 'data/data-brokers.csv'
CSV_DOWNLOAD_URL = 'https://raw.githubusercontent.com/optery/optery-data-brokers-directory/refs/heads/master/data/data-brokers.csv'
CONFIG_FILE_PATH = 'config.json'

# Email Content Template
EMAIL_SUBJECT = "Request to Opt-Out and Delete Personal Information (CPRA)"
EMAIL_BODY_TEMPLATE = """To the Privacy Compliance Officer at {broker_name},

I am a resident of California and I am writing to exercise my rights under the California Privacy Rights Act (CPRA).

I hereby request that you:
1. Do not sell or share my personal information.
2. Delete any and all personal information you have collected about me.
3. Direct any service providers or contractors to delete my personal information from their records.
4. Add my name to your suppression list.

Please use the following information to locate my records:
Name: {full_name}
Current Address: {address}
Email: {email}
Phone: {phone}

Please confirm via email when this request has been processed.

Sincerely,
{full_name}
"""

def send_opt_out_emails(brokers, config, profile_name, start_idx=None, end_idx=None):
    """
    Connects to Gmail and sends opt-out emails to brokers within the specified index range.
    Handles Gmail daily limit errors gracefully.
    """
    # Extract config variables
    gmail_user = config['gmail_user']
    gmail_password = config['gmail_app_password']
    
    # Check for user_details specifically here as it is required for templating
    if 'user_details' not in config:
        print(f"# Error: 'user_details' missing in profile '{profile_name}'. Required for email template.")
        sys.exit(1)
    user_details = config['user_details']

    # Handle range logic
    if start_idx is None: 
        start_idx = 1
    if end_idx is None:
        end_idx = len(brokers)
        
    # Adjust for 0-based indexing list slicing
    slice_start = max(0, start_idx - 1)
    slice_end = min(len(brokers), end_idx)
    
    target_brokers = brokers[slice_start:slice_end]

    if not target_brokers:
        print(f"# No brokers found in range {start_idx}-{end_idx}.")
        return

    print(f"# Preparing to send {len(target_brokers)} emails (Brokers #{start_idx} to #{end_idx if end_idx < len(brokers) else len(brokers)})...")

    # Connect to SMTP
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        print("# Successfully connected to Gmail SMTP server")
    except Exception as e:
        print(f"# Failed to connect to Gmail: {e}")
        return

    emails_sent = 0
    
    try:
        for i, broker in enumerate(target_brokers):
            current_number = slice_start + i + 1
            broker_name = broker['name']
            broker_email = broker['email']

            msg = MIMEMultipart()
            msg['From'] = gmail_user
            msg['To'] = broker_email
            msg['Subject'] = EMAIL_SUBJECT

            body_content = EMAIL_BODY_TEMPLATE.format(
                broker_name=broker_name,
                **user_details
            )
            msg.attach(MIMEText(body_content, 'plain'))

            try:
                server.send_message(msg)
                emails_sent += 1
                print(f"# [{emails_sent}/{len(target_brokers)}] Sent to #{current_number}: {broker_name} ({broker_email})")
                
                # Sleep to avoid hitting Gmail rate limits
                time.sleep(2) 
                
            except Exception as e:
                error_message = str(e)
                
                # Check for Gmail Daily Limit Exceeded Error (5.4.5)
                if "5.4.5 Daily user sending limit exceeded" in error_message or \
                   "Daily user sending limit exceeded" in error_message:
                    
                    print("\n" + "="*80)
                    print("# CRITICAL: GMAIL DAILY SENDING LIMIT REACHED")
                    print(f"# Failed to send to #{current_number}: {broker_name}")
                    print("# Gmail has blocked further emails for approximately 24 hours.")
                    print("# STOPPING PROCESS NOW.")
                    print("="*80)
                    
                    # Suggest command to resume
                    resume_range = f"{current_number}-{end_idx}" if end_idx else f"{current_number}-"
                    print(f"\n# To continue processing tomorrow, run this command:")
                    print(f"python {os.path.basename(__file__)} --profile {profile_name} --range {resume_range}")
                    print("\n")
                    return # Exit function immediately

                # Standard error logging for other issues (e.g. bad email address)
                print(f"# Error sending to #{current_number} {broker_name}: {e}")

    finally:
        server.quit()
        print("# Operation complete. Connection closed.")

def parse_range(range_str):
    """Parses a string like '5-100', '435-', or '-50' into a tuple (start, end)."""
    try:
        if '-' not in range_str:
            val = int(range_str)
            return val, val # Handle single number case
        
        parts = range_str.split('-')
        
        # Handle range starting from beginning (e.g. '-50')
        if parts[0].strip() == '':
             start = 1
        else:
             start = int(parts[0])
        
        # Handle open-ended range (e.g., '435-')
        if parts[1].strip() == '':
            end = None
        else:
            end = int(parts[1])
            
        return start, end

    except ValueError:
        print("# Error: Invalid range format. Please use format like '1-50', '435-', or '-50'")
        sys.exit(1)

def list_broker_emails(brokers):
    """
    Prints a list of all brokers with their corresponding ID numbers.
    """
    print(f"{'ID':<5} {'Broker Name':<40} {'Email Address'}")
    print("-" * 80)
    for i, broker in enumerate(brokers, 1):
        print(f"{i:<5} {broker['name'][:38]:<40} {broker['email']}")
    print("-" * 80)
    print(f"Total Brokers: {len(brokers)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Data Broker Opt-Out Requests via Gmail.")
    parser.add_argument('--list', action='store_true', help="List all data broker emails from the CSV with ID numbers.")
    parser.add_argument('--range', type=str, help="Specify a range of brokers (e.g., '1-50', '435-', or '-50'). Uses the IDs shown in --list.")
    parser.add_argument('--profile', nargs='?', const='__LIST__', default='personal', 
                        help="Select a profile from config.json. If used without a value, lists all profiles. Default: 'personal'")

    args = parser.parse_args()

    # Check if user just wants to list profiles
    if args.profile == '__LIST__':
        list_available_profiles(CONFIG_FILE_PATH)
        sys.exit(0)

    # 1. Load Configuration
    app_config = load_profile_config(CONFIG_FILE_PATH, args.profile)

    # 2. Ensure data file is present
    download_csv_if_missing(CSV_FILE_PATH, CSV_DOWNLOAD_URL)
    
    # 3. Load data once
    all_brokers = get_valid_brokers_list(CSV_FILE_PATH)

    if args.list:
        list_broker_emails(all_brokers)
    else:
        start = None
        end = None
        
        if args.range:
            start, end = parse_range(args.range)
            end_display = f"#{end}" if end is not None else "the end of the list"
            confirmation_msg = f"You are about to send emails to brokers #{start} through {end_display} using profile '{args.profile}'."
        else:
            confirmation_msg = f"You are about to send emails to ALL {len(all_brokers)} brokers listed using profile '{args.profile}'."

        print(confirmation_msg)
        print(f"Sender Email: {app_config['gmail_user']}")
        
        confirm = input("Continue? (y/n): ")
        
        if confirm.lower() == 'y':
            # Pass profile name to support resume suggestion
            send_opt_out_emails(all_brokers, app_config, args.profile, start, end)
        else:
            print("# Operation cancelled.")
