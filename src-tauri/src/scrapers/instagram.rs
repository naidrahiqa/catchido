use serde_json::Value;
use std::time::Duration;
use tokio::time::sleep;

use crate::config::AppConfig;
use super::MediaItem;

pub struct InstagramScraper {
    client: reqwest::Client,
    session_cookie: String,
}

impl InstagramScraper {
    pub fn new(session_cookie: String, _config: &AppConfig) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("Referer", reqwest::header::HeaderValue::from_static("https://www.instagram.com/"));
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
        }
    }

    pub async fn fetch_media(
        &self,
        query_or_username: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        let username = query_or_username.trim_start_matches('@');
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("X-IG-App-ID", reqwest::header::HeaderValue::from_static("936619743392459"));
        headers.insert("X-Requested-With", reqwest::header::HeaderValue::from_static("XMLHttpRequest"));
        headers.insert(
            "Referer",
            reqwest::header::HeaderValue::from_str(&format!("https://www.instagram.com/{}/", username)).unwrap(),
        );

        let items_needed = limit.unwrap_or(50);
        let mut media_items = Vec::new();

        // Method 1: Try user feed REST API
        let feed_url = format!("https://www.instagram.com/api/v1/feed/user/{}/username/", username);
        let resp_res = self.client.get(&feed_url).headers(headers.clone()).send().await;

        if let Ok(resp) = resp_res {
            if resp.status() == reqwest::StatusCode::OK {
                if let Ok(feed_data) = resp.json::<Value>().await {
                    let mut items = feed_data.get("items").and_then(|i| i.as_array()).cloned().unwrap_or_default();
                    let mut more_available = feed_data.get("more_available").and_then(|m| m.as_bool()).unwrap_or(false);
                    let mut next_max_id = feed_data.get("next_max_id").and_then(|n| n.as_str()).map(|s| s.to_string());
                    
                    let mut hit_since = false;
                    for item in &items {
                        let post_id = item.get("id").and_then(|i| i.as_str()).unwrap_or("");
                        if let Some(sid) = since_id {
                            if post_id == sid {
                                log::info!("Reached Instagram checkpoint: {}. Stopping.", sid);
                                hit_since = true;
                                break;
                            }
                        }
                        media_items.extend(self.parse_item_api(item, username));
                        if media_items.len() >= items_needed {
                            break;
                        }
                    }

                    // Paginate
                    while more_available && next_max_id.is_some() && media_items.len() < items_needed && !hit_since {
                        sleep(Duration::from_millis(2000)).await;
                        let max_id = next_max_id.as_ref().unwrap();
                        let next_url = format!(
                            "https://www.instagram.com/api/v1/feed/user/{}/username/?max_id={}",
                            username, max_id
                        );
                        
                        if let Ok(next_resp) = self.client.get(&next_url).headers(headers.clone()).send().await {
                            if next_resp.status() == reqwest::StatusCode::OK {
                                if let Ok(next_feed) = next_resp.json::<Value>().await {
                                    items = next_feed.get("items").and_then(|i| i.as_array()).cloned().unwrap_or_default();
                                    if items.is_empty() {
                                        break;
                                    }
                                    
                                    for item in &items {
                                        let post_id = item.get("id").and_then(|i| i.as_str()).unwrap_or("");
                                        if let Some(sid) = since_id {
                                            if post_id == sid {
                                                hit_since = true;
                                                break;
                                            }
                                        }
                                        media_items.extend(self.parse_item_api(item, username));
                                        if media_items.len() >= items_needed {
                                            break;
                                        }
                                    }
                                    
                                    more_available = next_feed.get("more_available").and_then(|m| m.as_bool()).unwrap_or(false);
                                    next_max_id = next_feed.get("next_max_id").and_then(|n| n.as_str()).map(|s| s.to_string());
                                } else {
                                    break;
                                }
                            } else {
                                break;
                            }
                        } else {
                            break;
                        }
                    }
                    
                    return Ok(media_items);
                }
            }
        }

        // Method 2: Fallback to web_profile_info
        log::warn!("REST feed failed for {}. Trying web_profile_info fallback.", username);
        let fallback_url = format!("https://www.instagram.com/api/v1/users/web_profile_info/?username={}", username);
        let resp = self.client.get(&fallback_url).headers(headers).send().await
            .map_err(|e| format!("Instagram profile request failed: {}", e))?;
            
        if resp.status() != reqwest::StatusCode::OK {
            return Err(format!("Instagram web_profile_info returned status: {}", resp.status()));
        }
        
        let profile_json: Value = resp.json().await
            .map_err(|e| format!("Instagram profile JSON parse failed: {}", e))?;
            
        let edges = profile_json.pointer("/data/user/edge_owner_to_timeline_media/edges")
            .and_then(|e| e.as_array())
            .ok_or_else(|| "Instagram timeline data not found in fallback".to_string())?;

        for edge in edges {
            let node = match edge.get("node") {
                Some(n) => n,
                None => continue,
            };
            
            let post_id = node.get("id").and_then(|i| i.as_str()).unwrap_or("");
            if let Some(sid) = since_id {
                if post_id == sid {
                    log::info!("Reached Instagram checkpoint: {}. Stopping.", sid);
                    break;
                }
            }
            
            media_items.extend(self.parse_node(node, username));
            if media_items.len() >= items_needed {
                break;
            }
        }

        Ok(media_items)
    }

    fn parse_node(&self, node: &Value, author: &str) -> Vec<MediaItem> {
        let mut media_items = Vec::new();
        let post_id = node.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
        
        let text = node.pointer("/edge_media_to_caption/edges")
            .and_then(|e| e.as_array())
            .and_then(|a| a.get(0))
            .and_then(|n| n.pointer("/node/text"))
            .and_then(|t| t.as_str())
            .unwrap_or("")
            .to_string();
            
        // Check sidecar children
        if let Some(children) = node.pointer("/edge_sidecar_to_children/edges").and_then(|c| c.as_array()) {
            for child in children {
                if let Some(child_node) = child.get("node") {
                    if let Some(item) = self.parse_node_single(child_node, &post_id, author, &text) {
                        media_items.push(item);
                    }
                }
            }
        } else {
            if let Some(item) = self.parse_node_single(node, &post_id, author, &text) {
                media_items.push(item);
            }
        }
        
        media_items
    }

    fn parse_node_single(&self, node: &Value, post_id: &str, author: &str, text: &str) -> Option<MediaItem> {
        let is_video = node.get("is_video").and_then(|v| v.as_bool()).unwrap_or(false);
        if is_video {
            if let Some(video_url) = node.get("video_url").and_then(|u| u.as_str()) {
                return Some(MediaItem {
                    url: video_url.to_string(),
                    platform: "instagram".to_string(),
                    post_id: post_id.to_string(),
                    author: author.to_string(),
                    media_type: "video".to_string(),
                    original_url: video_url.to_string(),
                    text: text.to_string(),
                });
            }
        } else {
            if let Some(display_url) = node.get("display_url").and_then(|u| u.as_str()) {
                return Some(MediaItem {
                    url: display_url.to_string(),
                    platform: "instagram".to_string(),
                    post_id: post_id.to_string(),
                    author: author.to_string(),
                    media_type: "photo".to_string(),
                    original_url: display_url.to_string(),
                    text: text.to_string(),
                });
            }
        }
        None
    }

    fn parse_item_api(&self, item: &Value, author: &str) -> Vec<MediaItem> {
        let mut media_items = Vec::new();
        let post_id = item.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
        
        let text = item.pointer("/caption/text").and_then(|t| t.as_str()).unwrap_or("").to_string();
        
        if let Some(carousel) = item.get("carousel_media").and_then(|c| c.as_array()) {
            for child in carousel {
                if let Some(parsed) = self.parse_item_single(child, &post_id, author, &text) {
                    media_items.push(parsed);
                }
            }
        } else {
            if let Some(parsed) = self.parse_item_single(item, &post_id, author, &text) {
                media_items.push(parsed);
            }
        }
        
        media_items
    }

    fn parse_item_single(&self, item: &Value, post_id: &str, author: &str, text: &str) -> Option<MediaItem> {
        let media_type_val = item.get("media_type").and_then(|t| t.as_i64()).unwrap_or(1);
        if media_type_val == 2 {
            // Video
            if let Some(video_versions) = item.get("video_versions").and_then(|v| v.as_array()) {
                // Find highest resolution
                let mut best_url = None;
                let mut max_width = 0;
                for video in video_versions {
                    let width = video.get("width").and_then(|w| w.as_i64()).unwrap_or(0);
                    if width > max_width {
                        max_width = width;
                        best_url = video.get("url").and_then(|u| u.as_str()).map(|s| s.to_string());
                    }
                }
                if let Some(url) = best_url {
                    return Some(MediaItem {
                        url: url.clone(),
                        platform: "instagram".to_string(),
                        post_id: post_id.to_string(),
                        author: author.to_string(),
                        media_type: "video".to_string(),
                        original_url: url,
                        text: text.to_string(),
                    });
                }
            }
        } else {
            // Image
            if let Some(candidates) = item.pointer("/image_versions2/candidates").and_then(|c| c.as_array()) {
                // First element is typically the highest resolution candidate
                if let Some(candidate) = candidates.get(0) {
                    if let Some(url) = candidate.get("url").and_then(|u| u.as_str()) {
                        return Some(MediaItem {
                            url: url.to_string(),
                            platform: "instagram".to_string(),
                            post_id: post_id.to_string(),
                            author: author.to_string(),
                            media_type: "photo".to_string(),
                            original_url: url.to_string(),
                            text: text.to_string(),
                        });
                    }
                }
            }
        }
        None
    }
}
