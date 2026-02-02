
FIND_JOB_LIST_JS = """
(() => {
    // === STRUCTURAL PATTERN RECOGNITION ALGORITHM ===
    
    // 1. Helper: Calculate Structural Fingerprint of a node
    function getFingerprint(node) {
        // e.g. "DIV.job-card-container" or "LI"
        let fp = node.tagName.toUpperCase();
        if (node.classList.length > 0) {
            // Add first class as part of fingerprint for specificity
            fp += "." + node.classList[0]; 
        }
        return fp;
    }

    // 2. Helper: Score a node based on "Job Signals"
    // 2. Helper: Score a node based on "Job Signals"
    function getJobContentScore(node) {
        const text = (node.textContent || "").toLowerCase();
        const html = (node.innerHTML || "").toLowerCase();
        let score = 0;
        
        // Critical Classes (Found via Snapshot Analysis)
        if (node.classList.contains('scaffold-layout__list-item')) score += 20; // 🎯 Absolute Match
        if (node.querySelector('.job-card-container')) score += 20; // 🎯 Absolute Match
        
        // Critical Keywords
        if (text.includes('remote') || text.includes('hybrid') || text.includes('on-site')) score += 2;
        if (text.includes('easy apply') || text.includes('solicitud sencilla')) score += 3;
        if (text.includes('days ago') || text.includes('minutes ago') || text.includes('horas')) score += 1;
        
        // Structure Signals
        if (node.querySelector('a[href*="/jobs/view/"]')) score += 5; // Direct job link
        if (node.querySelector('img')) score += 0.5; // Logo usually present
        
        return score;
    }

    // 3. Main Traversal
    // We look for any container that has at least 3 children
    const allElements = document.querySelectorAll('*');
    let bestContainer = null;
    let bestItemTag = '';
    let highestRank = 0;

    for (let el of allElements) {
        // Filter out irrelevant nodes cheap and fast
        if (el.children.length < 3) continue;
        if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'SVG') continue;
        
        // Group children by fingerprint
        const groups = {};
        let totalScore = 0;
        let validChildrenCount = 0;

        for (let child of el.children) {
            // Ignore hidden children
            const style = window.getComputedStyle(child);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            
            validChildrenCount++;
            
            const fp = getFingerprint(child);
            if (!groups[fp]) groups[fp] = { count: 0, totalContentScore: 0 };
            
            groups[fp].count++;
            groups[fp].totalContentScore += getJobContentScore(child);
        }

        // Analyze Groups in this container
        for (let fp in groups) {
            const group = groups[fp];
            
            // Heuristic: A list should have repetition (at least 3 items)
            if (group.count < 3) continue;
            
            // Heuristic: A job list usually takes up major screen space (Dominance)
            // But checking rects for every node is slow, so we rely on content score.
            
            // Average Content Score per item
            const avgScore = group.totalContentScore / group.count;
            
            // RANK FORMULA:
            // (Repetition ^ 1.5) * AvgRelevance
            // We want high repetition AND high relevance.
            let rank = Math.pow(group.count, 1.2) * avgScore;
            
            // Penalty for extremely deep nesting if score is tied? No needed yet.
            
            if (rank > highestRank) {
                highestRank = rank;
                bestContainer = el;
                // Extract just the tag name for the selector (e.g. from "DIV.class" -> "div")
                bestItemTag = fp.split('.')[0].toLowerCase();
            }
        }
    }

    if (bestContainer && highestRank > 10) { // Threshold to avoid garbage
        // VISUAL FEEDBACK
        bestContainer.style.border = "4px solid #00ff00"; // Green for "Structural Match"
        bestContainer.style.boxShadow = "0 0 25px rgba(0, 255, 0, 0.6)";
        bestContainer.scrollIntoView({behavior: "smooth", block: "center"});
        
        const uniqueId = 'struct_job_list_' + Math.floor(Math.random() * 10000);
        bestContainer.setAttribute('data-struct-list-id', uniqueId);
        
        return JSON.stringify({
            container: `[data-struct-list-id="${uniqueId}"]`,
            item_tag: bestItemTag
        });
    }
    
    return null;
})();
"""

FIND_TOTAL_RESULTS_JS = """
(() => {
    // === DYNAMIC RESULTS DISCOVERY ALGORITHM ===
    const patterns = [
        /([\d.,]+)\s+(?:results|resultados|vacantes|ofertas)/i,
        /(?:total\s+de\s+|total\s+)([\d.,]+)/i
    ];

    // Priority 1: Check known header areas first
    const headerSelectors = [
        'header.jobs-search-results-list__header',
        '.jobs-search-results-list__subtitle',
        '.jobs-search-results-list__header',
        '.results-context-header'
    ];

    for (let sel of headerSelectors) {
        let el = document.querySelector(sel);
        if (el && el.innerText) {
            for (let pat of patterns) {
                let m = el.innerText.match(pat);
                if (m) return m[1].replace(/[.,]/g, '');
            }
        }
    }

    // Priority 2: Broad scan of all visible small/span text
    const elements = document.querySelectorAll('span, small, h1, h2, h3');
    for (let el of elements) {
        if (el.innerText && el.innerText.length < 100) {
            for (let pat of patterns) {
                let m = el.innerText.match(pat);
                if (m) {
                    // Filter for "header-like" positioning (top 20% of screen approx)
                    let rect = el.getBoundingClientRect();
                    if (rect.top < 600 && rect.left < 600) {
                       return m[1].replace(/[.,]/g, '');
                    }
                }
            }
        }
    }
    return null;
})();
"""
