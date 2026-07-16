use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GeneralConfig {
    pub download_dir: String,
    pub max_concurrent_downloads: usize,
    pub auto_dedup: bool,
    pub dedup_threshold: u32,
    pub prefer_higher_res: bool,
    pub download_photos: bool,
    pub download_videos: bool,
}

impl Default for GeneralConfig {
    fn default() -> Self {
        Self {
            download_dir: "./data".to_string(),
            max_concurrent_downloads: 5,
            auto_dedup: true,
            dedup_threshold: 5,
            prefer_higher_res: true,
            download_photos: true,
            download_videos: false,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct TwitterConfig {
    pub bearer_token: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct InstagramConfig {
    pub session_cookie: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct ThreadsConfig {
    pub session_cookie: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct WeiboConfig {
    pub cookie: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct TikTokConfig {
    pub session_cookie: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct AppConfig {
    pub general: GeneralConfig,
    pub twitter: TwitterConfig,
    pub instagram: InstagramConfig,
    pub threads: ThreadsConfig,
    pub weibo: WeiboConfig,
    pub tiktok: TikTokConfig,
}

impl AppConfig {
    pub fn load_or_create(path: &Path) -> Result<Self, String> {
        if !path.exists() {
            let default_config = AppConfig::default();
            default_config.save(path)?;
            return Ok(default_config);
        }
        
        let content = fs::read_to_string(path)
            .map_err(|e| format!("Failed to read config file: {}", e))?;
            
        let config: AppConfig = toml::from_str(&content)
            .map_err(|e| format!("Failed to parse config file: {}", e))?;
            
        Ok(config)
    }

    pub fn save(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create config directory: {}", e))?;
        }
        
        let content = toml::to_string_pretty(self)
            .map_err(|e| format!("Failed to serialize config: {}", e))?;
            
        fs::write(path, content)
            .map_err(|e| format!("Failed to write config file: {}", e))?;
            
        Ok(())
    }
}
