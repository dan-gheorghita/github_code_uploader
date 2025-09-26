import os
import sys
import json
import glob
import datetime
import re
import hashlib
from github import Github
from pathlib import Path
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
HF_API_KEY = os.getenv('HF_API_KEY')
SOURCE_DIR = r'C:\Users\Dan\Downloads\Python codes'
UPLOAD_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'upload_history.json')

def load_upload_history():
    """Load the history of uploaded files"""
    if os.path.exists(UPLOAD_HISTORY_FILE):
        with open(UPLOAD_HISTORY_FILE, 'r') as f:
            return json.load(f)
    else:
        # Create empty history file if it doesn't exist
        empty_history = {
            "files": {},  # Store file hashes
            "upload_dates": []  # Store upload dates
        }
        with open(UPLOAD_HISTORY_FILE, 'w') as f:
            json.dump(empty_history, f, indent=4)
        return empty_history

def save_upload_history(history):
    """Save the history of uploaded files"""
    with open(UPLOAD_HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def get_file_hash(filepath):
    """Calculate SHA-256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def scan_for_sensitive_data(content):
    """Scan for potential sensitive data in the code"""
    # Patterns for sensitive data
    patterns = {
        'password': r'password\s*=\s*[\'"][^\'"]+[\'"]',
        'api_key': r'api[_-]key\s*=\s*[\'"][^\'"]+[\'"]',
        'token': r'token\s*=\s*[\'"][^\'"]+[\'"]',
        'secret': r'secret\s*=\s*[\'"][^\'"]+[\'"]',
        'credentials': r'credentials\s*=\s*[\'"][^\'"]+[\'"]'
    }
    
    censored_content = content
    found_sensitive = False
    
    for key, pattern in patterns.items():
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            found_sensitive = True
            censored_content = censored_content.replace(match.group(), f'{key}="[REDACTED]"')
    
    return found_sensitive, censored_content

def generate_description(file_content):
    """Generate a description of the code using Hugging Face's API"""
    try:
        client = InferenceClient(
            provider="fireworks-ai",
            model="meta-llama/Llama-3.1-8B-Instruct",
            api_key=HF_API_KEY
        )
        
        messages = [
            {
                "role": "system",
                "content": "You are a technical writer. Analyze the Python code and provide a clear, concise description of what it does."
            },
            {
                "role": "user",
                "content": f"Here's the Python code to analyze:\n\n{file_content}"
            }
        ]
        
        response = client.chat_completion(messages, max_tokens=200)
        return True, response.choices[0].message["content"].strip()
    except Exception as e:
        print(f"Error generating description: {e}")
        return False, str(e)

def add_code_comments(content):
    """Add descriptive comments to the code using Hugging Face's API"""
    try:
        client = InferenceClient(
            provider="fireworks-ai",
            model="meta-llama/Llama-3.1-8B-Instruct",
            api_key=HF_API_KEY
        )
        
        messages = [
            {
                "role": "system",
                "content": "You are a Python expert. Add descriptive comments to the code without changing the code itself. The output should only be the code with comments, without embedded marking, without without any additional explanations."
            },
            {
                "role": "user",
                "content": f"Here's the Python code to comment:\n\n{content}"
            }
        ]
        
        response = client.chat_completion(messages, max_tokens=2000)
        return True, response.choices[0].message["content"].strip()
    except Exception as e:
        print(f"Error adding comments: {e}")
        return False, content

def create_github_repository(g, filename):
    """Create a new GitHub repository for the file"""
    repo_name = os.path.splitext(filename)[0].lower().replace(' ', '_')
    try:
        user = g.get_user()
        repo = user.create_repo(repo_name, private=False)
        return repo
    except Exception as e:
        print(f"Error creating repository: {e}")
        return None

def main():
    if not GITHUB_TOKEN or not HF_API_KEY:
        print("Error: Missing required environment variables. Please set GITHUB_TOKEN and HF_API_KEY in .env file")
        sys.exit(1)

    # Initialize GitHub
    g = Github(GITHUB_TOKEN)
    
    # Load upload history
    history = load_upload_history()
    
    # Check if we already uploaded today
    today = datetime.date.today().isoformat()
    if today in history.get('upload_dates', []):
        print(f"Already uploaded a file today ({today})")
        return
        
    # Get all Python files
    python_files = glob.glob(os.path.join(SOURCE_DIR, '**', '*.py'), recursive=True)
    
    # Filter out files that have already been uploaded
    new_files = [f for f in python_files if get_file_hash(f) not in history.get('files', {}).values()]
    
    if not new_files:
        print("No new Python files to upload")
        return

    # Select one file for today
    file_to_upload = new_files[0]
    filename = os.path.basename(file_to_upload)
    
    print(f"Processing file: {filename}")
    
    # Read the file content
    with open(file_to_upload, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Scan for sensitive data
    has_sensitive, clean_content = scan_for_sensitive_data(content)
    if has_sensitive:
        print("Found and censored sensitive data in the code")
        content = clean_content
    
    # Add comments if needed
    if not re.search(r'^\s*#.*$', content, re.MULTILINE):
        print("Adding descriptive comments to the code...")
        success, result = add_code_comments(content)
        if not success:
            print(f"Failed to add comments to the code. Error: {result}")
            return
        content = result

    # Generate description before creating repository
    print("Generating code description...")
    success, description = generate_description(content)
    if not success:
        print(f"Failed to generate description. Error: {description}")
        return

    # Create repository and upload file
    repo = create_github_repository(g, filename)
    if repo:
        try:
            # Create README with description
            repo.create_file("README.md", 
                           "Initial commit", 
                           f"# {filename}\n\n{description}",
                           branch="main")
            
            # Upload the Python file
            repo.create_file(filename, 
                           "Add Python script", 
                           content,
                           branch="main")
            
            print(f"Successfully uploaded {filename} to GitHub")
            print(f"Repository URL: {repo.html_url}")

            # Only update history after successful upload
            print("Updating upload history...")
            if 'files' not in history:
                history['files'] = {}
            if 'upload_dates' not in history:
                history['upload_dates'] = []
            
            history['files'][file_to_upload] = get_file_hash(file_to_upload)
            history['upload_dates'].append(datetime.date.today().isoformat())
            save_upload_history(history)
            print("Upload history updated successfully")
            
        except Exception as e:
            print(f"Error uploading to GitHub: {e}")
            print("Upload history not updated due to error")
    else:
        print("Failed to create GitHub repository")

if __name__ == "__main__":
    main()
