use anyhow::Result;
use cbc::cipher::{block_padding::Pkcs7, BlockDecryptMut, KeyIvInit};
use rusqlite::Connection;
use std::path::PathBuf;

type Aes128CbcDec = cbc::Decryptor<aes::Aes128>;

#[derive(Debug, Clone)]
pub struct ChromeCookie {
    pub name: String,
    pub value: String,
    pub domain: String,
    pub path: String,
    pub secure: bool,
    pub http_only: bool,
    pub expires: f64,
}

pub fn decrypt_chrome_linux_cookie(encrypted_bytes: &[u8]) -> Option<String> {
    if encrypted_bytes.len() < 3 {
        return None;
    }
    let payload = if &encrypted_bytes[0..3] == b"v10" || &encrypted_bytes[0..3] == b"v11" {
        &encrypted_bytes[3..]
    } else {
        encrypted_bytes
    };

    let mut key = [0u8; 16];
    pbkdf2::pbkdf2_hmac::<sha1::Sha1>(b"peanuts", b"saltysalt", 1, &mut key);
    let iv = [b' '; 16]; // 16 spaces

    let mut buffer = payload.to_vec();
    let decryptor = Aes128CbcDec::new(&key.into(), &iv.into());
    let decrypted = decryptor.decrypt_padded_mut::<Pkcs7>(&mut buffer).ok()?;
    String::from_utf8(decrypted.to_vec()).ok()
}

pub fn extract_system_linkedin_cookies() -> Result<Vec<ChromeCookie>> {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/jcoronado".to_string());
    let potential_paths = vec![
        PathBuf::from(&home).join(".config/google-chrome/Profile 1/Cookies"),
        PathBuf::from(&home).join(".config/google-chrome/Default/Cookies"),
        PathBuf::from(&home).join(".config/google-chrome/Profile 2/Cookies"),
    ];

    let mut extracted_cookies = Vec::new();

    for cookie_path in potential_paths {
        if !cookie_path.exists() {
            continue;
        }

        // Copiar temporalmente la DB para evitar sqlite lock con Chrome abierto
        let temp_copy = std::env::temp_dir().join(format!("chrome_cookies_temp_{}.db", chrono::Utc::now().timestamp_millis()));
        if std::fs::copy(&cookie_path, &temp_copy).is_err() {
            continue;
        }

        if let Ok(conn) = Connection::open(&temp_copy) {
            let mut stmt = conn.prepare(
                "SELECT name, value, encrypted_value, host_key, path, is_secure, is_httponly, expires_utc FROM cookies WHERE host_key LIKE '%linkedin.com%'"
            )?;

            let rows = stmt.query_map([], |row| {
                let name: String = row.get(0)?;
                let plain_val: String = row.get(1)?;
                let enc_val: Vec<u8> = row.get(2)?;
                let host_key: String = row.get(3)?;
                let path: String = row.get(4)?;
                let is_secure: bool = row.get(5)?;
                let is_httponly: bool = row.get(6)?;
                let expires_utc: i64 = row.get(7)?;

                let final_val = if !plain_val.is_empty() {
                    plain_val
                } else if !enc_val.is_empty() {
                    decrypt_chrome_linux_cookie(&enc_val).unwrap_or_default()
                } else {
                    String::new()
                };

                let expires_epoch = if expires_utc > 0 {
                    (expires_utc as f64 / 1_000_000.0) - 11644473600.0
                } else {
                    -1.0
                };

                Ok(ChromeCookie {
                    name,
                    value: final_val,
                    domain: host_key,
                    path,
                    secure: is_secure,
                    http_only: is_httponly,
                    expires: expires_epoch,
                })
            })?;

            for r in rows.flatten() {
                if !r.value.is_empty() {
                    extracted_cookies.push(r);
                }
            }

            let _ = std::fs::remove_file(&temp_copy);

            if extracted_cookies.iter().any(|c| c.name == "li_at") {
                println!("🍪 [Cookie Extractor] ✅ Extraídas exitosamente {} cookies de LinkedIn (incluyendo li_at) desde {:?}", extracted_cookies.len(), cookie_path);
                break;
            }
        }
        let _ = std::fs::remove_file(&temp_copy);
    }

    Ok(extracted_cookies)
}
