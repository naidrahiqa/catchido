# PRD: Catchido — Future Updates

## Summary
Catchido is a smart HD media manager for K-pop/J-pop idol content. This PRD outlines the next features, fixes, and improvements.

---

## P1 — Critical Fixes

### 1. Catalog & Settings Blank Page
**Issue:** Catalog page shows no idol cards, Settings page shows blank fields, despite API returning correct data. Dashboard works fine.
**Root cause:** Likely JS runtime error preventing `fetchCatalog()`/`fetchSettings()` from completing.
**Fix:** Add error boundary + visible error messages in UI. Currently patched with console logging; needs browser-level verification.

### 2. Twitter API Always 401
**Issue:** `bearer_token` is `"undefined"` string, all Twitter API calls fail.
**Fix:** Validate/clean bearer token before saving; show warning in Settings when token is invalid.

### 3. Instagram Rate Limiting / 429 Handling
**Issue:** Mass downloads trigger Instagram CDN 429 errors.
**Current:** Exponential backoff implemented (retry with `(2^attempt)*5` seconds).
**Improvement:** Add adaptive rate limiting that pre-emptively slows down based on response headers.

---

## P2 — Feature Improvements

### 4. Selective Download
**Current:** Downloads ALL scraped media automatically.
**Goal:** Allow user to preview scraped items and select which to download (similar to gallery selection).

### 5. Download Queue Management
**Current:** Single job at a time.
**Goal:** Multi-job queue with pause/resume/cancel per idol or source. Show estimated time remaining.

### 6. Gallery Platform Filter + Delete
**Current:** Platform filter toggle and delete button added to code but untested.
**Goal:** Verify and polish the gallery filtering (Instagram/Twitter/Threads/TikTok/Weibo chips) and inline delete from lightbox.

### 7. Progress Bar for Downloads
**Current:** Basic polling endpoint + frontend bar.
**Goal:** Show per-file progress (file name, speed, ETA), not just total completed.

### 8. Data Usage / Quota Control
**Current:** `depth="recent"` vs `depth="full"` controls pagination.
**Goal:** Add explicit limits: max items per source, max pages, bandwidth cap warning. Useful for users with limited internet quota.

---

## P3 — New Features

### 9. Auto-Scrape Scheduling
**Current:** Background loop scrapes every N hours (configurable).
**Goal:** Per-idol schedule, smart interval (cooldown after full scrape, more frequent for active idols).

### 10. Search & Discovery
**Goal:** Auto-discover new fan accounts from mentions/retweets. Keyword-based content filtering. Relevance scoring for downloaded media.

### 11. Backup & Restore
**Goal:** Export/import idol profiles + sources as JSON. Optional media hash verification to detect corrupted files.

### 12. Mobile-Friendly Web UI
**Goal:** Responsive layout for phone browsing. Touch-friendly lightbox gestures (swipe).

### 13. Batch Add Idol
**Goal:** Import multiple idols from CSV/text file or paste list. Avoid repetitive form-filling for bulk additions.

### 14. Notification / Alert System
**Goal:** Push notification (desktop/browser) or email when a tracked idol posts new media. Optional per-idol frequency control.

### 15. Visual Dedup Comparison
**Goal:** Side-by-side preview of near-duplicate media before deletion. Let user choose which copy to keep instead of auto-delete.

### 16. Clipboard / Link Monitoring
**Goal:** Copy an IG/Twitter link → Catchido auto-detects idol → shows option to add source or download.

### 17. Lightbox Slideshow
**Goal:** Auto-play gallery with configurable interval, shuffle option, fullscreen mode.

### 18. Export Collection
**Goal:** Export media metadata (filename, source, date, platform) to CSV/JSON. Useful for backup, sharing, or external cataloging.

### 19. Platform Expansion
**Current:** Only Instagram scraper active. Twitter/Weibo/Threads/TikTok scrapers exist but need fixing.
**Goal:** Debug and activate all platform scrapers. Priority: Twitter (bearer token fix), then Weibo.

### 20. Theme Customization
**Goal:** Custom accent color picker in Settings. Save preference to config.

---

## P4 — Technical Debt

### 13. Test Coverage
**Current:** Only a few basic tests (database, dedup, scorer).
**Goal:** Add tests for web API endpoints, scraper edge cases, and frontend JS.

### 14. Error Standardization
**Goal:** Unified error response format across all API endpoints. Better user-facing error messages in Indonesian/English.

### 15. Config Validation
**Goal:** Validate config fields on save (download_dir must exist, delays must be positive, tokens must not be placeholder strings).

### 16. Performance
- Database query optimization (reduce `initialize()` calls per request)
- Lazy-load gallery images (already using `loading="lazy"`)
- Cache stats endpoint response (invalidated on new download)

---

## Timeline (Draft)

| Phase | Items | Target |
|-------|-------|--------|
| **Phase 1** | P1 items (catalog fix, Twitter auth, 429 handling) | Next release |
| **Phase 2** | P2 items (selective DL, queue, filter polish, progress) | Following release |
| **Phase 3** | P3 items (scheduling, discovery, backup) | Future |
| **Ongoing** | P4 items (tests, validation, performance) | Continuous |

---

*Last updated: 2026-07-16*
