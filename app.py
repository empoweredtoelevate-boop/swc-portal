"""
SWC Command Center — Web Server
Flask app serving the CRM portal, Agent Hub, and notification system.

Usage:
    python3 app.py                    # Start on port 5555
    python3 app.py --port 8080        # Custom port
    python3 app.py --public           # Listen on all interfaces (for external access)

Features:
    - Login-protected CRM portal
    - Agent Hub with draft review and approval
    - Live notification feed (SSE)
    - API endpoints for CRM data
    - Role-based access (admin vs client view)
"""

import json
import os
import glob
import hashlib
import secrets
import subprocess
import sys
from datetime import datetime, timedelta
from functools import wraps

sys.path.insert(0, os.path.dirname(__file__))

from flask import (Flask, render_template, jsonify, request, redirect,
                   url_for, session, Response, send_from_directory, abort)

BASE_DIR = os.environ.get('SWC_BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__, static_folder=BASE_DIR, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=30)

# ─── User accounts ───
# In production, move to a proper DB. For now, file-based.
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    # Default accounts
    default = {
        'stef': {
            'password_hash': hashlib.sha256('swc2026!'.encode()).hexdigest(),
            'role': 'admin',
            'name': 'Stefanie Will'
        },
        'client': {
            'password_hash': hashlib.sha256('swcview'.encode()).hexdigest(),
            'role': 'viewer',
            'name': 'Client View'
        }
    }
    with open(USERS_FILE, 'w') as f:
        json.dump(default, f, indent=2)
    return default

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def check_auth(username, password):
    users = load_users()
    if username in users:
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if users[username]['password_hash'] == pw_hash:
            return users[username]
    return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Auth Routes ───

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        user = check_auth(username, password)
        if user:
            session.permanent = True
            session['user'] = username
            session['role'] = user['role']
            session['name'] = user['name']
            return redirect(url_for('index'))
        error = 'Invalid username or password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── Main Routes ───

@app.route('/')
@login_required
def index():
    return render_template('portal.html',
                           user=session.get('name'),
                           role=session.get('role'))

@app.route('/static/<path:filename>')
@login_required
def serve_static(filename):
    return send_from_directory(BASE_DIR, filename)


# ─── API: CRM Data ───

@app.route('/api/leads')
@login_required
def api_leads():
    """Return all leads from the full CRM dataset (dashboard_data.js)."""
    # Primary source: dashboard_data.js (most current, 4000+ leads)
    js_path = os.path.join(BASE_DIR, 'dashboard_data.js')
    if os.path.exists(js_path):
        with open(js_path) as f:
            content = f.read()
        idx = content.find('{')
        if idx >= 0:
            data_str = content[idx:].rstrip().rstrip(';')
            try:
                data = json.loads(data_str)
                return jsonify(data.get('leads', []))
            except json.JSONDecodeError:
                pass
    # Fallback: dashboard_data.json
    json_path = os.path.join(BASE_DIR, 'dashboard_data.json')
    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
        return jsonify(data.get('leads', []))
    return jsonify([])

@app.route('/api/crm-data')
@login_required
def api_crm_data():
    """Return full CRM dashboard data with summary stats."""
    js_path = os.path.join(BASE_DIR, 'dashboard_data.js')
    if os.path.exists(js_path):
        with open(js_path) as f:
            content = f.read()
        idx = content.find('{')
        if idx >= 0:
            data_str = content[idx:].rstrip().rstrip(';')
            return Response(data_str, mimetype='application/json')
    json_path = os.path.join(BASE_DIR, 'dashboard_data.json')
    if os.path.exists(json_path):
        with open(json_path) as f:
            return jsonify(json.load(f))
    return jsonify({})


# ─── API: Agent Hub ───

@app.route('/api/agent/queue')
@login_required
def api_agent_queue():
    """Return the current opener queue."""
    queue_path = os.path.join(BASE_DIR, 'agents', 'opener_queue.md')
    if os.path.exists(queue_path):
        with open(queue_path) as f:
            return jsonify({'content': f.read(), 'exists': True})
    return jsonify({'content': '', 'exists': False})

@app.route('/api/agent/drafts')
@login_required
def api_agent_drafts():
    """Return all draft files."""
    drafts_dir = os.path.join(BASE_DIR, 'agents', 'drafts')
    drafts = []
    if os.path.isdir(drafts_dir):
        for fn in sorted(glob.glob(os.path.join(drafts_dir, '*.md')), reverse=True):
            with open(fn) as f:
                content = f.read()
            drafts.append({
                'filename': os.path.basename(fn),
                'content': content,
                'modified': datetime.fromtimestamp(os.path.getmtime(fn)).isoformat()
            })
    return jsonify(drafts)

@app.route('/api/agent/drafts/latest')
@login_required
def api_agent_drafts_latest():
    """Return the latest draft file parsed into individual DM drafts."""
    drafts_dir = os.path.join(BASE_DIR, 'agents', 'drafts')
    files = sorted(glob.glob(os.path.join(drafts_dir, '*.md')), reverse=True)
    if not files:
        return jsonify([])

    with open(files[0]) as f:
        content = f.read()

    # Parse the markdown into individual drafts
    drafts = []
    current = None
    for line in content.split('\n'):
        if line.startswith('### === ') or line.startswith('=== '):
            if current:
                drafts.append(current)
            name = line.replace('### ', '').replace('=== ', '').replace(' ===', '').strip()
            current = {'name': name, 'lines': [], 'approved': False, 'sent': False}
        elif current is not None:
            current['lines'].append(line)

    if current:
        drafts.append(current)

    # Extract metadata from each draft's lines
    for d in drafts:
        text = '\n'.join(d['lines'])
        d['raw'] = text
        # Extract DM content between > markers or --- markers
        dm_lines = []
        in_dm = False
        for line in d['lines']:
            if line.startswith('> '):
                dm_lines.append(line[2:])
            elif line.strip() == '---' and not in_dm:
                in_dm = True
            elif line.strip() == '---' and in_dm:
                in_dm = False
            elif in_dm:
                dm_lines.append(line)
        d['dm'] = '\n'.join(dm_lines) if dm_lines else ''

        # Extract fields
        for line in d['lines']:
            if line.startswith('**Keyword**:'):
                d['keyword'] = line.split(':', 1)[1].strip().rstrip('*')
            elif line.startswith('**Temperature**:'):
                d['temperature'] = line.split(':', 1)[1].strip().rstrip('*')
            elif line.startswith('**Priority**:'):
                d['priority'] = line.split(':', 1)[1].strip().rstrip('*')
            elif line.startswith('**Source**:'):
                d['source'] = line.split(':', 1)[1].strip().rstrip('*')
            elif line.startswith('**WHY THIS WORKS**:') or line.startswith('**WHY THIS WORKS:**'):
                d['why'] = line.split(':', 1)[1].strip().rstrip('*')

        del d['lines']

    return jsonify(drafts)


@app.route('/api/agent/approve', methods=['POST'])
@admin_required
def api_agent_approve():
    """Approve a draft DM for sending."""
    data = request.json
    name = data.get('name', '')
    # Log the approval
    log_path = os.path.join(BASE_DIR, 'agents', 'approval_log.json')
    log = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
    log.append({
        'name': name,
        'action': 'approved',
        'by': session.get('user'),
        'timestamp': datetime.now().isoformat()
    })
    with open(log_path, 'w') as f:
        json.dump(log, f, indent=2)
    return jsonify({'ok': True})

@app.route('/api/agent/reject', methods=['POST'])
@admin_required
def api_agent_reject():
    """Reject a draft DM."""
    data = request.json
    name = data.get('name', '')
    reason = data.get('reason', '')
    log_path = os.path.join(BASE_DIR, 'agents', 'approval_log.json')
    log = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
    log.append({
        'name': name,
        'action': 'rejected',
        'reason': reason,
        'by': session.get('user'),
        'timestamp': datetime.now().isoformat()
    })
    with open(log_path, 'w') as f:
        json.dump(log, f, indent=2)
    return jsonify({'ok': True})

@app.route('/api/agent/run-opener', methods=['POST'])
@admin_required
def api_run_opener():
    """Trigger the opener agent runner."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, 'agents', 'opener_runner.py'), '--source', 'json'],
            capture_output=True, text=True, timeout=30
        )
        return jsonify({'ok': True, 'output': result.stdout, 'error': result.stderr})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ─── API: Notifications (SSE) ───

@app.route('/api/notifications')
@login_required
def api_notifications():
    """Return recent notifications/activity."""
    items = []
    # Check for new leads (from JSON)
    json_path = os.path.join(BASE_DIR, 'codeword_leads_327.json')
    if os.path.exists(json_path):
        with open(json_path) as f:
            leads = json.load(f)
        today = datetime.now().strftime('%-m/%-d/%Y')
        for lead in leads:
            if lead.get('date') == '4/4/2026' or lead.get('date') == '4/5/2026':
                temp = lead.get('temp', 'Cool')
                items.append({
                    'type': 'new_lead',
                    'icon': 'hot' if temp == 'Hot' else 'new',
                    'title': f"New lead: {lead.get('name') or lead.get('ig', 'Unknown')}",
                    'subtitle': lead.get('notes', ''),
                    'date': lead.get('date', ''),
                    'keyword': lead.get('keyword', ''),
                    'priority': 'high' if temp == 'Hot' else 'normal'
                })

    # Check for CRM updates
    updates_dir = os.path.join(BASE_DIR, 'crm_updates')
    if os.path.isdir(updates_dir):
        for fn in sorted(glob.glob(os.path.join(updates_dir, '*.md')), reverse=True)[:3]:
            items.append({
                'type': 'crm_update',
                'icon': 'sync',
                'title': f"CRM Update: {os.path.basename(fn)}",
                'subtitle': 'Daily sync report available',
                'date': os.path.basename(fn)[:10],
                'priority': 'normal'
            })

    # Check approval log
    log_path = os.path.join(BASE_DIR, 'agents', 'approval_log.json')
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
        for entry in log[-10:]:
            items.append({
                'type': 'approval',
                'icon': 'check' if entry['action'] == 'approved' else 'x',
                'title': f"DM {entry['action']}: {entry['name']}",
                'subtitle': f"by {entry.get('by', 'unknown')}",
                'date': entry.get('timestamp', '')[:10],
                'priority': 'normal'
            })

    return jsonify(items)

@app.route('/api/agent/status')
@login_required
def api_agent_status():
    """Return agent status (which agents are enabled, last run times)."""
    status_path = os.path.join(BASE_DIR, 'agents', 'agent_status.json')
    if os.path.exists(status_path):
        with open(status_path) as f:
            return jsonify(json.load(f))
    # Default status
    default = {
        'opener': {'enabled': False, 'auto_send': False, 'last_run': None, 'label': 'Opener Agent', 'description': 'First-touch DM for keyword leads'},
        'setter': {'enabled': False, 'auto_send': False, 'last_run': None, 'label': 'Setter Brain', 'description': 'Pain deepening & call booking'},
        'closer': {'enabled': False, 'auto_send': False, 'last_run': None, 'label': 'Closer Brain', 'description': 'Call prep & close'},
        'nurture': {'enabled': False, 'auto_send': False, 'last_run': None, 'label': 'Nurture Agent', 'description': 'Long-term follow-up sequences'},
        'ig_sync': {'enabled': True, 'auto_send': False, 'last_run': '2026-04-05T18:00:00', 'label': 'IG Sync Agent', 'description': 'Daily IG notification processing'},
        'scraper': {'enabled': False, 'auto_send': False, 'last_run': None, 'label': 'Profile Scraper', 'description': 'IG profile data enrichment'}
    }
    with open(status_path, 'w') as f:
        json.dump(default, f, indent=2)
    return jsonify(default)

@app.route('/api/agent/toggle', methods=['POST'])
@admin_required
def api_agent_toggle():
    """Toggle an agent on/off."""
    data = request.json
    agent_id = data.get('agent')
    field = data.get('field', 'enabled')  # 'enabled' or 'auto_send'

    status_path = os.path.join(BASE_DIR, 'agents', 'agent_status.json')
    status = {}
    if os.path.exists(status_path):
        with open(status_path) as f:
            status = json.load(f)

    if agent_id in status:
        status[agent_id][field] = not status[agent_id].get(field, False)
        with open(status_path, 'w') as f:
            json.dump(status, f, indent=2)
        return jsonify({'ok': True, 'agent': agent_id, 'field': field, 'value': status[agent_id][field]})

    return jsonify({'ok': False, 'error': 'Agent not found'})


# ─── Start Server ───

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5555)))
    parser.add_argument('--public', action='store_true')
    args = parser.parse_args()

    os.makedirs(os.path.join(BASE_DIR, 'templates'), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'agents', 'drafts'), exist_ok=True)

    host = '0.0.0.0' if args.public or os.environ.get('RAILWAY_ENVIRONMENT') else '127.0.0.1'
    debug = not os.environ.get('RAILWAY_ENVIRONMENT')
    print(f'\n  SWC Command Center')
    print(f'  http://{host}:{args.port}')
    if debug:
        print(f'  Admin login: stef / swc2026!')
        print(f'  Client login: client / swcview\n')
    app.run(host=host, port=args.port, debug=debug)
