// Global State
let currentIdol = null;
let currentMediaList = [];
let lightboxIndex = 0;
let logPollInterval = null;
let scrapeDepth = "recent";

console.log("[Catchido] app.js loaded, version 2.3");

// Toast Notification System
function showToast(message, type = "info", duration = 4000) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    const icons = {
        success: "check-circle",
        error: "alert-circle",
        info: "info",
        warning: "alert-triangle"
    };
    
    toast.innerHTML = `
        <span class="toast-icon"><i data-lucide="${icons[type] || icons.info}"></i></span>
        <span class="toast-message">${message}</span>
    `;
    
    container.appendChild(toast);
    lucide.createIcons({ root: toast });
    
    requestAnimationFrame(() => {
        toast.classList.add("show");
    });
    
    // Pause dismiss on hover
    let dismissTimer = setTimeout(() => dismissToast(toast), duration);
    
    toast.addEventListener("mouseenter", () => clearTimeout(dismissTimer));
    toast.addEventListener("mouseleave", () => {
        dismissTimer = setTimeout(() => dismissToast(toast), duration);
    });
    
    toast.addEventListener("click", () => dismissToast(toast));
}

function dismissToast(toast) {
    toast.classList.remove("show");
    setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
}

// Dual-compatibility Request Wrapper
async function apiRequest(endpoint, method = "GET", body = null) {
    if (window.__TAURI__) {
        let cmd = "";
        let args = {};
        
        if (endpoint === "/api/stats") {
            cmd = "get_stats";
        } else if (endpoint === "/api/idols") {
            if (method === "POST") {
                cmd = "add_idol";
                args = { data: body };
            } else {
                cmd = "get_idols";
            }
        } else if (endpoint.startsWith("/api/idols/") && endpoint.endsWith("/media")) {
            cmd = "get_idol_media";
            const name = endpoint.split("/")[3];
            args = { name: decodeURIComponent(name) };
        } else if (endpoint.startsWith("/api/idols/") && endpoint.endsWith("/download")) {
            cmd = "trigger_download";
            const name = endpoint.split("/")[3];
            args = { name: decodeURIComponent(name) };
        } else if (endpoint.startsWith("/api/idols/")) {
            const name = endpoint.split("/")[3];
            if (method === "DELETE") {
                cmd = "delete_idol";
                args = { name: decodeURIComponent(name) };
            } else if (method === "PUT") {
                cmd = "update_idol";
                args = { name: decodeURIComponent(name), data: body };
            } else {
                cmd = "get_idol_detail";
                args = { name: decodeURIComponent(name) };
            }
        } else if (endpoint === "/api/logs") {
            cmd = "get_logs";
        } else if (endpoint === "/api/config") {
            if (method === "POST") {
                cmd = "save_web_config";
                args = { data: body };
            } else {
                cmd = "get_web_config";
            }
        }
        
        try {
            return await window.__TAURI__.core.invoke(cmd, args);
        } catch (e) {
            console.error(`Tauri command ${cmd} failed:`, e);
            throw new Error(e);
        }
    } else {
        const options = {
            method: method,
            headers: {}
        };
        if (body) {
            options.headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(body);
        }
        const response = await fetch(endpoint, options);
        if (!response.ok) {
            const err = await response.json();
            let msg = "Request failed";
            if (err.detail) {
                if (typeof err.detail === "string") {
                    msg = err.detail;
                } else if (Array.isArray(err.detail)) {
                    msg = err.detail.map(d => `${d.loc.join(".")}: ${d.msg}`).join("\n");
                } else {
                    msg = JSON.stringify(err.detail);
                }
            }
            throw new Error(msg);
        }
        return await response.json();
    }
}

// View switcher
function switchView(viewId) {
    document.querySelectorAll(".view-panel").forEach(panel => {
        panel.classList.remove("active");
    });
    document.querySelectorAll(".nav-btn").forEach(btn => {
        btn.classList.remove("active");
    });
    
    const targetPanel = document.getElementById(`view-${viewId}`);
    if (targetPanel) {
        targetPanel.classList.add("active");
    }
    
    const activeBtn = document.querySelector(`.nav-btn[data-view="${viewId}"]`);
    if (activeBtn) {
        activeBtn.classList.add("active");
    }

    // View specific hooks
    if (viewId === "dashboard") {
        fetchStats();
    } else if (viewId === "catalog") {
        console.log("[Catchido] switching to catalog, calling fetchCatalog()");
        fetchCatalog();
    } else if (viewId === "settings") {
        console.log("[Catchido] switching to settings, calling fetchSettings()");
        fetchSettings();
    }
}

// Format file size
function formatBytes(bytes) {
    if (bytes === 0) return "0.00 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

// Fetch Global Stats
async function fetchStats() {
    try {
        const data = await apiRequest("/api/stats");
        
        document.getElementById("stat-idols").innerText = data.total_idols;
        document.getElementById("stat-files").innerText = data.total_count;
        document.getElementById("stat-size").innerText = formatBytes(data.total_size);
        
        // Render platforms
        const platformStatsList = document.getElementById("platform-stats-list");
        platformStatsList.innerHTML = "";
        
        const platformColors = {
            "twitter": "text-blue-400",
            "instagram": "text-pink-500",
            "threads": "text-white",
            "tiktok": "text-green-400",
            "weibo": "text-pink-400"
        };
        
        for (const [platform, details] of Object.entries(data.platforms)) {
            const row = document.createElement("div");
            row.className = "platform-stat-row";
            row.innerHTML = `
                <div class="platform-label">
                    <i data-lucide="${getPlatformIcon(platform)}" style="width: 18px; height: 18px;"></i>
                    <span>${platform.toUpperCase()}</span>
                </div>
                <div class="platform-info-text">
                    <span class="platform-count">${details.count} files</span>
                    <span class="platform-size">${formatBytes(details.size)}</span>
                </div>
            `;
            platformStatsList.appendChild(row);
        }
        lucide.createIcons();
        
        // Update job status indicator
        updateJobIndicator(data.is_job_running, data.active_job_target);
    } catch (e) {
        console.error("Failed to fetch stats", e);
    }
}

function getPlatformIcon(platform) {
    const icons = {
        twitter: "twitter",
        instagram: "instagram",
        threads: "message-circle",
        tiktok: "music",
        weibo: "globe"
    };
    return icons[platform.toLowerCase()] || "link";
}

function updateJobIndicator(isRunning, target) {
    const indicator = document.getElementById("global-job-status");
    const textSpan = indicator.querySelector(".badge-text");
    
    if (isRunning) {
        indicator.classList.add("running");
        textSpan.innerText = `Scraping: ${target}`;
        
        // Start polling logs if not already polling
        if (!logPollInterval) {
            logPollInterval = setInterval(pollLogs, 1000);
        }
    } else {
        indicator.classList.remove("running");
        textSpan.innerText = "Scraper Idle";
        
        // Stop polling logs
        if (logPollInterval) {
            clearInterval(logPollInterval);
            logPollInterval = null;
        }
    }
}

// Fetch Catalog
async function fetchCatalog() {
    try {
        console.log("[Catchido] fetchCatalog: calling /api/idols");
        const data = await apiRequest("/api/idols");
        console.log("[Catchido] fetchCatalog: got", data.length, "idols");
        renderCatalog(data);
    } catch (e) {
        console.error("[Catchido] fetchCatalog error:", e);
        const grid = document.getElementById("idols-list-grid");
        if (grid) {
            grid.innerHTML = '<div class="data-box" style="grid-column:1/-1;text-align:center;padding:40px;"><p style="color:var(--red);">Failed to load catalog: ' + e.message + '</p></div>';
        }
    }
}

function renderCatalog(idols) {
    const grid = document.getElementById("idols-list-grid");
    grid.innerHTML = "";
    
    if (idols.length === 0) {
        grid.innerHTML = `
            <div class="data-box" style="grid-column: 1/-1; text-align: center; padding: 40px;">
                <p style="color: var(--text-secondary); margin-bottom: 16px;">No tracked idols found.</p>
                <button class="btn btn-primary" onclick="document.getElementById('modal-add-idol').classList.add('active')">Add Your First Idol</button>
            </div>
        `;
        return;
    }
    
    idols.forEach(idol => {
        const card = document.createElement("div");
        card.className = "idol-card";
        card.onclick = () => showIdolDetail(idol.name);
        
        card.innerHTML = `
            <div class="idol-card-avatar">${idol.name.charAt(0).toUpperCase()}</div>
            <div>
                <div class="idol-card-header">
                    <span class="idol-card-name">${idol.name}</span>
                    <span class="badge ${idol.type}">${idol.type.toUpperCase()}</span>
                </div>
                <div class="idol-card-details" style="margin-top: 8px;">
                    <span>Group: ${idol.group}</span>
                    <span>Company: ${idol.company}</span>
                    <span>Status: <b style="color: ${idol.status === 'active' ? 'var(--green)' : 'var(--text-secondary)'}">${idol.status}</b></span>
                </div>
            </div>
            <div class="idol-card-footer">
                <span class="media-count-indicator">
                    <i data-lucide="image"></i>
                    <span>${idol.media_count} files</span>
                </span>
                <button class="btn btn-sm btn-outline"><i data-lucide="chevron-right"></i></button>
            </div>
        `;
        grid.appendChild(card);
    });
    
    lucide.createIcons();
}

// Catalog Search Filter
document.getElementById("catalog-search").addEventListener("input", (e) => {
    const query = e.target.value.toLowerCase().trim();
    document.querySelectorAll(".idol-card").forEach(card => {
        const name = card.querySelector(".idol-card-name").innerText.toLowerCase();
        const details = card.querySelector(".idol-card-details").innerText.toLowerCase();
        
        if (name.includes(query) || details.includes(query)) {
            card.classList.remove("hidden");
        } else {
            card.classList.add("hidden");
        }
    });
});

// Show Idol Details
async function showIdolDetail(name) {
    try {
        const data = await apiRequest(`/api/idols/${name}`);
        
        currentIdol = data.profile;
        currentIdol._sources = data.sources || [];
        
        document.getElementById("detail-display-name").innerText = data.profile.name;
        document.getElementById("detail-type").innerText = data.profile.type.toUpperCase();
        document.getElementById("detail-type").className = `badge ${data.profile.type}`;
        
        const subtitle = data.profile.group ? `${data.profile.group} — ${data.profile.company || '-'}` : "Soloist";
        document.getElementById("detail-subtitle").innerText = subtitle;
        
        // Metadata Grid Fields
        const fields = [
            { label: "Status", value: data.profile.status },
            { label: "Birthday", value: data.profile.birthday || "-" },
            { label: "Debut Date", value: data.profile.debut || "-" },
            { label: "Download Folder", value: data.profile.download_dir || "Global Default" }
        ];
        
        if (data.profile.type === "jp") {
            fields.push(
                { label: "Kanji Name", value: data.profile.kanji || "-" },
                { label: "Generation", value: data.profile.generation || "-" },
                { label: "Team", value: data.profile.team || "-" }
            );
        } else {
            fields.push(
                { label: "Hangul Name", value: data.profile.hangul || "-" },
                { label: "Stage Name", value: data.profile.stage_name || "-" },
                { label: "Real Name", value: data.profile.real_name || "-" },
                { label: "Position", value: data.profile.positions ? data.profile.positions.join(", ") : "-" }
            );
        }
        
        const fieldsGrid = document.getElementById("detail-fields-grid");
        fieldsGrid.innerHTML = "";
        fields.forEach(f => {
            fieldsGrid.innerHTML += `
                <div class="meta-field">
                    <span class="meta-label">${f.label}</span>
                    <span class="meta-value">${f.value}</span>
                </div>
            `;
        });
        
        // Accounts badges with delete buttons
        const accountsList = document.getElementById("detail-accounts-list");
        accountsList.innerHTML = "";
        
        if (data.sources.length === 0) {
            accountsList.innerHTML = `<span style="color: var(--text-secondary);">No sources yet. Add one below.</span>`;
        } else {
            data.sources.forEach(src => {
                accountsList.innerHTML += `
                    <span class="platform-badge ${src.platform}" style="display: inline-flex; align-items: center; gap: 4px;">
                        <i data-lucide="${getPlatformIcon(src.platform)}" style="width: 14px; height: 14px;"></i>
                        <span>${src.username || src.platform.toUpperCase()}</span>
                        <button class="btn-remove-source" data-platform="${src.platform}" data-username="${src.username}" style="background: none; border: none; color: var(--text-secondary); cursor: pointer; padding: 0; margin-left: 2px; line-height: 1;" title="Remove">&times;</button>
                    </span>
                `;
            });
            lucide.createIcons();
        }
        
        // Fetch & Render Gallery
        fetchIdolMedia(name);
        
        switchView("idol-detail");
    } catch (e) {
        console.error("Failed to load idol detail", e);
    }
}

// --- Gallery pagination state ---
let galleryPage = { name: "", limit: 50, offset: 0, total: 0, loading: false };

// Fetch media downloaded for this idol
async function fetchIdolMedia(name) {
    galleryPage = { name, limit: 50, offset: 0, total: 0, loading: false };
    currentMediaList = [];
    document.getElementById("idol-gallery-grid").innerHTML = "";
    document.getElementById("gallery-load-more").style.display = "none";
    await loadMoreMedia(true);
}

async function loadMoreMedia(reset = false) {
    if (galleryPage.loading) return;
    galleryPage.loading = true;
    const btn = document.querySelector("#gallery-load-more button");
    if (btn) btn.disabled = true;

    try {
        const q = `/api/idols/${galleryPage.name}/media?limit=${galleryPage.limit}&offset=${galleryPage.offset}`;
        const data = await apiRequest(q);
        const items = data.items || [];
        galleryPage.total = data.total;
        galleryPage.offset += items.length;

        const grid = document.getElementById("idol-gallery-grid");
        const startIdx = currentMediaList.length;

        items.forEach((item, i) => {
            const galleryItem = document.createElement("div");
            galleryItem.className = "gallery-item";

            let src = item.src;
            if (window.__TAURI__) {
                src = window.__TAURI__.core.convertFileSrc(item.src);
            }

            const idx = startIdx + i;
            galleryItem.onclick = () => openLightbox(idx);

            galleryItem.innerHTML = `
                <img src="${src}" loading="lazy" alt="Media item">
                <div class="gallery-item-overlay">
                    <span class="gallery-item-platform ${item.platform}">${item.platform}</span>
                </div>
            `;
            grid.appendChild(galleryItem);
        });

        if (document.getElementById("platform-filter-toggle").checked) {
            applyPlatformFilter();
        }

        currentMediaList = currentMediaList.concat(items);
        document.getElementById("gallery-count").innerText = currentMediaList.length;

        if (currentMediaList.length === 0) {
            grid.innerHTML = `
                <div class="data-box" style="grid-column: 1/-1; text-align: center; padding: 40px; border-style: dashed;">
                    <p style="color: var(--text-secondary);">No photos downloaded yet. Click "Scrape & Download" to start.</p>
                </div>
            `;
        }

        const hasMore = currentMediaList.length < galleryPage.total;
        const loadMoreDiv = document.getElementById("gallery-load-more");
        if (hasMore) {
            loadMoreDiv.style.display = "block";
            if (btn) btn.textContent = `Load More (${currentMediaList.length}/${galleryPage.total})`;
        } else {
            loadMoreDiv.style.display = "none";
        }
    } catch (e) {
        console.error("Failed to load media list", e);
    } finally {
        galleryPage.loading = false;
        if (btn) btn.disabled = false;
    }
}

// Open Lightbox
let currentMediaId = null;

function openLightbox(index) {
    lightboxIndex = index;
    const item = currentMediaList[index];
    if (!item) return;
    
    currentMediaId = item.id;
    
    const modal = document.getElementById("lightbox-modal");
    const img = document.getElementById("lightbox-img");
    const caption = document.getElementById("lightbox-caption");
    const platform = document.getElementById("lightbox-platform");
    const postId = document.getElementById("lightbox-post-id");
    const dateSpan = document.getElementById("lightbox-date");
    
    let src = item.src;
    if (window.__TAURI__) {
        src = window.__TAURI__.core.convertFileSrc(item.src);
    }
    img.src = src;
    caption.innerText = item.caption || "No caption description.";
    platform.innerText = item.platform.toUpperCase();
    platform.className = `lightbox-platform-badge ${item.platform}`;
    postId.innerText = `Post: ${item.post_id}`;
    
    const formattedDate = item.created_at ? item.created_at.substring(0, 10) : "-";
    dateSpan.innerText = formattedDate;
    
    modal.classList.add("active");
}

function closeLightbox() {
    document.getElementById("lightbox-modal").classList.remove("active");
}

// Lightbox Navigation
function navigateLightbox(direction) {
    let nextIndex = lightboxIndex + direction;
    if (nextIndex < 0) nextIndex = currentMediaList.length - 1;
    if (nextIndex >= currentMediaList.length) nextIndex = 0;
    openLightbox(nextIndex);
}

// Delete current media
async function deleteCurrentMedia() {
    if (currentMediaId == null) return;
    if (!confirm("Delete this media file?")) return;
    try {
        await apiRequest(`/api/media/${currentMediaId}`, "DELETE");
        currentMediaList.splice(lightboxIndex, 1);
        closeLightbox();
        document.getElementById("gallery-count").innerText = currentMediaList.length;
        // Re-render gallery grid
        const grid = document.getElementById("idol-gallery-grid");
        grid.innerHTML = "";
        currentMediaList.forEach((item, i) => {
            const el = document.createElement("div");
            el.className = "gallery-item";
            let src = item.src;
            if (window.__TAURI__) src = window.__TAURI__.core.convertFileSrc(item.src);
            el.onclick = () => openLightbox(i);
            el.innerHTML = `<img src="${src}" loading="lazy"><div class="gallery-item-overlay"><span class="gallery-item-platform ${item.platform}">${item.platform}</span></div>`;
            grid.appendChild(el);
        });
    } catch (e) {
        console.error("Delete failed", e);
        alert("Failed to delete media");
    }
}

// Platform filter
let activePlatformFilter = "all";

function togglePlatformFilter() {
    const checked = document.getElementById("platform-filter-toggle").checked;
    document.getElementById("platform-filter-chips").style.display = checked ? "flex" : "none";
    if (!checked) {
        activePlatformFilter = "all";
        applyPlatformFilter();
    }
}

function setPlatformFilter(platform) {
    activePlatformFilter = platform;
    document.querySelectorAll(".filter-chip").forEach(el => {
        el.classList.toggle("active", el.dataset.platform === platform);
    });
    applyPlatformFilter();
}

function applyPlatformFilter() {
    const grid = document.getElementById("idol-gallery-grid");
    const items = grid.querySelectorAll(".gallery-item");
    items.forEach(el => {
        const platform = el.querySelector(".gallery-item-platform")?.textContent;
        if (activePlatformFilter === "all" || platform === activePlatformFilter) {
            el.style.display = "";
        } else {
            el.style.display = "none";
        }
    });
}

// Download progress polling
let progressInterval = null;

function startProgressPoll() {
    const bar = document.getElementById("download-progress-bar");
    bar.style.display = "block";
    if (progressInterval) clearInterval(progressInterval);
    progressInterval = setInterval(async () => {
        try {
            const d = await apiRequest("/api/download-progress");
            document.getElementById("progress-status").textContent = d.status;
            if (d.total > 0) {
                const pct = Math.round((d.completed / d.total) * 100);
                document.getElementById("progress-fill").style.width = pct + "%";
                document.getElementById("progress-count").textContent = `${d.completed}/${d.total}`;
            } else {
                document.getElementById("progress-fill").style.width = "100%";
                document.getElementById("progress-count").textContent = d.status;
            }
            if (!d.running) {
                clearInterval(progressInterval);
                progressInterval = null;
                setTimeout(() => { bar.style.display = "none"; }, 3000);
            }
        } catch (e) { /* ignore */ }
    }, 1000);
}

// Poll logs
async function pollLogs() {
    try {
        const logs = await apiRequest("/api/logs");
        
        if (logs.length > 0) {
            const consoleBody = document.getElementById("console-logs");
            logs.forEach(log => {
                const line = document.createElement("span");
                
                // Color mapping
                let logClass = "info-line";
                if (log.includes("ERROR") || log.includes("❌")) logClass = "error-line";
                else if (log.includes("WARN") || log.includes("WARNING")) logClass = "warn-line";
                else if (log.includes("SUCCESS") || log.includes("Finished") || log.includes("complete")) logClass = "success-line";
                
                line.className = `log-line ${logClass}`;
                line.innerText = log;
                consoleBody.appendChild(line);
            });
            
            // Auto scroll to bottom
            consoleBody.scrollTop = consoleBody.scrollHeight;
        }
    } catch(e) {
        console.error("Failed to poll logs", e);
    }
}

// Scrape Idol
async function scrapeIdol() {
    if (!currentIdol) return;
    const name = currentIdol.name;
    const depth = scrapeDepth;
    
    try {
        document.getElementById("console-logs").innerHTML = `<span class="log-line system-line">[${new Date().toLocaleTimeString()}] Triggering ${depth} scrape for ${name}...</span>`;
        showToast("Scraping " + name + " (" + depth + ")", "info");
        switchView("dashboard"); // Go to dashboard to watch logs
        
        await apiRequest(`/api/idols/${name}/download`, "POST", { depth: depth });
        
        startProgressPoll();
        fetchStats(); 
    } catch (e) {
        showToast("Failed to trigger download: " + e.message, "error");
        console.error("Failed to trigger download", e);
    }
}

// Delete Idol
async function deleteIdol() {
    if (!currentIdol) return;
    const name = currentIdol.name;
    
    if (confirm(`Are you sure you want to remove ${name} from tracking? (This won't delete downloaded files on disk)`)) {
        try {
            await apiRequest(`/api/idols/${name}`, "DELETE");
            switchView("catalog");
        } catch (e) {
            console.error("Failed to delete idol", e);
        }
    }
}

// Add Idol Modal Handlers
document.getElementById("btn-open-add-modal").onclick = () => {
    document.getElementById("modal-add-idol").classList.add("active");
};

function closeAddModal() {
    document.getElementById("modal-add-idol").classList.remove("active");
    document.getElementById("form-add-idol").reset();
}

document.getElementById("btn-close-add-modal").onclick = closeAddModal;
document.getElementById("btn-cancel-add-modal").onclick = closeAddModal;

// Edit Idol Modal
function openEditModal() {
    if (!currentIdol) return;
    const p = currentIdol;

    document.getElementById("edit-name").value = p.name || "";
    document.getElementById("edit-type").value = p.type || "kr";
    document.getElementById("edit-hangul").value = p.hangul || "";
    document.getElementById("edit-stage-name").value = p.stage_name || "";
    document.getElementById("edit-real-name").value = p.real_name || "";
    document.getElementById("edit-positions").value = (p.positions || []).join(", ");
    document.getElementById("edit-kanji").value = p.kanji || "";
    document.getElementById("edit-generation").value = p.generation || "";
    document.getElementById("edit-team").value = p.team || "";
    document.getElementById("edit-grad-date").value = p.graduation_date || "";
    document.getElementById("edit-group").value = p.group || "";
    document.getElementById("edit-company").value = p.company || "";
    document.getElementById("edit-fandom").value = p.fandom || "";
    document.getElementById("edit-birthday").value = p.birthday || "";
    document.getElementById("edit-debut").value = p.debut || "";
    document.getElementById("edit-status").value = p.status || "active";
    document.getElementById("edit-nicknames").value = "";
    document.getElementById("edit-exclude").value = "";
    document.getElementById("edit-download-dir").value = p.download_dir || "";

    // Trigger type change to show correct fields
    document.getElementById("edit-type").dispatchEvent(new Event("change"));

    // Load current sources into fields
    const sources = currentIdol._sources || [];
    const platformMap = { twitter: [], instagram: [], threads: [], tiktok: [], weibo: [] };
    sources.forEach(s => {
        if (platformMap[s.platform]) platformMap[s.platform].push(s.username);
    });
    document.getElementById("edit-twitter").value = platformMap.twitter.join(", ");
    document.getElementById("edit-instagram").value = platformMap.instagram.join(", ");
    document.getElementById("edit-threads").value = platformMap.threads.join(", ");
    document.getElementById("edit-tiktok").value = platformMap.tiktok.join(", ");
    document.getElementById("edit-weibo").value = platformMap.weibo.join(", ");

    document.getElementById("modal-edit-idol").classList.add("active");
    lucide.createIcons();
}

function closeEditModal() {
    document.getElementById("modal-edit-idol").classList.remove("active");
    document.getElementById("form-edit-idol").reset();
}

document.getElementById("btn-edit-idol").onclick = openEditModal;
document.getElementById("btn-close-edit-modal").onclick = closeEditModal;
document.getElementById("btn-cancel-edit-modal").onclick = closeEditModal;

// Toggle JP vs KR fields based on dropdown selection
document.getElementById("add-type").onchange = (e) => {
    const type = e.target.value;
    if (type === "jp") {
        document.querySelectorAll("#modal-add-idol .kr-fields").forEach(el => el.classList.add("hidden"));
        document.querySelectorAll("#modal-add-idol .jp-fields").forEach(el => el.classList.remove("hidden"));
    } else {
        document.querySelectorAll("#modal-add-idol .kr-fields").forEach(el => el.classList.remove("hidden"));
        document.querySelectorAll("#modal-add-idol .jp-fields").forEach(el => el.classList.add("hidden"));
    }
};

// Edit Modal Toggle JP vs KR fields
document.getElementById("edit-type").onchange = (e) => {
    const type = e.target.value;
    if (type === "jp") {
        document.querySelectorAll("#modal-edit-idol .kr-fields").forEach(el => el.classList.add("hidden"));
        document.querySelectorAll("#modal-edit-idol .jp-fields").forEach(el => el.classList.remove("hidden"));
    } else {
        document.querySelectorAll("#modal-edit-idol .kr-fields").forEach(el => el.classList.remove("hidden"));
        document.querySelectorAll("#modal-edit-idol .jp-fields").forEach(el => el.classList.add("hidden"));
    }
};

// Form Add Idol Submit
document.getElementById("form-add-idol").onsubmit = async (e) => {
    e.preventDefault();
    
    const name = document.getElementById("add-name").value;
    const type = document.getElementById("add-type").value;
    
    const twitterVal = document.getElementById("add-twitter").value;
    const instagramVal = document.getElementById("add-instagram").value;
    const threadsVal = document.getElementById("add-threads").value;
    const tiktokVal = document.getElementById("add-tiktok").value;
    const weiboVal = document.getElementById("add-weibo").value;
    
    const payload = {
        name: name,
        type: type,
        group: document.getElementById("add-group").value || null,
        company: document.getElementById("add-company").value || null,
        fandom: document.getElementById("add-fandom").value || null,
        birthday: document.getElementById("add-birthday").value || null,
        debut: document.getElementById("add-debut").value || null,
        status: document.getElementById("add-status").value || "active",
        nicknames: document.getElementById("add-nicknames").value || "",
        exclude: document.getElementById("add-exclude").value || "",
        download_dir: document.getElementById("add-download-dir").value || null,
        
        // J-Pop Specific
        kanji: document.getElementById("add-kanji").value || null,
        generation: document.getElementById("add-generation").value || null,
        team: document.getElementById("add-team").value || null,
        graduation_date: document.getElementById("add-grad-date").value || null,
        
        // K-Pop Specific
        hangul: document.getElementById("add-hangul").value || null,
        stage_name: document.getElementById("add-stage-name").value || null,
        real_name: document.getElementById("add-real-name").value || null,
        positions: document.getElementById("add-positions").value ? document.getElementById("add-positions").value.split(",").map(s => s.trim()) : [],
        
        twitter: twitterVal ? twitterVal.split(",").map(s => s.trim()) : [],
        instagram: instagramVal ? instagramVal.split(",").map(s => s.trim()) : [],
        threads: threadsVal ? threadsVal.split(",").map(s => s.trim()) : [],
        tiktok: tiktokVal ? tiktokVal.split(",").map(s => s.trim()) : [],
        weibo: weiboVal ? weiboVal.split(",").map(s => s.trim()) : []
    };
    
    try {
        const response = await apiRequest("/api/idols", "POST", payload);
        closeAddModal();
        fetchCatalog();
    } catch (e) {
        showToast("Failed to add idol: " + e.message, "error");
        console.error("Failed to add idol", e);
    }
};

// Form Edit Idol Submit
document.getElementById("form-edit-idol").onsubmit = async (e) => {
    e.preventDefault();

    const originalName = currentIdol.name;
    const name = document.getElementById("edit-name").value;
    const type = document.getElementById("edit-type").value;

    const twitterVal = document.getElementById("edit-twitter").value;
    const instagramVal = document.getElementById("edit-instagram").value;
    const threadsVal = document.getElementById("edit-threads").value;
    const tiktokVal = document.getElementById("edit-tiktok").value;
    const weiboVal = document.getElementById("edit-weibo").value;

    const payload = {
        name: name,
        type: type,
        group: document.getElementById("edit-group").value || null,
        company: document.getElementById("edit-company").value || null,
        fandom: document.getElementById("edit-fandom").value || null,
        birthday: document.getElementById("edit-birthday").value || null,
        debut: document.getElementById("edit-debut").value || null,
        status: document.getElementById("edit-status").value || "active",
        nicknames: document.getElementById("edit-nicknames").value || "",
        exclude: document.getElementById("edit-exclude").value || "",
        download_dir: document.getElementById("edit-download-dir").value || null,

        kanji: document.getElementById("edit-kanji").value || null,
        generation: document.getElementById("edit-generation").value || null,
        team: document.getElementById("edit-team").value || null,
        graduation_date: document.getElementById("edit-grad-date").value || null,

        hangul: document.getElementById("edit-hangul").value || null,
        stage_name: document.getElementById("edit-stage-name").value || null,
        real_name: document.getElementById("edit-real-name").value || null,
        positions: document.getElementById("edit-positions").value ? document.getElementById("edit-positions").value.split(",").map(s => s.trim()) : [],

        twitter: twitterVal ? twitterVal.split(",").map(s => s.trim()) : [],
        instagram: instagramVal ? instagramVal.split(",").map(s => s.trim()) : [],
        threads: threadsVal ? threadsVal.split(",").map(s => s.trim()) : [],
        tiktok: tiktokVal ? tiktokVal.split(",").map(s => s.trim()) : [],
        weibo: weiboVal ? weiboVal.split(",").map(s => s.trim()) : []
    };

    try {
        await apiRequest(`/api/idols/${originalName}`, "PUT", payload);
        closeEditModal();
        showIdolDetail(name);
        showToast("Idol updated successfully!", "success");
    } catch (e) {
        showToast("Failed to update idol: " + e.message, "error");
        console.error("Failed to update idol", e);
    }
};

// Fetch Settings
async function fetchSettings() {
    try {
        console.log("[Catchido] fetchSettings: calling /api/config");
        const data = await apiRequest("/api/config");
        console.log("[Catchido] fetchSettings: got config data");
        
        document.getElementById("setting-download-dir").value = data.download_dir;
        document.getElementById("setting-max-downloads").value = data.max_concurrent_downloads;
        document.getElementById("setting-dedup-threshold").value = data.dedup_threshold;
        
        document.getElementById("setting-auto-dedup").checked = data.auto_dedup;
        document.getElementById("setting-prefer-highres").checked = data.prefer_higher_res;
        document.getElementById("setting-download-photos").checked = data.download_photos;
        document.getElementById("setting-download-videos").checked = data.download_videos;
        document.getElementById("setting-auto-scrape-interval").value = data.auto_scrape_interval_hours || 0;
        
        // Search
        document.getElementById("setting-min-relevance").value = data.min_relevance_score;
        document.getElementById("setting-auto-discover").checked = data.auto_discover_accounts;
        document.getElementById("setting-auto-keywords").checked = data.auto_generate_keywords;
        document.getElementById("setting-include-fan").checked = data.include_fan_content;
        document.getElementById("setting-exclude-fanart").checked = data.exclude_fanart;
        
        // Proxy
        document.getElementById("setting-proxy-enabled").checked = data.proxy_enabled;
        document.getElementById("setting-proxy-http").value = data.proxy_http || "";
        document.getElementById("setting-proxy-https").value = data.proxy_https || "";
        
        // Delays
        document.getElementById("setting-twitter-delay").value = data.twitter_request_delay;
        document.getElementById("setting-ig-delay").value = data.ig_request_delay;
        document.getElementById("setting-threads-delay").value = data.threads_request_delay;
        document.getElementById("setting-tiktok-delay").value = data.tiktok_request_delay;
        document.getElementById("setting-weibo-delay").value = data.weibo_request_delay;
        
        // Tokens
        document.getElementById("setting-twitter-bearer").value = data.twitter_bearer;
        document.getElementById("setting-instagram-cookie").value = data.instagram_cookie;
        document.getElementById("setting-threads-cookie").value = data.threads_cookie;
        document.getElementById("setting-tiktok-cookie").value = data.tiktok_cookie;
        document.getElementById("setting-weibo-cookie").value = data.weibo_cookie;
    } catch(e) {
        console.error("Failed to load settings", e);
        document.querySelectorAll("#form-settings .form-control, #form-settings input[type=text], #form-settings input[type=number]").forEach(el => {
            el.style.borderColor = "var(--red)";
        });
        showToast("Failed to load settings: " + e.message, "error");
    }
}

// Form Settings Submit
document.getElementById("form-settings").onsubmit = async (e) => {
    e.preventDefault();
    
    function v(id) { return document.getElementById(id).value; }
    function c(id) { return document.getElementById(id).checked; }
    
    const payload = {
        download_dir: v("setting-download-dir"),
        max_concurrent_downloads: parseInt(v("setting-max-downloads")),
        dedup_threshold: parseInt(v("setting-dedup-threshold")),
        
        auto_dedup: c("setting-auto-dedup"),
        prefer_higher_res: c("setting-prefer-highres"),
        download_photos: c("setting-download-photos"),
        download_videos: c("setting-download-videos"),
        auto_scrape_interval_hours: parseInt(v("setting-auto-scrape-interval")) || 0,
        
        // Search
        min_relevance_score: parseFloat(v("setting-min-relevance")),
        auto_discover_accounts: c("setting-auto-discover"),
        auto_generate_keywords: c("setting-auto-keywords"),
        include_fan_content: c("setting-include-fan"),
        exclude_fanart: c("setting-exclude-fanart"),
        
        // Proxy
        proxy_enabled: c("setting-proxy-enabled"),
        proxy_http: v("setting-proxy-http") || null,
        proxy_https: v("setting-proxy-https") || null,
        
        // Delays
        twitter_request_delay: parseInt(v("setting-twitter-delay")),
        ig_request_delay: parseInt(v("setting-ig-delay")),
        threads_request_delay: parseInt(v("setting-threads-delay")),
        tiktok_request_delay: parseInt(v("setting-tiktok-delay")),
        weibo_request_delay: parseInt(v("setting-weibo-delay")),
        
        // Tokens
        twitter_bearer: v("setting-twitter-bearer"),
        instagram_cookie: v("setting-instagram-cookie"),
        threads_cookie: v("setting-threads-cookie"),
        tiktok_cookie: v("setting-tiktok-cookie"),
        weibo_cookie: v("setting-weibo-cookie"),
    };
    
    try {
        await apiRequest("/api/config", "POST", payload);
        showToast("Settings saved successfully!", "success");
        fetchStats();
    } catch (e) {
        showToast("Failed to save settings: " + e.message, "error");
        console.error("Failed to save settings", e);
    }
};

// Event Bindings
document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.onclick = () => {
        const view = btn.getAttribute("data-view");
        switchView(view);
    };
});

document.getElementById("btn-back-to-catalog").onclick = () => switchView("catalog");
document.getElementById("btn-scrape-idol").onclick = scrapeIdol;
document.getElementById("btn-delete-idol").onclick = deleteIdol;

// Depth Toggle
document.querySelectorAll(".depth-btn").forEach(btn => {
    btn.onclick = () => {
        document.querySelectorAll(".depth-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        scrapeDepth = btn.getAttribute("data-depth");
    };
});

// --- Source Account Management ---
function extractUsername(raw, platform) {
    raw = raw.trim();
    if (!raw) return "";
    if (raw.startsWith("@")) return raw.slice(1);
    if (raw.includes("http") || raw.includes("/")) {
        const patterns = {
            instagram: /instagram\.com\/([A-Za-z0-9_.]+)/,
            twitter: /(?:twitter|x)\.com\/([A-Za-z0-9_]+)/,
            threads: /threads\.net\/@?([A-Za-z0-9_.]+)/,
            tiktok: /tiktok\.com\/@([A-Za-z0-9_.]+)/,
            weibo: /weibo\.com\/u\/(\d+)/
        };
        const match = raw.match(patterns[platform] || /\/([A-Za-z0-9_]+)$/);
        if (match) return match[1];
    }
    return raw;
}

document.getElementById("btn-add-source").onclick = async () => {
    if (!currentIdol) return;
    const platform = document.getElementById("add-source-platform").value;
    const raw = document.getElementById("add-source-username").value.trim();
    if (!raw) return showToast("Enter a username or paste a link", "error");
    const username = extractUsername(raw, platform);
    if (!username) return showToast("Could not extract username from input", "error");
    
    try {
        await apiRequest(`/api/idols/${currentIdol.name}/sources`, "POST", { platform, username });
        document.getElementById("add-source-username").value = "";
        showToast(`@${username} added`, "success");
        showIdolDetail(currentIdol.name);
    } catch (e) {
        showToast("Failed: " + e.message, "error");
    }
};

document.getElementById("detail-accounts-list").onclick = async (e) => {
    const btn = e.target.closest(".btn-remove-source");
    if (!btn || !currentIdol) return;
    
    const platform = btn.dataset.platform;
    const username = btn.dataset.username;
    if (!confirm(`Remove @${username} from ${platform}?`)) return;
    
    try {
        await apiRequest(`/api/idols/${currentIdol.name}/sources?platform=${platform}&username=${encodeURIComponent(username)}`, "DELETE");
        showToast(`@${username} removed`, "success");
        showIdolDetail(currentIdol.name);
    } catch (e) {
        showToast("Failed: " + e.message, "error");
    }
};

// Enter key to add source
document.getElementById("add-source-username").onkeydown = (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        document.getElementById("btn-add-source").click();
    }
};

// Test Cookies
document.getElementById("btn-test-cookies").onclick = testCookies;

async function testCookies() {
    const payload = {
        instagram_cookie: document.getElementById("setting-instagram-cookie").value,
        weibo_cookie: document.getElementById("setting-weibo-cookie").value,
        tiktok_cookie: document.getElementById("setting-tiktok-cookie").value,
        threads_cookie: document.getElementById("setting-threads-cookie").value
    };
    
    const resultsDiv = document.getElementById("cookie-test-results");
    resultsDiv.innerHTML = `
        <div style="color: var(--text-secondary); font-size: 14px; padding: 12px 0;">
            <i data-lucide="loader" class="spin-icon"></i> Testing cookies...
        </div>
    `;
    resultsDiv.classList.remove("hidden");
    lucide.createIcons();
    
    try {
        const results = await apiRequest("/api/utils/test-cookies", "POST", payload);
        
        resultsDiv.innerHTML = "";
        
        const platformNames = {
            instagram: "Instagram",
            weibo: "Weibo",
            tiktok: "TikTok",
            threads: "Threads"
        };
        
        const statusIcons = {
            ok: "check-circle",
            error: "x-circle",
            empty: "minus-circle"
        };
        
        const statusClasses = {
            ok: "test-ok",
            error: "test-error",
            empty: "test-empty"
        };
        
        for (const [key, result] of Object.entries(results)) {
            const row = document.createElement("div");
            row.className = `cookie-test-row ${statusClasses[result.status] || "test-empty"}`;
            row.innerHTML = `
                <span class="test-status-icon"><i data-lucide="${statusIcons[result.status] || statusIcons.empty}"></i></span>
                <span style="flex-grow: 1;">${platformNames[key] || key}</span>
                <span style="font-weight: 400; color: var(--text-secondary);">${result.message}</span>
            `;
            resultsDiv.appendChild(row);
        }
        
        lucide.createIcons();
        
        const hasError = Object.values(results).some(r => r.status === "error");
        if (hasError) {
            showToast("Some cookies have expired. Check results for details.", "warning");
        } else {
            showToast("All configured cookies are valid!", "success");
        }
    } catch (e) {
        resultsDiv.innerHTML = `<div class="cookie-test-row test-error">
            <span class="test-status-icon"><i data-lucide="x-circle"></i></span>
            <span>Test failed: ${e.message}</span>
        </div>`;
        lucide.createIcons();
        showToast("Cookie test failed: " + e.message, "error");
    }
}

document.getElementById("btn-clear-console").onclick = () => {
    document.getElementById("console-logs").innerHTML = `<span class="log-line system-line">Console cleared.</span>`;
};

// Lightbox Handlers
document.querySelector(".lightbox-close").onclick = closeLightbox;
document.querySelector(".lightbox-prev").onclick = () => navigateLightbox(-1);
document.querySelector(".lightbox-next").onclick = () => navigateLightbox(1);

document.getElementById("lightbox-modal").onclick = (e) => {
    if (e.target.id === "lightbox-modal" || e.target.closest(".lightbox-close")) {
        closeLightbox();
    }
};

// Keyboard navigation for Lightbox
document.addEventListener("keydown", (e) => {
    const modal = document.getElementById("lightbox-modal");
    if (modal.classList.contains("active")) {
        if (e.key === "ArrowLeft") {
            navigateLightbox(-1);
        } else if (e.key === "ArrowRight") {
            navigateLightbox(1);
        } else if (e.key === "Escape") {
            closeLightbox();
        }
    }
});

// App Entry Point
window.onload = () => {
    console.log("[Catchido] window.onload fired");
    try {
        switchView("dashboard");
        setInterval(fetchStats, 4000);
        console.log("[Catchido] dashboard initialized");
    } catch (e) {
        console.error("[Catchido] App init error:", e);
        document.getElementById("stat-idols").innerText = "ERR";
        document.getElementById("stat-files").innerText = e.message;
        showToast("App failed to initialize: " + e.message, "error");
    }
};
