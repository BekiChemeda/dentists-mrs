# ADR 0001 — Modular monolith on Django + DRF + PostgreSQL

Date: 2026-11-20 · Status: accepted

## Context

A clinic server has ~8 GB RAM and is supported by a small team. The product must be reliable, secure by default, easy to install, and maintainable for years. Options compared: Django + DRF, NestJS + Prisma, ASP.NET Core, Spring Boot. Adopting OpenMRS O3, Bahmni or OpenEMR was also considered.

## Decision

Build a modular monolith with Django 5.2 LTS, Django REST Framework and PostgreSQL 16, with a React + TypeScript SPA served by Nginx.

## Reasons

- Security-critical features ship in the framework: sessions, CSRF, Argon2 hashing, password validation, clickjacking protection, parameterised ORM.
- Built-in, reversible migrations and declarative database constraints.
- Low memory footprint compared with the JVM options; one process type to operate.
- Python is widely taught in Ethiopia, easing hiring and handover.
- Existing open-source EMRs are strong but heavy (Bahmni runs four systems), shaped around other billing models (OpenEMR), or need specialist implementers (OpenMRS). A product owned end-to-end is easier to support commercially for small private clinics.

## Consequences

- One deployable backend; module boundaries are enforced by convention (services only) and code review, not by network calls.
- No Redis, Celery, message broker or Kubernetes until a measured need appears.
- If a single free deployment were the goal, adopting OpenMRS O3 or Bahmni Lite should be reconsidered.
