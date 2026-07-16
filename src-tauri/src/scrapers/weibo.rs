use regex::Regex;
use serde_json::Value;
use std::time::Duration;
use tokio::time::sleep;

use crate::config::AppConfig;
use super::MediaItem;

pub struct WeiboScraper {
    client: reqwest::Client,
    cookie: String,
    delay: u64,
}

impl WeiboScraper {
    pub fn new(cookie: String, config: &AppConfig) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("Referer", reqwest::header::HeaderValue::from_static("https://m.weibo.cn/"));
        headers.insert("X-Requested-With", reqwest::header::HeaderValue::from_static("XMLHttpRequest"));
        headers.insert(
            "User-Agent",
            reqwest::header::HeaderValue::from_static(
                "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Mobile Safari/537.36",
            ),
        );
        
        if !cookie.is_empty() {
            if let Ok(cookie_val) = reqwest::header::HeaderValue::from_str(&cookie) {
                headers.insert("Cookie", cookie_val);
            }
        }

        let client = reqwest::Client::builder()
            .default_headers(headers)
            .timeout(Duration::from_seconds(15))
            .build()
            .unwrap_or_default();

        Self {
            client,
            cookie,
            delay: 2, // 2 seconds default delay
        }
    }

    pub fn get_hd_url(&self, url: &str) -> String {
        if !url.contains("sinaimg.cn") {
            return url.to_string();
        }
        let re = Regex::new(r"/(thumbnail|mw2048|bmiddle|orj360|woriginal|mw690)/").unwrap();
        re.replace(url, "/large/").to_string()
    }

    pub async fn fetch_media(
        &self,
        query_or_username: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        if query_or_username.chars().all(|c| c.is_ascii_digit()) {
            self.fetch_user_posts(query_or_username, since_id, limit).await
        } else {
            self.fetch_search_results(query_or_username, since_id, limit).await
        }
    }

    async fn fetch_user_posts(
        &self,
        user_id: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        let mut media_items = Vec::new();
        let limit_val = limit.unwrap_or(50);
        
        // 1. Get containerid
        let index_url = format!("https://m.weibo.cn/api/container/getIndex?type=uid&value={}", user_id);
        let resp = self.client.get(&index_url).send().await
            .map_err(|e| format!("Weibo index request failed: {}", e))?;
            
        let index_json: Value = resp.json().await
            .map_err(|e| format!("Weibo index JSON parse failed: {}", e))?;
            
        let mut container_id = None;
        if let Some(tabs) = index_json.pointer("/data/tabsInfo/tabs").and_then(|t| t.as_array()) {
            for tab in tabs {
                if tab.get("tab_type").and_then(|t| t.as_str()) == Some("weibo") {
                    container_id = tab.get("containerid").and_then(|c| c.as_str()).map(|s| s.to_string());
                    break;
                }
            }
        }
        
        let container_id = container_id.unwrap_or_else(|| format!("107603{}", user_id));
        let mut page = 1;
        let mut has_more = true;

        while media_items.len() < limit_val && has_more {
            if page > 1 {
                sleep(Duration::from_millis(1500)).await;
            }
            
            let page_url = format!(
                "https://m.weibo.cn/api/container/getIndex?containerid={}&page={}",
                container_id, page
            );
            
            let resp = match self.client.get(&page_url).send().await {
                Ok(r) => r,
                Err(e) => {
                    log::warn!("Weibo page {} request failed: {}", page, e);
                    break;
                }
            };
            
            let page_json: Value = match resp.json().await {
                Ok(j) => j,
                Err(e) => {
                    log::warn!("Weibo page {} JSON parse failed: {}", page, e);
                    break;
                }
            };

            let cards = match page_json.pointer("/data/cards").and_then(|c| c.as_array()) {
                Some(c) => c,
                None => {
                    has_more = false;
                    break;
                }
            };

            if cards.is_empty() {
                has_more = false;
                break;
            }

            let mut reached_checkpoint = false;
            for card in cards {
                if card.get("card_type").and_then(|t| t.as_i64()) != Some(9) {
                    continue; // Type 9 is weibo post card
                }
                
                let mblog = match card.get("mblog") {
                    Some(m) => m,
                    None => continue,
                };
                
                let post_id = mblog.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
                if post_id.is_empty() {
                    continue;
                }

                if let Some(sid) = since_id {
                    if post_id == sid {
                        log::info!("Reached Weibo checkpoint: {}. Stopping.", sid);
                        reached_checkpoint = true;
                        break;
                    }
                }

                let author = mblog.pointer("/user/screen_name").and_then(|s| s.as_str()).unwrap_or("").to_string();
                let text = mblog.get("text").and_then(|t| t.as_str()).unwrap_or("").to_string();
                
                // Parse pics
                if let Some(pics) = mblog.get("pics").and_then(|p| p.as_array()) {
                    for pic in pics {
                        if let Some(url_str) = pic.pointer("/large/url").or_else(|| pic.get("url")).and_then(|u| u.as_str()) {
                            media_items.push(MediaItem {
                                url: self.get_hd_url(url_str),
                                platform: "weibo".to_string(),
                                post_id: post_id.clone(),
                                author: author.clone(),
                                media_type: "photo".to_string(),
                                original_url: url_str.to_string(),
                                text: text.clone(),
                            });
                        }
                    }
                }
                
                // Retweet pics
                if let Some(retweet) = mblog.get("retweeted_status") {
                    if let Some(pics) = retweet.get("pics").and_then(|p| p.as_array()) {
                        for pic in pics {
                            if let Some(url_str) = pic.pointer("/large/url").or_else(|| pic.get("url")).and_then(|u| u.as_str()) {
                                media_items.push(MediaItem {
                                    url: self.get_hd_url(url_str),
                                    platform: "weibo".to_string(),
                                    post_id: post_id.clone(),
                                    author: author.clone(),
                                    media_type: "photo".to_string(),
                                    original_url: url_str.to_string(),
                                    text: text.clone(),
                                });
                            }
                        }
                    }
                }
            }

            if reached_checkpoint {
                break;
            }
            
            page += 1;
        }

        Ok(media_items)
    }

    async fn fetch_search_results(
        &self,
        query: &str,
        since_id: Option<&str>,
        limit: Option<usize>,
    ) -> Result<Vec<MediaItem>, String> {
        let mut media_items = Vec::new();
        let limit_val = limit.unwrap_or(50);
        let mut page = 1;
        let mut has_more = true;

        while media_items.len() < limit_val && has_more {
            if page > 1 {
                sleep(Duration::from_millis(1500)).await;
            }
            
            let search_url = format!(
                "https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D1%26q%3D{}&page={}",
                urlencoding::encode(query), page
            );
            
            let resp = match self.client.get(&search_url).send().await {
                Ok(r) => r,
                Err(e) => {
                    log::warn!("Weibo search page {} request failed: {}", page, e);
                    break;
                }
            };
            
            let page_json: Value = match resp.json().await {
                Ok(j) => j,
                Err(e) => {
                    log::warn!("Weibo search page {} JSON parse failed: {}", page, e);
                    break;
                }
            };

            let cards = match page_json.pointer("/data/cards").and_then(|c| c.as_array()) {
                Some(c) => c,
                None => {
                    has_more = false;
                    break;
                }
            };

            if cards.is_empty() {
                has_more = false;
                break;
            }

            let mut reached_checkpoint = false;
            for card in cards {
                // Search result cards can have different nested structures.
                // Usually type 9, or a "card_group" containing cards of type 9
                if let Some(card_group) = card.get("card_group").and_then(|g| g.as_array()) {
                    for group_card in card_group {
                        if group_card.get("card_type").and_then(|t| t.as_i64()) == Some(9) {
                            if let Some(mblog) = group_card.get("mblog") {
                                let post_id = mblog.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
                                if post_id.is_empty() {
                                    continue;
                                }

                                if let Some(sid) = since_id {
                                    if post_id == sid {
                                        reached_checkpoint = true;
                                        break;
                                    }
                                }

                                let author = mblog.pointer("/user/screen_name").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                let text = mblog.get("text").and_then(|t| t.as_str()).unwrap_or("").to_string();

                                if let Some(pics) = mblog.get("pics").and_then(|p| p.as_array()) {
                                    for pic in pics {
                                        if let Some(url_str) = pic.pointer("/large/url").or_else(|| pic.get("url")).and_then(|u| u.as_str()) {
                                            media_items.push(MediaItem {
                                                url: self.get_hd_url(url_str),
                                                platform: "weibo".to_string(),
                                                post_id: post_id.clone(),
                                                author: author.clone(),
                                                media_type: "photo".to_string(),
                                                original_url: url_str.to_string(),
                                                text: text.clone(),
                                            });
                                        }
                                    }
                                }
                            }
                        }
                    }
                } else if card.get("card_type").and_then(|t| t.as_i64()) == Some(9) {
                    if let Some(mblog) = card.get("mblog") {
                        let post_id = mblog.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
                        if post_id.is_empty() {
                            continue;
                        }

                        if let Some(sid) = since_id {
                            if post_id == sid {
                                reached_checkpoint = true;
                                break;
                            }
                        }

                        let author = mblog.pointer("/user/screen_name").and_then(|s| s.as_str()).unwrap_or("").to_string();
                        let text = mblog.get("text").and_then(|t| t.as_str()).unwrap_or("").to_string();

                        if let Some(pics) = mblog.get("pics").and_then(|p| p.as_array()) {
                            for pic in pics {
                                if let Some(url_str) = pic.pointer("/large/url").or_else(|| pic.get("url")).and_then(|u| u.as_str()) {
                                    media_items.push(MediaItem {
                                        url: self.get_hd_url(url_str),
                                        platform: "weibo".to_string(),
                                        post_id: post_id.clone(),
                                        author: author.clone(),
                                        media_type: "photo".to_string(),
                                        original_url: url_str.to_string(),
                                        text: text.clone(),
                                    });
                                }
                            }
                        }
                    }
                }
                
                if reached_checkpoint {
                    break;
                }
            }

            if reached_checkpoint {
                break;
            }

            page += 1;
        }

        Ok(media_items)
    }
}
