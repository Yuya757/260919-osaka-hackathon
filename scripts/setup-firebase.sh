#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-osaka-hackathon-260919}"
SITE_ID="${FIREBASE_SITE_ID:-${PROJECT_ID}}"
token="$(gcloud auth print-access-token)"

firebase_project_url="https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}"
project_status="$(curl -sS -o /tmp/firebase-project.json -w '%{http_code}' \
  -H "Authorization: Bearer ${token}" \
  -H "x-goog-user-project: ${PROJECT_ID}" \
  "${firebase_project_url}")"

if [[ "${project_status}" == "404" ]]; then
  echo "Adding Firebase resources to ${PROJECT_ID}..."
  operation="$(
    curl -sS -X POST \
      -H "Authorization: Bearer ${token}" \
      -H "x-goog-user-project: ${PROJECT_ID}" \
      -H "Content-Type: application/json" \
      "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}:addFirebase" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])'
  )"

  for _ in {1..30}; do
    operation_json="$(
      curl -sS \
        -H "Authorization: Bearer ${token}" \
        -H "x-goog-user-project: ${PROJECT_ID}" \
        "https://firebase.googleapis.com/v1beta1/${operation}"
    )"
    if python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("done") else 1)' \
      <<<"${operation_json}"; then
      if python3 -c 'import json,sys; raise SystemExit(1 if json.load(sys.stdin).get("error") else 0)' \
        <<<"${operation_json}"; then
        break
      fi
      echo "${operation_json}" >&2
      exit 1
    fi
    sleep 5
  done
elif [[ "${project_status}" != "200" ]]; then
  cat /tmp/firebase-project.json >&2
  exit 1
fi

site_url="https://firebasehosting.googleapis.com/v1beta1/projects/${PROJECT_ID}/sites/${SITE_ID}"
site_status="$(curl -sS -o /tmp/firebase-site.json -w '%{http_code}' \
  -H "Authorization: Bearer ${token}" \
  -H "x-goog-user-project: ${PROJECT_ID}" \
  "${site_url}")"

if [[ "${site_status}" == "404" ]]; then
  echo "Creating Firebase Hosting site ${SITE_ID}..."
  curl -sS -X POST \
    -H "Authorization: Bearer ${token}" \
    -H "x-goog-user-project: ${PROJECT_ID}" \
    -H "Content-Type: application/json" \
    "https://firebasehosting.googleapis.com/v1beta1/projects/${PROJECT_ID}/sites?siteId=${SITE_ID}" \
    >/tmp/firebase-site.json
elif [[ "${site_status}" != "200" ]]; then
  cat /tmp/firebase-site.json >&2
  exit 1
fi

echo "Firebase project ready."
echo "FIREBASE_PROJECT_ID=${PROJECT_ID}"
echo "FIREBASE_SITE_ID=${SITE_ID}"
echo "HOSTING_URL=https://${SITE_ID}.web.app"
