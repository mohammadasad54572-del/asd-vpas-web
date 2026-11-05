import os
import zipfile
import time
import threading
import subprocess
import re
import json
import base64
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import logging
import hashlib
import tempfile
import shutil
import stat

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8691115476:AAGUfVfXWGR_SUvtT7J1jx8uVSYq4NoOHJc"
ADMIN_USERS = set()

# ==================== HOSTING PLATFORM DETECTION ====================
# Auto-detect with FULL platform info (repo, username, account, etc.)

HOSTING_PLATFORM = os.environ.get('HOSTING_PLATFORM', 'auto')
PLATFORM_INFO = {}

if HOSTING_PLATFORM == 'auto':
    # RENDER DETECTION
    if os.environ.get('RENDER'):
        HOSTING_PLATFORM = 'render'
        PLATFORM_INFO = {
            'platform': 'Render',
            'emoji': '🟢',
            'service_name': os.environ.get('RENDER_SERVICE_NAME', 'Unknown'),
            'service_slug': os.environ.get('RENDER_SERVICE_SLUG', 'Unknown'),
            'owner': os.environ.get('RENDER_OWNER', 'Unknown'),
            'repo': os.environ.get('RENDER_GIT_REPO', 'Unknown'),
            'branch': os.environ.get('RENDER_GIT_BRANCH', 'Unknown'),
            'commit': os.environ.get('RENDER_GIT_COMMIT', 'Unknown')[:8],
            'region': os.environ.get('RENDER_REGION', 'Unknown'),
            'instance_id': os.environ.get('RENDER_INSTANCE_ID', 'Unknown'),
            'disk_name': os.environ.get('RENDER_DISK_NAME', 'None'),
            'root': os.environ.get('RENDER_PROJECT_DIR', '/app')
        }

    # RAILWAY DETECTION
    elif os.environ.get('RAILWAY_ENVIRONMENT'):
        HOSTING_PLATFORM = 'railway'
        PLATFORM_INFO = {
            'platform': 'Railway',
            'emoji': '🚂',
            'project_name': os.environ.get('RAILWAY_PROJECT_NAME', 'Unknown'),
            'project_id': os.environ.get('RAILWAY_PROJECT_ID', 'Unknown'),
            'environment': os.environ.get('RAILWAY_ENVIRONMENT', 'Unknown'),
            'environment_id': os.environ.get('RAILWAY_ENVIRONMENT_ID', 'Unknown'),
            'service_name': os.environ.get('RAILWAY_SERVICE_NAME', 'Unknown'),
            'service_id': os.environ.get('RAILWAY_SERVICE_ID', 'Unknown'),
            'deployment_id': os.environ.get('RAILWAY_DEPLOYMENT_ID', 'Unknown')[:8],
            'replica_id': os.environ.get('RAILWAY_REPLICA_ID', 'Unknown'),
            'root': os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '/app')
        }

    # REPLIT DETECTION
    elif os.environ.get('REPL_ID'):
        HOSTING_PLATFORM = 'replit'
        PLATFORM_INFO = {
            'platform': 'Replit',
            'emoji': '🌀',
            'repl_id': os.environ.get('REPL_ID', 'Unknown'),
            'repl_slug': os.environ.get('REPL_SLUG', 'Unknown'),
            'repl_owner': os.environ.get('REPL_OWNER', 'Unknown'),
            'repl_owner_id': os.environ.get('REPL_OWNER_ID', 'Unknown'),
            'repl_image': os.environ.get('REPL_IMAGE', 'Unknown'),
            'cluster': os.environ.get('REPL_CLUSTER', 'Unknown'),
            'root': os.environ.get('REPL_HOME', '/home/runner')
        }

    # HEROKU DETECTION
    elif os.environ.get('HEROKU_APP_NAME'):
        HOSTING_PLATFORM = 'heroku'
        PLATFORM_INFO = {
            'platform': 'Heroku',
            'emoji': '💜',
            'app_name': os.environ.get('HEROKU_APP_NAME', 'Unknown'),
            'dyno': os.environ.get('DYNO', 'Unknown'),
            'release_version': os.environ.get('HEROKU_RELEASE_VERSION', 'Unknown'),
            'slug_commit': os.environ.get('HEROKU_SLUG_COMMIT', 'Unknown')[:8],
            'stack': os.environ.get('STACK', 'Unknown'),
            'root': '/app'
        }

    # KOYEB DETECTION
    elif os.environ.get('KOYEB_APP_NAME'):
        HOSTING_PLATFORM = 'koyeb'
        PLATFORM_INFO = {
            'platform': 'Koyeb',
            'emoji': '🚀',
            'app_name': os.environ.get('KOYEB_APP_NAME', 'Unknown'),
            'service_name': os.environ.get('KOYEB_SERVICE_NAME', 'Unknown'),
            'service_type': os.environ.get('KOYEB_SERVICE_TYPE', 'Unknown'),
            'root': '/app'
        }

    # FLY.IO DETECTION
    elif os.environ.get('FLY_APP_NAME'):
        HOSTING_PLATFORM = 'fly'
        PLATFORM_INFO = {
            'platform': 'Fly.io',
            'emoji': '🪰',
            'app_name': os.environ.get('FLY_APP_NAME', 'Unknown'),
            'alloc_id': os.environ.get('FLY_ALLOC_ID', 'Unknown'),
            'region': os.environ.get('FLY_REGION', 'Unknown'),
            'vm_size': os.environ.get('FLY_VM_SIZE', 'Unknown'),
            'root': '/app'
        }

    # GITHUB CODESPACES DETECTION
    elif os.environ.get('CODESPACE_NAME'):
        HOSTING_PLATFORM = 'codespace'
        PLATFORM_INFO = {
            'platform': 'GitHub Codespaces',
            'emoji': '💻',
            'codespace_name': os.environ.get('CODESPACE_NAME', 'Unknown'),
            'repository': os.environ.get('GITHUB_REPOSITORY', 'Unknown'),
            'repo_owner': os.environ.get('GITHUB_REPOSITORY_OWNER', 'Unknown'),
            'actor': os.environ.get('GITHUB_ACTOR', 'Unknown'),
            'sha': os.environ.get('GITHUB_SHA', 'Unknown')[:8],
            'ref': os.environ.get('GITHUB_REF_NAME', 'Unknown'),
            'root': '/workspaces'
        }

    # GITPOD DETECTION
    elif os.environ.get('GITPOD_WORKSPACE_ID'):
        HOSTING_PLATFORM = 'gitpod'
        PLATFORM_INFO = {
            'platform': 'Gitpod',
            'emoji': '🌿',
            'workspace_id': os.environ.get('GITPOD_WORKSPACE_ID', 'Unknown'),
            'workspace_cluster_host': os.environ.get('GITPOD_WORKSPACE_CLUSTER_HOST', 'Unknown'),
            'owner': os.environ.get('GITPOD_GIT_USER_NAME', 'Unknown'),
            'email': os.environ.get('GITPOD_GIT_USER_EMAIL', 'Unknown'),
            'root': '/workspace'
        }

    # VPS / LOCAL / DEFAULT
    else:
        HOSTING_PLATFORM = 'vps'
        PLATFORM_INFO = {
            'platform': 'VPS / Local',
            'emoji': '🐧',
            'hostname': os.uname().nodename if hasattr(os, 'uname') else 'Unknown',
            'user': os.environ.get('USER', 'Unknown'),
            'home': os.environ.get('HOME', 'Unknown'),
            'root': '/'
        }

# Set root directory
ROOT_DIRECTORY = PLATFORM_INFO.get('root', '/')
SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# ==================== SETTINGS ====================
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_ZIP_SIZE = 50 * 1024 * 1024
MAX_FILES_PER_PAGE = 50
MAX_PREVIEW_CHARS = 4000
ZIP_TIMEOUT = 30
SEARCH_RESULTS_LIMIT = 20

# User states
user_editing = {}
user_current_path = {}
user_page = {}
path_cache = {}
user_favorites = {}
user_search_results = {}
user_awaiting = {}
user_roles = {}
user_activity_log = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== UTILITY FUNCTIONS ====================

def get_size_format(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024*1024):.2f} MB"
    else:
        return f"{size / (1024*1024*1024):.2f} GB"

def get_short_id(path):
    return hashlib.md5(path.encode()).hexdigest()[:8]

def read_file_content(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {str(e)}"

def save_file_content(file_path, content):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, "Saved successfully!"
    except Exception as e:
        return False, f"Error: {str(e)}"

def get_file_icon(filename):
    ext = os.path.splitext(filename)[1].lower()
    icons = {
        '.py': '🐍', '.js': '📜', '.ts': '📘', '.html': '🌐', '.htm': '🌐',
        '.css': '🎨', '.scss': '🎨', '.sass': '🎨', '.json': '📋', '.xml': '📰',
        '.txt': '📄', '.md': '📝', '.rst': '📝', '.yml': '⚙️', '.yaml': '⚙️',
        '.env': '🔐', '.ini': '⚙️', '.cfg': '⚙️', '.conf': '⚙️',
        '.sh': '🔧', '.bash': '🔧', '.zsh': '🔧', '.fish': '🔧',
        '.sql': '🗄️', '.db': '🗄️', '.sqlite': '🗄️',
        '.zip': '📦', '.tar': '📦', '.gz': '📦', '.rar': '📦', '.7z': '📦',
        '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️', '.svg': '🖼️', '.webp': '🖼️',
        '.mp4': '🎬', '.avi': '🎬', '.mkv': '🎬', '.mov': '🎬',
        '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵', '.aac': '🎵',
        '.pdf': '📕', '.doc': '📘', '.docx': '📘', '.xls': '📗', '.xlsx': '📗', '.ppt': '📙', '.pptx': '📙',
        '.csv': '📊', '.tsv': '📊',
        '.dockerfile': '🐳', '.gitignore': '🔀', '.lock': '🔒', '.log': '📋',
        '.go': '🔵', '.rs': '🦀', '.java': '☕', '.kt': '🔶', '.cpp': '⚡', '.c': '⚡', '.h': '⚡',
        '.php': '🐘', '.rb': '💎', '.swift': '🐦', '.dart': '🎯', '.lua': '🌙',
    }
    return icons.get(ext, '📄')

def is_editable_file(filename):
    editable = ['.py', '.js', '.ts', '.html', '.htm', '.css', '.scss', '.sass', '.json', '.xml',
                '.txt', '.md', '.rst', '.yml', '.yaml', '.env', '.ini', '.cfg', '.conf',
                '.sh', '.bash', '.zsh', '.fish', '.sql', '.csv', '.tsv', '.dockerfile', '.gitignore',
                '.go', '.rs', '.java', '.kt', '.cpp', '.c', '.h', '.php', '.rb', '.swift', '.dart', '.lua']
    ext = os.path.splitext(filename)[1].lower()
    return ext in editable

def get_file_permissions(path):
    try:
        mode = os.stat(path).st_mode
        perms = stat.filemode(mode)
        return perms
    except:
        return "?????????"

def get_file_details(path):
    try:
        stat_info = os.stat(path)
        size = get_size_format(stat_info.st_size)
        perms = stat.filemode(stat_info.st_mode)
        modified = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        created = datetime.fromtimestamp(stat_info.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
        return size, perms, modified, created
    except:
        return "N/A", "?????????", "N/A", "N/A"

def run_terminal_command(command, cwd=None):
    try:
        dangerous = ['rm -rf /', 'mkfs', 'dd if=', ':(){ :|:& };:', 'chmod -R 777 /']
        for d in dangerous:
            if d in command:
                return False, f"Dangerous command blocked: {d}"
        result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if len(output) > 4000:
            output = output[:4000] + "\n... (truncated)"
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out (30s limit)"
    except Exception as e:
        return False, f"Error: {str(e)}"

def create_zip_of_folder(folder_path, output_path):
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                    zipf.write(file_path, arcname)
        return True
    except Exception as e:
        logger.error(f"Error creating zip: {e}")
        return False

def log_activity(user_id, action):
    if user_id not in user_activity_log:
        user_activity_log[user_id] = []
    user_activity_log[user_id].append((datetime.now().strftime('%Y-%m-%d %H:%M:%S'), action))
    if len(user_activity_log[user_id]) > 100:
        user_activity_log[user_id] = user_activity_log[user_id][-100:]

def get_platform_display_info():
    """Get formatted platform info for display"""
    p = PLATFORM_INFO
    emoji = p.get('emoji', '🖥️')
    platform = p.get('platform', 'Unknown')

    info_lines = [f"{emoji} *{platform}*"]

    if HOSTING_PLATFORM == 'render':
        info_lines.extend([
            f"📦 *Service:* `{p.get('service_name', 'N/A')}`",
            f"👤 *Owner:* `{p.get('owner', 'N/A')}`",
            f"📁 *Repo:* `{p.get('repo', 'N/A')}`",
            f"🌿 *Branch:* `{p.get('branch', 'N/A')}`",
            f"🔖 *Commit:* `{p.get('commit', 'N/A')}`",
            f"🌍 *Region:* `{p.get('region', 'N/A')}`",
            f"🆔 *Instance:* `{p.get('instance_id', 'N/A')[:20]}...`",
        ])
    elif HOSTING_PLATFORM == 'railway':
        info_lines.extend([
            f"📦 *Project:* `{p.get('project_name', 'N/A')}`",
            f"🔧 *Service:* `{p.get('service_name', 'N/A')}`",
            f"🌍 *Environment:* `{p.get('environment', 'N/A')}`",
            f"🆔 *Deployment:* `{p.get('deployment_id', 'N/A')}`",
            f"🔄 *Replica:* `{p.get('replica_id', 'N/A')[:20]}...`",
        ])
    elif HOSTING_PLATFORM == 'replit':
        info_lines.extend([
            f"📦 *Repl:* `{p.get('repl_slug', 'N/A')}`",
            f"👤 *Owner:* `{p.get('repl_owner', 'N/A')}`",
            f"🆔 *ID:* `{p.get('repl_id', 'N/A')[:20]}...`",
            f"🖼️ *Image:* `{p.get('repl_image', 'N/A')}`",
            f"☸️ *Cluster:* `{p.get('cluster', 'N/A')}`",
        ])
    elif HOSTING_PLATFORM == 'heroku':
        info_lines.extend([
            f"📦 *App:* `{p.get('app_name', 'N/A')}`",
            f"🔄 *Dyno:* `{p.get('dyno', 'N/A')}`",
            f"🔖 *Release:* `{p.get('release_version', 'N/A')}`",
            f"🔖 *Commit:* `{p.get('slug_commit', 'N/A')}`",
            f"📚 *Stack:* `{p.get('stack', 'N/A')}`",
        ])
    elif HOSTING_PLATFORM == 'koyeb':
        info_lines.extend([
            f"📦 *App:* `{p.get('app_name', 'N/A')}`",
            f"🔧 *Service:* `{p.get('service_name', 'N/A')}`",
            f"📋 *Type:* `{p.get('service_type', 'N/A')}`",
        ])
    elif HOSTING_PLATFORM == 'fly':
        info_lines.extend([
            f"📦 *App:* `{p.get('app_name', 'N/A')}`",
            f"🌍 *Region:* `{p.get('region', 'N/A')}`",
            f"💻 *VM:* `{p.get('vm_size', 'N/A')}`",
            f"🆔 *Alloc:* `{p.get('alloc_id', 'N/A')[:20]}...`",
        ])
    elif HOSTING_PLATFORM == 'codespace':
        info_lines.extend([
            f"📦 *Codespace:* `{p.get('codespace_name', 'N/A')}`",
            f"📁 *Repo:* `{p.get('repository', 'N/A')}`",
            f"👤 *Owner:* `{p.get('repo_owner', 'N/A')}`",
            f"👤 *Actor:* `{p.get('actor', 'N/A')}`",
            f"🌿 *Branch:* `{p.get('ref', 'N/A')}`",
            f"🔖 *SHA:* `{p.get('sha', 'N/A')}`",
        ])
    elif HOSTING_PLATFORM == 'gitpod':
        info_lines.extend([
            f"📦 *Workspace:* `{p.get('workspace_id', 'N/A')[:30]}...`",
            f"☸️ *Cluster:* `{p.get('workspace_cluster_host', 'N/A')}`",
            f"👤 *User:* `{p.get('owner', 'N/A')}`",
            f"📧 *Email:* `{p.get('email', 'N/A')}`",
        ])
    else:  # VPS
        info_lines.extend([
            f"🖥️ *Hostname:* `{p.get('hostname', 'N/A')}`",
            f"👤 *User:* `{p.get('user', 'N/A')}`",
            f"🏠 *Home:* `{p.get('home', 'N/A')}`",
        ])

    info_lines.extend([
        f"📂 *Root:* `{ROOT_DIRECTORY}`",
        f"📁 *Script:* `{SCRIPT_DIRECTORY}`",
    ])

    return "\n".join(info_lines)

# ==================== START COMMAND ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_current_path[chat_id] = ROOT_DIRECTORY
    user_page[chat_id] = 0

    if chat_id in user_editing:
        del user_editing[chat_id]
    if chat_id in user_awaiting:
        del user_awaiting[chat_id]

    if user_id not in user_roles:
        user_roles[user_id] = 'user'

    log_activity(user_id, 'started bot')

    platform_display = get_platform_display_info()

    welcome_text = (
        "🚀 *MEGA ULTIMATE FILE MANAGER* 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{platform_display}\n\n"
        "⚡ *Quick Commands:*\n"
        "`/allzip` - ⚡ Zip project (30s)\n"
        "`/search <name>` - 🔍 Find files\n"
        "`/terminal <cmd>` - 🖥️ Run commands\n"
        "`/newfile <name>` - 📄 Create file\n"
        "`/newfolder <name>` - 📁 Create folder\n"
        "`/platform` - 🖥️ Full platform info\n"
        "`/favorites` - ⭐ Saved locations\n"
        "`/help` - ❓ Full help\n\n"
        "👇 *Browse your files:*"
    )

    await update.message.reply_text(welcome_text, parse_mode='Markdown')
    await show_current_folder(update, context, ROOT_DIRECTORY)

# ==================== SHOW FOLDER ====================

async def show_current_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, path, page=0):
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.from_user.id

    try:
        items = os.listdir(path)
        folders = []
        files = []

        for item in items:
            item_path = os.path.join(path, item)
            try:
                if os.path.isdir(item_path):
                    folders.append(item)
                else:
                    file_size = os.path.getsize(item_path)
                    files.append((item, file_size))
            except (PermissionError, OSError):
                continue

        folders.sort(key=str.lower)
        files.sort(key=lambda x: x[0].lower())

        total_items = len(folders) + len(files)
        items_per_page = MAX_FILES_PER_PAGE
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page

        all_items = [(f, None, 'folder') for f in folders] + [(f, s, 'file') for f, s in files]
        paginated_items = all_items[start_idx:end_idx]
        total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)

        keyboard = []

        nav_buttons = []
        if path != ROOT_DIRECTORY:
            parent_path = os.path.dirname(path)
            parent_id = get_short_id(parent_path)
            path_cache[parent_id] = parent_path
            nav_buttons.append(InlineKeyboardButton("⬆️", callback_data=f"op:{parent_id}"))

        home_id = get_short_id(ROOT_DIRECTORY)
        path_cache[home_id] = ROOT_DIRECTORY
        nav_buttons.append(InlineKeyboardButton("🏠", callback_data=f"op:{home_id}"))

        if path != ROOT_DIRECTORY:
            fav_id = get_short_id(path)
            path_cache[fav_id] = path
            nav_buttons.append(InlineKeyboardButton("⭐", callback_data=f"fav:{fav_id}"))

        search_id = get_short_id(path)
        path_cache[search_id] = path
        nav_buttons.append(InlineKeyboardButton("🔍", callback_data=f"search_here:{search_id}"))

        keyboard.append(nav_buttons)

        for item, size, item_type in paginated_items:
            item_path = os.path.join(path, item)
            item_id = get_short_id(item_path)
            path_cache[item_id] = item_path

            if item_type == 'folder':
                keyboard.append([
                    InlineKeyboardButton(f"📁 {item}/", callback_data=f"op:{item_id}"),
                    InlineKeyboardButton("📦", callback_data=f"zp:{item_id}"),
                    InlineKeyboardButton("🗑️", callback_data=f"del:{item_id}")
                ])
            else:
                icon = get_file_icon(item)
                editable = is_editable_file(item)

                row = [InlineKeyboardButton(f"{icon} {item}", callback_data=f"vw:{item_id}")]

                if editable:
                    row.append(InlineKeyboardButton("✏️", callback_data=f"ed:{item_id}"))
                else:
                    row.append(InlineKeyboardButton("📋", callback_data=f"vw:{item_id}"))

                row.append(InlineKeyboardButton("⬇️", callback_data=f"dl:{item_id}"))
                keyboard.append(row)

        if total_pages > 1:
            page_buttons = []
            if page > 0:
                page_id = get_short_id(f"{path}|{page-1}")
                path_cache[page_id] = f"{path}|{page-1}"
                page_buttons.append(InlineKeyboardButton("◀️", callback_data=f"pg:{page_id}"))

            page_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))

            if page < total_pages - 1:
                page_id = get_short_id(f"{path}|{page+1}")
                path_cache[page_id] = f"{path}|{page+1}"
                page_buttons.append(InlineKeyboardButton("▶️", callback_data=f"pg:{page_id}"))

            keyboard.append(page_buttons)

        action_buttons = []
        if files:
            zip_id = get_short_id(path)
            path_cache[zip_id] = path
            action_buttons.append(InlineKeyboardButton("📦 ZIP", callback_data=f"zp:{zip_id}"))

        allzip_id = get_short_id(path)
        path_cache[allzip_id] = path
        action_buttons.append(InlineKeyboardButton("⚡ ALLZIP", callback_data=f"az:{allzip_id}"))
        action_buttons.append(InlineKeyboardButton("🆕 NEW", callback_data=f"new_menu:{allzip_id}"))
        action_buttons.append(InlineKeyboardButton("ℹ️", callback_data="info"))
        keyboard.append(action_buttons)

        total_size = sum(size for _, size in files)
        py_files = sum(1 for f, _ in files if f.endswith('.py'))
        editable_files = sum(1 for f, _ in files if is_editable_file(f))

        folder_name = os.path.basename(path) or 'Root'

        message_text = (
            f"📍 *{folder_name}*\n"
            f"`{path}`\n\n"
            f"📊 {len(folders)} 📁 | {len(files)} 📄 | {editable_files} ✏️ | {py_files} 🐍\n"
            f"💾 Total: {get_size_format(total_size)} | 📄 Page {page+1}/{total_pages}"
        )

        if total_items == 0:
            message_text += "\n\n⚠️ *Empty folder*"

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=message_text, parse_mode='Markdown', reply_markup=reply_markup
                )
            except:
                await update.callback_query.message.reply_text(
                    text=message_text, parse_mode='Markdown', reply_markup=reply_markup
                )
            await update.callback_query.answer()
        else:
            await update.message.reply_text(
                text=message_text, parse_mode='Markdown', reply_markup=reply_markup
            )

    except PermissionError:
        error_text = f"❌ *Permission Denied*\n`{path}`"
        if update.callback_query:
            await update.callback_query.edit_message_text(text=error_text, parse_mode='Markdown')
            await update.callback_query.answer()
        else:
            await update.message.reply_text(text=error_text, parse_mode='Markdown')
    except Exception as e:
        error_text = f"❌ *Error:* `{str(e)}`"
        if update.callback_query:
            await update.callback_query.edit_message_text(text=error_text, parse_mode='Markdown')
            await update.callback_query.answer()
        else:
            await update.message.reply_text(text=error_text, parse_mode='Markdown')

# ==================== /ALLZIP COMMAND ====================

async def allzip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_path = user_current_path.get(chat_id, ROOT_DIRECTORY)
    folder_name = os.path.basename(current_path) or "project"

    zip_filename = f"{folder_name}_{HOSTING_PLATFORM}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = os.path.join(tempfile.gettempdir(), zip_filename)

    start_time = time.time()

    status_msg = await update.message.reply_text(
        "⚡ *ALLZIP STARTED* ⚡\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📁 *Target:* `{current_path}`\n"
        f"🖥️ *Platform:* `{HOSTING_PLATFORM.upper()}`\n"
        "⏱️ *Limit:* 30 seconds\n\n"
        "🔄 *Zipping... (skipping node_modules, .git, venv)*",
        parse_mode='Markdown'
    )

    try:
        zip_result = {'success': False, 'error': None, 'size': 0}

        def do_zip():
            try:
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(current_path):
                        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', '__pycache__', 'venv', '.venv', 'env', '.env', 'dist', 'build']]
                        for file in files:
                            file_path = os.path.join(root, file)
                            try:
                                arcname = os.path.relpath(file_path, current_path)
                                zipf.write(file_path, arcname)
                            except:
                                continue
                zip_result['success'] = True
                zip_result['size'] = os.path.getsize(zip_path)
            except Exception as e:
                zip_result['error'] = str(e)

        zip_thread = threading.Thread(target=do_zip)
        zip_thread.start()
        zip_thread.join(timeout=ZIP_TIMEOUT)

        elapsed = time.time() - start_time

        if zip_thread.is_alive():
            await status_msg.edit_text(
                f"⏱️ *TIMEOUT!*\nZipping took >{ZIP_TIMEOUT}s.\nTry `/zip` for smaller folders.",
                parse_mode='Markdown'
            )
            return

        if not zip_result['success']:
            await status_msg.edit_text(f"❌ *ZIP FAILED*\n`{zip_result['error']}`", parse_mode='Markdown')
            return

        zip_size = zip_result['size']

        if zip_size > MAX_ZIP_SIZE:
            os.remove(zip_path)
            await status_msg.edit_text(
                f"❌ *ZIP TOO LARGE*\n{get_size_format(zip_size)} > 50MB limit.\nTry `/zip` for specific folders.",
                parse_mode='Markdown'
            )
            return

        await status_msg.edit_text(
            "✅ *ZIP READY!*\n"
            f"📦 {zip_filename}\n"
            f"💾 {get_size_format(zip_size)}\n"
            f"⏱️ {elapsed:.1f}s\n\n"
            "📤 *Uploading...*",
            parse_mode='Markdown'
        )

        with open(zip_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=InputFile(f, filename=zip_filename),
                caption=(
                    "⚡ *ALLZIP COMPLETE* ⚡\n"
                    f"📁 `{folder_name}`\n"
                    f"🖥️ `{HOSTING_PLATFORM.upper()}`\n"
                    f"💾 {get_size_format(zip_size)}\n"
                    f"⏱️ {elapsed:.1f}s\n\n"
                    "✅ Full backup ready!"
                ),
                parse_mode='Markdown'
            )

        os.remove(zip_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ *ALLZIP ERROR*\n`{str(e)}`", parse_mode='Markdown')

# ==================== /SEARCH COMMAND ====================

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "🔍 *SEARCH FILES*\n\n"
            "Usage: `/search <filename>`\n"
            "Example: `/search app.py`\n\n"
            "Or click 🔍 in any folder to search there.",
            parse_mode='Markdown'
        )
        return

    query = ' '.join(args).lower()
    search_path = user_current_path.get(chat_id, ROOT_DIRECTORY)

    status_msg = await update.message.reply_text(
        f"🔍 *Searching for:* `{query}`\n"
        f"📂 *In:* `{search_path}`\n\n"
        "⏳ Please wait...",
        parse_mode='Markdown'
    )

    try:
        results = []
        count = 0
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]
            for file in files:
                if query in file.lower():
                    full_path = os.path.join(root, file)
                    results.append((full_path, file, 'file'))
                    count += 1
                    if count >= SEARCH_RESULTS_LIMIT:
                        break
            if count >= SEARCH_RESULTS_LIMIT:
                break

        user_search_results[chat_id] = results

        if not results:
            await status_msg.edit_text(f"❌ *No results found for:* `{query}`", parse_mode='Markdown')
            return

        keyboard = []
        for path, name, item_type in results:
            item_id = get_short_id(path)
            path_cache[item_id] = path
            icon = get_file_icon(name)
            keyboard.append([
                InlineKeyboardButton(f"{icon} {name}", callback_data=f"vw:{item_id}"),
                InlineKeyboardButton("⬇️", callback_data=f"dl:{item_id}")
            ])

        keyboard.append([InlineKeyboardButton("🔙 BACK TO BROWSER", callback_data=f"op:{get_short_id(search_path)}")])
        path_cache[get_short_id(search_path)] = search_path

        await status_msg.edit_text(
            "🔍 *SEARCH RESULTS*\n"
            f"Query: `{query}`\n"
            f"Found: {len(results)} items\n\n"
            "👇 Click to open:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ *Search Error:* `{str(e)}`", parse_mode='Markdown')

# ==================== /TERMINAL COMMAND ====================

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "🖥️ *TERMINAL*\n\n"
            "Usage: `/terminal <command>`\n"
            "Examples:\n"
            "`/terminal ls -la`\n"
            "`/terminal ps aux`\n"
            "`/terminal df -h`\n"
            "`/terminal python --version`\n\n"
            "⚠️ *Blocked:* rm -rf /, mkfs, dd, fork bombs",
            parse_mode='Markdown'
        )
        return

    command = ' '.join(args)
    current_path = user_current_path.get(chat_id, ROOT_DIRECTORY)

    status_msg = await update.message.reply_text(
        f"🖥️ *Running:* `{command}`\n"
        f"📂 *In:* `{current_path}`\n\n"
        "⏳ Executing...",
        parse_mode='Markdown'
    )

    success, output = run_terminal_command(command, cwd=current_path)
    icon = "✅" if success else "❌"

    result_text = (
        f"{icon} *TERMINAL OUTPUT*\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📂 `{current_path}`\n"
        f"🖥️ `{command}`\n\n"
        f"```\n{output}\n```"
    )

    if len(result_text) > 4096:
        result_text = result_text[:4000] + "\n... (truncated)"

    keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data=f"op:{get_short_id(current_path)}")]]
    path_cache[get_short_id(current_path)] = current_path

    await status_msg.edit_text(
        text=result_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==================== /NEWFILE & /NEWFOLDER ====================

async def newfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        user_awaiting[chat_id] = {'action': 'newfile', 'path': user_current_path.get(chat_id, ROOT_DIRECTORY)}
        await update.message.reply_text(
            "🆕 *CREATE NEW FILE*\n\n"
            "Send the filename now:\n"
            "Example: `config.py` or `README.md`",
            parse_mode='Markdown'
        )
        return

    filename = ' '.join(args)
    current_path = user_current_path.get(chat_id, ROOT_DIRECTORY)
    file_path = os.path.join(current_path, filename)

    try:
        with open(file_path, 'w') as f:
            f.write("")
        await update.message.reply_text(
            f"✅ *File created!*\n\n📄 `{file_path}`",
            parse_mode='Markdown'
        )
        await show_current_folder(update, context, current_path)
    except Exception as e:
        await update.message.reply_text(f"❌ *Error:* `{str(e)}`", parse_mode='Markdown')

async def newfolder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        user_awaiting[chat_id] = {'action': 'newfolder', 'path': user_current_path.get(chat_id, ROOT_DIRECTORY)}
        await update.message.reply_text(
            "🆕 *CREATE NEW FOLDER*\n\n"
            "Send the folder name now:\n"
            "Example: `my_project`",
            parse_mode='Markdown'
        )
        return

    foldername = ' '.join(args)
    current_path = user_current_path.get(chat_id, ROOT_DIRECTORY)
    folder_path = os.path.join(current_path, foldername)

    try:
        os.makedirs(folder_path, exist_ok=True)
        await update.message.reply_text(
            f"✅ *Folder created!*\n\n📁 `{folder_path}`",
            parse_mode='Markdown'
        )
        await show_current_folder(update, context, current_path)
    except Exception as e:
        await update.message.reply_text(f"❌ *Error:* `{str(e)}`", parse_mode='Markdown')

# ==================== /PLATFORM COMMAND ====================

async def platform_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    platform_display = get_platform_display_info()

    try:
        stat = shutil.disk_usage(ROOT_DIRECTORY)
        disk_used = get_size_format(stat.used)
        disk_total = get_size_format(stat.total)
        disk_free = get_size_format(stat.free)
        disk_pct = (stat.used / stat.total) * 100
    except:
        disk_used = disk_total = disk_free = "N/A"
        disk_pct = 0

    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
        mem_total = re.search(r'MemTotal:\s+(\d+)', meminfo)
        mem_free = re.search(r'MemAvailable:\s+(\d+)', meminfo)
        if mem_total and mem_free:
            mem_total_mb = int(mem_total.group(1)) / 1024
            mem_free_mb = int(mem_free.group(1)) / 1024
            mem_used_mb = mem_total_mb - mem_free_mb
            memory_info = f"💾 *RAM:* {mem_used_mb:.0f}MB / {mem_total_mb:.0f}MB used"
        else:
            memory_info = "💾 *RAM:* N/A"
    except:
        memory_info = "💾 *RAM:* N/A"

    platform_text = (
        "🖥️ *PLATFORM INFORMATION* 🖥️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{platform_display}\n\n"
        "📊 *System Resources:*\n"
        f"💾 *Disk:* {disk_used} / {disk_total} used\n"
        f"📊 *Disk Free:* {disk_free} ({100-disk_pct:.1f}%)\n"
        f"{memory_info}\n\n"
        "✅ *Supported Platforms:*\n"
        "🟢 Render | 🚂 Railway | 🌀 Replit\n"
        "💜 Heroku | 🚀 Koyeb | 🪰 Fly.io\n"
        "💻 Codespaces | 🌿 Gitpod | 🐧 VPS\n\n"
        "⚡ Use `/allzip` for instant backup!"
    )

    await update.message.reply_text(platform_text, parse_mode='Markdown')

# ==================== /FAVORITES COMMAND ====================

async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    favs = user_favorites.get(user_id, [])

    if not favs:
        await update.message.reply_text(
            "⭐ *NO FAVORITES*\n\n"
            "Navigate to a folder and click ⭐ to save.",
            parse_mode='Markdown'
        )
        return

    keyboard = []
    for i, path in enumerate(favs[:10]):
        fav_id = get_short_id(path)
        path_cache[fav_id] = path
        name = os.path.basename(path) or 'Root'
        keyboard.append([
            InlineKeyboardButton(f"📁 {name}", callback_data=f"op:{fav_id}"),
            InlineKeyboardButton("🗑️", callback_data=f"fav_del:{fav_id}")
        ])

    await update.message.reply_text(
        "⭐ *YOUR FAVORITES*\n\n👇 Click to navigate:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==================== CALLBACK HANDLERS ====================

async def handle_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, ROOT_DIRECTORY)
        chat_id = query.from_user.id

        if chat_id in user_editing:
            del user_editing[chat_id]
        if chat_id in user_awaiting:
            del user_awaiting[chat_id]

        user_current_path[chat_id] = path
        user_page[chat_id] = 0

        await show_current_folder(update, context, path)
    except Exception as e:
        logger.error(f"Open error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        page_id = query.data.split(':', 1)[1]
        path_data = path_cache.get(page_id, "")

        if "|" in path_data:
            path, page = path_data.rsplit("|", 1)
            page = int(page)
        else:
            path = path_data
            page = 0

        chat_id = query.from_user.id
        user_current_path[chat_id] = path
        user_page[chat_id] = page

        await show_current_folder(update, context, path, page)
    except Exception as e:
        logger.error(f"Page error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        file_path = path_cache.get(file_id, "")

        if not file_path or not os.path.exists(file_path):
            await query.answer("File not found!", show_alert=True)
            return

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        icon = get_file_icon(file_name)
        editable = is_editable_file(file_name)
        size, perms, modified, created = get_file_details(file_path)

        parent_id = get_short_id(os.path.dirname(file_path))
        path_cache[parent_id] = os.path.dirname(file_path)

        home_id = get_short_id(ROOT_DIRECTORY)
        path_cache[home_id] = ROOT_DIRECTORY

        dl_id = get_short_id(file_path)
        path_cache[dl_id] = file_path

        keyboard = [
            [InlineKeyboardButton("⬇️ DOWNLOAD", callback_data=f"dl:{dl_id}")]
        ]

        if editable:
            ed_id = get_short_id(file_path)
            path_cache[ed_id] = file_path
            keyboard[0].append(InlineKeyboardButton("✏️ EDIT", callback_data=f"ed:{ed_id}"))

        keyboard[0].append(InlineKeyboardButton("✏️ RENAME", callback_data=f"rn:{dl_id}"))
        keyboard.append([InlineKeyboardButton("🗑️ DELETE", callback_data=f"del:{dl_id}")])
        keyboard.append([InlineKeyboardButton("📋 COPY PATH", callback_data=f"cp_path:{dl_id}")])
        keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data=f"op:{parent_id}")])
        keyboard.append([InlineKeyboardButton("🏠 HOME", callback_data=f"op:{home_id}")])

        preview_text = ""
        if editable and file_size < 100000:
            content = read_file_content(file_path)
            lines = content.split('\n')[:15]
            preview = '\n'.join(lines)
            if len(content) > len(preview):
                preview += "\n..."
            lang = os.path.splitext(file_name)[1].replace('.', '') or 'text'
            preview_text = f"\n\n📝 *Preview:*\n```{lang}\n{preview}\n```"

        file_info = (
            f"{icon} *FILE INFO*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"📛 *Name:* `{file_name}`\n"
            f"📂 *Path:* `{os.path.dirname(file_path)}`\n"
            f"💾 *Size:* {size}\n"
            f"🔐 *Permissions:* `{perms}`\n"
            f"📅 *Modified:* `{modified}`\n"
            f"📅 *Created:* `{created}`\n"
            f"✏️ *Editable:* {'Yes ✅' if editable else 'No ❌'}\n"
            f"{preview_text}"
        )

        await query.edit_message_text(
            text=file_info, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.answer()
    except Exception as e:
        logger.error(f"View error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        file_path = path_cache.get(file_id, "")

        if not file_path or not os.path.exists(file_path):
            await query.answer("File not found!", show_alert=True)
            return

        if not is_editable_file(os.path.basename(file_path)):
            await query.answer("Not editable!", show_alert=True)
            return

        file_name = os.path.basename(file_path)
        current_content = read_file_content(file_path)

        chat_id = query.from_user.id
        user_editing[chat_id] = {
            'file_path': file_path,
            'content': current_content,
            'message_id': query.message.message_id
        }

        if len(current_content) > MAX_PREVIEW_CHARS:
            content_preview = current_content[:MAX_PREVIEW_CHARS] + "\n\n... (truncated)"
        else:
            content_preview = current_content

        keyboard = [
            [InlineKeyboardButton("💾 SAVE", callback_data=f"save:{file_id}")],
            [InlineKeyboardButton("📥 DOWNLOAD", callback_data=f"dl:{file_id}")],
            [InlineKeyboardButton("❌ CANCEL", callback_data=f"cancel:{file_id}")],
            [InlineKeyboardButton("🔙 BACK", callback_data=f"vw:{file_id}")]
        ]

        lang = os.path.splitext(file_name)[1].replace('.', '') or 'text'

        edit_text = (
            f"✏️ *EDITING: {file_name}*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"📂 `{file_path}`\n\n"
            "📝 *Current Content:*\n"
            f"```{lang}\n{content_preview}\n```\n\n"
            "📋 *Steps:*\n"
            "1️⃣ Copy content above\n"
            "2️⃣ Make changes\n"
            "3️⃣ **Send new content as message**\n"
            "4️⃣ **Click 💾 SAVE**"
        )

        await query.edit_message_text(
            text=edit_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Edit error: {e}")
        await query.answer(f"Error: {str(e)[:50]}", show_alert=True)

async def handle_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        file_path = path_cache.get(file_id, "")
        chat_id = query.from_user.id

        if not file_path or not os.path.exists(file_path):
            await query.answer("File not found!", show_alert=True)
            return

        if chat_id not in user_editing or 'new_content' not in user_editing[chat_id]:
            keyboard = [[InlineKeyboardButton("❌ CANCEL", callback_data=f"cancel:{file_id}")]]
            await query.edit_message_text(
                text="✏️ *SEND CONTENT FIRST*\n\nSend new content, then click SAVE.",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await query.answer()
            return

        new_content = user_editing[chat_id]['new_content']
        success, message = save_file_content(file_path, new_content)

        if success:
            del user_editing[chat_id]
            await query.edit_message_text(
                text=f"✅ *SAVED!*\n\n📄 `{os.path.basename(file_path)}`\n\n🔙 Use /start to browse.",
                parse_mode='Markdown'
            )
        else:
            keyboard = [[InlineKeyboardButton("❌ CANCEL", callback_data=f"cancel:{file_id}")]]
            await query.edit_message_text(
                text=f"❌ *ERROR*\n{message}",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Save error: {e}")
        await query.answer(f"Error: {str(e)[:50]}", show_alert=True)

async def handle_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        chat_id = query.from_user.id

        if chat_id in user_editing:
            del user_editing[chat_id]
        if chat_id in user_awaiting:
            del user_awaiting[chat_id]

        await handle_view_callback(update, context)
    except Exception as e:
        logger.error(f"Cancel error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_rename_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        file_path = path_cache.get(file_id, "")
        chat_id = query.from_user.id

        if not file_path or not os.path.exists(file_path):
            await query.answer("File not found!", show_alert=True)
            return

        user_awaiting[chat_id] = {'action': 'rename', 'path': file_path}

        await query.edit_message_text(
            "✏️ *RENAME*\n\n"
            f"Current: `{os.path.basename(file_path)}`\n\n"
            "📝 *Send the new name now:*",
            parse_mode='Markdown'
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Rename error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        item_id = query.data.split(':', 1)[1]
        item_path = path_cache.get(item_id, "")

        if not item_path or not os.path.exists(item_path):
            await query.answer("Not found!", show_alert=True)
            return

        name = os.path.basename(item_path)
        parent = os.path.dirname(item_path)
        parent_id = get_short_id(parent)
        path_cache[parent_id] = parent

        keyboard = [
            [InlineKeyboardButton("✅ YES, DELETE", callback_data=f"del_confirm:{item_id}")],
            [InlineKeyboardButton("❌ NO, CANCEL", callback_data=f"op:{parent_id}")]
        ]

        await query.edit_message_text(
            "🗑️ *DELETE CONFIRMATION*\n\n"
            f"Are you sure you want to delete:\n"
            f"`{name}`?\n\n"
            "⚠️ This action cannot be undone!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Delete error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        item_id = query.data.split(':', 1)[1]
        item_path = path_cache.get(item_id, "")

        if not item_path or not os.path.exists(item_path):
            await query.answer("Not found!", show_alert=True)
            return

        parent = os.path.dirname(item_path)

        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)

        await query.edit_message_text(
            "✅ *DELETED!*\n\n"
            f"🗑️ `{os.path.basename(item_path)}` has been removed.",
            parse_mode='Markdown'
        )

        await show_current_folder(update, context, parent)
    except Exception as e:
        logger.error(f"Delete confirm error: {e}")
        await query.answer(f"Error: {str(e)[:50]}", show_alert=True)

async def handle_copy_path_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        file_path = path_cache.get(file_id, "")

        if not file_path:
            await query.answer("Path not found!", show_alert=True)
            return

        await query.answer(f"Path: {file_path}", show_alert=True)
    except Exception as e:
        logger.error(f"Copy path error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_favorite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, "")
        user_id = query.from_user.id

        if user_id not in user_favorites:
            user_favorites[user_id] = []

        if path not in user_favorites[user_id]:
            user_favorites[user_id].append(path)
            await query.answer("⭐ Added to favorites!", show_alert=True)
        else:
            await query.answer("Already in favorites!", show_alert=True)

        await show_current_folder(update, context, path)
    except Exception as e:
        logger.error(f"Favorite error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_favorite_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, "")
        user_id = query.from_user.id

        if user_id in user_favorites and path in user_favorites[user_id]:
            user_favorites[user_id].remove(path)
            await query.answer("⭐ Removed from favorites!", show_alert=True)

        await favorites_command(update, context)
    except Exception as e:
        logger.error(f"Fav del error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_search_here_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, "")
        chat_id = query.from_user.id

        user_awaiting[chat_id] = {'action': 'search', 'path': path}

        await query.edit_message_text(
            "🔍 *SEARCH IN FOLDER*\n\n"
            f"📂 `{path}`\n\n"
            "📝 *Send search query now:*",
            parse_mode='Markdown'
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Search here error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_new_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, "")
        chat_id = query.from_user.id

        keyboard = [
            [InlineKeyboardButton("📄 New File", callback_data=f"new_file:{path_id}")],
            [InlineKeyboardButton("📁 New Folder", callback_data=f"new_folder:{path_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"op:{path_id}")]
        ]

        await query.edit_message_text(
            "🆕 *CREATE NEW*\n\n"
            f"📂 `{path}`\n\n"
            "👇 Choose what to create:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.answer()
    except Exception as e:
        logger.error(f"New menu error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_new_file_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, "")
        chat_id = query.from_user.id

        user_awaiting[chat_id] = {'action': 'newfile', 'path': path}

        await query.edit_message_text(
            "🆕 *CREATE NEW FILE*\n\n"
            f"📂 `{path}`\n\n"
            "📝 *Send filename now:*",
            parse_mode='Markdown'
        )
        await query.answer()
    except Exception as e:
        logger.error(f"New file cb error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_new_folder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        path_id = query.data.split(':', 1)[1]
        path = path_cache.get(path_id, "")
        chat_id = query.from_user.id

        user_awaiting[chat_id] = {'action': 'newfolder', 'path': path}

        await query.edit_message_text(
            "🆕 *CREATE NEW FOLDER*\n\n"
            f"📂 `{path}`\n\n"
            "📝 *Send folder name now:*",
            parse_mode='Markdown'
        )
        await query.answer()
    except Exception as e:
        logger.error(f"New folder cb error: {e}")
        await query.answer("Error!", show_alert=True)

async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        file_id = query.data.split(':', 1)[1]
        file_path = path_cache.get(file_id, "")

        if not file_path or not os.path.exists(file_path):
            await query.answer("File not found!", show_alert=True)
            return

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        if file_size > MAX_FILE_SIZE:
            parent_id = get_short_id(os.path.dirname(file_path))
            path_cache[parent_id] = os.path.dirname(file_path)
            keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data=f"op:{parent_id}")]]
            await query.edit_message_text(
                text=f"❌ *TOO LARGE*\n{get_size_format(file_size)} > 50MB limit.",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await query.answer()
            return

        await query.edit_message_text(
            f"⬇️ *Downloading*\n`{file_name}`\n\nPlease wait...",
            parse_mode='Markdown'
        )

        with open(file_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(f, filename=file_name),
                caption=f"✅ `{file_name}`\n💾 {get_size_format(file_size)}",
                parse_mode='Markdown'
            )

        await show_current_folder(update, context, os.path.dirname(file_path))
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.answer(f"Error: {str(e)[:50]}", show_alert=True)

async def handle_zip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        folder_id = query.data.split(':', 1)[1]
        folder_path = path_cache.get(folder_id, "")

        if not folder_path or not os.path.exists(folder_path):
            await query.answer("Folder not found!", show_alert=True)
            return

        folder_name = os.path.basename(folder_path) or "root"
        zip_path = os.path.join(tempfile.gettempdir(), f"{folder_name}_{get_short_id(folder_path)}.zip")

        await query.edit_message_text(
            f"📦 *Creating ZIP*\n\n`{folder_path}`\n\n⏳ Please wait...",
            parse_mode='Markdown'
        )

        if create_zip_of_folder(folder_path, zip_path):
            zip_size = os.path.getsize(zip_path)

            if zip_size > MAX_ZIP_SIZE:
                os.remove(zip_path)
                await query.edit_message_text(
                    f"❌ *ZIP TOO LARGE*\n{get_size_format(zip_size)} > 50MB",
                    parse_mode='Markdown'
                )
                return

            with open(zip_path, 'rb') as zip_file:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=InputFile(zip_file, filename=f"{folder_name}.zip"),
                    caption=f"✅ `{folder_path}`\n💾 {get_size_format(zip_size)}",
                    parse_mode='Markdown'
                )

            os.remove(zip_path)
            await show_current_folder(update, context, folder_path)
        else:
            await query.edit_message_text(text="❌ *ZIP FAILED*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Zip error: {e}")
        await query.answer(f"Error: {str(e)[:50]}", show_alert=True)

async def handle_allzip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id

    class FakeUpdate:
        def __init__(self, chat_id, message):
            self.effective_chat = type('obj', (object,), {'id': chat_id})()
            self.message = message
            self.effective_user = query.from_user

    fake_update = FakeUpdate(chat_id, query.message)
    await allzip_command(fake_update, context)
    await query.answer()

async def handle_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    platform_display = get_platform_display_info()

    keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data=f"op:{get_short_id(ROOT_DIRECTORY)}")]]
    path_cache[get_short_id(ROOT_DIRECTORY)] = ROOT_DIRECTORY

    info_text = (
        "ℹ️ *BOT INFORMATION*\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{platform_display}\n\n"
        "✅ *Supported:*\n"
        "Render, Railway, Replit, Heroku,\n"
        "Koyeb, Fly.io, Codespaces, Gitpod, VPS"
    )

    await query.edit_message_text(
        text=info_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.answer()

# ==================== MESSAGE HANDLER ====================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    text = message.text

    # Handle awaiting actions
    if user_id in user_awaiting:
        action_data = user_awaiting[user_id]
        action = action_data['action']
        path = action_data['path']

        if action == 'rename':
            old_path = path
            new_name = text.strip()
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            try:
                os.rename(old_path, new_path)
                await message.reply_text(
                    f"✅ *Renamed!*\n\n"
                    f"`{os.path.basename(old_path)}` → `{new_name}`",
                    parse_mode='Markdown'
                )
                await show_current_folder(update, context, os.path.dirname(new_path))
            except Exception as e:
                await message.reply_text(f"❌ *Error:* `{str(e)}`", parse_mode='Markdown')
            del user_awaiting[user_id]
            return

        elif action == 'newfile':
            filename = text.strip()
            file_path = os.path.join(path, filename)
            try:
                with open(file_path, 'w') as f:
                    f.write("")
                await message.reply_text(
                    f"✅ *File created!*\n\n📄 `{file_path}`",
                    parse_mode='Markdown'
                )
                await show_current_folder(update, context, path)
            except Exception as e:
                await message.reply_text(f"❌ *Error:* `{str(e)}`", parse_mode='Markdown')
            del user_awaiting[user_id]
            return

        elif action == 'newfolder':
            foldername = text.strip()
            folder_path = os.path.join(path, foldername)
            try:
                os.makedirs(folder_path, exist_ok=True)
                await message.reply_text(
                    f"✅ *Folder created!*\n\n📁 `{folder_path}`",
                    parse_mode='Markdown'
                )
                await show_current_folder(update, context, path)
            except Exception as e:
                await message.reply_text(f"❌ *Error:* `{str(e)}`", parse_mode='Markdown')
            del user_awaiting[user_id]
            return

        elif action == 'search':
            query_text = text.strip()
            status_msg = await message.reply_text(
                f"🔍 *Searching for:* `{query_text}`\n⏳ Please wait...",
                parse_mode='Markdown'
            )

            try:
                results = []
                count = 0
                for root, dirs, files in os.walk(path):
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]
                    for file in files:
                        if query_text.lower() in file.lower():
                            full_path = os.path.join(root, file)
                            results.append((full_path, file, 'file'))
                            count += 1
                            if count >= SEARCH_RESULTS_LIMIT:
                                break
                    if count >= SEARCH_RESULTS_LIMIT:
                        break

                user_search_results[chat_id] = results

                if not results:
                    await status_msg.edit_text(f"❌ *No results for:* `{query_text}`", parse_mode='Markdown')
                    del user_awaiting[user_id]
                    return

                keyboard = []
                for fpath, name, item_type in results:
                    item_id = get_short_id(fpath)
                    path_cache[item_id] = fpath
                    icon = get_file_icon(name)
                    keyboard.append([
                        InlineKeyboardButton(f"{icon} {name}", callback_data=f"vw:{item_id}"),
                        InlineKeyboardButton("⬇️", callback_data=f"dl:{item_id}")
                    ])

                keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data=f"op:{get_short_id(path)}")])
                path_cache[get_short_id(path)] = path

                await status_msg.edit_text(
                    f"🔍 *RESULTS: {query_text}*\n"
                    f"Found: {len(results)} items\n\n👇 Click:",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                await status_msg.edit_text(f"❌ *Error:* `{str(e)}`", parse_mode='Markdown')

            del user_awaiting[user_id]
            return

    # Handle file editing
    if user_id in user_editing:
        user_editing[user_id]['new_content'] = text
        user_editing[user_id]['awaiting_save'] = True

        await message.reply_text(
            "✅ *Content received!*\n\n"
            "📝 Now click **💾 SAVE** to save changes.",
            parse_mode='Markdown'
        )
        return

    # Default: not in any mode
    await message.reply_text(
        "❓ *Not in any mode*\n\n"
        "Available commands:\n"
        "`/start` - Browse files\n"
        "`/search <query>` - Find files\n"
        "`/terminal <cmd>` - Run commands\n"
        "`/newfile <name>` - Create file\n"
        "`/newfolder <name>` - Create folder\n"
        "`/allzip` - Backup project\n"
        "`/platform` - System info\n"
        "`/favorites` - Saved locations",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 *ULTIMATE FILE MANAGER* 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Commands:*\n"
        "/start - 🗂️ Browse files\n"
        "/allzip - ⚡ Zip project (30s)\n"
        "/search <name> - 🔍 Find files\n"
        "/terminal <cmd> - 🖥️ Run commands\n"
        "/newfile <name> - 📄 Create file\n"
        "/newfolder <name> - 📁 Create folder\n"
        "/platform - 🖥️ Full platform info\n"
        "/favorites - ⭐ Saved locations\n"
        "/help - ❓ This help\n\n"
        "*Features:*\n"
        "• 50 files per page with pagination\n"
        "• Edit ANY text file (20+ formats)\n"
        "• Rename & Delete files/folders\n"
        "• Create new files & folders\n"
        "• Search files across directories\n"
        "• Terminal command execution\n"
        "• File permissions & timestamps\n"
        "• Favorites system\n"
        "• Copy full path\n"
        "• Fast ALLZIP in 30 seconds\n\n"
        "*Supported Platforms:*\n"
        "🟢 Render | 🚂 Railway | 🌀 Replit\n"
        "💜 Heroku | 🚀 Koyeb | 🪰 Fly.io\n"
        "💻 Codespaces | 🌿 Gitpod | 🐧 VPS"
    )

    await update.message.reply_text(help_text, parse_mode='Markdown')

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ==================== MAIN ====================

def main():
    print("🚀 MEGA ULTIMATE FILE MANAGER STARTING...")
    print(f"🖥️  Platform: {HOSTING_PLATFORM.upper()}")
    print(f"📂 Root: {ROOT_DIRECTORY}")
    print(f"📁 Script: {SCRIPT_DIRECTORY}")
    print(f"⚡ ALLZIP timeout: {ZIP_TIMEOUT}s")
    print(f"✅ Ready for Render, Railway, Replit, Heroku, Koyeb, Fly.io, Codespaces, Gitpod, VPS!")

    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("allzip", allzip_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("terminal", terminal_command))
    application.add_handler(CommandHandler("newfile", newfile_command))
    application.add_handler(CommandHandler("newfolder", newfolder_command))
    application.add_handler(CommandHandler("platform", platform_command))
    application.add_handler(CommandHandler("favorites", favorites_command))

    # Callbacks
    application.add_handler(CallbackQueryHandler(handle_open_callback, pattern='^op:'))
    application.add_handler(CallbackQueryHandler(handle_page_callback, pattern='^pg:'))
    application.add_handler(CallbackQueryHandler(handle_view_callback, pattern='^vw:'))
    application.add_handler(CallbackQueryHandler(handle_edit_callback, pattern='^ed:'))
    application.add_handler(CallbackQueryHandler(handle_save_callback, pattern='^save:'))
    application.add_handler(CallbackQueryHandler(handle_cancel_callback, pattern='^cancel:'))
    application.add_handler(CallbackQueryHandler(handle_rename_callback, pattern='^rn:'))
    application.add_handler(CallbackQueryHandler(handle_delete_callback, pattern='^del:'))
    application.add_handler(CallbackQueryHandler(handle_delete_confirm_callback, pattern='^del_confirm:'))
    application.add_handler(CallbackQueryHandler(handle_copy_path_callback, pattern='^cp_path:'))
    application.add_handler(CallbackQueryHandler(handle_favorite_callback, pattern='^fav:'))
    application.add_handler(CallbackQueryHandler(handle_favorite_delete_callback, pattern='^fav_del:'))
    application.add_handler(CallbackQueryHandler(handle_search_here_callback, pattern='^search_here:'))
    application.add_handler(CallbackQueryHandler(handle_new_menu_callback, pattern='^new_menu:'))
    application.add_handler(CallbackQueryHandler(handle_new_file_callback, pattern='^new_file:'))
    application.add_handler(CallbackQueryHandler(handle_new_folder_callback, pattern='^new_folder:'))
    application.add_handler(CallbackQueryHandler(handle_download_callback, pattern='^dl:'))
    application.add_handler(CallbackQueryHandler(handle_zip_callback, pattern='^zp:'))
    application.add_handler(CallbackQueryHandler(handle_allzip_callback, pattern='^az:'))
    application.add_handler(CallbackQueryHandler(handle_info_callback, pattern='^info$'))
    application.add_handler(CallbackQueryHandler(noop_callback, pattern='^noop'))

    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
