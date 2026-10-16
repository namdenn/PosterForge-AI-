# Acme Coffee render assets

This directory contains two generated demo assets ready for local Sprint 3 testing:

1. `logos/acme-logo.png`: transparent Acme Coffee logo.
2. `products/acme-citrus-cold-brew.png`: transparent product cutout.

The assets are marked `approved` in `asset_manifest.json` so the local demo workflow can resolve
them. This means locally approved for testing only; they are not official corporate assets. Before
production use, replace both files with brand-owner-approved sources and update their versions and
descriptions in the manifest.

Sprint 3 deliberately stops before an API call when a required asset is missing, outside this
directory, unapproved, assigned to another channel, or scoped to another tenant/brand.
