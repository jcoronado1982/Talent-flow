use chromiumoxide::browser::Browser;
use chromiumoxide::cdp::browser_protocol::target::TargetId;
use chromiumoxide::Page;
use std::collections::HashSet;
use std::time::Duration;

/// Snapshot of the browser's currently open page/tab targets — take one before an
/// action that might open a new tab (e.g. clicking Apply), then diff against a second
/// snapshot afterward with `wait_for_new_page`.
pub async fn snapshot_target_ids(browser: &Browser) -> HashSet<TargetId> {
    browser
        .pages()
        .await
        .unwrap_or_default()
        .iter()
        .map(|p| p.target_id().clone())
        .collect()
}

/// Polls for a new page/tab that wasn't in `before` (e.g. one opened via
/// `target="_blank"` after clicking Apply). chromiumoxide auto-discovers and
/// auto-attaches new targets on its own (confirmed against 0.9.1 source —
/// `SetDiscoverTargetsParams(true)` + attach-on-`EventTargetCreated`), so no extra
/// wiring is needed beyond polling `Browser::pages()`.
///
/// Returns the first genuinely new, navigated (non-blank) page found within `timeout`,
/// or `None` if nothing new appeared — the caller should then fall back to same-tab
/// URL-diffing (the pre-existing detection path).
pub async fn wait_for_new_page(browser: &Browser, before: &HashSet<TargetId>, timeout: Duration) -> Option<Page> {
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if let Ok(pages) = browser.pages().await {
            for page in pages {
                if before.contains(page.target_id()) {
                    continue;
                }
                let url = page.url().await.ok().flatten().unwrap_or_default();
                if url.is_empty() || url == "about:blank" {
                    // Target exists but hasn't navigated yet — keep polling.
                    continue;
                }
                println!("      🌍 [Tabs] Pestaña nueva detectada: {}", url);
                return Some(page);
            }
        }
        tokio::time::sleep(Duration::from_millis(300)).await;
    }
    None
}
