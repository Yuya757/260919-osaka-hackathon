#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-osaka-hackathon-260919}"
PROJECT_NAME="${PROJECT_NAME:-Osaka Hackathon Event Agent}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-011C80-57B12D-69BD5E}"
REGION="${REGION:-asia-northeast1}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-Yuya757/260919-osaka-hackathon}"
AR_REPOSITORY="${AR_REPOSITORY:-apps}"
WIF_POOL="${WIF_POOL:-github-pool}"
WIF_PROVIDER="${WIF_PROVIDER:-github-provider}"
DEPLOYER_SA="${DEPLOYER_SA:-github-deployer}"
RUNTIME_SA="${RUNTIME_SA:-event-agent-runtime}"
SCHEDULER_SA="${SCHEDULER_SA:-event-agent-scheduler}"
# 月額予算のアラート（ADR-008 決定6）。請求アカウントの通貨に合わせる
BUDGET_AMOUNT="${BUDGET_AMOUNT:-10000}"
BUDGET_CURRENCY="${BUDGET_CURRENCY:-JPY}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-(default)}"

active_account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
if [[ -z "${active_account}" ]]; then
  echo "No active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi

echo "Using account: ${active_account}"
echo "Project: ${PROJECT_ID}"

if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud projects create "${PROJECT_ID}" --name="${PROJECT_NAME}"
fi

gcloud billing projects link "${PROJECT_ID}" \
  --billing-account="${BILLING_ACCOUNT}"

gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud config set run/region "${REGION}" >/dev/null

apis=(
  aiplatform.googleapis.com
  billingbudgets.googleapis.com
  artifactregistry.googleapis.com
  cloudbuild.googleapis.com
  cloudresourcemanager.googleapis.com
  cloudscheduler.googleapis.com
  cloudtasks.googleapis.com
  firestore.googleapis.com
  firebase.googleapis.com
  firebasehosting.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  identitytoolkit.googleapis.com
  logging.googleapis.com
  monitoring.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  serviceusage.googleapis.com
  sts.googleapis.com
)

gcloud services enable "${apis[@]}" --project="${PROJECT_ID}"

# Firestore Native データベース（§7）。作成済みなら何もしない。
# ロケーションは一度決めると変更できないため、Cloud Run と同じ REGION に置く。
if ! gcloud firestore databases describe --database="${FIRESTORE_DATABASE}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud firestore databases create \
    --database="${FIRESTORE_DATABASE}" \
    --location="${REGION}" \
    --type=firestore-native \
    --project="${PROJECT_ID}"
fi

if ! gcloud artifacts repositories describe "${AR_REPOSITORY}" \
  --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${AR_REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Application container images" \
    --project="${PROJECT_ID}"
fi

create_service_account() {
  local account_id="$1"
  local display_name="$2"
  local email="${account_id}@${PROJECT_ID}.iam.gserviceaccount.com"

  if ! gcloud iam service-accounts describe "${email}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${account_id}" \
      --display-name="${display_name}" \
      --project="${PROJECT_ID}"
  fi
}

create_service_account "${DEPLOYER_SA}" "GitHub Actions deployer"
create_service_account "${RUNTIME_SA}" "Event Agent runtime"
# Cloud Scheduler が Cloud Run Job を起動するときの身元。Job への run.invoker は
# deploy ワークフローが付ける
create_service_account "${SCHEDULER_SA}" "Event Agent scheduler"

deployer_roles=(
  roles/artifactregistry.writer
  roles/cloudscheduler.admin
  roles/firebasehosting.admin
  roles/firebaserules.admin
  roles/run.admin
  roles/serviceusage.apiKeysViewer
  roles/serviceusage.serviceUsageConsumer
)

runtime_roles=(
  roles/aiplatform.user
  roles/cloudtasks.enqueuer
  roles/datastore.user
  roles/logging.logWriter
  roles/secretmanager.secretAccessor
)

for role in "${deployer_roles[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

for role in "${runtime_roles[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

gcloud iam service-accounts add-iam-policy-binding \
  "${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null

# Scheduler ジョブに --oauth-service-account-email を付けるには、deployer が
# その SA を actAs できる必要がある
gcloud iam service-accounts add-iam-policy-binding \
  "${SCHEDULER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null

# 月額予算のアラート（50 / 90 / 100%）。請求アカウントの Costs Manager 権限が要る。
# 通知先は既定（請求管理者へのメール）。既にあれば作らない
budget_name="event-agent monthly ${PROJECT_ID}"
project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
if ! gcloud billing budgets list --billing-account="${BILLING_ACCOUNT}" \
    --filter="displayName='${budget_name}'" --format='value(name)' 2>/dev/null | grep -q .; then
  gcloud billing budgets create \
    --billing-account="${BILLING_ACCOUNT}" \
    --display-name="${budget_name}" \
    --budget-amount="${BUDGET_AMOUNT}${BUDGET_CURRENCY}" \
    --filter-projects="projects/${project_number}" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 \
    || echo "WARN: budget alert not created (needs Billing Account Costs Manager on ${BILLING_ACCOUNT})" >&2
fi

if ! gcloud iam workload-identity-pools describe "${WIF_POOL}" \
  --location=global --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${WIF_POOL}" \
    --location=global \
    --display-name="GitHub Actions" \
    --project="${PROJECT_ID}"
fi

if ! gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER}" \
  --workload-identity-pool="${WIF_POOL}" \
  --location=global \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER}" \
    --workload-identity-pool="${WIF_POOL}" \
    --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPOSITORY}' && assertion.ref=='refs/heads/develop'" \
    --project="${PROJECT_ID}"
fi

project_number="$(gcloud projects describe "${PROJECT_ID}" \
  --format='value(projectNumber)')"
principal="principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPOSITORY}"

gcloud iam service-accounts add-iam-policy-binding \
  "${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="${principal}" \
  --role="roles/iam.workloadIdentityUser" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null

provider_name="$(gcloud iam workload-identity-pools providers describe \
  "${WIF_PROVIDER}" \
  --workload-identity-pool="${WIF_POOL}" \
  --location=global \
  --project="${PROJECT_ID}" \
  --format='value(name)')"

echo
echo "GCP bootstrap complete."
echo "PROJECT_ID=${PROJECT_ID}"
echo "GCP_REGION=${REGION}"
echo "AR_REPOSITORY=${AR_REPOSITORY}"
echo "WIF_PROVIDER=${provider_name}"
echo "DEPLOYER_SERVICE_ACCOUNT=${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "RUNTIME_SERVICE_ACCOUNT=${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
