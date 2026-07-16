use regex::Regex;
use serde_json::Value;
use std::time::Duration;

use crate::config::AppConfig;
use super::MediaItem;

pub struct TikTokScraper {
    client: reqwest::Client,
    session_cookie: String,
    download_photos: bool,
    download_videos: bool,
}

impl TikTokScraper {
    pub fn new(session_cookie: String, config: &AppConfig) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("Referer", reqwest::header::HeaderValue::from_static("https://www.tiktok.com/"));
        headers.insert("Sec-Fetch-Dest", reqwest::header::HeaderValue::from_static("document"));
        headers.insert("Sec-Fetch-Mode", reqwest::header::HeaderValue::from_static("navigate"));
        headers.insert("Sec-Fetch-Site", reqwest::header::HeaderValue::from_static("none"));
        headers.insert(
            "User-Agent",
            reqwest::header::HeaderValue::from_static(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ),
        );
        
        if !session_cookie.is_empty() {
            let cookie_str = format!("sessionid={}", session_cookie);
            if let Ok(cookie_val) = reqwest::header::HeaderValue::from_str(&cookie_str) {
                headers.insert("Cookie", cookie_val);
            }
        }

        let client = reqwest::Client::builder()
            .default_headers(headers)
            .timeout(Duration::from_secs(15))
            .build()
            .unwrap_or_default();

        Self {
            client,
            session_cookie,
            download_photos: config.general.download_photos,
            download_videos: config.general.download_videos,
        }
    }

    pub fn get_hd_url(&self, url: &str) -> String {
        url.to_string()
    }

    pub async fn fetch_media(
        &self,
        query_or_username: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        let username = query_or_username.trim_start_matches('@');
        let url = format!("https://www.tiktok.com/@{}", username);
        
        let resp = self.client.get(&url).send().await
            .map_err(|e| format!("TikTok profile request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("TikTok profile returned status: {}", resp.status()));
        }

        let html = resp.text().await
            .map_err(|e| format!("Failed to read TikTok response: {}", e))?;
            
        let mut media_items = Vec::new();
        
        // 1. Find rehydration or state script tags
        let state_patterns = [
            r#"<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([\s\S]*?)</script>"#,
            r#"<script id="SIGI_STATE"[^>]*>([\s\S]*?)</script>"#,
            r#"<script id="sigi-state"[^>]*>([\s\S]*?)</script>"#
        ];

        for pattern in &state_patterns {
            let re = Regex::new(pattern).unwrap();
            for cap in re.captures_iter(&html) {
                let mut content = cap.get(1).map(|m| m.as_str()).unwrap_or("").trim().to_string();
                
                // Clean up JS assignment if needed (e.g. window.SIGI_STATE = ...)
                if content.contains('=') && !content.starts_with('{') {
                    let assign_re = Regex::new(r"=\s*(\{.*?\});?$").unwrap();
                    if let Some(m) = assign_re.captures(&content) {
                        content = m.get(1).map(|x| x.as_str()).unwrap_or("").to_string();
                    }
                }
                
                if let Ok(json_val) = serde_json::from_str::<Value>(&content) {
                    let mut items = Vec::new();
                    self.extract_media_from_json(&json_val, username, &mut items);
                    media_items.extend(items);
                }
            }
        }

        // 2. Fallback: Regex parse TikTok photo CDN URLs
        if media_items.is_empty() && self.download_photos {
            log::debug!("Falling back to regex parsing for TikTok photo CDN URLs");
            let cdn_re = Regex::new(r#"https://[a-zA-Z0-9.-]+\.(?:tiktokcdn|byteoversea|ibyteimg|tiktokcdn-us)\.com/[^"']+\.(?:jpg|jpeg|png|webp)"#).unwrap();
            
            let mut unique_urls = Vec::new();
            for cap in cdn_re.captures_iter(&html) {
                let cdn_url = cap.get(0).map(|m| m.as_str()).unwrap_or("");
                if !unique_urls.contains(&cdn_url.to_string()) {
                    unique_urls.push(cdn_url.to_string());
                }
            }

            for cdn_url in unique_urls {
                let clean_url = cdn_url.replace("\\u0026", "&").replace("&amp;", "&");
                let hash = md5::compute(clean_url.as_bytes());
                let post_id = format!("{:x}", hash)[..16].to_string();

                media_items.push(MediaItem {
                    url: self.get_hd_url(&clean_url),
                    platform: "tiktok".to_string(),
                    post_id,
                    author: username.to_string(),
                    media_type: "photo".to_string(),
                    original_url: clean_url,
                    text: "".to_string(),
                });
            }
        }

        // Deduplicate
        let mut unique_results = std::collections::HashMap::new();
        for item in media_items {
            unique_results.insert(item.url.clone(), item);
        }
        
        let mut final_list: Vec<MediaItem> = unique_results.into_values().collect();
        
        // Filter by since_id
        if let Some(sid) = since_id {
            if let Some(pos) = final_list.iter().position(|item| item.post_id == sid) {
                log::info!("Reached TikTok checkpoint: {}. Stopping.", sid);
                final_list.truncate(pos);
            }
        }

        if let Some(lim) = limit {
            if final_list.len() > lim {
                final_list.truncate(lim);
            }
        }

        Ok(final_list)
    }

    fn extract_media_from_json(&self, data: &Value, author: &str, items: &mut Vec<MediaItem>) {
        if let Some(obj) = data.as_object() {
            let is_post = obj.contains_key("id") && 
                (obj.contains_key("imagePost") || obj.contains_key("video") || obj.contains_key("desc"));
                
            if is_post {
                let post_id = obj.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
                let caption_text = obj.get("desc").or_else(|| obj.get("caption")).and_then(|t| t.as_str()).unwrap_or("").to_string();
                
                // Process photo slideshow
                if let Some(image_post_info) = obj.get("imagePost").or_else(|| obj.get("image_post_info")) {
                    if self.download_photos {
                        if let Some(images) = image_post_info.get("images").and_then(|i| i.as_array()) {
                            for (idx, img) in images.iter().enumerate() {
                                let mut display_url = None;
                                if let Some(url_list) = img.pointer("/display_image/url_list").or_else(|| img.get("url_list")).and_then(|l| l.as_array()) {
                                    if let Some(first_url) = url_list.get(0).and_then(|u| u.as_str()) {
                                        display_url = Some(first_url.to_string());
                                    }
                                } else if let Some(url) = img.get("url").and_then(|u| u.as_str()) {
                                    display_url = Some(url.to_string());
                                }
                                
                                if let Some(url) = display_url {
                                    items.push(MediaItem {
                                        url: self.get_hd_url(&url),
                                        platform: "tiktok".to_string(),
                                        post_id: format!("{}_{}", post_id, idx),
                                        author: author.to_string(),
                                        media_type: "photo".to_string(),
                                        original_url: url,
                                        text: caption_text.clone(),
                                    });
                                }
                            }
                        }
                    }
                }
                // Process video
                else if obj.contains_key("video") && self.download_videos {
                    let video_struct = obj.get("video").unwrap();
                    let url = video_struct.get("downloadAddr").or_else(|| video_struct.get("playAddr")).and_then(|u| u.as_str());
                    if let Some(video_url) = url {
                        items.push(MediaItem {
                            url: video_url.to_string(),
                            platform: "tiktok".to_string(),
                            post_id: post_id.clone(),
                            author: author.to_string(),
                            media_type: "video".to_string(),
                            original_url: video_url.to_string(),
                            text: caption_text.clone(),
                        });
                    }
                }
            } else {
                for value in obj.values() {
                    self.extract_media_from_json(value, author, items);
                }
            }
        } else if let Some(arr) = data.as_array() {
            for value in arr {
                self.extract_media_from_json(value, author, items);
            }
        }
    }
}
