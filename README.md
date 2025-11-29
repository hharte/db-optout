# Data Broker Opt-Out Automation

This Python script automates the process of sending opt-out requests to data brokers under the **California Privacy Rights Act (CPRA)**. It connects to a Gmail account via SMTP to send templated emails to a list of known data brokers.

## Features

* **Automated Mailing:** Iterates through a CSV list of data brokers and sends opt-out emails.

* **Profile Support:** Manage multiple identities (e.g., `personal`, `business`) via `config.json`.

* **Rate Limit Handling:** Automatically detects Gmail's daily sending limits (Error 5.4.5), pauses execution, and suggests a command to resume later.

* **Range Selection:** Send emails to specific batches of brokers (e.g., 1-50) to manage volume.

* **Auto-Update:** Downloads the latest data broker list from GitHub if missing.

## Prerequisites

* Python 3.x

* A Gmail account

* **Google App Password** (Required for SMTP access).

### How to Generate a Google App Password

To use this script, you **cannot** use your standard Gmail login password. You must generate a specific 16-character "App Password".

1. Go to your [Google Account Security page](https://myaccount.google.com/security).

2. Ensure **2-Step Verification** is enabled (this is required).

3. Go directly to the [App Passwords page](https://myaccount.google.com/apppasswords).

4. Type a name for the app (e.g., "Data Broker Opt-Out") and click **Create**.

5. Copy the 16-character password shown.

6. Paste this password into the `gmail_app_password` field in your `config.json`.

## Installation & Setup

1. Ensure `db-optout.py` and `utils.py` are in the same directory.

2. Create a `config.json` file in the same directory.

### Configuration (`config.json`)

You must define at least one profile. The `user_details` section populates the email template.

```json

{

 "profiles": {

   "personal": {

     "gmail_user": "your.email@gmail.com",

     "gmail_app_password": "your-16-digit-app-password",

     "user_details": {

       "full_name": "Jane Doe",

       "address": "123 Privacy Ln, Sacramento, CA",

       "email": "your.email@gmail.com",

       "phone": "(555) 123-4567"

     }

   }

 }

}

```

## Usage

Run the script from the command line.

### 1. List all available brokers

View the ID numbers and names of brokers in the database.

```bash

python db-optout.py --list

```

### 2. List available profiles

Check which profiles are configured in your JSON file.

```bash

python db-optout.py --profile

```

### 3. Send emails (Default)

Sends emails to **ALL** brokers using the default `personal` profile.

```bash

python db-optout.py

```

### 4. Send with a specific profile

Send emails using the "business" profile defined in `config.json`.

```bash

python db-optout.py --profile business

```

### 5. Send to a specific range

Useful for breaking up the task over multiple days.

```bash

# Send to brokers 1 through 50

python db-optout.py --range 1-50



# Send from broker 100 to the end of the list

python db-optout.py --range 100-

```

## Rate Limiting & Safety

The script sleeps for 2 seconds between emails to be polite to the SMTP server. If Gmail's daily sending limit is reached, the script will:

1. Stop sending immediately.

2. Log the error.

3. Print the exact command needed to resume from where it left off the next day.

## Attribution

This project uses data provided by [Optery](https://www.optery.com/).

The data broker email list is sourced from the [Optery Data Brokers Directory](https://github.com/optery/optery-data-brokers-directory).

## Disclaimer

**This Python script is a work in progress. Users should use it with caution and at their own risk.**

This script is provided for educational and privacy-protection purposes. Review the generated emails and target list to ensure they meet your specific legal requirements (CPRA, GDPR, etc.).
