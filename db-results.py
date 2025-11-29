import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
import re
import datetime
import time
import argparse
import sys

# Import shared utilities
from utils import list_available_profiles, load_profile_config, download_csv_if_missing, get_valid_brokers_list

# Configuration Constants
CONFIG_FILE_PATH = 'config.json'
CSV_FILE_PATH = 'data/data-brokers.csv'
CSV_DOWNLOAD_URL = 'https://raw.githubusercontent.com/optery/optery-data-brokers-directory/refs/heads/master/data/data-brokers.csv'
DEFAULT_SUBJECT_KEYWORD = "Request to Opt-Out" # Matches the subject in db-optout.py

class DataBrokerCleaner:
    def __init__(self, email_address, app_password, request_subject_keyword, broker_map, debug_mode=False):
        self.email_address = email_address
        self.password = app_password
        self.request_subject_keyword = request_subject_keyword
        self.broker_map = broker_map # Map of email -> ID
        self.debug_mode = debug_mode
        self.imap = None
        
        # Keywords for categorization
        self.keywords = {
            'bounce': [
                'mailer-daemon', 'delivery status notification', 'failure notice', 'undeliverable', 'blocked',
                'no longer monitored', 'email box is being retired'
            ],
            'web_only': [
                'fill out', 'web form', 'online form', 'visit our website', 'portal', 'click here', 'submit a request', 
                'use our form', 'opt-out page', 'set your preferences', 'submit a ticket', 'using this form', 
                'data subject requests can be filed at', 'information control link', 'complete the form', 
                'submit your request', 'opt-out process', 'do not sell my personal data', 'designated method', 
                'visit https', 'unauthorized channels', 'monitored for general privacy inquiries only', 
                'removals are now done on the websites', 'opt-out form'
            ],
            'success': [
                'confirmed', 'successfully removed', 'data has been deleted', 'request processed', 'completed', 
                'opted out', 'suppressed', 'records have been removed', 'information has been removed', 
                'already been deleted', 'suppression list', 'no longer available'
            ],
            'pending': [
                'received your request', 'verification', 'click to verify', 'ticket has been created', 'case number', 
                'reviewing', 'in process', 'under process', 'message has been received', 
                'message will be soon attended to', 'has been received', 'being reviewed', 'has been raised', 
                'acknowledgment of deletion'
            ],
            'not_found': [
                'not found', 'no record', 'unable to locate', 'no information', 'no personal information', 
                'do not maintain', 'no match found', 'no data found', 'no longer maintains', 
                'do not have your information', 'unable to pull up', 'does not possess', 'does not have any', 
                'no data on this individual', 'unable to find your account', 'could not locate', 'does not compile', 
                'does not have any database', 'do not have your profile information'
            ],
        }

        # Storage for categorized threads
        self.categories = {
            'failed': [],       # 1. Failed to send
            'web_required': [], # 2. Web form required
            'success': [],      # 3. Successful
            'no_response': [],  # 4. No response
            'pending': [],      # 5. Pending/Received
            'not_found': [],    # 6. Data not found
            'uncategorized': [] # 7. Other
        }

    def connect(self):
        print(f"Connecting to Gmail as {self.email_address}...")
        try:
            self.imap = imaplib.IMAP4_SSL("imap.gmail.com")
            self.imap.login(self.email_address, self.password)
            print("Login successful.")
        except Exception as e:
            print(f"Login failed: {e}")
            return False
        return True

    def decode_str(self, text):
        """Decodes email headers."""
        if not text:
            return ""
        decoded_list = decode_header(text)
        header_parts = []
        for content, encoding in decoded_list:
            if isinstance(content, bytes):
                if encoding:
                    try:
                        header_parts.append(content.decode(encoding))
                    except LookupError:
                        header_parts.append(content.decode('utf-8', errors='ignore'))
                else:
                    header_parts.append(content.decode('utf-8', errors='ignore'))
            else:
                header_parts.append(str(content))
        return "".join(header_parts)

    def get_email_body(self, msg):
        """Extracts plain text body from email message. Returns original case, whitespaced normalized."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get('Content-Disposition'))
                
                # Skip attachments
                if 'attachment' in cdispo:
                    continue
                    
                if ctype == 'text/plain':
                    try:
                        body += part.get_payload(decode=True).decode()
                    except:
                        pass
                elif ctype == 'text/html' and body == "":
                    # Fallback to HTML if no plain text, strip tags roughly
                    try:
                        html_content = part.get_payload(decode=True).decode()
                        # Replace <br> and other tags with space to prevent word concatenation
                        body += re.sub('<[^<]+?>', ' ', html_content)
                    except:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode()
            except:
                pass
        
        # Normalize whitespace: replaces newlines, tabs, and multiple spaces with a single space
        return " ".join(body.split())

    def extract_url(self, text):
        """Attempts to find the first http/https URL in the text."""
        # Simple regex to capture urls starting with http or https until a whitespace or common punctuation
        match = re.search(r'(https?://[^\s<>"]+)', text)
        if match:
            return match.group(1).rstrip('.,;:)')
        return None
    
    def extract_email_address(self, raw_header):
        """Extracts just the email address from 'Name <email@domain.com>'."""
        name, addr = parseaddr(raw_header)
        return addr.lower()

    def analyze_thread(self, thread_id, original_sent_msg):
        """Fetches all emails in a thread and categorizes the interaction."""
        
        # Search for all emails with this Thread ID (X-GM-THRID)
        # Note: We need to search 'All Mail' to find both sent and received items in one go
        self.imap.select('"[Gmail]/All Mail"', readonly=True)
        status, data = self.imap.search(None, f'(X-GM-THRID {thread_id})')
        
        # Initialize replies list
        replies = []
        
        # If thread data is found, process it
        if status == 'OK' and data[0]:
            msg_ids = data[0].split()
            
            # Fetch all messages in thread
            for mid in msg_ids:
                res, msg_data = self.imap.fetch(mid, '(RFC822)')
                if res != 'OK': continue
                
                msg = email.message_from_bytes(msg_data[0][1])
                sender = self.decode_str(msg.get("From"))
                
                # Skip our own emails in the thread
                if self.email_address in sender:
                    continue
                    
                replies.append(msg)

        # --- FALLBACK SEARCH ---
        # If no threaded replies found, search for unthreaded replies from this broker
        if not replies:
            clean_email = original_sent_msg.get('email_clean')
            if clean_email:
                try:
                    # Parse the date we sent the request
                    sent_dt = parsedate_to_datetime(original_sent_msg['date'])
                    # Format for IMAP (DD-Mon-YYYY) e.g., "01-Jan-2023"
                    since_str = sent_dt.strftime("%d-%b-%Y")
                    
                    # Search for emails FROM this broker SINCE the request date
                    fallback_query = f'(FROM "{clean_email}" SINCE "{since_str}")'
                    status, fallback_data = self.imap.search(None, fallback_query)
                    
                    if status == 'OK' and fallback_data[0]:
                        fallback_ids = fallback_data[0].split()
                        
                        # Fetch the latest one found
                        latest_id = fallback_ids[-1]
                        res, msg_data = self.imap.fetch(latest_id, '(RFC822)')
                        if res == 'OK':
                            found_msg = email.message_from_bytes(msg_data[0][1])
                            # Double check it's not from us (e.g. if we replied to ourselves)
                            if self.email_address not in self.decode_str(found_msg.get("From")):
                                replies.append(found_msg)
                except Exception as e:
                    # Fail silently on date parsing errors, defaults to no response
                    pass

        # Final check: if still no replies, mark as no response
        if not replies:
            self.categories['no_response'].append(original_sent_msg)
            return

        # Analyze the LATEST reply to determine status
        latest_reply = replies[-1]
        sender = self.decode_str(latest_reply.get("From")).lower()
        subject = self.decode_str(latest_reply.get("Subject")).lower()
        
        # Get body (raw for display, lower for processing)
        raw_body = self.get_email_body(latest_reply)
        body = raw_body.lower()
        
        # Determine Broker ID
        clean_to_email = self.extract_email_address(original_sent_msg['to'])
        broker_id = self.broker_map.get(clean_to_email, "???")
        
        info = {
            'id': broker_id,
            'broker': original_sent_msg['to'],
            'sent_date': original_sent_msg['date'],
            'reply_subject': subject,
            'reply_from': sender
        }

        # 1. Failed / Bounced
        if any(k in sender for k in self.keywords['bounce']) or 'postmaster' in sender:
            self.categories['failed'].append(info)
            return

        # 2. Web Form Required
        if any(k in body for k in self.keywords['web_only']):
            # Try to extract the link
            url = self.extract_url(body)
            if url:
                info['url'] = url
            self.categories['web_required'].append(info)
            return

        # 3. Success
        if any(k in body for k in self.keywords['success']):
            self.categories['success'].append(info)
            return

        # 5. Pending (Check before Uncategorized)
        if any(k in body for k in self.keywords['pending']):
            self.categories['pending'].append(info)
            return

        # 6. Not Found
        if any(k in body for k in self.keywords['not_found']):
            self.categories['not_found'].append(info)
            return

        # 7. Uncategorized
        if self.debug_mode:
            info['body_preview'] = raw_body
        self.categories['uncategorized'].append(info)

    def scan_requests(self):
        # Select Sent Items
        print("Scanning Sent Mail for deletion requests...")
        self.imap.select('"[Gmail]/Sent Mail"', readonly=True)
        
        # Search for sent emails with specific subject keyword
        # Date format for IMAP: "01-Jan-2023"
        since_date = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%d-%b-%Y")
        
        # Construct search query: Sent SINCE date AND Subject contains Keyword
        query = f'(SINCE "{since_date}" SUBJECT "{self.request_subject_keyword}")'
        status, messages = self.imap.search(None, query)
        
        if status != 'OK' or not messages[0]:
            print(f"No sent requests found matching keyword: '{self.request_subject_keyword}'")
            return

        sent_ids = messages[0].split()
        print(f"Found {len(sent_ids)} potential deletion requests. Analyzing threads...")

        processed_threads = set()

        for i, mid in enumerate(sent_ids):
            # Fetch headers and Gmail Thread ID
            res, msg_data = self.imap.fetch(mid, '(RFC822.HEADER X-GM-THRID)')
            
            # Parse Thread ID
            # Response looks like: b'123 (X-GM-THRID 17823823823 RFC822.HEADER ...)'
            response_text = msg_data[0][0].decode()
            thread_id_match = re.search(r'X-GM-THRID (\d+)', response_text)
            
            if not thread_id_match:
                continue
                
            thread_id = thread_id_match.group(1)
            
            # Skip if we already processed this conversation thread
            if thread_id in processed_threads:
                continue
            processed_threads.add(thread_id)
            
            # Parse Email Headers
            msg = email.message_from_bytes(msg_data[0][1])
            to_addr = self.decode_str(msg.get("To"))
            date_sent = self.decode_str(msg.get("Date"))
            
            # Check ID for No Response category immediately
            clean_to_email = self.extract_email_address(to_addr)
            broker_id = self.broker_map.get(clean_to_email, "???")

            original_msg = {
                'id': broker_id,
                'email_clean': clean_to_email, # Store for fallback
                'to': to_addr,
                'date': date_sent,
                'thread_id': thread_id
            }

            self.analyze_thread(thread_id, original_msg)
            
            # Rate limiting slightly to be nice to the API
            if i % 10 == 0:
                print(f"Processed {i+1}/{len(sent_ids)} requests...")
            time.sleep(0.2) 

        self.print_report()
        self.imap.logout()

    def print_report(self):
        print("\n" + "="*50)
        print("DATA REMOVAL REQUEST REPORT")
        print("="*50)
        
        categories = [
            ('SUCCESSFUL', self.categories['success']),
            ('DATA NOT FOUND', self.categories['not_found']),
            ('WEB FORM REQUIRED', self.categories['web_required']),
            ('PENDING / ACKNOWLEDGED', self.categories['pending']),
            ('FAILED TO SEND', self.categories['failed']),
            ('NO RESPONSE', self.categories['no_response']),
            ('UNCATEGORIZED ANSWERS', self.categories['uncategorized'])
        ]
        
        for name, items in categories:
            print(f"\n[{name}]: {len(items)}")
            
            # Sort items by ID if possible (handling '???' strings vs ints)
            try:
                items.sort(key=lambda x: int(x['id']) if isinstance(x['id'], int) or (isinstance(x['id'], str) and x['id'].isdigit()) else 999999)
            except:
                pass # Skip sorting if complex

            for item in items:
                # Formatting the display name
                if 'to' in item: # It was a no response item
                     print(f"  - [#{item['id']}] Sent to: {item['to']} on {item['date'][:16]}")
                else: # It has reply info
                     print(f"  - [#{item['id']}] Broker: {item['broker']}")
                     print(f"    Reply: {item['reply_subject']}")
                     
                     # Print extracted URL for Web Required items
                     if name == 'WEB FORM REQUIRED' and 'url' in item:
                         print(f"    Link: {item['url']}")

                     # Debug output for Uncategorized
                     if name == 'UNCATEGORIZED ANSWERS' and self.debug_mode and 'body_preview' in item:
                         print(f"    [DEBUG] Body Preview:\n    {'-'*40}")
                         # Indent the body slightly for readability
                         clean_body = item['body_preview'].replace('\n', '\n    ').strip()
                         print(f"    {clean_body}")
                         print(f"    {'-'*40}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze Gmail threads for Data Broker deletion request outcomes.")
    parser.add_argument('--profile', nargs='?', const='__LIST__', default='personal', 
                        help="Select a profile from config.json. If used without a value, lists all profiles. Default: 'personal'")
    parser.add_argument('--keyword', type=str, default=DEFAULT_SUBJECT_KEYWORD,
                        help=f"Subject keyword to search for in Sent Mail. Default: '{DEFAULT_SUBJECT_KEYWORD}'")
    parser.add_argument('--debug', action='store_true',
                        help="Enable debug mode to display the body text of uncategorized answers.")

    args = parser.parse_args()

    # Check if user just wants to list profiles
    if args.profile == '__LIST__':
        list_available_profiles(CONFIG_FILE_PATH)
        sys.exit(0)

    # Load Configuration
    app_config = load_profile_config(CONFIG_FILE_PATH, args.profile)
    
    # Load and map brokers
    download_csv_if_missing(CSV_FILE_PATH, CSV_DOWNLOAD_URL)
    brokers_list = get_valid_brokers_list(CSV_FILE_PATH)
    
    # Create email -> ID mapping
    # Index starts at 1 to match the output of db-optout.py
    broker_map = {b['email'].lower(): i for i, b in enumerate(brokers_list, 1)}
    
    email_user = app_config['gmail_user']
    app_password = app_config['gmail_app_password']

    print(f"Starting analysis for profile: {args.profile} ({email_user})")
    print(f"Loaded {len(brokers_list)} brokers from CSV.")
    print(f"Searching for sent emails with subject: '{args.keyword}'")
    
    tracker = DataBrokerCleaner(email_user, app_password, args.keyword, broker_map, debug_mode=args.debug)
    if tracker.connect():
        tracker.scan_requests()
