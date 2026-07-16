mod config;
mod db;
mod scrapers;
mod downloader;

use std::sync::Mutex;
use std::path::{Path, PathBuf};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State};

use config::AppConfig;
use db::{Database, IdolProfile, TrustedAccount, IdolKeyword, DownloadCheckpoint};
use scrapers::MediaItem;
use scrapers::twitter::TwitterScraper;
use scrapers::weibo::WeiboScraper;
use scrapers::instagram::InstagramScraper;
use scrapers::threads::ThreadsScraper;
use scrapers::tiktok::TikTokScraper;
use downloader::DownloadManager;

// Global States
pub struct LogState {
    pub logs: Mutex<Vec<String>>,
}

pub struct JobState {
    pub is_running: Mutex<bool>,
    pub target: Mutex<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct IdolSchema {
    pub name: String,
    pub idol_type: String, // "jp" or "kr"
    pub kanji: Option<String>,
    pub generation: Option<String>,
    pub team: Option<String>,
    pub hangul: Option<String>,
    pub stage_name: Option<String>,
    pub real_name: Option<String>,
    pub positions: Option<Vec<String>>,
    pub group: Option<String>,
    pub company: Option<String>,
    pub fandom: Option<String>,
    pub birthday: Option<String>,
    pub debut: Option<String>,
    pub status: Option<String>,
    pub graduation_date: Option<String>,
    pub nicknames: Option<String>,
    pub exclude: Option<String>,
    pub twitter: Option<Vec<String>>,
    pub weibo: Option<Vec<String>>,
    pub instagram: Option<Vec<String>>,
    pub threads: Option<Vec<String>>,
    pub tiktok: Option<Vec<String>>,
}

// Logger helpers
fn log_info(logs: &State<LogState>, msg: &str) {
    let log_line = format!("{} | INFO    | {}", chrono::Local::now().format("%H:%M:%S"), msg);
    println!("{}", log_line);
    if let Ok(mut l) = logs.logs.lock() {
        l.push(log_line);
        if l.len() > 1000 {
            l.remove(0);
        }
    }
}

fn log_warn(logs: &State<LogState>, msg: &str) {
    let log_line = format!("{} | WARNING | {}", chrono::Local::now().format("%H:%M:%S"), msg);
    eprintln!("{}", log_line);
    if let Ok(mut l) = logs.logs.lock() {
        l.push(log_line);
    }
}

fn log_error(logs: &State<LogState>, msg: &str) {
    let log_line = format!("{} | ERROR   | {}", chrono::Local::now().format("%H:%M:%S"), msg);
    eprintln!("{}", log_line);
    if let Ok(mut l) = logs.logs.lock() {
        l.push(log_line);
    }
}

fn get_db_path() -> PathBuf {
    let cfg = load_app_config();
    Path::new(&cfg.general.download_dir).join("catchido.db")
}

fn load_app_config() -> AppConfig {
    AppConfig::load_or_create(Path::new("config.toml")).unwrap_or_default()
}

// 🎯 Commands definition

#[tauri::command]
async fn get_stats(logs: State<'_, LogState>, job: State<'_, JobState>) -> Result<Value, String> {
    let db_path = get_db_path();
    let db = Database::new(&db_path);
    db.initialize().map_err(|e| e.to_string())?;

    let stats = db.get_download_stats().map_err(|e| e.to_string())?;
    let idols = db.list_idols().map_err(|e| e.to_string())?;

    let is_running = *job.is_running.lock().unwrap();
    let target = job.target.lock().unwrap().clone();

    let mut result = stats.as_object().unwrap().clone();
    result.insert("total_idols".to_string(), json!(idols.len()));
    result.insert("is_job_running".to_string(), json!(is_running));
    result.insert("active_job_target".to_string(), json!(target));

    Ok(Value::Object(result))
}

#[tauri::command]
async fn get_idols() -> Result<Value, String> {
    let db_path = get_db_path();
    let db = Database::new(&db_path);
    db.initialize().map_err(|e| e.to_string())?;

    let idols = db.list_idols().map_err(|e| e.to_string())?;
    let mut result = Vec::new();

    for idol in idols {
        let media_count = db.get_media_count(&idol.display_name).unwrap_or(0);
        result.push(json!({
            "name": idol.display_name,
            "type": idol.idol_type,
            "group": idol.group_name.unwrap_or_else(|| "Solo".to_string()),
            "company": idol.company.unwrap_or_else(|| "-".to_string()),
            "status": idol.status,
            "media_count": media_count
        }));
    }

    Ok(json!(result))
}

#[tauri::command]
async fn get_idol_detail(name: String) -> Result<Value, String> {
    let db_path = get_db_path();
    let db = Database::new(&db_path);
    
    let idol = db.get_idol(&name).map_err(|e| e.to_string())?
        .ok_or_else(|| "Idol not found".to_string())?;
        
    let keywords = db.get_keywords_for_idol(&name).map_err(|e| e.to_string())?;
    let trusted = db.get_trusted_accounts(&name).map_err(|e| e.to_string())?;
    let media_count = db.get_media_count(&name).unwrap_or(0);

    Ok(json!({
        "profile": {
            "name": idol.display_name,
            "type": idol.idol_type,
            "kanji": idol.kanji_name,
            "generation": idol.generation,
            "team": idol.team,
            "hangul": idol.hangul_name,
            "stage_name": idol.stage_name,
            "real_name": idol.real_name,
            "positions": idol.positions,
            "group": idol.group_name,
            "company": idol.company,
            "fandom": idol.fandom_name,
            "birthday": idol.birthday,
            "debut": idol.debut_date,
            "status": idol.status,
            "graduation_date": idol.graduation_date,
            "media_count": media_count
        },
        "sources": trusted.iter().map(|t| json!({
            "platform": t.platform,
            "username": t.username,
            "type": t.account_type
        })).collect::<Vec<_>>(),
        "keywords": keywords.iter().map(|k| k.keyword.clone()).collect::<Vec<_>>()
    }))
}

#[tauri::command]
async fn add_idol(data: IdolSchema) -> Result<Value, String> {
    let db_path = get_db_path();
    let db = Database::new(&db_path);

    let profile = IdolProfile {
        display_name: data.name.clone(),
        idol_type: data.type.clone(),
        kanji_name: data.kanji.clone(),
        generation: data.generation.clone(),
        team: data.team.clone(),
        hangul_name: data.hangul.clone(),
        stage_name: data.stage_name.clone(),
        real_name: data.real_name.clone(),
        positions: data.positions.clone().unwrap_or_default(),
        group_name: data.group.clone(),
        company: data.company.clone(),
        fandom_name: data.fandom.clone(),
        birthday: data.birthday.clone(),
        debut_date: data.debut.clone(),
        status: data.status.clone().unwrap_or_else(|| "active".to_string()),
        graduation_date: data.graduation_date.clone(),
    };

    db.add_idol(&profile).map_err(|e| e.to_string())?;

    // Add platform accounts
    let platforms = [
        ("twitter", &data.twitter),
        ("weibo", &data.weibo),
        ("instagram", &data.instagram),
        ("threads", &data.threads),
        ("tiktok", &data.tiktok),
    ];

    for (plat_name, accounts_opt) in &platforms {
        if let Some(accounts) = accounts_opt {
            for acct in accounts {
                let clean_acct = acct.trim();
                if !clean_acct.is_empty() {
                    db.add_trusted_account(&TrustedAccount {
                        idol_name: data.name.clone(),
                        platform: plat_name.to_string(),
                        username: clean_acct.to_string(),
                        account_type: if clean_acct.to_lowercase() == format!("@{}", data.name.to_lowercase()) {
                            "official".to_string()
                        } else {
                            "fansite".to_string()
                        },
                    }).map_err(|e| e.to_string())?;
                }
            }
        }
    }

    // Auto-generate basic search keywords
    let mut keywords = Vec::new();
    
    // Add display name
    keywords.push(IdolKeyword {
        idol_name: data.name.clone(),
        idol_type: data.type.clone(),
        keyword: data.name.clone(),
        script_type: "alias".to_string(),
        platform: "all".to_string(),
        is_auto_generated: true,
    });

    if let Some(kanji) = &data.kanji {
        keywords.push(IdolKeyword {
            idol_name: data.name.clone(),
            idol_type: data.type.clone(),
            keyword: kanji.clone(),
            script_type: "alias".to_string(),
            platform: "all".to_string(),
            is_auto_generated: true,
        });
    }

    if let Some(hangul) = &data.hangul {
        keywords.push(IdolKeyword {
            idol_name: data.name.clone(),
            idol_type: data.type.clone(),
            keyword: hangul.clone(),
            script_type: "alias".to_string(),
            platform: "all".to_string(),
            is_auto_generated: true,
        });
    }

    if let Some(group) = &data.group {
        keywords.push(IdolKeyword {
            idol_name: data.name.clone(),
            idol_type: data.type.clone(),
            keyword: format!("{} {}", group, data.name),
            script_type: "generated".to_string(),
            platform: "all".to_string(),
            is_auto_generated: true,
        });
        
        keywords.push(IdolKeyword {
            idol_name: data.name.clone(),
            idol_type: data.type.clone(),
            keyword: format!("#{}", group),
            script_type: "hashtag".to_string(),
            platform: "all".to_string(),
            is_auto_generated: true,
        });
    }

    keywords.push(IdolKeyword {
        idol_name: data.name.clone(),
        idol_type: data.type.clone(),
        keyword: format!("#{}", data.name),
        script_type: "hashtag".to_string(),
        platform: "all".to_string(),
        is_auto_generated: true,
    });

    for kw in keywords {
        db.add_keyword(&kw).ok();
    }

    Ok(json!({"status": "ok", "message": "Idol added successfully"}))
}

#[tauri::command]
async fn delete_idol(name: String) -> Result<Value, String> {
    let db_path = get_db_path();
    let db = Database::new(&db_path);
    db.delete_idol(&name).map_err(|e| e.to_string())?;
    Ok(json!({"status": "ok", "message": "Idol deleted"}))
}

#[tauri::command]
async fn get_idol_media(name: String) -> Result<Value, String> {
    let db_path = get_db_path();
    let db = Database::new(&db_path);
    let conn = db.connect().map_err(|e| e.to_string())?;
    
    let mut stmt = conn.prepare(
        "SELECT file_path, source_platform, post_id, created_at, text FROM media_hashes WHERE idol_name = ? ORDER BY created_at DESC"
    ).map_err(|e| e.to_string())?;

    let rows = stmt.query_map([&name], |row| {
        Ok(json!({
            "src": row.get::<_, String>(0)?,
            "platform": row.get::<_, String>(1)?,
            "post_id": row.get::<_, String>(2)?,
            "created_at": row.get::<_, String>(3)?,
            "caption": row.get::<_, Option<String>>(4)?.unwrap_or_default()
        }))
    }).map_err(|e| e.to_string())?;

    let mut result = Vec::new();
    for r in rows {
        if let Ok(val) = r {
            result.push(val);
        }
    }

    Ok(json!(result))
}

#[tauri::command]
async fn get_logs(logs: State<'_, LogState>) -> Result<Vec<String>, String> {
    let mut l = logs.logs.lock().unwrap();
    let result = l.clone();
    l.clear();
    Ok(result)
}

// Background scraping job handler
async fn run_scrape_background(
    logs: State<'_, LogState>,
    job: State<'_, JobState>,
    name: String,
) {
    *job.is_running.lock().unwrap() = true;
    *job.target.lock().unwrap() = name.clone();

    log_info(&logs, &format!("=== Starting Scrape Session for {} ===", name));

    let cfg = load_app_config();
    let db_path = get_db_path();
    let db = Database::new(&db_path);

    let idol_res = db.get_idol(&name);
    if let Ok(Some(idol)) = idol_res {
        let trusted_res = db.get_trusted_accounts(&name);
        let trusted = trusted_res.unwrap_or_default();

        let tw_scraper = TwitterScraper::new(cfg.twitter.bearer_token.clone(), &cfg);
        let wb_scraper = WeiboScraper::new(cfg.weibo.cookie.clone(), &cfg);
        let ig_scraper = InstagramScraper::new(cfg.instagram.session_cookie.clone(), &cfg);
        let th_scraper = ThreadsScraper::new(cfg.threads.session_cookie.clone(), &cfg);
        let tk_scraper = TikTokScraper::new(cfg.tiktok.session_cookie.clone(), &cfg);
        let downloader = DownloadManager::new(&cfg, &db_path);

        let mut media_items_to_download = Vec::new();

        // 1. Twitter Scrape
        let tw_sources: Vec<_> = trusted.iter().filter(|t| t.platform == "twitter").collect();
        if !cfg.twitter.bearer_token.is_empty() && !tw_sources.is_empty() {
            log_info(&logs, &format!("[{}] Scraping Twitter sources...", name));
            for src in tw_sources {
                let chk = db.get_checkpoint(&name, "twitter", &src.username).unwrap_or(None);
                match tw_scraper.fetch_media(&src.username, chk.as_deref(), Some(20)).await {
                    Ok(items) => {
                        if !items.is_empty() {
                            let mut numeric_ids: Vec<u64> = items.iter()
                                .filter_map(|i| i.post_id.parse::<u64>().ok())
                                .collect();
                            numeric_ids.sort();
                            let latest_id = numeric_ids.last().map(|id| id.to_string())
                                .unwrap_or_else(|| items[0].post_id.clone());
                                
                            db.update_checkpoint(&DownloadCheckpoint {
                                idol_name: name.clone(),
                                platform: "twitter".to_string(),
                                source_username: src.username.clone(),
                                last_id: latest_id,
                            }).ok();
                            media_items_to_download.extend(items);
                        }
                    }
                    Err(e) => log_error(&logs, &format!("Twitter scrape failed for {}: {}", src.username, e)),
                }
            }
        }

        // 2. Weibo Scrape
        let wb_sources: Vec<_> = trusted.iter().filter(|t| t.platform == "weibo").collect();
        if !wb_sources.is_empty() {
            log_info(&logs, &format!("[{}] Scraping Weibo sources...", name));
            for src in wb_sources {
                let chk = db.get_checkpoint(&name, "weibo", &src.username).unwrap_or(None);
                match wb_scraper.fetch_media(&src.username, chk.as_deref(), Some(20)).await {
                    Ok(items) => {
                        if !items.is_empty() {
                            db.update_checkpoint(&DownloadCheckpoint {
                                idol_name: name.clone(),
                                platform: "weibo".to_string(),
                                source_username: src.username.clone(),
                                last_id: items[0].post_id.clone(),
                            }).ok();
                            media_items_to_download.extend(items);
                        }
                    }
                    Err(e) => log_error(&logs, &format!("Weibo scrape failed for {}: {}", src.username, e)),
                }
            }
        }

        // 3. Instagram Scrape
        let ig_sources: Vec<_> = trusted.iter().filter(|t| t.platform == "instagram").collect();
        if !ig_sources.is_empty() {
            log_info(&logs, &format!("[{}] Scraping Instagram sources...", name));
            for src in ig_sources {
                let chk = db.get_checkpoint(&name, "instagram", &src.username).unwrap_or(None);
                match ig_scraper.fetch_media(&src.username, chk.as_deref(), Some(20)).await {
                    Ok(items) => {
                        if !items.is_empty() {
                            db.update_checkpoint(&DownloadCheckpoint {
                                idol_name: name.clone(),
                                platform: "instagram".to_string(),
                                source_username: src.username.clone(),
                                last_id: items[0].post_id.clone(),
                            }).ok();
                            media_items_to_download.extend(items);
                        }
                    }
                    Err(e) => log_error(&logs, &format!("Instagram scrape failed for {}: {}", src.username, e)),
                }
            }
        }

        // 4. Threads Scrape
        let th_sources: Vec<_> = trusted.iter().filter(|t| t.platform == "threads").collect();
        if !th_sources.is_empty() {
            log_info(&logs, &format!("[{}] Scraping Threads sources...", name));
            for src in th_sources {
                let chk = db.get_checkpoint(&name, "threads", &src.username).unwrap_or(None);
                match th_scraper.fetch_media(&src.username, chk.as_deref(), Some(20)).await {
                    Ok(items) => {
                        if !items.is_empty() {
                            db.update_checkpoint(&DownloadCheckpoint {
                                idol_name: name.clone(),
                                platform: "threads".to_string(),
                                source_username: src.username.clone(),
                                last_id: items[0].post_id.clone(),
                            }).ok();
                            media_items_to_download.extend(items);
                        }
                    }
                    Err(e) => log_error(&logs, &format!("Threads scrape failed for {}: {}", src.username, e)),
                }
            }
        }

        // 5. TikTok Scrape
        let tk_sources: Vec<_> = trusted.iter().filter(|t| t.platform == "tiktok").collect();
        if !tk_sources.is_empty() {
            log_info(&logs, &format!("[{}] Scraping TikTok sources...", name));
            for src in tk_sources {
                let chk = db.get_checkpoint(&name, "tiktok", &src.username).unwrap_or(None);
                match tk_scraper.fetch_media(&src.username, chk.as_deref(), Some(20)).await {
                    Ok(items) => {
                        if !items.is_empty() {
                            db.update_checkpoint(&DownloadCheckpoint {
                                idol_name: name.clone(),
                                platform: "tiktok".to_string(),
                                source_username: src.username.clone(),
                                last_id: items[0].post_id.clone(),
                            }).ok();
                            media_items_to_download.extend(items);
                        }
                    }
                    Err(e) => log_error(&logs, &format!("TikTok scrape failed for {}: {}", src.username, e)),
                }
            }
        }

        // Deduplicate in memory
        let mut unique_items = std::collections::HashMap::new();
        for item in media_items_to_download {
            unique_items.insert(item.url.clone(), item);
        }
        let final_list: Vec<_> = unique_items.into_values().collect();
        log_info(&logs, &format!("Found {} unique media items for {}", final_list.len(), name));

        if !final_list.is_empty() {
            let report = downloader.download_media(
                &final_list,
                &idol.display_name,
                &idol.group_name.unwrap_or_else(|| "Solo".to_string()),
                &idol.idol_type,
                &cfg.general.download_dir,
            ).await;
            
            log_info(&logs, &format!(
                "Scrape complete: New: {}, Replaced: {}, Skipped: {}, Failed: {}",
                report.new_downloaded, report.replaced_near_duplicate, report.skipped_duplicate, report.failed
            ));
        }
    } else {
        log_error(&logs, &format!("Idol {} not found in database", name));
    }

    log_info(&logs, "=== Scrape Session Finished ===");
    *job.is_running.lock().unwrap() = false;
    *job.target.lock().unwrap() = String::new();
}

#[tauri::command]
async fn trigger_download(
    name: String,
    logs: State<'_, LogState>,
    job: State<'_, JobState>,
    app: AppHandle,
) -> Result<Value, String> {
    let is_running = *job.is_running.lock().unwrap();
    if is_running {
        return Err("Another download job is already running".to_string());
    }

    // Spawn async background scraper task
    let logs_clone = app.state::<LogState>();
    let job_clone = app.state::<JobState>();
    tokio::spawn(async move {
        run_scrape_background(logs_clone, job_clone, name).await;
    });

    Ok(json!({"status": "ok", "message": "Scrape triggered in background"}))
}

#[tauri::command]
async fn get_web_config() -> Result<Value, String> {
    let c = load_app_config();
    Ok(json!({
        "download_dir": c.general.download_dir,
        "max_concurrent_downloads": c.general.max_concurrent_downloads,
        "auto_dedup": c.general.auto_dedup,
        "dedup_threshold": c.general.dedup_threshold,
        "prefer_higher_res": c.general.prefer_higher_res,
        "download_photos": c.general.download_photos,
        "download_videos": c.general.download_videos,
        "twitter_bearer": c.twitter.bearer_token,
        "weibo_cookie": c.weibo.cookie,
        "instagram_cookie": c.instagram.session_cookie,
        "threads_cookie": c.threads.session_cookie,
        "tiktok_cookie": c.tiktok.session_cookie,
    }))
}

#[tauri::command]
async fn save_web_config(data: Value) -> Result<Value, String> {
    let mut c = load_app_config();
    if let Some(obj) = data.as_object() {
        if let Some(dir) = obj.get("download_dir").and_then(|d| d.as_str()) {
            c.general.download_dir = dir.to_string();
        }
        if let Some(max) = obj.get("max_concurrent_downloads").and_then(|m| m.as_u64()) {
            c.general.max_concurrent_downloads = max as usize;
        }
        if let Some(dedup) = obj.get("auto_dedup").and_then(|d| d.as_bool()) {
            c.general.auto_dedup = dedup;
        }
        if let Some(threshold) = obj.get("dedup_threshold").and_then(|t| t.as_u64()) {
            c.general.dedup_threshold = threshold as u32;
        }
        if let Some(pref) = obj.get("prefer_higher_res").and_then(|p| p.as_bool()) {
            c.general.prefer_higher_res = pref;
        }
        if let Some(photos) = obj.get("download_photos").and_then(|p| p.as_bool()) {
            c.general.download_photos = photos;
        }
        if let Some(videos) = obj.get("download_videos").and_then(|v| v.as_bool()) {
            c.general.download_videos = videos;
        }
        if let Some(tw) = obj.get("twitter_bearer").and_then(|t| t.as_str()) {
            c.twitter.bearer_token = tw.to_string();
        }
        if let Some(ig) = obj.get("instagram_cookie").and_then(|i| i.as_str()) {
            c.instagram.session_cookie = ig.to_string();
        }
        if let Some(th) = obj.get("threads_cookie").and_then(|t| t.as_str()) {
            c.threads.session_cookie = th.to_string();
        }
        if let Some(tk) = obj.get("tiktok_cookie").and_then(|t| t.as_str()) {
            c.tiktok.session_cookie = tk.to_string();
        }
        if let Some(wb) = obj.get("weibo_cookie").and_then(|w| w.as_str()) {
            c.weibo.cookie = wb.to_string();
        }
    }

    c.save(Path::new("config.toml")).map_err(|e| e.to_string())?;
    Ok(json!({"status": "ok", "message": "Settings saved successfully"}))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_log::Builder::default().build())
    .manage(LogState { logs: Mutex::new(Vec::new()) })
    .manage(JobState { is_running: Mutex::new(false), target: Mutex::new(String::new()) })
    .invoke_handler(tauri::generate_handler![
        get_stats,
        get_idols,
        add_idol,
        delete_idol,
        get_idol_detail,
        get_idol_media,
        trigger_download,
        get_web_config,
        save_web_config,
        get_logs
    ])
    .setup(|app| {
        // Initialize SQLite DB
        let db_path = get_db_path();
        let db = Database::new(&db_path);
        db.initialize().expect("Failed to initialize database schema");
        Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
