#!/bin/bash
# deploy_portal.sh — Push latest dashboard_data.js to GitHub and trigger Railway redeploy
# Called by the scheduled portal sync task

set -e

SWC_DIR="/Users/annagamez/Desktop/cowork swc/SWC"
cd "$SWC_DIR"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M')

# 1. Export CRM → dashboard_data.js
echo "[$TIMESTAMP] Exporting CRM to dashboard_data.js..."
python3 export_dashboard.py 2>&1

# 2. Check if dashboard_data.js changed
if git diff --quiet dashboard_data.js 2>/dev/null; then
    echo "[$TIMESTAMP] No changes to dashboard_data.js — skipping deploy"
    exit 0
fi

# 3. Commit and push
echo "[$TIMESTAMP] Changes detected — pushing to GitHub..."
git add dashboard_data.js
git commit -m "Auto-sync portal data $TIMESTAMP

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git push origin main 2>&1

# 4. Trigger Railway redeploy
echo "[$TIMESTAMP] Triggering Railway redeploy..."
RAILWAY_TOKEN="ea40456d-e3e5-4794-9d72-f9a21c37b203"
PROJECT_ID="90473f1b-db81-4c3e-bbe9-b007a2eb298c"
SERVICE_ID="30b22ce3-4872-4079-976c-3e030f8afa7a"
ENV_ID="5fdddfb6-0463-4439-bd97-87018241fecf"

# Use serviceInstanceRedeploy (pulls from connected GitHub repo)
RESULT=$(curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation { serviceInstanceRedeploy(serviceId: \\\"$SERVICE_ID\\\", environmentId: \\\"$ENV_ID\\\") }\"}")

echo "[$TIMESTAMP] Railway response: $RESULT"

# 5. Wait and verify
sleep 90
STATUS=$(curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"query { deployments(input: { serviceId: \\\"$SERVICE_ID\\\", environmentId: \\\"$ENV_ID\\\" }) { edges { node { status createdAt } } } }\"}" \
  | python3 -c "import sys,json; edges=json.load(sys.stdin)['data']['deployments']['edges']; print(edges[0]['node']['status'] if edges else 'UNKNOWN')")

echo "[$TIMESTAMP] Deploy status: $STATUS"

if [ "$STATUS" = "SUCCESS" ]; then
    echo "[$TIMESTAMP] Portal updated successfully!"
else
    echo "[$TIMESTAMP] WARNING: Deploy status is $STATUS — may need manual check"
fi
