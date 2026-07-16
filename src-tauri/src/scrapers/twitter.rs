use regex::Regex;
use serde_json::Value;
use std::time::Duration;

use crate::config::AppConfig;
use super::MediaItem;

pub struct TwitterScraper {
    client: reqwest::Client,
    bearer_token: String,
}

impl TwitterScraper {
    pub fn new(bearer_token: String, _config: &AppConfig) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            "User-Agent",
            reqwest::header::HeaderValue::from_static(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ),
        );
        
        if !bearer_token.is_empty() {
            let auth_str = format!("Bearer {}", bearer_token);
            if let Ok(auth_val) = reqwest::header::HeaderValue::from_str(&auth_str) {
                headers.insert("Authorization", auth_val);
            }
        }

        let client = reqwest::Client::builder()
            .default_headers(headers)
            .timeout(Duration::from_secs(15))
            .build()
            .unwrap_or_default();

        Self {
            client,
            bearer_token,
        }
    }

    pub fn get_hd_url(&self, url: &str) -> String {
        if !url.contains("pbs.twimg.com/media/") {
            return url.to_string();
        }
        
        let parsed_url = url.split('?').next().unwrap_or(url);
        let re_ext = Regex::new(r"\.(\w+)$").unwrap();
        let fmt = re_ext.captures(parsed_url)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str())
            .unwrap_or("jpg");

        let re_base = Regex::new(r"\.\w+$").unwrap();
        let base_url = re_base.replace(parsed_url, "");
        format!("{}?format={}&name=4096x4096", base_url, fmt)
    }

    pub async fn fetch_media(
        &self,
        query_or_username: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        if self.bearer_token.is_empty() {
            log::warn!("Twitter Bearer Token is not configured. Skipping Twitter scrape.");
            return Ok(Vec::new());
        }

        if query_or_username.starts_with('@') {
            let username = query_or_username.trim_start_matches('@');
            self.fetch_user_timeline(username, since_id, limit).await
        } else {
            self.fetch_search(query_or_username, since_id, limit).await
        }
    }

    async fn fetch_user_timeline(
        &self,
        username: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        // 1. Get User ID
        let user_url = format!("https://api.twitter.com/2/users/by/username/{}", username);
        let resp = self.client.get(&user_url).send().await
            .map_err(|e| format!("Twitter user ID request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("Twitter user by username returned status: {}", resp.status()));
        }

        let user_data: Value = resp.json().await
            .map_err(|e| format!("Twitter user JSON parse failed: {}", e))?;
            
        let user_id = user_data.pointer("/data/id").and_then(|id| id.as_str())
            .ok_or_else(|| format!("User {} not found on Twitter", username))?;

        // 2. Fetch Tweets
        let tweets_url = format!("https://api.twitter.com/2/users/{}/tweets", user_id);
        let mut query_params = vec![
            ("max_results", limit.unwrap_or(20).min(100).to_string()),
            ("expansions", "attachments.media_keys".to_string()),
            ("media.fields", "type,url,width,height,variants".to_string()),
            ("tweet.fields", "created_at,text".to_string()),
        ];
        if let Some(sid) = since_id {
            query_params.push(("since_id", sid.to_string()));
        }

        let resp = self.client.get(&tweets_url).query(&query_params).send().await
            .map_err(|e| format!("Twitter timeline request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("Twitter timeline returned status: {}", resp.status()));
        }

        let tweets_data: Value = resp.json().await
            .map_err(|e| format!("Twitter timeline JSON parse failed: {}", e))?;

        Ok(self.parse_api_response(&tweets_data, username))
    }

    async fn fetch_search(
        &self,
        query: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        let search_url = "https://api.twitter.com/2/tweets/search/recent";
        let mut query_params = vec![
            ("query", query.to_string()),
            ("max_results", limit.unwrap_or(20).min(100).to_string()),
            ("expansions", "attachments.media_keys".to_string()),
            ("media.fields", "type,url,width,height,variants".to_string()),
            ("tweet.fields", "created_at,text".to_string()),
        ];
        if let Some(sid) = since_id {
            query_params.push(("since_id", sid.to_string()));
        }

        let resp = self.client.get(search_url).query(&query_params).send().await
            .map_err(|e| format!("Twitter search request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("Twitter search returned status: {}", resp.status()));
        }

        let search_data: Value = resp.json().await
            .map_err(|e| format!("Twitter search JSON parse failed: {}", e))?;

        Ok(self.parse_api_response(&search_data, "unknown"))
    }

    fn parse_api_response(&self, response_data: &Value, default_author: &str) -> Vec<MediaItem> {
        let mut media_items = Vec::new();
        
        let data = match response_data.get("data") {
            Some(d) => d,
            None => return Vec::new(),
        };

        let tweets = if let Some(arr) = data.as_array() {
            arr.clone()
        } else {
            vec![data.clone()]
        };

        // Create media mapping
        let mut media_map = std::collections::HashMap::new();
        if let Some(media_arr) = response_data.pointer("/includes/media").and_then(|m| m.as_array()) {
            for media in media_arr {
                if let Some(key) = media.get("media_key").and_then(|k| k.as_str()) {
                    media_map.insert(key.to_string(), media.clone());
                }
            }
        }

        for tweet in tweets {
            let tweet_id = tweet.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
            let text = tweet.get("text").and_then(|t| t.as_str()).unwrap_or("").to_string();

            if let Some(media_keys) = tweet.pointer("/attachments/media_keys").and_then(|k| k.as_array()) {
                for key_val in media_keys {
                    let key = key_val.as_str().unwrap_or("");
                    if let Some(media_info) = media_map.get(key) {
                        let m_type = media_info.get("type").and_then(|t| t.as_str()).unwrap_or("");
                        
                        if m_type == "photo" {
                            if let Some(url) = media_info.get("url").and_then(|u| u.as_str()) {
                                media_items.push(MediaItem {
                                    url: self.get_hd_url(url),
                                    platform: "twitter".to_string(),
                                    post_id: tweet_id.clone(),
                                    author: default_author.to_string(),
                                    media_type: "photo".to_string(),
                                    original_url: url.to_string(),
                                    text: text.clone(),
                                });
                            }
                        } else if m_type == "video" || m_type == "animated_gif" {
                            if let Some(variants) = media_info.get("variants").and_then(|v| v.as_array()) {
                                if let Some(url) = self.get_best_video_variant(variants) {
                                    media_items.push(MediaItem {
                                        url: url.clone(),
                                        platform: "twitter".to_string(),
                                        post_id: tweet_id.clone(),
                                        author: default_author.to_string(),
                                        media_type: "video".to_string(),
                                        original_url: url,
                                        text: text.clone(),
                                    });
                                }
                            }
                        }
                    }
                }
            }
        }

        media_items
    }

    fn get_best_video_variant(&self, variants: &[Value]) -> Option<String> {
        let mut best_url = None;
        let mut max_bitrate = -1;
        
        for var in variants {
            if var.get("content_type").and_then(|c| c.as_str()) == Some("video/mp4") {
                let bitrate = var.get("bitrate").and_then(|b| b.as_i64()).unwrap_or(0);
                if bitrate > max_bitrate {
                    max_bitrate = bitrate;
                    best_url = var.get("url").and_then(|u| u.as_str()).map(|s| s.to_string());
                }
            }
        }
        
        best_url.or_else(|| {
            variants.first().and_then(|v| v.get("url")).and_then(|u| u.as_str()).map(|s| s.to_string())
        })
    }
}
