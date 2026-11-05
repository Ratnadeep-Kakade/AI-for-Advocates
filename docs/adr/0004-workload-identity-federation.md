# ADR-0004: Keyless GCP Workload Identity Federation (WIF)

## Status
Accepted

## Context
Deploying service account JSON keys inside Modal secrets violates security best practices and exposes long-lived credentials. Google Cloud recommends keyless authentication via Workload Identity Federation.

## Decision
Configure a GCP WIF Pool with Modal's OIDC issuer. Exchange the short-lived Modal identity token for short-lived Google Cloud access tokens. For Cloud SQL and GCS, authenticate using the federated identity. For GCS Signed URLs, invoke the IAM Credentials `signBlob` API with `roles/iam.serviceAccountTokenCreator`.

## Consequences
Zero persistent keys stored in environment variables or Modal secrets.
