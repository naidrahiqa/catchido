use rusqlite::{params, Connection, Result, Row};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct IdolProfile {
    pub display_name: String,
    pub idol_type: String, // "jp" or "kr"
    pub kanji_name: Option<String>,
    pub generation: Option<String>,
    pub team: Option<String>,
    pub hangul_name: Option<String>,
    pub stage_name: Option<String>,
    pub real_name: Option<String>,
    pub positions: Vec<String>,
    pub group_name: Option<String>,
    pub company: Option<String>,
    pub fandom_name: Option<String>,
    pub birthday: Option<String>,
    pub debut_date: Option<String>,
    pub status: String, // "active", "hiatus", "graduated", "left", "solo"
    pub graduation_date: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TrustedAccount {
    pub idol_name: String,
    pub platform: String, // "twitter", "weibo", "instagram", "threads", "tiktok"
    pub username: String,
    pub account_type: String, // "official" or "fansite"
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct IdolKeyword {
    pub idol_name: String,
    pub idol_type: String,
    pub keyword: String,
    pub script_type: String, // "generated", "hashtag", "alias"
    pub platform: String,    // "all", "twitter", "weibo"
    pub is_auto_generated: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct MediaHash {
    pub file_path: String,
    pub phash: String,
    pub exact_hash: String,
    pub file_size: u64,
    pub source_platform: String,
    pub post_id: String,
    pub idol_name: String,
    pub created_at: String,
    pub text: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct DownloadCheckpoint {
    pub idol_name: String,
    pub platform: String,
    pub source_username: String,
    pub last_id: String,
}

pub struct Database {
    db_path: PathBuf,
}

impl Database {
    pub fn new(path: &Path) -> Self {
        Self {
            db_path: path.to_path_buf(),
        }
    }

    fn connect(&self) -> Result<Connection> {
        if let Some(parent) = self.db_path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        Connection::open(&self.db_path)
    }

    pub fn initialize(&self) -> Result<()> {
        let conn = self.connect()?;
        
        // 1. idol_profiles
        conn.execute(
            "CREATE TABLE IF NOT EXISTS idol_profiles (
                display_name TEXT PRIMARY KEY,
                idol_type TEXT NOT NULL,
                kanji_name TEXT,
                generation TEXT,
                team TEXT,
                hangul_name TEXT,
                stage_name TEXT,
                real_name TEXT,
                positions TEXT,
                group_name TEXT,
                company TEXT,
                fandom_name TEXT,
                birthday TEXT,
                debut_date TEXT,
                status TEXT DEFAULT 'active',
                graduation_date TEXT
            )",
            [],
        )?;

        // 2. trusted_accounts
        conn.execute(
            "CREATE TABLE IF NOT EXISTS trusted_accounts (
                idol_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                username TEXT NOT NULL,
                account_type TEXT DEFAULT 'fansite',
                PRIMARY KEY (idol_name, platform, username),
                FOREIGN KEY (idol_name) REFERENCES idol_profiles(display_name) ON DELETE CASCADE
            )",
            [],
        )?;

        // 3. idol_keywords
        conn.execute(
            "CREATE TABLE IF NOT EXISTS idol_keywords (
                idol_name TEXT NOT NULL,
                idol_type TEXT NOT NULL,
                keyword TEXT NOT NULL,
                script_type TEXT NOT NULL,
                platform TEXT DEFAULT 'all',
                is_auto_generated INTEGER DEFAULT 0,
                PRIMARY KEY (idol_name, keyword),
                FOREIGN KEY (idol_name) REFERENCES idol_profiles(display_name) ON DELETE CASCADE
            )",
            [],
        )?;

        // 4. media_hashes
        conn.execute(
            "CREATE TABLE IF NOT EXISTS media_hashes (
                file_path TEXT PRIMARY KEY,
                phash TEXT,
                exact_hash TEXT NOT NULL,
                file_size INTEGER,
                source_platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                idol_name TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                text TEXT,
                FOREIGN KEY (idol_name) REFERENCES idol_profiles(display_name) ON DELETE CASCADE
            )",
            [],
        )?;

        // 5. download_checkpoints
        conn.execute(
            "CREATE TABLE IF NOT EXISTS download_checkpoints (
                idol_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_username TEXT NOT NULL,
                last_id TEXT NOT NULL,
                PRIMARY KEY (idol_name, platform, source_username),
                FOREIGN KEY (idol_name) REFERENCES idol_profiles(display_name) ON DELETE CASCADE
            )",
            [],
        )?;

        Ok(())
    }

    pub fn list_idols(&self) -> Result<Vec<IdolProfile>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare("SELECT * FROM idol_profiles ORDER BY display_name ASC")?;
        let rows = stmt.query_map([], |row| self.map_idol(row))?;
        
        let mut result = Vec::new();
        for r in rows {
            result.push(r?);
        }
        Ok(result)
    }

    pub fn get_idol(&self, name: &str) -> Result<Option<IdolProfile>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare("SELECT * FROM idol_profiles WHERE display_name = ?")?;
        let mut rows = stmt.query_map([name], |row| self.map_idol(row))?;
        
        if let Some(r) = rows.next() {
            Ok(Some(r?))
        } else {
            Ok(None)
        }
    }

    pub fn add_idol(&self, profile: &IdolProfile) -> Result<()> {
        let conn = self.connect()?;
        let positions_str = profile.positions.join(",");
        conn.execute(
            "INSERT OR REPLACE INTO idol_profiles (
                display_name, idol_type, kanji_name, generation, team,
                hangul_name, stage_name, real_name, positions, group_name,
                company, fandom_name, birthday, debut_date, status, graduation_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                profile.display_name,
                profile.idol_type,
                profile.kanji_name,
                profile.generation,
                profile.team,
                profile.hangul_name,
                profile.stage_name,
                profile.real_name,
                positions_str,
                profile.group_name,
                profile.company,
                profile.fandom_name,
                profile.birthday,
                profile.debut_date,
                profile.status,
                profile.graduation_date,
            ],
        )?;
        Ok(())
    }

    pub fn delete_idol(&self, name: &str) -> Result<()> {
        let conn = self.connect()?;
        conn.execute("DELETE FROM idol_profiles WHERE display_name = ?", [name])?;
        Ok(())
    }

    pub fn get_trusted_accounts(&self, name: &str) -> Result<Vec<TrustedAccount>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT * FROM trusted_accounts WHERE idol_name = ? ORDER BY platform ASC",
        )?;
        let rows = stmt.query_map([name], |row| {
            Ok(TrustedAccount {
                idol_name: row.get(0)?,
                platform: row.get(1)?,
                username: row.get(2)?,
                account_type: row.get(3)?,
            })
        })?;
        
        let mut result = Vec::new();
        for r in rows {
            result.push(r?);
        }
        Ok(result)
    }

    pub fn add_trusted_account(&self, acct: &TrustedAccount) -> Result<()> {
        let conn = self.connect()?;
        conn.execute(
            "INSERT OR REPLACE INTO trusted_accounts (idol_name, platform, username, account_type) VALUES (?, ?, ?, ?)",
            params![acct.idol_name, acct.platform, acct.username, acct.account_type],
        )?;
        Ok(())
    }

    pub fn get_keywords_for_idol(&self, name: &str) -> Result<Vec<IdolKeyword>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare("SELECT * FROM idol_keywords WHERE idol_name = ?")?;
        let rows = stmt.query_map([name], |row| {
            let auto_gen: i32 = row.get(5)?;
            Ok(IdolKeyword {
                idol_name: row.get(0)?,
                idol_type: row.get(1)?,
                keyword: row.get(2)?,
                script_type: row.get(3)?,
                platform: row.get(4)?,
                is_auto_generated: auto_gen != 0,
            })
        })?;
        
        let mut result = Vec::new();
        for r in rows {
            result.push(r?);
        }
        Ok(result)
    }

    pub fn add_keyword(&self, kw: &IdolKeyword) -> Result<()> {
        let conn = self.connect()?;
        conn.execute(
            "INSERT OR REPLACE INTO idol_keywords (idol_name, idol_type, keyword, script_type, platform, is_auto_generated) VALUES (?, ?, ?, ?, ?, ?)",
            params![
                kw.idol_name,
                kw.idol_type,
                kw.keyword,
                kw.script_type,
                kw.platform,
                if kw.is_auto_generated { 1 } else { 0 }
            ],
        )?;
        Ok(())
    }

    pub fn get_media_count(&self, name: &str) -> Result<u32> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare("SELECT COUNT(*) FROM media_hashes WHERE idol_name = ?")?;
        let count: u32 = stmt.query_row([name], |r| r.get(0))?;
        Ok(count)
    }

    pub fn get_checkpoint(&self, idol_name: &str, platform: &str, source_username: &str) -> Result<Option<String>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT last_id FROM download_checkpoints WHERE idol_name = ? AND platform = ? AND source_username = ?",
        )?;
        let mut rows = stmt.query_map([idol_name, platform, source_username], |row| row.get(0))?;
        
        if let Some(r) = rows.next() {
            Ok(Some(r?))
        } else {
            Ok(None)
        }
    }

    pub fn update_checkpoint(&self, chk: &DownloadCheckpoint) -> Result<()> {
        let conn = self.connect()?;
        conn.execute(
            "INSERT OR REPLACE INTO download_checkpoints (idol_name, platform, source_username, last_id) VALUES (?, ?, ?, ?)",
            params![chk.idol_name, chk.platform, chk.source_username, chk.last_id],
        )?;
        Ok(())
    }

    pub fn get_download_stats(&self) -> Result<serde_json::Value> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare("SELECT COUNT(*), SUM(file_size) FROM media_hashes")?;
        let (count, size): (u32, Option<u64>) = stmt.query_row([], |r| Ok((r.get(0)?, r.get(1)?)))?;
        
        let mut stmt_plat = conn.prepare(
            "SELECT source_platform, COUNT(*), SUM(file_size) FROM media_hashes GROUP BY source_platform",
        )?;
        let rows = stmt_plat.query_map([], |row| {
            let plat: String = row.get(0)?;
            let plat_count: u32 = row.get(1)?;
            let plat_size: Option<u64> = row.get(2)?;
            Ok((plat, plat_count, plat_size.unwrap_or(0)))
        })?;

        let mut platforms = serde_json::Map::new();
        for r in rows {
            let (plat, p_count, p_size) = r?;
            let mut val = serde_json::Map::new();
            val.insert("count".to_string(), serde_json::Value::Number(p_count.into()));
            val.insert("size".to_string(), serde_json::Value::Number(p_size.into()));
            platforms.insert(plat, serde_json::Value::Object(val));
        }

        let mut result = serde_json::Map::new();
        result.insert("total_count".to_string(), serde_json::Value::Number(count.into()));
        result.insert("total_size".to_string(), serde_json::Value::Number(size.unwrap_or(0).into()));
        result.insert("platforms".to_string(), serde_json::Value::Object(platforms));
        
        Ok(serde_json::Value::Object(result))
    }

    fn map_idol(&self, row: &Row) -> Result<IdolProfile> {
        let pos_str: String = row.get(8)?;
        let positions = if pos_str.is_empty() {
            Vec::new()
        } else {
            pos_str.split(',').map(|s| s.to_string()).collect()
        };

        Ok(IdolProfile {
            display_name: row.get(0)?,
            idol_type: row.get(1)?,
            kanji_name: row.get(2)?,
            generation: row.get(3)?,
            team: row.get(4)?,
            hangul_name: row.get(5)?,
            stage_name: row.get(6)?,
            real_name: row.get(7)?,
            positions,
            group_name: row.get(9)?,
            company: row.get(10)?,
            fandom_name: row.get(11)?,
            birthday: row.get(12)?,
            debut_date: row.get(13)?,
            status: row.get(14)?,
            graduation_date: row.get(15)?,
        })
    }
}
