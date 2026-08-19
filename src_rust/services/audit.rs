use serde_json::json;
use std::fs;
use std::path::Path;
use chrono::Utc;

pub fn log_audit_event(
    step: &str,
    subtask: &str,
    result: &str,
    reason: &str,
    details: &str,
    dom_dump_path: Option<String>,
    screenshot_path: Option<String>,
    action_taken: &str,
    developer_note: &str,
) {
    let logs_dir = Path::new("logs");
    if !logs_dir.exists() {
        let _ = fs::create_dir_all(logs_dir);
    }

    let timestamp = Utc::now().to_rfc3339();
    
    let mut artifacts = serde_json::Map::new();
    if let Some(d) = dom_dump_path {
        artifacts.insert("dom_dump".to_string(), json!(d));
    }
    if let Some(s) = screenshot_path {
        artifacts.insert("screenshot".to_string(), json!(s));
    }

    let log_entry = json!({
        "timestamp": timestamp,
        "step": step,
        "subtask": subtask,
        "result": result,
        "reason": reason,
        "details": details,
        "artifacts": if artifacts.is_empty() { json!(null) } else { json!(artifacts) },
        "action_taken": action_taken,
        "developer_note": developer_note
    });

    let log_file = logs_dir.join("audit.jsonl");
    let log_line = format!("{}\n", log_entry.to_string());
    
    use std::io::Write;
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(log_file) {
        let _ = file.write_all(log_line.as_bytes());
    }

    // Also print to console
    if result == "OK" {
        println!("✅ [{} - {}] {}", step, subtask, details);
    } else {
        println!("🚨 [{} - {}] FAIL: {} | {}", step, subtask, reason, details);
        println!("   👉 Acción tomada: {}", action_taken);
    }
}
