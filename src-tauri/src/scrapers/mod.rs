use serde::{Deserialize, Serialize};

pub mod twitter;
pub mod weibo;
pub mod instagram;
pub mod threads;
pub mod tiktok;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct MediaItem {
    pub url: String,
    pub platform: String,
    pub post_id: String,
    pub author: String,
    pub media_type: String, // "photo" or "video"
    pub original_url: String,
    pub text: String,
}
