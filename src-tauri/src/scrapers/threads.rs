use regex::Regex;
use serde_json::Value;
use std::time::Duration;

use crate::config::AppConfig;
use super::MediaItem;

pub struct ThreadsScraper {
    client: reqwest::Client,
    session_cookie: String,
}

impl ThreadsScraper {
    pub fn new(session_cookie: String, _config: &AppConfig) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("Referer", reqwest::header::HeaderValue::from_static("https://www.threads.net/"));
        headers.insert("Sec-Fetch-Dest", reqwest::header::HeaderValue::from_static("empty"));
        headers.insert("Sec-Fetch-Mode", reqwest::header::HeaderValue::from_static("cors"));
        headers.insert("Sec-Fetch-Site", reqwest::header::HeaderValue::from_static("same-origin"));
        headers.insert(
            "User-Agent",
            reqwest::header::HeaderValue::from_static(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ),
        );
        
        if !session_cookie.is_empty() {
            let cookie_str = if session_cookie.contains('=') {
                session_cookie.clone()
            } else {
                format!("sessionid={}", session_cookie)
            };
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
        }
    }

    pub fn get_hd_url(&self, url: &str) -> String {
        // Strip stp parameter if present to get high res
        if url.contains("cdninstagram.com") {
            let re = Regex::new(r"&stp=[^&]+").unwrap();
            return re.replace_all(url, "").to_string();
        }
        url.to_string()
    }

    pub async fn fetch_media(
        &self,
        query_or_username: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        let username = query_or_username.trim_start_matches('@');
        let url = format!("https://www.threads.net/@{}", username);
        
        let resp = self.client.get(&url).send().await
            .map_err(|e| format!("Threads request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("Threads profile returned status: {}", resp.status()));
        }

        let html = resp.text().await
            .map_err(|e| format!("Failed to read Threads response: {}", e))?;
            
        let mut media_items = Vec::new();
        
        // 1. Try parsing JSON from script tags
        let script_re = Regex::new(r#"<script type="application/json"[^>]*>([\s\S]*?)</script>"#).unwrap();
        for cap in script_re.captures_iter(&html) {
            let script_content = cap.get(1).map(|m| m.as_str()).unwrap_or("");
            if script_content.contains("image_versions2") || script_content.contains("carousel_media") {
                if let Ok(json_val) = serde_json::from_str::<Value>(script_content) {
                    let mut items = Vec::new();
                    self.extract_media_from_json(&json_val, username, &mut items);
                    media_items.extend(items);
                }
            }
        }

        // 2. Fallback: Regex parse CDN links
        if media_items.is_empty() {
            log::debug!("Falling back to regex parsing for Threads media links");
            let cdn_re = Regex::new(r#"https://scontent[^"']+\.cdninstagram\.com/[^"']+\.(?:jpg|jpeg|png|webp|mp4)"#).unwrap();
            
            let mut unique_urls = Vec::new();
            for cap in cdn_re.captures_iter(&html) {
                let cdn_url = cap.get(0).map(|m| m.as_str()).unwrap_or("");
                if !unique_urls.contains(&cdn_url.to_string()) {
                    unique_urls.push(cdn_url.to_string());
                }
            }

            for cdn_url in unique_urls {
                let clean_url = cdn_url.replace("\\u0026", "&").replace("&amp;", "&");
                let ext = clean_url.split('?').next().unwrap_or("").split('.').last().unwrap_or("").to_lowercase();
                
                let media_type = if ext == "mp4" || ext == "webm" {
                    "video"
                } else {
                    "photo"
                };

                // MD5 hash of clean_url as stable post_id
                let hash = md5::compute(clean_url.as_bytes());
                let post_id = format!("{:x}", hash)[..16].to_string();

                media_items.push(MediaItem {
                    url: self.get_hd_url(&clean_url),
                    platform: "threads".to_string(),
                    post_id,
                    author: username.to_string(),
                    media_type,
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
                log::info!("Reached Threads checkpoint: {}. Stopping.", sid);
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
            if let Some(post_id) = obj.get("id").and_then(|i| i.as_str()) {
                // Check if carousel or single image
                let text = obj.pointer("/caption/text").and_then(|t| t.as_str()).unwrap_or("").to_string();
                
                if let Some(carousel) = obj.get("carousel_media").and_then(|c| c.as_array()) {
                    for child in carousel {
                        if let Some(url) = child.pointer("/image_versions2/candidates").and_then(|c| c.as_array())
                            .and_then(|a| a.get(0)).and_then(|c| c.get("url")).and_then(|u| u.as_str()) {
                            items.push(MediaItem {
                                url: self.get_hd_url(url),
                                platform: "threads".to_string(),
                                post_id: post_id.to_string(),
                                author: author.to_string(),
                                media_type: "photo".to_string(),
                                original_url: url.to_string(),
                                text: text.clone(),
                            });
                        }
                    }
                } else if let Some(candidates) = obj.pointer("/image_versions2/candidates").and_then(|c| c.as_array()) {
                    if let Some(url) = candidates.get(0).and_then(|c| c.get("url")).and_then(|u| u.as_str()) {
                        items.push(MediaItem {
                            url: self.get_hd_url(url),
                            platform: "threads".to_string(),
                            post_id: post_id.to_string(),
                            author: author.to_string(),
                            media_type: "photo".to_string(),
                            original_url: url.to_string(),
                            text: text.clone(),
                        });
                    }
                }
            }
            
            // Recurse
            for value in obj.values() {
                self.extract_media_from_json(value, author, items);
            }
        } else if let Some(arr) = data.as_array() {
            for value in arr {
                self.extract_media_from_json(value, author, items);
            }
        }
    }
}
