"""
opener_runner.py — SWC Opener Agent Runner

Reads leads from CRM data sources, identifies which leads need first-touch DMs,
and generates a structured prompt for the Opener Brain to draft openers.

Usage:
    python3 opener_runner.py                    # Process all pending leads
    python3 opener_runner.py --date 4/4/2026    # Process leads from specific date
    python3 opener_runner.py --hot-only         # Only hot/priority leads
    python3 opener_runner.py --source json      # Read from codeword_leads JSON
    python3 opener_runner.py --source tracker   # Read from tracker_import TSV
    python3 opener_runner.py --source crm       # Read from SWC_CRM.xlsx

Output: opener_queue.md — structured prompt ready for the Opener Brain
"""

import argparse
import json
import csv
import os
from datetime import datetime, date

BASE_DIR = '/Users/annagamez/Desktop/cowork swc/SWC'
JSON_PATH = os.path.join(BASE_DIR, 'codeword_leads_327.json')
TSV_PATH = os.path.join(BASE_DIR, 'tracker_import.tsv')
QUEUE_PATH = os.path.join(BASE_DIR, 'agents', 'opener_queue.md')
DRAFTS_DIR = os.path.join(BASE_DIR, 'agents', 'drafts')

# Stages that need openers (haven't been contacted yet)
NEEDS_OPENER = {'Contact Received'}

# Stages already past opener
PAST_OPENER = {
    'Responder Sent', 'Qualifying - Confirming', 'Qualifying - Confirmed',
    'Call Invite Sent', 'Call Booked', 'Call Done - Closed',
    'Call Done - Follow Up', 'Nurture - Organic', 'Nurture - Ad'
}

# Keywords and their content context
KEYWORD_CONTEXT = {
    'RESULTS': {
        'content': 'Over-45 "feel good in your body again" reel',
        'emotional_entry': 'Tired of feeling stuck, wants to feel herself again',
        'ad': False
    },
    'Results': {
        'content': 'Over-45 "feel good in your body again" reel',
        'emotional_entry': 'Tired of feeling stuck, wants to feel herself again',
        'ad': False
    },
    'ALIGNED!': {
        'content': 'Retired women 55+ ad — grandkids, travel, move easier',
        'emotional_entry': 'Wants energy + freedom in her next chapter',
        'ad': True
    },
    'Aligned!': {
        'content': 'Retired women 55+ ad — grandkids, travel, move easier',
        'emotional_entry': 'Wants energy + freedom in her next chapter',
        'ad': True
    },
    'Aligned': {
        'content': 'Retired women 55+ post — grandkids, travel, move easier',
        'emotional_entry': 'Wants energy + freedom in her next chapter',
        'ad': False
    },
    'aligned': {
        'content': 'Retired women 55+ ad reel',
        'emotional_entry': 'Wants energy + freedom in her next chapter',
        'ad': True
    },
    'Transform': {
        'content': 'General transformation content',
        'emotional_entry': 'Ready for a change',
        'ad': False
    },
}


def load_json_leads():
    """Load leads from codeword_leads JSON."""
    if not os.path.exists(JSON_PATH):
        print(f"JSON not found: {JSON_PATH}")
        return []
    with open(JSON_PATH, 'r') as f:
        return json.load(f)


def load_tsv_leads():
    """Load leads from tracker_import TSV."""
    if not os.path.exists(TSV_PATH):
        print(f"TSV not found: {TSV_PATH}")
        return []
    leads = []
    with open(TSV_PATH, 'r') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            lead = {
                'name': row.get('Name', ''),
                'ig': row.get('Instagram', ''),
                'keyword': row.get('Keyword', ''),
                'date': row.get('Date', ''),
                'source': 'tracker',
                'ad': row.get('Targeting', '') == 'retired' and row.get('Creative', '') == 'ad reel',
                'stage': row.get('Stage', ''),
                'notes': row.get('ICA Notes', ''),
                'goal': row.get('Goals', ''),
            }
            leads.append(lead)
    return leads


def classify_temperature(lead):
    """Classify lead temperature based on available signals."""
    notes = (lead.get('notes', '') or '').lower()
    keyword = lead.get('keyword', '') or ''
    stage = lead.get('stage', '') or ''

    # Hot signals
    hot_signals = ['pricing', 'cost', 'how much', 'send me info', 'programs you offer',
                   'what does it cost', 'interested in']
    if any(s in notes for s in hot_signals):
        return 'Hot'

    if lead.get('temp', '') == 'Hot':
        return 'Hot'

    # Warm signals
    if stage == 'Qualifying - Confirming' or lead.get('temp', '') == 'Warm':
        return 'Warm'
    if keyword and any(g for g in [lead.get('goal', ''), lead.get('pain', '')] if g):
        return 'Warm'

    # Cool — has keyword but nothing else
    if keyword:
        return 'Cool'

    # Cold — ad follow, no engagement
    if lead.get('ad', False) and not keyword:
        return 'Cold'

    return 'Cool'


def needs_opener(lead):
    """Check if lead needs a first-touch DM."""
    stage = lead.get('stage', '')

    # Already past opener
    if stage in PAST_OPENER:
        return False

    # Needs opener
    if stage in NEEDS_OPENER or stage == '' or stage == 'Looks Avatar':
        # Check if qualifier already sent (already contacted)
        notes = (lead.get('notes', '') or '').lower()
        if 'qualifier sent' in notes:
            return False
        if 'outreach sent' in notes:
            return False
        return True

    return False


def determine_priority(lead, temp):
    """Determine processing priority."""
    if temp == 'Hot':
        return 'HIGH'
    if temp == 'Warm':
        return 'MEDIUM'
    notes = (lead.get('notes', '') or '').lower()
    if 'x2' in notes or 'multiple' in notes:
        return 'MEDIUM'
    return 'LOW'


def format_lead_for_prompt(lead, temp, priority):
    """Format a single lead as a section in the opener prompt."""
    name = lead.get('name', '') or lead.get('ig', '') or 'Unknown'
    ig = lead.get('ig', '')
    keyword = lead.get('keyword', '')
    notes = lead.get('notes', '')
    goal = lead.get('goal', '') or lead.get('pain', '') or ''
    is_ad = lead.get('ad', False)
    date_str = lead.get('date', '')

    # Get keyword context
    kw_ctx = KEYWORD_CONTEXT.get(keyword, {})
    content = kw_ctx.get('content', 'Unknown content')
    emotional = kw_ctx.get('emotional_entry', '')

    # Determine source type
    if is_ad:
        source_type = 'Paid Ad'
    elif keyword:
        source_type = 'IG Organic (keyword comment)'
    else:
        source_type = 'IG Organic'

    # Check for sensitive flag
    sensitive = 'sensitive' in (notes or '').lower() or 'copd' in (notes or '').lower() or 'hospice' in (notes or '').lower()

    lines = []
    lines.append(f"### {name}" + (f" (@{ig})" if ig else ""))
    lines.append(f"- **Date**: {date_str}")
    lines.append(f"- **Keyword**: {keyword or 'None'}")
    lines.append(f"- **Source**: {source_type}")
    if content:
        lines.append(f"- **Content That Brought Them In**: {content}")
    if emotional:
        lines.append(f"- **Emotional Entry Point**: {emotional}")
    lines.append(f"- **Temperature**: {temp}")
    lines.append(f"- **Priority**: {priority}")
    if goal:
        lines.append(f"- **Goal**: {goal}")
    if notes:
        lines.append(f"- **Notes**: {notes}")
    if sensitive:
        lines.append(f"- **FLAG: SENSITIVE SITUATION — Lead with compassion, do not sell**")
    lines.append("")

    return '\n'.join(lines)


def generate_queue(leads, filter_date=None, hot_only=False):
    """Generate the opener queue markdown."""
    # Filter to leads needing openers
    pending = []
    skipped_already_contacted = 0
    skipped_past_stage = 0

    for lead in leads:
        # Date filter
        if filter_date and lead.get('date', '') != filter_date:
            continue

        if not needs_opener(lead):
            stage = lead.get('stage', '')
            notes = (lead.get('notes', '') or '').lower()
            if 'qualifier sent' in notes or 'outreach sent' in notes:
                skipped_already_contacted += 1
            else:
                skipped_past_stage += 1
            continue

        temp = classify_temperature(lead)
        priority = determine_priority(lead, temp)

        if hot_only and priority != 'HIGH':
            continue

        pending.append((lead, temp, priority))

    # Sort by priority: HIGH first, then MEDIUM, then LOW
    priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    pending.sort(key=lambda x: priority_order.get(x[2], 3))

    # Generate the queue document
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = []
    lines.append(f"# SWC Opener Agent Queue")
    lines.append(f"Generated: {now}")
    lines.append(f"")
    lines.append(f"## Summary")
    lines.append(f"- **Total leads needing openers**: {len(pending)}")
    lines.append(f"- Skipped (already contacted): {skipped_already_contacted}")
    lines.append(f"- Skipped (past opener stage): {skipped_past_stage}")

    high = sum(1 for _, _, p in pending if p == 'HIGH')
    med = sum(1 for _, _, p in pending if p == 'MEDIUM')
    low = sum(1 for _, _, p in pending if p == 'LOW')
    lines.append(f"- HIGH priority: {high}")
    lines.append(f"- MEDIUM priority: {med}")
    lines.append(f"- LOW priority: {low}")
    lines.append("")

    if not pending:
        lines.append("**No leads currently need openers.** All leads have been contacted or are past the opener stage.")
        return '\n'.join(lines)

    lines.append("---")
    lines.append("")
    lines.append("## Instructions")
    lines.append("For each lead below, generate a first-touch DM draft following the Opener Brain rules.")
    lines.append("Process in order (HIGH priority first). Output each draft in the standard format.")
    lines.append("")

    # Group by priority
    if high > 0:
        lines.append("---")
        lines.append("## HIGH PRIORITY (respond today)")
        lines.append("")
        for lead, temp, priority in pending:
            if priority == 'HIGH':
                lines.append(format_lead_for_prompt(lead, temp, priority))

    if med > 0:
        lines.append("---")
        lines.append("## MEDIUM PRIORITY")
        lines.append("")
        for lead, temp, priority in pending:
            if priority == 'MEDIUM':
                lines.append(format_lead_for_prompt(lead, temp, priority))

    if low > 0:
        lines.append("---")
        lines.append("## LOW PRIORITY")
        lines.append("")
        for lead, temp, priority in pending:
            if priority == 'LOW':
                lines.append(format_lead_for_prompt(lead, temp, priority))

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='SWC Opener Agent Runner')
    parser.add_argument('--source', choices=['json', 'tracker', 'both'], default='json',
                        help='Data source: json (codeword_leads), tracker (TSV), or both')
    parser.add_argument('--date', type=str, default=None,
                        help='Filter to specific date (e.g., 4/4/2026)')
    parser.add_argument('--hot-only', action='store_true',
                        help='Only process hot/high-priority leads')
    args = parser.parse_args()

    leads = []
    if args.source in ('json', 'both'):
        json_leads = load_json_leads()
        print(f"Loaded {len(json_leads)} leads from JSON")
        leads.extend(json_leads)

    if args.source in ('tracker', 'both'):
        tsv_leads = load_tsv_leads()
        print(f"Loaded {len(tsv_leads)} leads from TSV")
        leads.extend(tsv_leads)

    print(f"Total leads: {len(leads)}")

    queue = generate_queue(leads, filter_date=args.date, hot_only=args.hot_only)

    # Write queue file
    os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
    with open(QUEUE_PATH, 'w') as f:
        f.write(queue)
    print(f"\nOpener queue written to: {QUEUE_PATH}")

    # Also create drafts directory for output
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    print(f"Drafts directory ready: {DRAFTS_DIR}")


if __name__ == '__main__':
    main()
