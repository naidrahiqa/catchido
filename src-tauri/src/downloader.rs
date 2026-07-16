use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use rusqlite::params;
use image::GenericImageView;
use img_hash::{HasherConfig, HashAlg};

use crate::config::AppConfig;
use crate::db::{Database, MediaHash};
use crate::scrapers::MediaItem;

pub struct DownloadManager {
    client: reqwest::Client,
    db_path: PathBuf,
    auto_dedup: bool,
    dedup_threshold: u32,
    prefer_higher_res: bool,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct DownloadReport {
    pub new_downloaded: u32,
    pub skipped_duplicate: u32,
    pub replaced_near_duplicate: u32,
    pub failed: u32,
}

impl DownloadManager {
    pub fn new(config: &AppConfig, db_path: &Path) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .unwrap_or_default();

        Self {
            client,
            db_path: db_path.to_path_buf(),
            auto_dedup: config.general.auto_dedup,
            dedup_threshold: config.general.dedup_threshold,
            prefer_higher_res: config.general.prefer_higher_res,
        }
    }

    pub async fn download_media(&self, items: &[MediaItem], idol_name: &str, group_name: &str, idol_type: &str, base_dir: &str) -> DownloadReport {
        let mut report = DownloadReport {
            new_downloaded: 0,
            skipped_duplicate: 0,
            replaced_near_duplicate: 0,
            failed: 0,
        };

        let db = Database::new(&self.db_path);

        for item in items {
            log::info!("Downloading: {}", item.url);
            match self.download_single_item(&db, item, idol_name, group_name, idol_type, base_dir).await {
                Ok(status) => match status {
                    DownloadStatus::New => report.new_downloaded += 1,
                    DownloadStatus::SkippedDuplicate => report.skipped_duplicate += 1,
                    DownloadStatus::ReplacedNearDuplicate => report.replaced_near_duplicate += 1,
                },
                Err(e) => {
                    log::error!("Failed to download {}: {}", item.url, e);
                    report.failed += 1;
                }
            }
        }

        report
    }

    async fn download_single_item(
        &self,
        db: &Database,
        item: &MediaItem,
        idol_name: &str,
        group_name: &str,
        idol_type: &str,
        base_dir: &str,
    ) -> Result<DownloadStatus, String> {
        // 1. Fetch bytes
        let resp = self.client.get(&item.url).send().await
            .map_err(|e| format!("HTTP request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("Server returned status: {}", resp.status()));
        }

        let bytes = resp.bytes().await
            .map_err(|e| format!("Failed to read response bytes: {}", e))?;
            
        if bytes.is_empty() {
            return Err("Empty response bytes".to_string());
        }

        // 2. Calculate exact SHA-256 hash
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        let exact_hash = format!("{:x}", hasher.finalize());

        // Check exact duplicate in DB
        let conn = db.connect().map_err(|e| e.to_string())?;
        let mut stmt = conn.prepare("SELECT file_path FROM media_hashes WHERE exact_hash = ?").map_err(|e| e.to_string())?;
        let mut rows = stmt.query_map([&exact_hash], |row| row.get::<_, String>(0)).map_err(|e| e.to_string())?;
        if let Some(r) = rows.next() {
            let path_str = r.map_err(|e| e.to_string())?;
            if Path::new(&path_str).exists() {
                log::info!("Exact duplicate found at {}. Skipping.", path_str);
                return Ok(DownloadStatus::SkippedDuplicate);
            }
        }

        // 3. Detect media extension
        let url_path = item.url.split('?').next().unwrap_or(&item.url);
        let mut ext = url_path.split('.').last().unwrap_or("jpg").to_lowercase();
        if ext.len() > 4 || ext.contains('/') {
            ext = "jpg".to_string();
        }

        // Determine photos/videos subfolder
        let subfolder = if ext == "mp4" || ext == "webm" || ext == "mov" || ext == "mkv" {
            "videos"
        } else {
            "photos"
        };

        // Determine group directory name with country flags
        let flag = if idol_type == "jp" { "🇯🇵 " } else { "🇰🇷 " };
        let group_dir_name = if group_name.is_empty() || group_name == "Solo" {
            "Solo".to_string()
        } else {
            format!("{}{}", flag, group_name)
        };

        // 4. Calculate perceptual hash (pHash) if it's a photo
        let mut phash_str = String::new();
        let is_photo = subfolder == "photos";
        if is_photo {
            if let Ok(img) = image::load_from_memory(&bytes) {
                let img_hasher = HasherConfig::new()
                    .hash_alg(HashAlg::Gradient)
                    .hash_size(8, 8)
                    .to_hasher();
                let hash = img_hasher.hash_image(&img);
                phash_str = hash.to_base64();
                
                // Check near duplicate (Hamming distance)
                if self.auto_dedup {
                    let mut stmt = conn.prepare("SELECT file_path, phash, file_size FROM media_hashes WHERE phash IS NOT NULL AND phash != ''").map_err(|e| e.to_string())?;
                    let hash_rows = stmt.query_map([], |row| {
                        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, u64>(2)?))
                    }).map_err(|e| e.to_string())?;

                    let current_hash = img_hash::ImageHash::from_base64(&phash_str).map_err(|e| e.to_string())?;
                    let mut near_dup_found = None;

                    for r in hash_rows {
                        let (existing_path, existing_phash, existing_size) = r.map_err(|e| e.to_string())?;
                        if let Ok(ex_hash) = img_hash::ImageHash::from_base64(&existing_phash) {
                            let dist = current_hash.dist(&ex_hash);
                            if dist <= self.dedup_threshold {
                                near_dup_found = Some((existing_path, existing_size));
                                break;
                            }
                        }
                    }

                    if let Some((ex_path, ex_size)) = near_dup_found {
                        let current_size = bytes.len() as u64;
                        if self.prefer_higher_res && current_size > ex_size {
                            log::info!("Replacing near duplicate {} (size: {}B) with higher res (size: {}B)", ex_path, ex_size, current_size);
                            fs::remove_file(&ex_path).ok();
                            conn.execute("DELETE FROM media_hashes WHERE file_path = ?", [&ex_path]).map_err(|e| e.to_string())?;
                            
                            // Let it continue to save the new file
                        } else {
                            log::info!("Near duplicate found at {} with threshold {}. Skipping.", ex_path, self.dedup_threshold);
                            return Ok(DownloadStatus::SkippedDuplicate);
                        }
                    }
                }
            }
        }

        // 5. Create directory structure
        // Pattern: {base_dir}/{group}/{idol_name}/{platform}/{photos|videos}/{YYYY-MM}/{filename}
        let now = chrono::Utc::now();
        let month_str = now.format("%Y-%m").to_string();
        
        let target_dir = Path::new(base_dir)
            .join(&group_dir_name)
            .join(idol_name)
            .join(&item.platform)
            .join(subfolder)
            .join(&month_str);

        fs::create_dir_all(&target_dir)
            .map_err(|e| format!("Failed to create directories: {}", e))?;

        // Filename: {username}_{post_id}.{ext}
        let safe_username = item.author.replace(|c: char| !c.is_alphanumeric() && c != '_', "");
        let filename = format!("{}_{}.{}", safe_username, item.post_id, ext);
        let file_path = target_dir.join(&filename);

        // 6. Write file to disk
        fs::write(&file_path, &bytes)
            .map_err(|e| format!("Failed to write file to disk: {}", e))?;

        // 7. Save metadata into SQLite
        let file_path_str = file_path.to_string_lossy().to_string();
        let file_size = bytes.len() as u64;
        let created_at_str = now.to_rfc3339();

        conn.execute(
            "INSERT OR REPLACE INTO media_hashes (
                file_path, phash, exact_hash, file_size, source_platform, post_id, idol_name, created_at, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                file_path_str,
                phash_str,
                exact_hash,
                file_size,
                item.platform,
                item.post_id,
                idol_name,
                created_at_str,
                if item.text.is_empty() { None } else { Some(&item.text) },
            ],
        ).map_err(|e| format!("Failed to save media metadata: {}", e))?;

        Ok(DownloadStatus::New)
    }
}

enum DownloadStatus {
    New,
    SkippedDuplicate,
    ReplacedNearDuplicate,
}
