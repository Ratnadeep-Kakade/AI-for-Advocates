# Terraform configuration for Cicero GCP Infrastructure
# Cloud SQL (PostgreSQL with pgvector), Google Cloud Storage, and Workload Identity Federation

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Google Cloud Storage Bucket for Legal Documents
resource "google_storage_bucket" "legal_documents" {
  name          = var.gcs_bucket_name
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  cors {
    origin          = ["*"]
    method          = ["GET", "PUT", "HEAD"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}

# 2. Workload Identity Pool for Modal OIDC
resource "google_iam_workload_identity_pool" "modal_pool" {
  workload_identity_pool_id = "modal-cicero-pool"
  display_name              = "Modal Cicero Identity Pool"
  description               = "Trusts Modal's OIDC issuer for keyless service authentication"
}

# 3. Workload Identity Provider for Modal
resource "google_iam_workload_identity_pool_provider" "modal_provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.modal_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "modal-cicero-provider"
  display_name                       = "Modal OIDC Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.app_name"   = "assertion.app_name"
    "attribute.func_name"  = "assertion.function_name"
  }

  oidc {
    issuer_uri = "https://oidc.modal.com"
  }
}
