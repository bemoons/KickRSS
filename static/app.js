// Hook/override global fetch and EventSource to support frontend-backend decoupling (configurable backend URL)
(function() {
    const apiBase = window.localStorage.getItem('KICKRSS_API_BASE') || '';
    if (apiBase) {
        const originalFetch = window.fetch;
        window.fetch = function(input, init) {
            if (typeof input === 'string' && input.startsWith('/')) {
                input = apiBase + input;
            }
            return originalFetch(input, init);
        };

        const OriginalEventSource = window.EventSource;
        window.EventSource = function(url, configuration) {
            if (typeof url === 'string' && url.startsWith('/')) {
                url = apiBase + url;
            }
            return new OriginalEventSource(url, configuration);
        };
        window.EventSource.prototype = OriginalEventSource.prototype;
    }
})();

// Global State Management
const state = {
    feeds: [],
    selectedFeedId: null,
    selectedCategoryId: null,
    selectedEntryId: null,
    entries: [],
    filterUnreadOnly: true,
    activeView: 'unread', // 'unread' or 'category' or 'feed'
    currentOpenEntry: null,
    isRefreshing: false,
    autoSummary: true,
    systemLang: 'zh',
    currentOpenEntryFulltext: "",
    isBilingualMode: false,
    isTranslating: false,
    translatedContentCache: null,
    selectedNotesIds: new Set(),
    
    // Pagination state for entries list
    entriesOffset: 0,
    entriesLimit: 50,
    hasMoreEntries: true,
    isLoadingMore: false,
    
    // Reading profile state
    interestProfileEnabled: false,
    profileTrendView: 'week', // 'week' or 'month'
    interestProfileData: null
};

let currentEngagement = null;

// UI Elements Cache
const elements = {
    feedsList: document.getElementById('feeds-list'),
    entriesList: document.getElementById('entries-list'),
    entriesScrollContainer: document.querySelector('#entries-column .panel-scroll-content'),
    globalUnreadCount: document.getElementById('global-unread-count'),
    currentCategoryName: document.getElementById('current-category-name'),
    entriesCountLabel: document.getElementById('entries-count-label'),
    filterUnreadToggle: document.getElementById('filter-unread-toggle'),
    markAllReadBtn: document.getElementById('mark-all-read-btn'),
    searchInput: document.getElementById('search-input'),
    
    // Detail View Elements
    detailEmptyState: document.getElementById('detail-empty-state'),
    detailActiveView: document.getElementById('detail-active-view'),
    artTitleLink: document.getElementById('art-title-link'),
    artFeedBadge: document.getElementById('art-feed-badge'),
    artAuthor: document.getElementById('art-author'),
    artDate: document.getElementById('art-date'),
    artOriginalLink: document.getElementById('art-original-link'),
    artToggleReadBtn: document.getElementById('art-toggle-read-btn'),
    attnBtnGlance: document.getElementById('attn-btn-glance'),
    attnBtnSkim: document.getElementById('attn-btn-skim'),
    attnBtnRead: document.getElementById('attn-btn-read'),
    
    // AI Elements
    aiSummaryBlock: document.getElementById('ai-summary-block'),
    summaryMetaInfo: document.getElementById('summary-meta-info'),
    summaryContent: document.getElementById('summary-content'),
    summaryStatusBadge: document.getElementById('summary-status-badge'),
    regenerateSummaryBtn: document.getElementById('regenerate-summary-btn'),
    clickbaitBanner: document.getElementById('clickbait-banner'),
    clickbaitText: document.getElementById('clickbait-text'),
    toggleFulltextBtn: document.getElementById('toggle-fulltext-btn'),
    fulltextContentArea: document.getElementById('fulltext-content-area'),
    expanderText: document.getElementById('expander-text'),
    expanderIcon: document.getElementById('expander-icon'),
    
    // Chat Elements
    chatHistory: document.getElementById('chat-history'),
    chatInputForm: document.getElementById('chat-input-form'),
    chatInputField: document.getElementById('chat-input-field'),
    chatSendBtn: document.getElementById('chat-send-btn'),
    exportChatBtn: document.getElementById('export-chat-btn'),
    btnNotes: document.getElementById('btn-notes'),
    notesCount: document.getElementById('notes-count'),
    btnSelectAllNotes: document.getElementById('select-all-notes-btn'),
    btnBatchExportNotes: document.getElementById('batch-export-notes-btn'),
    clearChatBtn: document.getElementById('clear-chat-btn'),
    btnRequestBadgePermission: document.getElementById('btn-request-badge-permission'),
    
    // Footer Buttons
    refreshAllBtn: document.getElementById('refresh-all-btn'),
    refreshIcon: document.getElementById('refresh-icon'),
    addFeedBtn: document.getElementById('add-feed-btn'),
    opmlImportBtn: document.getElementById('opml-import-btn'),
    btnAllUnread: document.getElementById('btn-all-unread'),
    btnStarred: document.getElementById('btn-starred'),
    starredCount: document.getElementById('starred-count'),
    artToggleStarBtn: document.getElementById('art-toggle-star-btn'),
    artTranslateBtn: document.getElementById('art-translate-btn'),
    themeToggleBtn: document.getElementById('theme-toggle-btn'),
    manageFeedsBtn: document.getElementById('manage-feeds-btn'),
    articleScrollView: document.querySelector('.article-scroll-view'),
    backToTopBtn: document.getElementById('back-to-top-btn'),
    
    // Modals
    addFeedModal: document.getElementById('add-feed-modal'),
    opmlModal: document.getElementById('opml-modal'),
    manageFeedsModal: document.getElementById('manage-feeds-modal'),
    manageFeedsList: document.getElementById('manage-feeds-list'),
    opmlExportBtn: document.getElementById('opml-export-btn'),
    
    // Settings tab elements
    tabBtnFeeds: document.getElementById('tab-btn-feeds'),
    tabBtnSettings: document.getElementById('tab-btn-settings'),
    tabContentFeeds: document.getElementById('tab-content-feeds'),
    tabContentSettings: document.getElementById('tab-content-settings'),
    settingsSaveBtn: document.getElementById('settings-save-btn'),
    btnManualMaintenance: document.getElementById('btn-manual-maintenance'),
    systemSettingsForm: document.getElementById('system-settings-form'),
    
    // Settings inputs
    settingApiBase: document.getElementById('setting-api-base'),
    settingFetchInterval: document.getElementById('setting-fetch-interval'),
    settingMinTextChars: document.getElementById('setting-min-text-chars'),
    settingAiUrl: document.getElementById('setting-ai-url'),
    settingAiKey: document.getElementById('setting-ai-key'),
    settingAiModel: document.getElementById('setting-ai-model'),
    settingAiPregenerate: document.getElementById('setting-ai-pregenerate'),
    settingAiStream: document.getElementById('setting-ai-stream'),
    settingAiAutoSummary: document.getElementById('setting-ai-auto-summary'),
    settingPromoteThreshold: document.getElementById('setting-promote-threshold'),
    settingChatUrl: document.getElementById('setting-chat-url'),
    settingChatKey: document.getElementById('setting-chat-key'),
    settingChatModel: document.getElementById('setting-chat-model'),
    settingChatTokens: document.getElementById('setting-chat-tokens'),
    settingAiSummaryLang: document.getElementById('setting-ai-summary-lang'),
    settingSystemLang: document.getElementById('setting-system-lang'),
    
    feedUrlInput: document.getElementById('feed-url-input'),
    submitFeedBtn: document.getElementById('submit-feed-btn'),
    opmlFileInput: document.getElementById('opml-file-input'),
    fileDropZone: document.getElementById('file-drop-zone'),
    submitOpmlBtn: document.getElementById('submit-opml-btn'),
    fileUploadLabel: document.getElementById('file-upload-label'),
    
    // Mobile Back Buttons
    mobileBackToFeeds: document.getElementById('mobile-back-to-feeds'),
    mobileBackToEntries: document.getElementById('mobile-back-to-entries'),
    
    // Reading Profile Elements
    showProfileBtn: document.getElementById('show-profile-btn'),
    profileModal: document.getElementById('profile-modal'),
    closeProfileModalBtn: document.getElementById('close-profile-modal-btn'),
    closeProfileModalBtnFooter: document.getElementById('close-profile-modal-btn-footer'),
    profileStatusView: document.getElementById('profile-status-view'),
    profileStatusTitle: document.getElementById('profile-status-title'),
    profileStatusDesc: document.getElementById('profile-status-desc'),
    profileMainContent: document.getElementById('profile-main-content'),
    profileStatTotal: document.getElementById('profile-stat-total'),
    profileStatHigh: document.getElementById('profile-stat-high'),
    profileStatLow: document.getElementById('profile-stat-low'),
    profileTagCloud: document.getElementById('profile-tag-cloud'),
    profileDetailPanel: document.getElementById('profile-detail-panel'),
    profileDetailTitle: document.getElementById('profile-detail-title'),
    profileDetailCount: document.getElementById('profile-detail-count'),
    profileDetailStarred: document.getElementById('profile-detail-starred'),
    profileDetailOriginal: document.getElementById('profile-detail-original'),
    profileDetailTrend: document.getElementById('profile-detail-trend'),
    profileDetailArticles: document.getElementById('profile-detail-articles'),
    closeProfileDetailBtn: document.getElementById('close-profile-detail-btn'),
    profileHeatmapContainer: document.getElementById('profile-heatmap-container'),
    profileInsightBox: document.getElementById('profile-insight-box'),
    profileInsightText: document.getElementById('profile-insight-text'),
    settingInterestProfileEnabled: document.getElementById('setting-interest-profile-enabled'),
    profileToggleWeek: document.getElementById('profile-toggle-week'),
    profileToggleMonth: document.getElementById('profile-toggle-month'),
    profileDetailTrendTitle: document.getElementById('profile-detail-trend-title'),
    profileTabWeekContent: document.getElementById('profile-tab-week-content'),
    profileTabMonthContent: document.getElementById('profile-tab-month-content'),
    profileCategoryDistributionList: document.getElementById('profile-category-distribution-list'),
    profileHeatmapLegend: document.getElementById('profile-heatmap-legend'),
    profileActivityHeatmap: document.getElementById('profile-activity-heatmap'),
    profileHabitInsightText: document.getElementById('profile-habit-insight-text')
};

// ----------------------------------------------------
// INITIALIZATION
// ----------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initEventListeners();
    loadSettingsOnStartup().then(() => {
        loadFeeds();
        selectGlobalUnread(true);
    });
    initResizers();
    initChatDrawer();
    initPwaGestures();
    initEngagementTracking();

    // Register Service Worker for PWA
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('./sw.js')
                .then(reg => console.log('ServiceWorker registered successfully with scope: ', reg.scope))
                .catch(err => console.warn('ServiceWorker registration failed: ', err));
        });
    }

    // iOS Safari PWA Badge Permission Request
    if (window.navigator.standalone && 'Notification' in window) {
        if (Notification.permission === 'default') {
            const requestPermission = () => {
                Notification.requestPermission().then(permission => {
                    console.log("iOS Notification permission response:", permission);
                    if (permission === 'granted' && state.feeds) {
                        let totalUnread = 0;
                        state.feeds.forEach(f => totalUnread += f.unread_count || 0);
                        if (totalUnread > 0 && 'setAppBadge' in navigator) {
                            navigator.setAppBadge(totalUnread).catch(err => console.error("Error setting app badge:", err));
                        }
                    }
                }).catch(err => console.error("Failed to request notification permission:", err));
                document.removeEventListener('click', requestPermission);
                document.removeEventListener('touchstart', requestPermission);
            };
            document.addEventListener('click', requestPermission);
            document.addEventListener('touchstart', requestPermission);
        }
    }
});

async function loadSettingsOnStartup() {
    try {
        const response = await fetch('/settings');
        if (response.ok) {
            const data = await response.json();
            state.autoSummary = data.ai_auto_summary !== false; // default true
            state.systemLang = data.system_lang || 'zh';
            state.interestProfileEnabled = data.interest_profile_enabled === true;
            updateUILanguage(state.systemLang);
        }
    } catch (e) {
        console.error("Failed to load startup settings:", e);
        state.autoSummary = true;
        state.systemLang = 'zh';
        state.interestProfileEnabled = false;
    }
}

// ----------------------------------------------------
// EVENT LISTENERS
// ----------------------------------------------------
function initEventListeners() {
    // Infinite Scroll for Entries Column
    if (elements.entriesScrollContainer) {
        elements.entriesScrollContainer.addEventListener('scroll', () => {
            if (state.isLoadingMore || !state.hasMoreEntries) return;
            
            const threshold = 100; // px from bottom to trigger fetch
            const scrollTop = elements.entriesScrollContainer.scrollTop;
            const clientHeight = elements.entriesScrollContainer.clientHeight;
            const scrollHeight = elements.entriesScrollContainer.scrollHeight;
            
            if (scrollHeight - (scrollTop + clientHeight) < threshold) {
                loadMoreEntries();
            }
        });
    }

    // Unread Filters
    if (elements.filterUnreadToggle) {
        elements.filterUnreadToggle.addEventListener('change', (e) => {
            state.filterUnreadOnly = e.target.checked;
            if (state.activeView === 'unread') {
                loadUnreadEntries();
            } else if (state.activeView === 'feed' && state.selectedFeedId) {
                loadFeedEntries(state.selectedFeedId);
            } else if (state.activeView === 'category' && state.selectedCategoryId) {
                loadCategoryEntries(state.selectedCategoryId);
            } else if (state.activeView === 'starred') {
                loadStarredEntries();
            } else if (state.activeView === 'search') {
                const query = elements.searchInput ? elements.searchInput.value.trim() : '';
                if (query) {
                    loadSearchEntries(query);
                }
            } else {
                refreshEntriesList();
            }
        });
    }
    
    if (elements.markAllReadBtn) {
        elements.markAllReadBtn.addEventListener('click', markAllAsRead);
    }
    
    // Global Search Input
    if (elements.searchInput) {
        elements.searchInput.addEventListener('input', (e) => {
            const val = e.target.value.trim();
            if (val === '') {
                if (state.activeView === 'search') {
                    selectGlobalUnread();
                }
                return;
            }
            
            clearTimeout(window.searchTimeout);
            window.searchTimeout = setTimeout(() => {
                state.activeView = 'search';
                document.querySelectorAll('.feed-row').forEach(node => node.classList.remove('active'));
                document.querySelectorAll('.category-row').forEach(node => node.classList.remove('active'));
                if (elements.btnAllUnread) elements.btnAllUnread.classList.remove('active');
                if (elements.btnStarred) elements.btnStarred.classList.remove('active');
                if (elements.btnNotes) elements.btnNotes.classList.remove('active');
                
                if (elements.currentCategoryName) elements.currentCategoryName.textContent = `搜索: "${val}"`;
                loadSearchEntries(val);
                document.body.classList.add('show-entries'); // Navigate to entries list on mobile search
            }, 300);
        });
    }
    
    // Quick Links
    if (elements.btnAllUnread) {
        elements.btnAllUnread.addEventListener('click', () => selectGlobalUnread());
    }
    if (elements.btnStarred) {
        elements.btnStarred.addEventListener('click', () => selectStarredView());
    }
    if (elements.btnNotes) {
        elements.btnNotes.addEventListener('click', () => selectNotesView());
    }
    if (elements.btnSelectAllNotes) {
        elements.btnSelectAllNotes.addEventListener('click', () => toggleSelectAllNotes());
    }
    if (elements.btnBatchExportNotes) {
        elements.btnBatchExportNotes.addEventListener('click', () => exportSelectedNotes());
    }
    
    if (elements.clearChatBtn) {
        elements.clearChatBtn.addEventListener('click', async () => {
            if (!state.currentOpenEntry) return;
            const entryId = state.currentOpenEntry.id;
            if (!confirm('确定要彻底删除该文章的所有 AI 对话笔记吗？此操作无法恢复。')) {
                return;
            }
            
            try {
                const response = await fetch(`/entries/${entryId}/chat`, { method: 'DELETE' });
                if (response.ok) {
                    reloadChatHistory(entryId);
                    
                    if (state.activeView === 'notes') {
                        const card = elements.entriesList.querySelector(`.entry-card[data-id="${entryId}"]`);
                        if (card) {
                            card.style.transition = "opacity 0.2s ease, max-height 0.2s ease";
                            card.style.opacity = "0";
                            setTimeout(() => {
                                state.entries = state.entries.filter(e => e.id !== entryId);
                                refreshEntriesList();
                            }, 200);
                        } else {
                            state.entries = state.entries.filter(e => e.id !== entryId);
                            refreshEntriesList();
                        }
                    }
                    
                    loadNotesCount();
                } else {
                    alert('删除失败，请重试');
                }
            } catch (err) {
                console.error("Failed to clear chat notes:", err);
                alert('删除失败，请重试');
            }
        });
    }

    if (elements.btnRequestBadgePermission) {
        if ('Notification' in window) {
            if (Notification.permission === 'granted') {
                elements.btnRequestBadgePermission.textContent = '✅ 已开启角标';
                elements.btnRequestBadgePermission.disabled = true;
                elements.btnRequestBadgePermission.style.opacity = '0.7';
            } else if (Notification.permission === 'denied') {
                elements.btnRequestBadgePermission.textContent = '❌ 已拒绝权限';
                elements.btnRequestBadgePermission.disabled = true;
                elements.btnRequestBadgePermission.style.opacity = '0.7';
            }
        } else {
            elements.btnRequestBadgePermission.textContent = '⚠️ 浏览器不支持角标';
            elements.btnRequestBadgePermission.disabled = true;
            elements.btnRequestBadgePermission.style.opacity = '0.7';
        }
        
        elements.btnRequestBadgePermission.addEventListener('click', async () => {
            if (!('Notification' in window)) {
                alert('您的浏览器或运行环境不支持 Web Notification 权限申请。如果是 iOS，请先添加此页面到主屏幕 (PWA)。');
                return;
            }
            try {
                const permission = await Notification.requestPermission();
                if (permission === 'granted') {
                    elements.btnRequestBadgePermission.textContent = '✅ 已开启角标';
                    elements.btnRequestBadgePermission.disabled = true;
                    elements.btnRequestBadgePermission.style.opacity = '0.7';
                    alert('推送与角标权限已成功开启！');
                    loadFeeds();
                } else if (permission === 'denied') {
                    elements.btnRequestBadgePermission.textContent = '❌ 已拒绝权限';
                    elements.btnRequestBadgePermission.disabled = true;
                    elements.btnRequestBadgePermission.style.opacity = '0.7';
                    alert('权限申请被拒绝，如需开启请在系统设置中允许该 PWA 应用的通知权限。');
                }
            } catch (err) {
                console.error("Failed to request badge permission:", err);
                alert("申请权限失败: " + err.message);
            }
        });
    }
    
    // Theme Switcher
    if (elements.themeToggleBtn) {
        elements.themeToggleBtn.addEventListener('click', toggleTheme);
    }
    
    const transBtn = document.getElementById('art-translate-btn');
    if (transBtn) {
        transBtn.addEventListener('click', toggleBilingualTranslation);
    }
    
    // Back to Top Button Listeners
    if (elements.articleScrollView && elements.backToTopBtn) {
        elements.articleScrollView.addEventListener('scroll', () => {
            if (elements.articleScrollView.scrollTop > 300) {
                elements.backToTopBtn.classList.add('visible');
            } else {
                elements.backToTopBtn.classList.remove('visible');
            }
        });
        
        elements.backToTopBtn.addEventListener('click', () => {
            elements.articleScrollView.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        });
    }
    
    // Footer actions
    if (elements.refreshAllBtn) {
        elements.refreshAllBtn.addEventListener('click', forceRefresh);
    }
    
    // Modal Toggles
    if (elements.addFeedBtn) {
        elements.addFeedBtn.addEventListener('click', () => showModal(elements.addFeedModal));
    }
    if (elements.opmlImportBtn) {
        elements.opmlImportBtn.addEventListener('click', () => {
            hideAllModals();
            showModal(elements.opmlModal);
        });
    }
    if (elements.manageFeedsBtn) {
        elements.manageFeedsBtn.addEventListener('click', () => {
            showModal(elements.manageFeedsModal);
            switchManageModalTab('feeds');
            loadAndRenderManageFeeds();
        });
    }
    if (elements.tabBtnFeeds) {
        elements.tabBtnFeeds.addEventListener('click', () => {
            switchManageModalTab('feeds');
            loadAndRenderManageFeeds();
        });
    }
    if (elements.tabBtnSettings) {
        elements.tabBtnSettings.addEventListener('click', () => {
            switchManageModalTab('settings');
            loadAndRenderSystemSettings();
        });
    }
    if (elements.settingsSaveBtn) {
        elements.settingsSaveBtn.addEventListener('click', saveSystemSettings);
    }
    const btnTestLLM = document.getElementById('btn-test-llm');
    if (btnTestLLM) {
        btnTestLLM.addEventListener('click', async () => {
            const apiBaseUrl = document.getElementById('setting-ai-url').value.trim();
            const apiKey = document.getElementById('setting-ai-key').value.trim();
            const apiModel = document.getElementById('setting-ai-model').value.trim();
            
            const resultSpan = document.getElementById('llm-test-result');
            resultSpan.textContent = '正在测试连接...';
            resultSpan.style.color = 'var(--text-muted)';
            
            btnTestLLM.disabled = true;
            
            try {
                const startTime = Date.now();
                const res = await fetch('/settings/test-llm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ai_base_url: apiBaseUrl,
                        ai_api_key: apiKey,
                        ai_model: apiModel
                    })
                });
                
                const data = await res.json();
                const duration = ((Date.now() - startTime) / 1000).toFixed(1);
                
                if (data.success) {
                    resultSpan.textContent = `连接成功！耗时 ${duration}s，响应: ${data.model_response}`;
                    resultSpan.style.color = '#10b981';
                } else {
                    resultSpan.textContent = `连接失败: ${data.message}`;
                    resultSpan.style.color = '#ef4444';
                }
            } catch (err) {
                console.error(err);
                resultSpan.textContent = '网络错误，连接失败。';
                resultSpan.style.color = '#ef4444';
            } finally {
                btnTestLLM.disabled = false;
            }
        });
    }
    if (elements.btnManualMaintenance) {
        elements.btnManualMaintenance.addEventListener('click', triggerManualMaintenance);
    }
    if (elements.opmlExportBtn) {
        elements.opmlExportBtn.addEventListener('click', exportOpml);
    }
    
    document.querySelectorAll('.close-modal-btn').forEach(btn => {
        btn.addEventListener('click', hideAllModals);
    });
    
    // Modal Actions
    if (elements.submitFeedBtn) {
        elements.submitFeedBtn.addEventListener('click', addFeedSubmit);
    }
    if (elements.submitOpmlBtn) {
        elements.submitOpmlBtn.addEventListener('click', importOpmlSubmit);
    }
    
    // Drag & Drop OPML
    if (elements.fileDropZone) {
        elements.fileDropZone.addEventListener('click', () => {
            if (elements.opmlFileInput) elements.opmlFileInput.click();
        });
        elements.fileDropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            elements.fileDropZone.classList.add('dragover');
        });
        elements.fileDropZone.addEventListener('dragleave', () => {
            elements.fileDropZone.classList.remove('dragover');
        });
        elements.fileDropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            elements.fileDropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0 && elements.opmlFileInput) {
                elements.opmlFileInput.files = e.dataTransfer.files;
                handleOpmlFileSelect();
            }
        });
    }
    if (elements.opmlFileInput) {
        elements.opmlFileInput.addEventListener('change', handleOpmlFileSelect);
    }
    
    // Article Detail Controls
    if (elements.artToggleReadBtn) {
        elements.artToggleReadBtn.addEventListener('click', toggleCurrentEntryReadStatus);
    }
    if (elements.artToggleStarBtn) {
        elements.artToggleStarBtn.addEventListener('click', toggleCurrentEntryStarStatus);
    }
    if (elements.toggleFulltextBtn) {
        elements.toggleFulltextBtn.addEventListener('click', toggleFulltextExpansion);
    }
    
    if (elements.regenerateSummaryBtn) {
        elements.regenerateSummaryBtn.addEventListener('click', () => {
            if (state.currentOpenEntry) {
                streamSummary(state.currentOpenEntry.id, true);
            }
        });
    }
    
    // Attention Level Buttons
    if (elements.attnBtnGlance) {
        elements.attnBtnGlance.addEventListener('click', () => setEntryAttentionLevel('glance'));
    }
    if (elements.attnBtnSkim) {
        elements.attnBtnSkim.addEventListener('click', () => setEntryAttentionLevel('skim'));
    }
    if (elements.attnBtnRead) {
        elements.attnBtnRead.addEventListener('click', () => setEntryAttentionLevel('read'));
    }
    
    // Chat Submit
    if (elements.chatInputForm) {
        elements.chatInputForm.addEventListener('submit', handleChatSubmit);
    }
    if (elements.exportChatBtn) {
        elements.exportChatBtn.addEventListener('click', exportReadingNotes);
    }
    
    // Chat Message Delete (Event Delegation)
    if (elements.chatHistory) {
        elements.chatHistory.addEventListener('click', async (e) => {
            const btn = e.target.closest('.delete-msg-btn');
            if (!btn) return;
            
            e.preventDefault();
            const bubble = btn.closest('.chat-bubble');
            if (!bubble) return;
            
            const msgId = bubble.dataset.messageId;
            if (!msgId) return;
            
            if (confirm("确定要删除这条对话记录吗？")) {
                try {
                    btn.disabled = true;
                    btn.textContent = "删除中...";
                    const response = await fetch(`/chat-messages/${msgId}`, { method: 'DELETE' });
                    if (response.ok) {
                        bubble.style.transition = "opacity 0.3s ease, transform 0.3s ease";
                        bubble.style.opacity = "0";
                        bubble.style.transform = "scale(0.95)";
                        setTimeout(() => {
                            if (state.currentOpenEntry) {
                                reloadChatHistory(state.currentOpenEntry.id);
                            }
                        }, 300);
                    } else {
                        alert("删除失败，请稍后重试。");
                        btn.disabled = false;
                        btn.textContent = "删除";
                    }
                } catch (err) {
                    console.error("Error deleting chat message:", err);
                    alert("网络错误，删除失败。");
                    btn.disabled = false;
                    btn.textContent = "删除";
                }
            }
        });
    }
    
    // Mobile Nav Back Actions
    if (elements.mobileBackToFeeds) {
        elements.mobileBackToFeeds.addEventListener('click', () => {
            document.body.classList.remove('show-entries');
            // Auto collapse current feed if it has no more unread entries
            if (state.selectedFeedId !== null) {
                const feed = state.feeds.find(f => f.id === state.selectedFeedId);
                if (feed && (!feed.unread_count || feed.unread_count === 0)) {
                    state.selectedFeedId = null;
                    state.selectedCategoryId = null;
                    loadFeeds();
                }
            }
        });
    }
    if (elements.mobileBackToEntries) {
        elements.mobileBackToEntries.addEventListener('click', () => {
            submitCurrentEngagement();
            document.body.classList.remove('show-detail');
            const detailCol = document.getElementById('detail-column');
            const chatSection = document.getElementById('chat-section');
            if (detailCol) detailCol.classList.remove('chat-open');
            if (chatSection) chatSection.classList.remove('open');
        });
    }

    // Auto refresh on window focus / visibility change (with a cooldown of 15 seconds)
    let lastFocusRefreshTime = 0;
    const focusRefreshCooldownMs = 15000; // 15 seconds

    const handleFocusRefresh = () => {
        const now = Date.now();
        if (now - lastFocusRefreshTime > focusRefreshCooldownMs) {
            lastFocusRefreshTime = now;
            simpleRefresh();
        }
    };

    window.addEventListener('focus', handleFocusRefresh);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            handleFocusRefresh();
        }
    });

    // Reading Profile Listeners
    if (elements.showProfileBtn) {
        elements.showProfileBtn.addEventListener('click', showProfileModal);
    }
    if (elements.closeProfileDetailBtn) {
        elements.closeProfileDetailBtn.addEventListener('click', () => {
            if (elements.profileDetailPanel) elements.profileDetailPanel.classList.add('hidden');
            // Unhighlight all tag elements
            if (elements.profileTagCloud) {
                elements.profileTagCloud.querySelectorAll('.profile-tag').forEach(el => {
                    el.style.outline = 'none';
                });
            }
        });
    }
    if (elements.profileToggleWeek) {
        elements.profileToggleWeek.addEventListener('click', () => {
            if (state.profileTrendView === 'week') return;
            state.profileTrendView = 'week';
            elements.profileToggleWeek.classList.add('active');
            elements.profileToggleWeek.style.background = 'var(--accent-indigo, #6366f1)';
            elements.profileToggleWeek.style.color = '#fff';
            elements.profileToggleMonth.classList.remove('active');
            elements.profileToggleMonth.style.background = 'transparent';
            elements.profileToggleMonth.style.color = 'var(--text-muted)';
            
            if (elements.profileTabWeekContent) elements.profileTabWeekContent.classList.remove('hidden');
            if (elements.profileTabMonthContent) elements.profileTabMonthContent.classList.add('hidden');
            
            if (state.interestProfileData) {
                renderProfileTokenStats(state.interestProfileData.token_stats);
                renderProfileCategoryDistribution(state.interestProfileData.category_distribution);
            }
        });
    }
    if (elements.profileToggleMonth) {
        elements.profileToggleMonth.addEventListener('click', () => {
            if (state.profileTrendView === 'month') return;
            state.profileTrendView = 'month';
            elements.profileToggleMonth.classList.add('active');
            elements.profileToggleMonth.style.background = 'var(--accent-indigo, #6366f1)';
            elements.profileToggleMonth.style.color = '#fff';
            elements.profileToggleWeek.classList.remove('active');
            elements.profileToggleWeek.style.background = 'transparent';
            elements.profileToggleWeek.style.color = 'var(--text-muted)';
            
            if (elements.profileTabMonthContent) elements.profileTabMonthContent.classList.remove('hidden');
            if (elements.profileTabWeekContent) elements.profileTabWeekContent.classList.add('hidden');
            
            if (state.interestProfileData && state.interestProfileData.topics) {
                renderProfileHeatmap(state.interestProfileData.topics);
                if (elements.profileDetailPanel && !elements.profileDetailPanel.classList.contains('hidden')) {
                    showTopicDetail(elements.profileDetailTitle.textContent);
                }
            }
        });
    }
}

// ----------------------------------------------------
// CORE DATA LOADING (FEEDS & CATEGORIES)
// ----------------------------------------------------
async function loadFeeds() {
    try {
        const response = await fetch('/feeds?t=' + Date.now());
        const feeds = await response.json();
        state.feeds = feeds;
        
        // Calculate global unread count
        let totalUnread = 0;
        feeds.forEach(f => totalUnread += f.unread_count || 0);
        elements.globalUnreadCount.textContent = totalUnread;

        // Update browser tab title
        document.title = totalUnread > 0 ? `(${totalUnread}) KickRSS` : "KickRSS — AI RSS Reader";

        // Update PWA desktop/homescreen badge
        if ('setAppBadge' in navigator) {
            if (totalUnread > 0) {
                navigator.setAppBadge(totalUnread).catch(err => console.error("Error setting app badge:", err));
            } else {
                navigator.clearAppBadge().catch(err => console.error("Error clearing app badge:", err));
            }
        }
        
        renderFeedsTree();
        
        // Refresh starred count
        loadStarredCount();
        loadNotesCount();
    } catch (e) {
        console.error("Failed to load feeds:", e);
    }
}

async function loadStarredCount() {
    try {
        const response = await fetch('/entries/starred/count?t=' + Date.now());
        if (response.ok) {
            const data = await response.json();
            elements.starredCount.textContent = data.total_count;
        }
    } catch (e) {
        console.error("Failed to load starred count:", e);
    }
}

let draggingElement = null;

function renderFeedsTree() {
    elements.feedsList.innerHTML = '';
    
    if (state.feeds.length === 0) {
        elements.feedsList.innerHTML = `
            <div class="loading-placeholder">
                <p>暂无订阅</p>
                <p style="font-size:11px; margin-top:4px;">点击右上角按钮添加。</p>
            </div>
        `;
        return;
    }
    
    // Sort state.feeds based on custom order in localStorage
    const savedOrder = JSON.parse(window.localStorage.getItem('KICKRSS_MANUAL_FEED_ORDER') || '[]');
    state.feeds.sort((a, b) => {
        const idxA = savedOrder.indexOf(a.id);
        const idxB = savedOrder.indexOf(b.id);
        
        if (idxA !== -1 && idxB !== -1) {
            return idxA - idxB;
        }
        if (idxA !== -1) return -1;
        if (idxB !== -1) return 1;
        return a.title.localeCompare(b.title, 'zh-CN');
    });
    
    state.feeds.forEach(feed => {
        const feedItem = document.createElement('div');
        feedItem.className = 'feed-item';
        feedItem.dataset.id = feed.id;
        
        // Make feedItem draggable for manual sorting
        feedItem.setAttribute('draggable', true);
        
        feedItem.addEventListener('dragstart', (e) => {
            draggingElement = feedItem;
            feedItem.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
        });
        
        feedItem.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (feedItem === draggingElement) return;
            
            const rect = feedItem.getBoundingClientRect();
            const midpoint = rect.top + rect.height / 2;
            
            feedItem.classList.remove('drag-over-top', 'drag-over-bottom');
            if (e.clientY < midpoint) {
                feedItem.classList.add('drag-over-top');
            } else {
                feedItem.classList.add('drag-over-bottom');
            }
        });
        
        feedItem.addEventListener('dragleave', () => {
            feedItem.classList.remove('drag-over-top', 'drag-over-bottom');
        });
        
        feedItem.addEventListener('dragend', () => {
            feedItem.classList.remove('dragging', 'drag-over-top', 'drag-over-bottom');
            document.querySelectorAll('.feed-item').forEach(el => {
                el.classList.remove('drag-over-top', 'drag-over-bottom');
            });
            draggingElement = null;
        });
        
        feedItem.addEventListener('drop', (e) => {
            e.preventDefault();
            feedItem.classList.remove('drag-over-top', 'drag-over-bottom');
            if (!draggingElement || feedItem === draggingElement) return;
            
            const draggedId = parseInt(draggingElement.dataset.id);
            const targetId = parseInt(feedItem.dataset.id);
            
            const rect = feedItem.getBoundingClientRect();
            const midpoint = rect.top + rect.height / 2;
            const insertBefore = e.clientY < midpoint;
            
            const draggedFeedIndex = state.feeds.findIndex(f => f.id === draggedId);
            const draggedFeed = state.feeds[draggedFeedIndex];
            
            // Remove from old position
            state.feeds.splice(draggedFeedIndex, 1);
            
            // Find target position after removal
            let targetFeedIndex = state.feeds.findIndex(f => f.id === targetId);
            if (!insertBefore) {
                targetFeedIndex += 1;
            }
            
            // Insert at new position
            state.feeds.splice(targetFeedIndex, 0, draggedFeed);
            
            // Save new order to localStorage
            const feedIds = state.feeds.map(f => f.id);
            window.localStorage.setItem('KICKRSS_MANUAL_FEED_ORDER', JSON.stringify(feedIds));
            
            // Re-render immediately
            renderFeedsTree();
        });
        
        // Expand automatically if selected
        if (state.selectedFeedId === feed.id) {
            feedItem.classList.add('expanded');
        }
        
        const feedRow = document.createElement('div');
        feedRow.className = `feed-row ${state.selectedFeedId === feed.id && state.selectedCategoryId === null ? 'active' : ''} ${feed.enabled ? '' : 'disabled'}`;
        
        feedRow.innerHTML = `
            <span class="drag-handle" title="按住拖动排序">⋮⋮</span>
            <span class="toggle-icon">▶</span>
            <span class="feed-icon">📰</span>
            <span class="feed-title-text" title="${feed.title}">${feed.title}</span>
            ${feed.unread_count > 0 ? `<span class="unread-badge">${feed.unread_count}</span>` : ''}
        `;
        
        const dragHandle = feedRow.querySelector('.drag-handle');
        
        // Mobile touch support for manual drag-and-drop sorting
        dragHandle.addEventListener('touchstart', (e) => {
            // Stop standard touch scrolling/selection when dragging starts
            e.preventDefault();
            draggingElement = feedItem;
            feedItem.classList.add('dragging');
        }, { passive: false });
        
        dragHandle.addEventListener('touchmove', (e) => {
            e.preventDefault();
            if (!draggingElement) return;
            const touch = e.touches[0];
            const element = document.elementFromPoint(touch.clientX, touch.clientY);
            const targetFeedItem = element ? element.closest('.feed-item') : null;
            
            // Clear hover classes from all items
            document.querySelectorAll('.feed-item').forEach(el => {
                if (el !== targetFeedItem) {
                    el.classList.remove('drag-over-top', 'drag-over-bottom');
                }
            });
            
            if (targetFeedItem && targetFeedItem !== draggingElement) {
                const rect = targetFeedItem.getBoundingClientRect();
                const midpoint = rect.top + rect.height / 2;
                targetFeedItem.classList.remove('drag-over-top', 'drag-over-bottom');
                if (touch.clientY < midpoint) {
                    targetFeedItem.classList.add('drag-over-top');
                } else {
                    targetFeedItem.classList.add('drag-over-bottom');
                }
            }
        }, { passive: false });
        
        dragHandle.addEventListener('touchend', (e) => {
            e.preventDefault();
            if (!draggingElement) return;
            
            const targetFeedItem = document.querySelector('.feed-item.drag-over-top, .feed-item.drag-over-bottom');
            
            feedItem.classList.remove('dragging');
            document.querySelectorAll('.feed-item').forEach(el => {
                el.classList.remove('drag-over-top', 'drag-over-bottom');
            });
            
            if (targetFeedItem && targetFeedItem !== draggingElement) {
                const insertBefore = targetFeedItem.classList.contains('drag-over-top');
                const draggedId = parseInt(draggingElement.dataset.id);
                const targetId = parseInt(targetFeedItem.dataset.id);
                
                const draggedFeedIndex = state.feeds.findIndex(f => f.id === draggedId);
                const draggedFeed = state.feeds[draggedFeedIndex];
                
                state.feeds.splice(draggedFeedIndex, 1);
                
                let targetFeedIndex = state.feeds.findIndex(f => f.id === targetId);
                if (!insertBefore) {
                    targetFeedIndex += 1;
                }
                
                state.feeds.splice(targetFeedIndex, 0, draggedFeed);
                
                window.localStorage.setItem('KICKRSS_MANUAL_FEED_ORDER', JSON.stringify(state.feeds.map(f => f.id)));
                
                draggingElement = null;
                renderFeedsTree();
            } else {
                draggingElement = null;
            }
        }, { passive: false });

        // Click on toggle expands tree
        feedRow.querySelector('.toggle-icon').addEventListener('click', (e) => {
            e.stopPropagation();
            feedItem.classList.toggle('expanded');
            // Lazy load categories if expanded and not loaded
            if (feedItem.classList.contains('expanded')) {
                loadCategoriesForFeed(feed.id, feedItem);
            }
        });
        
        // Click on feed row selects the feed as filter
        feedRow.addEventListener('click', () => {
            selectFeed(feed.id);
            // Also expand categories
            feedItem.classList.add('expanded');
            loadCategoriesForFeed(feed.id, feedItem);
        });
        
        feedItem.appendChild(feedRow);
        
        // Container for subcategories (categories)
        const categoriesContainer = document.createElement('div');
        categoriesContainer.className = 'category-children';
        feedItem.appendChild(categoriesContainer);
        
        elements.feedsList.appendChild(feedItem);
        
        // If already expanded (e.g. selected), load categories right away
        if (feedItem.classList.contains('expanded')) {
            loadCategoriesForFeed(feed.id, feedItem);
        }
    });
}

async function loadCategoriesForFeed(feedId, feedItemNode) {
    const container = feedItemNode.querySelector('.category-children');
    
    // Avoid double loading if already loaded (unless selected)
    if (container.children.length > 0 && container.dataset.loaded === 'true') {
        // Just refresh highlight active
        const rows = container.querySelectorAll('.category-row');
        rows.forEach(row => {
            const catId = parseInt(row.dataset.id);
            if (state.selectedCategoryId === catId) {
                row.classList.add('active');
            } else {
                row.classList.remove('active');
            }
        });
        return;
    }
    
    try {
        const response = await fetch(`/feeds/${feedId}/categories?t=${Date.now()}`);
        const categories = await response.json();
        
        container.innerHTML = '';
        categories.forEach(cat => {
            const catRow = document.createElement('div');
            catRow.className = `category-row ${state.selectedCategoryId === cat.id ? 'active' : ''}`;
            catRow.dataset.id = cat.id;
            
            // Icon according to default
            const icon = cat.is_default ? '📁' : '🏷️';
            
            catRow.innerHTML = `
                <span class="category-icon">${icon}</span>
                <span class="category-name-text">${cat.name}</span>
                ${cat.unread_count > 0 ? `<span class="badge">${cat.unread_count}</span>` : ''}
            `;
            
            catRow.addEventListener('click', (e) => {
                e.stopPropagation();
                selectCategory(feedId, cat.id, cat.name);
            });
            
            container.appendChild(catRow);
        });
        
        container.dataset.loaded = 'true';
    } catch (e) {
        console.error("Failed to load categories:", e);
    }
}

// ----------------------------------------------------
// NAVIGATION ACTIONS
// ----------------------------------------------------
function selectGlobalUnread(isStartup = false) {
    state.activeView = 'unread';
    state.selectedFeedId = null;
    state.selectedCategoryId = null;
    
    document.querySelectorAll('.feed-row').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.category-row').forEach(node => node.classList.remove('active'));
    elements.btnAllUnread.classList.add('active');
    elements.btnStarred.classList.remove('active');
    if (elements.btnNotes) elements.btnNotes.classList.remove('active');
    
    elements.currentCategoryName.textContent = "所有未读";
    loadUnreadEntries();
    
    // Mobile panel transition: only navigate to entries list if not starting up
    if (isStartup !== true) {
        document.body.classList.add('show-entries');
    }
}

function selectStarredView(isStartup = false) {
    state.activeView = 'starred';
    state.selectedFeedId = null;
    state.selectedCategoryId = null;
    
    document.querySelectorAll('.feed-row').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.category-row').forEach(node => node.classList.remove('active'));
    elements.btnAllUnread.classList.remove('active');
    elements.btnStarred.classList.add('active');
    if (elements.btnNotes) elements.btnNotes.classList.remove('active');
    
    elements.currentCategoryName.textContent = "我的收藏";
    loadStarredEntries();
    
    if (isStartup !== true) {
        document.body.classList.add('show-entries');
    }
}

async function loadStarredEntries(appendMode = false) {
    if (!appendMode) {
        state.entriesOffset = 0;
        state.hasMoreEntries = true;
        elements.entriesList.innerHTML = '<div class="loading-placeholder">正在加载收藏文章...</div>';
    }
    try {
        const offset = state.entriesOffset;
        const limit = state.entriesLimit;
        const response = await fetch(`/entries/starred?unread=0&limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        if (data.length < limit) {
            state.hasMoreEntries = false;
        }
        
        if (appendMode) {
            state.entries = [...state.entries, ...data];
        } else {
            state.entries = data;
        }
        state.entriesOffset += data.length;
        refreshEntriesList(appendMode, data);
    } catch (e) {
        console.error("Failed to load starred entries:", e);
        if (!appendMode) {
            elements.entriesList.innerHTML = '<div class="loading-placeholder">加载收藏文章失败</div>';
        }
    }
}

async function selectFeed(feedId) {
    state.activeView = 'feed';
    state.selectedFeedId = feedId;
    state.selectedCategoryId = null;
    
    elements.btnAllUnread.classList.remove('active');
    elements.btnStarred.classList.remove('active');
    if (elements.btnNotes) elements.btnNotes.classList.remove('active');
    
    // Refresh feeds listing highlights
    renderFeedsTree();
    
    const feed = state.feeds.find(f => f.id === feedId);
    elements.currentCategoryName.textContent = feed ? feed.title : "订阅源";
    
    loadFeedEntries(feedId);
    
    // Mobile panel transition
    document.body.classList.add('show-entries');
}

async function loadFeedEntries(feedId, appendMode = false) {
    if (!appendMode) {
        state.entriesOffset = 0;
        state.hasMoreEntries = true;
        elements.entriesList.innerHTML = '<div class="loading-placeholder">正在加载订阅源文章...</div>';
    }
    try {
        const offset = state.entriesOffset;
        const limit = state.entriesLimit;
        const unreadParam = state.filterUnreadOnly ? 1 : 0;
        const response = await fetch(`/feeds/${feedId}/entries?unread=${unreadParam}&limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        if (data.length < limit) {
            state.hasMoreEntries = false;
        }
        
        if (appendMode) {
            state.entries = [...state.entries, ...data];
        } else {
            state.entries = data;
        }
        state.entriesOffset += data.length;
        refreshEntriesList(appendMode, data);
    } catch (e) {
        console.error("Failed to load feed entries:", e);
        if (!appendMode) {
            elements.entriesList.innerHTML = '<div class="loading-placeholder">加载订阅源文章失败</div>';
        }
    }
}

async function loadSearchEntries(query, appendMode = false) {
    if (!appendMode) {
        state.entriesOffset = 0;
        state.hasMoreEntries = true;
        elements.entriesList.innerHTML = '<div class="loading-placeholder">正在搜索文章...</div>';
    }
    try {
        const offset = state.entriesOffset;
        const limit = state.entriesLimit;
        const response = await fetch(`/search?q=${encodeURIComponent(query)}&unread=0&limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        if (data.length < limit) {
            state.hasMoreEntries = false;
        }
        
        if (appendMode) {
            state.entries = [...state.entries, ...data];
        } else {
            state.entries = data;
        }
        state.entriesOffset += data.length;
        refreshEntriesList(appendMode, data);
    } catch (e) {
        console.error("Failed to search entries:", e);
        if (!appendMode) {
            elements.entriesList.innerHTML = '<div class="loading-placeholder">搜索文章失败</div>';
        }
    }
}

function selectCategory(feedId, catId, catName) {
    state.activeView = 'category';
    state.selectedFeedId = feedId;
    state.selectedCategoryId = catId;
    
    elements.btnAllUnread.classList.remove('active');
    elements.btnStarred.classList.remove('active');
    if (elements.btnNotes) elements.btnNotes.classList.remove('active');
    
    // Highlight category in tree
    document.querySelectorAll('.feed-row').forEach(node => node.classList.remove('active'));
    const parentFeedRow = document.querySelector(`.feed-item[data-id="${feedId}"] .feed-row`);
    if (parentFeedRow) parentFeedRow.classList.add('active');
    
    document.querySelectorAll('.category-row').forEach(node => {
        if (parseInt(node.dataset.id) === catId) {
            node.classList.add('active');
        } else {
            node.classList.remove('active');
        }
    });
    
    const feed = state.feeds.find(f => f.id === feedId);
    elements.currentCategoryName.textContent = feed ? `${feed.title} › ${catName}` : catName;
    
    loadCategoryEntries(catId);
    
    // Mobile panel transition
    document.body.classList.add('show-entries');
}

// ----------------------------------------------------
// ARTICLES LOADER & RENDERER
// ----------------------------------------------------
async function loadUnreadEntries(appendMode = false) {
    if (!appendMode) {
        state.entriesOffset = 0;
        state.hasMoreEntries = true;
        elements.entriesList.innerHTML = '<div class="loading-placeholder">正在加载未读文章...</div>';
    }
    try {
        const offset = state.entriesOffset;
        const limit = state.entriesLimit;
        const response = await fetch(`/entries/unread?limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        if (data.length < limit) {
            state.hasMoreEntries = false;
        }
        
        if (appendMode) {
            state.entries = [...state.entries, ...data];
        } else {
            state.entries = data;
        }
        state.entriesOffset += data.length;
        refreshEntriesList(appendMode, data);
    } catch (e) {
        console.error("Failed to load unread entries:", e);
        if (!appendMode) {
            elements.entriesList.innerHTML = '<div class="loading-placeholder">加载未读文章失败</div>';
        }
    }
}

async function loadCategoryEntries(catId, appendMode = false) {
    if (!appendMode) {
        state.entriesOffset = 0;
        state.hasMoreEntries = true;
        elements.entriesList.innerHTML = '<div class="loading-placeholder">正在加载文章列表...</div>';
    }
    try {
        const offset = state.entriesOffset;
        const limit = state.entriesLimit;
        const unreadParam = state.filterUnreadOnly ? 1 : 0;
        const response = await fetch(`/categories/${catId}/entries?unread=${unreadParam}&limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        const feed = state.feeds.find(f => f.id === state.selectedFeedId);
        data.forEach(entry => {
            entry.feed_title = feed ? feed.title : "订阅源";
        });
        
        if (data.length < limit) {
            state.hasMoreEntries = false;
        }
        
        if (appendMode) {
            state.entries = [...state.entries, ...data];
        } else {
            state.entries = data;
        }
        state.entriesOffset += data.length;
        refreshEntriesList(appendMode, data);
    } catch (e) {
        console.error("Failed to load category entries:", e);
        if (!appendMode) {
            elements.entriesList.innerHTML = '<div class="loading-placeholder">加载文章列表失败</div>';
        }
    }
}

function updateEntriesCountLabel() {
    if (!elements.entriesCountLabel) return;
    
    const totalCards = elements.entriesList.querySelectorAll('.entry-card').length;
    const unreadCount = elements.entriesList.querySelectorAll('.entry-card.unread').length;
    
    if (state.activeView === 'notes') {
        elements.entriesCountLabel.textContent = `${totalCards} 篇笔记`;
    } else if (state.activeView === 'starred') {
        elements.entriesCountLabel.textContent = `${totalCards} 篇收藏`;
    } else if (state.activeView === 'search') {
        elements.entriesCountLabel.textContent = `${totalCards} 篇结果`;
    } else {
        elements.entriesCountLabel.textContent = `${unreadCount} 篇未读`;
    }
}

function refreshEntriesList(appendMode = false, newAddedData = []) {
    toggleNotesHeaderControls(state.activeView === 'notes');
    
    if (!appendMode) {
        elements.entriesList.innerHTML = '';
        
        // Sort entries by published_at descending (newest first)
        state.entries.sort((a, b) => {
            const dateA = parseEntryDate(a.published_at);
            const dateB = parseEntryDate(b.published_at);
            return dateB - dateA;
        });
    }
    
    // Client-side filtering if activeView is global unread (in case we loaded all categories and want to toggle)
    let filtered = state.entries;
    if (state.filterUnreadOnly && state.activeView !== 'search' && state.activeView !== 'starred' && state.activeView !== 'notes') {
        filtered = state.entries.filter(e => e.is_read === 0);
    }
    
    // Show/hide mark-all-read button dynamically based on unread presence
    const hasUnread = filtered.some(e => e.is_read === 0);
    if (elements.markAllReadBtn) {
        if (hasUnread) {
            elements.markAllReadBtn.style.display = 'inline-block';
        } else {
            elements.markAllReadBtn.style.display = 'none';
        }
    }
    
    if (filtered.length === 0) {
        elements.entriesList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">☕</span>
                <h3>没有找到文章</h3>
                <p>该分类下目前没有符合筛选条件的文章。</p>
            </div>
        `;
        updateEntriesCountLabel();
        return;
    }
    
    // Decide which array of entries to render as DOM cards
    const entriesToRender = appendMode ? newAddedData : filtered;
    
    entriesToRender.forEach(entry => {
        // Skip read entries if filterUnreadOnly is enabled and not in search/starred/notes view
        if (appendMode && state.filterUnreadOnly && state.activeView !== 'search' && state.activeView !== 'starred' && state.activeView !== 'notes' && entry.is_read === 1) {
            return;
        }
        
        const card = document.createElement('div');
        card.className = `entry-card ${entry.is_read === 0 ? 'unread' : ''} ${state.selectedEntryId === entry.id ? 'active' : ''}`;
        card.dataset.id = entry.id;
        
        // Format date beautifully
        let dateStr = "";
        if (entry.published_at) {
            dateStr = formatRelativeTime(entry.published_at);
        }
        
        // Attention level text
        let attentionLabel = "";
        if (entry.attention) {
            let labelText = "扫读";
            if (entry.attention === 'read') labelText = "精读";
            if (entry.attention === 'glance') labelText = "掠读";
            attentionLabel = `<span class="attention-badge ${entry.attention}">${labelText}</span>`;
        }
        
        // Video indicator
        const isVideo = entry.likely_no_text === 1 ? '<span class="indicator-icon" title="主要包含视频/媒体">🎥</span>' : '';
        
        // Unread indicator light (small blue light)
        const lightClass = entry.is_read === 0 ? 'lit' : '';
        const unreadLight = `<span class="unread-indicator-light ${lightClass}" title="${entry.is_read === 0 ? '标记为已读' : '标记为未读'}"></span>`;
        
        // Star indicator button
        const starIcon = `<span class="star-indicator-btn ${entry.is_starred === 1 ? 'starred' : ''}" title="${entry.is_starred === 1 ? '取消收藏' : '加入收藏'}">★</span>`;
        
        // Checkbox for batch notes export
        const checkboxHtml = state.activeView === 'notes'
            ? `<input type="checkbox" class="note-selector-checkbox" data-id="${entry.id}" ${state.selectedNotesIds && state.selectedNotesIds.has(entry.id) ? 'checked' : ''} style="margin-right: 12px; cursor: pointer; transform: scale(1.2); flex-shrink: 0; align-self: center;" />`
            : '';
        
        card.innerHTML = `
            <div class="entry-card-bg-action">
                <span>标记已读</span>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            </div>
            <div class="entry-card-content" style="${state.activeView === 'notes' ? 'display: flex; flex-direction: row; align-items: center;' : ''}">
                ${checkboxHtml}
                <div style="${state.activeView === 'notes' ? 'flex-grow: 1; min-width: 0;' : ''}">
                    <div class="card-meta">
                        <span class="feed-badge">${entry.feed_title || ""}</span>
                        <span>${dateStr}</span>
                        ${attentionLabel}
                        ${starIcon}
                        ${unreadLight}
                        <div class="card-indicators">${isVideo}</div>
                    </div>
                    <h4 class="card-title">${entry.title}</h4>
                    <div class="card-desc">${entry.author || ""}</div>
                </div>
            </div>
        `;
        
        // Add click event for the note selector checkbox
        const chk = card.querySelector('.note-selector-checkbox');
        if (chk) {
            chk.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = parseInt(chk.dataset.id);
                if (chk.checked) {
                    state.selectedNotesIds.add(id);
                } else {
                    state.selectedNotesIds.delete(id);
                }
                updateBatchNotesButtonsUI();
            });
        }
        
        // Add click event for the star button
        const starBtn = card.querySelector('.star-indicator-btn');
        starBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const isStarred = entry.is_starred === 1;
            const endpoint = isStarred ? `/entries/${entry.id}/unstar` : `/entries/${entry.id}/star`;
            try {
                const response = await fetch(endpoint, { method: 'POST' });
                if (response.ok) {
                      entry.is_starred = isStarred ? 0 : 1;
                      if (entry.is_starred === 1) {
                          starBtn.classList.add('starred');
                          starBtn.title = "取消收藏";
                      } else {
                          starBtn.classList.remove('starred');
                          starBtn.title = "加入收藏";
                          if (state.activeView === 'starred') {
                              card.style.transition = "opacity 0.2s ease, max-height 0.2s ease";
                              card.style.opacity = "0";
                              setTimeout(() => {
                                  state.entries = state.entries.filter(e => e.id !== entry.id);
                                  refreshEntriesList();
                              }, 200);
                          }
                      }
                      if (state.currentOpenEntry && state.currentOpenEntry.id === entry.id) {
                          state.currentOpenEntry.is_starred = entry.is_starred;
                          updateStarButtonUI(entry.is_starred);
                      }
                      loadStarredCount();
                }
            } catch (err) {
                console.error("Failed to toggle star status:", err);
            }
        });
        
        // Add click event for the unread indicator light (small blue light)
        const light = card.querySelector('.unread-indicator-light');
        light.addEventListener('click', async (e) => {
            e.stopPropagation(); // prevent clicking the light from triggering card selection
            const wasRead = entry.is_read === 1;
            const endpoint = wasRead ? `/entries/${entry.id}/unread` : `/entries/${entry.id}/read`;
            try {
                const response = await fetch(endpoint, { method: 'POST' });
                if (response.ok) {
                    entry.is_read = wasRead ? 0 : 1;
                    
                    if (wasRead) {
                        card.classList.add('unread');
                        light.classList.add('lit');
                        light.title = "标记为已读";
                    } else {
                        card.classList.remove('unread');
                        light.classList.remove('lit');
                        light.title = "标记为未读";
                    }
                    
                    if (state.currentOpenEntry && state.currentOpenEntry.id === entry.id) {
                        state.currentOpenEntry.is_read = entry.is_read;
                        updateReadButtonUI(entry.is_read);
                    }
                    
                    loadFeeds();
                }
            } catch (err) {
                console.error("Failed to toggle read status:", err);
            }
        });
        
        card.addEventListener('click', () => {
            if (window.preventClickFlag) return;
            selectEntry(entry.id);
        });
        
        elements.entriesList.appendChild(card);
    });
    
    if (state.activeView === 'notes') {
        updateBatchNotesButtonsUI();
    }
    updateEntriesCountLabel();
}

async function loadMoreEntries() {
    if (state.isLoadingMore || !state.hasMoreEntries) return;
    
    state.isLoadingMore = true;
    
    // Create and append a loading indicator at the bottom of the list
    const loader = document.createElement('div');
    loader.className = 'loading-more-indicator';
    loader.style.padding = '15px';
    loader.style.textAlign = 'center';
    loader.style.color = 'var(--text-muted)';
    loader.style.fontSize = '13px';
    loader.textContent = (state.systemLang || 'zh') === 'en' ? 'Loading more articles...' : '正在加载更多文章...';
    elements.entriesList.appendChild(loader);
    
    try {
        if (state.activeView === 'unread') {
            await loadUnreadEntries(true);
        } else if (state.activeView === 'feed' && state.selectedFeedId) {
            await loadFeedEntries(state.selectedFeedId, true);
        } else if (state.activeView === 'category' && state.selectedCategoryId) {
            await loadCategoryEntries(state.selectedCategoryId, true);
        } else if (state.activeView === 'starred') {
            await loadStarredEntries(true);
        } else if (state.activeView === 'notes') {
            await loadNotesEntries(true);
        } else if (state.activeView === 'search') {
            const query = elements.searchInput.value.trim();
            if (query) {
                await loadSearchEntries(query, true);
            }
        }
    } catch (err) {
        console.error("Failed to load more entries:", err);
    } finally {
        // Remove the loading indicator
        if (loader.parentNode) {
            loader.remove();
        }
        state.isLoadingMore = false;
    }
}

// ----------------------------------------------------
// ARTICLE DETAIL VIEW
// ----------------------------------------------------
async function selectEntry(entryId) {
    submitCurrentEngagement();
    state.selectedEntryId = entryId;
    
    // Highlight card
    document.querySelectorAll('.entry-card').forEach(card => {
        if (parseInt(card.dataset.id) === entryId) {
            card.classList.add('active');
        } else {
            card.classList.remove('active');
        }
    });
    
    const entry = state.entries.find(e => e.id === entryId);
    if (!entry) return;
    
    state.currentOpenEntry = entry;
    
    // Show active layout
    elements.detailEmptyState.classList.add('hidden');
    elements.detailActiveView.classList.remove('hidden');
    
    // Fill basic details
    elements.artTitleLink.textContent = entry.title;
    elements.artTitleLink.href = entry.url;
    elements.artFeedBadge.textContent = entry.feed_title;
    elements.artAuthor.textContent = entry.author ? `作者: ${entry.author}` : "未知作者";
    
    // Format published_at
    if (entry.published_at) {
        const d = parseEntryDate(entry.published_at);
        elements.artDate.textContent = `${formatRelativeTime(d)} (${d.toLocaleString('zh-CN')})`;
    } else {
        elements.artDate.textContent = "";
    }
    
    elements.artOriginalLink.href = entry.url;
    
    // Update read/unread btn label
    updateReadButtonUI(entry.is_read);
    
    // Update star button label
    updateStarButtonUI(entry.is_starred);
    
    // Update attention level buttons
    updateAttentionButtonsUI(entry.attention);
    
    // Mark as read immediately on open
    if (entry.is_read === 0) {
        markEntryAsRead(entryId);
    }
    
    // Load fulltext and AI summary
    loadArticleDetails(entry);
    
    // Slide open chat drawer if in Notes view, otherwise close it
    const detailCol = document.getElementById('detail-column');
    const chatSection = document.getElementById('chat-section');
    if (state.activeView === 'notes') {
        if (detailCol) detailCol.classList.add('chat-open');
        if (chatSection) chatSection.classList.add('open');
    } else {
        if (detailCol) detailCol.classList.remove('chat-open');
        if (chatSection) chatSection.classList.remove('open');
    }
    
    // Mobile navigation transition
    document.body.classList.add('show-detail');
    
    // Initialize engagement tracking for this article
    currentEngagement = {
        entryId: entry.id,
        startTime: Date.now(),
        activeDwellMs: 0,
        lastActiveTime: Date.now(),
        isActive: true,
        maxScrollPct: 0,
        openedOriginal: false,
        idleTimer: setTimeout(() => {
            if (currentEngagement) {
                const idleNow = Date.now();
                if (currentEngagement.isActive) {
                    currentEngagement.activeDwellMs += (idleNow - currentEngagement.lastActiveTime);
                    currentEngagement.isActive = false;
                }
            }
        }, 30000)
    };
}

function updateReadButtonUI(isRead) {
    const lang = state.systemLang || 'zh';
    const btnText = elements.artToggleReadBtn ? elements.artToggleReadBtn.querySelector('.btn-text') : null;
    const textVal = isRead === 1 ? TRANSLATIONS[lang]["mark_unread"] : TRANSLATIONS[lang]["mark_read"];
    if (elements.artToggleReadBtn) {
        if (btnText) btnText.textContent = textVal;
        else elements.artToggleReadBtn.textContent = textVal;
        
        elements.artToggleReadBtn.title = textVal;
        if (isRead === 1) {
            elements.artToggleReadBtn.classList.add('read');
        } else {
            elements.artToggleReadBtn.classList.remove('read');
        }
    }
}

function updateAttentionButtonsUI(level) {
    elements.attnBtnGlance.classList.remove('active');
    elements.attnBtnSkim.classList.remove('active');
    elements.attnBtnRead.classList.remove('active');
    
    if (level === 'glance') elements.attnBtnGlance.classList.add('active');
    else if (level === 'skim') elements.attnBtnSkim.classList.add('active');
    else if (level === 'read') elements.attnBtnRead.classList.add('active');
}

async function setEntryAttentionLevel(level) {
    if (!state.currentOpenEntry) return;
    const entryId = state.currentOpenEntry.id;
    try {
        const response = await fetch(`/entries/${entryId}/attention`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ attention: level })
        });
        if (response.ok) {
            state.currentOpenEntry.attention = level;
            updateAttentionButtonsUI(level);
            
            const entry = state.entries.find(e => e.id === entryId);
            if (entry) {
                entry.attention = level;
            }
            
            const card = document.querySelector(`.entry-card[data-id="${entryId}"]`);
            if (card) {
                let badge = card.querySelector('.attention-badge');
                if (!badge) {
                    const meta = card.querySelector('.card-meta');
                    const light = card.querySelector('.unread-indicator-light');
                    badge = document.createElement('span');
                    badge.className = 'attention-badge';
                    meta.insertBefore(badge, light);
                }
                badge.className = `attention-badge ${level}`;
                let labelText = "扫读";
                if (level === 'read') labelText = "精读";
                if (level === 'glance') labelText = "掠读";
                badge.textContent = labelText;
            }
        }
    } catch (err) {
        console.error("Failed to update attention level:", err);
    }
}

async function markEntryAsRead(entryId) {
    try {
        const response = await fetch(`/entries/${entryId}/read`, { method: 'POST' });
        if (response.ok) {
            // Update local state
            const entry = state.entries.find(e => e.id === entryId);
            if (entry) {
                entry.is_read = 1;
                updateReadButtonUI(1);
                
                // Update card unread class & indicator dot locally
                const card = document.querySelector(`.entry-card[data-id="${entryId}"]`);
                if (card) {
                    card.classList.remove('unread');
                    const light = card.querySelector('.unread-indicator-light');
                    if (light) {
                        light.classList.remove('lit');
                        light.title = (state.systemLang || 'zh') === 'en' ? "Mark as unread" : "标记为未读";
                    }
                }
                
                updateEntriesCountLabel();
                
                // Reload counts
                loadFeeds();
            }
        }
    } catch (e) {
        console.error("Failed to mark entry read:", e);
    }
}

async function markAllAsRead() {
    let response;
    try {
        if (state.activeView === 'category' && state.selectedCategoryId) {
            response = await fetch(`/categories/${state.selectedCategoryId}/read`, { method: 'POST' });
        } else if (state.activeView === 'feed' && state.selectedFeedId) {
            response = await fetch(`/feeds/${state.selectedFeedId}/read`, { method: 'POST' });
        } else {
            // global unread list
            const unreadIds = state.entries.filter(e => e.is_read === 0).map(e => e.id);
            if (unreadIds.length === 0) return;
            response = await fetch('/entries/read', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: unreadIds })
            });
        }
        
        if (response && response.ok) {
            const data = await response.json();
            const markedIds = data.ids || [];
            
            // Update local state
            state.entries.forEach(e => {
                if (markedIds.includes(e.id)) {
                    e.is_read = 1;
                }
            });
            
            if (state.currentOpenEntry && markedIds.includes(state.currentOpenEntry.id)) {
                state.currentOpenEntry.is_read = 1;
                updateReadButtonUI(1);
            }
            
            await loadFeeds();
            refreshEntriesList();
            
            if (markedIds.length > 0) {
                showUndoToast(markedIds);
            }
        }
    } catch (e) {
        console.error("Failed to mark all as read:", e);
    }
}

let undoToastTimeout = null;

function showUndoToast(entryIds) {
    if (!entryIds || entryIds.length === 0) return;
    
    // Remove existing toast if any
    let toast = document.getElementById('undo-read-toast');
    if (toast) {
        toast.remove();
    }
    if (undoToastTimeout) {
        clearTimeout(undoToastTimeout);
    }
    
    // Create toast element
    toast = document.createElement('div');
    toast.id = 'undo-read-toast';
    toast.className = 'undo-toast';
    toast.innerHTML = `
        <div class="undo-toast-progress-container">
            <svg class="undo-toast-progress-svg" viewBox="0 0 24 24">
                <circle class="undo-toast-progress-circle-bg" cx="12" cy="12" r="10"></circle>
                <circle id="undo-toast-circle" class="undo-toast-progress-circle" cx="12" cy="12" r="10"></circle>
            </svg>
        </div>
        <span class="undo-toast-text">已将 ${entryIds.length} 篇文章标记为已读</span>
        <button id="undo-read-btn" class="undo-toast-btn">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"></path><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"></path></svg>
            撤回
        </button>
    `;
    
    document.body.appendChild(toast);
    
    // Trigger reflow to start transition
    toast.offsetHeight;
    toast.classList.add('show');
    
    // Start circle animation (transition takes 5s)
    const circle = document.getElementById('undo-toast-circle');
    circle.offsetHeight;
    circle.style.strokeDashoffset = '63';
    
    // Set up Undo button event
    document.getElementById('undo-read-btn').addEventListener('click', async () => {
        toast.classList.remove('show');
        if (undoToastTimeout) clearTimeout(undoToastTimeout);
        setTimeout(() => toast.remove(), 400);
        await undoMarkAsRead(entryIds);
    });
    
    // Auto hide after 5 seconds
    undoToastTimeout = setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, 5000);
}

async function undoMarkAsRead(entryIds) {
    if (!entryIds || entryIds.length === 0) return;
    
    try {
        const response = await fetch('/entries/unread', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: entryIds })
        });
        
        if (response.ok) {
            // Update local state entries
            entryIds.forEach(id => {
                const entry = state.entries.find(e => e.id === id);
                if (entry) {
                    entry.is_read = 0;
                }
            });
            
            // If current open entry was in the list, set it back to unread
            if (state.currentOpenEntry && entryIds.includes(state.currentOpenEntry.id)) {
                state.currentOpenEntry.is_read = 0;
                updateReadButtonUI(0);
            }
            
            await loadFeeds();
            refreshEntriesList();
        }
    } catch (e) {
        console.error("Failed to undo mark read:", e);
    }
}

async function toggleCurrentEntryReadStatus() {
    if (!state.currentOpenEntry) return;
    
    const entryId = state.currentOpenEntry.id;
    const currentStatus = state.currentOpenEntry.is_read;
    const newStatus = currentStatus === 1 ? 0 : 1;
    
    const endpoint = newStatus === 1 ? `/entries/${entryId}/read` : `/entries/${entryId}/unread`;
    try {
        const response = await fetch(endpoint, { method: 'POST' });
        if (response.ok) {
            state.currentOpenEntry.is_read = newStatus;
            updateReadButtonUI(newStatus);
            
            // Sync with local state entries
            const entry = state.entries.find(e => e.id === entryId);
            if (entry) {
                entry.is_read = newStatus;
            }
            
            // Sync with card UI
            const card = document.querySelector(`.entry-card[data-id="${entryId}"]`);
            if (card) {
                const light = card.querySelector('.unread-indicator-light');
                if (newStatus === 0) {
                    card.classList.add('unread');
                    if (light) {
                        light.classList.add('lit');
                        light.title = "标记为已读";
                    }
                } else {
                    card.classList.remove('unread');
                    if (light) {
                        light.classList.remove('lit');
                        light.title = "标记为未读";
                    }
                }
            }
            
            updateEntriesCountLabel();
            
            loadFeeds();
        }
    } catch (e) {
        console.error("Failed to toggle read status:", e);
    }
}

function updateStarButtonUI(isStarred) {
    const lang = state.systemLang || 'zh';
    const btnText = elements.artToggleStarBtn ? elements.artToggleStarBtn.querySelector('.btn-text') : null;
    const textVal = isStarred === 1 ? TRANSLATIONS[lang]["unstar"] : TRANSLATIONS[lang]["star"];
    if (elements.artToggleStarBtn) {
        if (btnText) btnText.textContent = textVal;
        else elements.artToggleStarBtn.textContent = textVal;
        
        elements.artToggleStarBtn.title = textVal;
        if (isStarred === 1) {
            elements.artToggleStarBtn.classList.add('starred');
        } else {
            elements.artToggleStarBtn.classList.remove('starred');
        }
    }
}

async function toggleCurrentEntryStarStatus() {
    if (!state.currentOpenEntry) return;
    const entry = state.currentOpenEntry;
    
    elements.artToggleStarBtn.disabled = true;
    try {
        const response = await fetch(`/entries/${entry.id}/favorite`, { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            entry.is_starred = data.is_favorited;
            updateStarButtonUI(entry.is_starred);
            
            // Sync with local state entries
            const listEntry = state.entries.find(e => e.id === entry.id);
            if (listEntry) {
                listEntry.is_starred = entry.is_starred;
            }
            
            // Sync with card UI
            const card = document.querySelector(`.entry-card[data-id="${entry.id}"]`);
            if (card) {
                const starBtn = card.querySelector('.star-indicator-btn');
                if (starBtn) {
                    if (entry.is_starred === 1) {
                        starBtn.classList.add('starred');
                        starBtn.title = "取消收藏";
                    } else {
                        starBtn.classList.remove('starred');
                        starBtn.title = "加入收藏";
                         if (state.activeView === 'starred') {
                             card.style.transition = "opacity 0.2s ease, max-height 0.2s ease";
                             card.style.opacity = "0";
                             setTimeout(() => {
                                 state.entries = state.entries.filter(e => e.id !== entry.id);
                                 refreshEntriesList();
                             }, 200);
                         }
                    }
                }
            }
            
            loadStarredCount();
        }
    } catch (err) {
        console.error("Failed to toggle current entry star status:", err);
    } finally {
        elements.artToggleStarBtn.disabled = false;
    }
}

// Expand/Collapse fulltext
function toggleFulltextExpansion() {
    const lang = state.systemLang || 'zh';
    const isHidden = elements.fulltextContentArea.classList.contains('hidden');
    if (isHidden) {
        elements.fulltextContentArea.classList.remove('hidden');
        if (elements.artTranslateBtn) {
            elements.artTranslateBtn.classList.remove('hidden');
        }
        elements.expanderText.textContent = TRANSLATIONS[lang]["collapse_fulltext"];
        elements.expanderIcon.style.transform = "rotate(180deg)";
        
        // Lazy load fulltext content if not loaded
        if (elements.fulltextContentArea.dataset.loaded !== 'true') {
            loadFulltextText(state.currentOpenEntry.id);
        }
    } else {
        elements.fulltextContentArea.classList.add('hidden');
        if (elements.artTranslateBtn) {
            elements.artTranslateBtn.classList.add('hidden');
        }
        elements.expanderText.textContent = TRANSLATIONS[lang]["expand_fulltext"];
        elements.expanderIcon.style.transform = "rotate(0deg)";
    }
}

function applyInlineMarkdown(htmlText) {
    if (!htmlText) return "";
    
    // 1. Replace markdown images: ![alt](url)
    let formatted = htmlText.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, src) => {
        const cleanSrc = src.trim().replace(/^["']|["']$/g, '');
        return `<img src="${cleanSrc}" alt="${escapeHTML(alt)}" class="article-image" loading="lazy" referrerpolicy="no-referrer" />`;
    });
    
    // 2. Replace markdown links: [text](url)
    formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, href) => {
        const cleanHref = href.trim().replace(/^["']|["']$/g, '');
        return `<a href="${cleanHref}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    });
    
    // 3. Replace bold: **text** or __text__
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    
    // 4. Replace italic: *text* or _text_
    formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/_([^_]+)_/g, '<em>$1</em>');

    // 5. Inline code: `code`
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

    return formatted;
}

function renderSingleParagraph(text) {
    if (!text) return "";
    
    // 1. Detect Markdown Headers
    const headerMatch = text.match(/^(#{1,6})\s+(.+)$/);
    if (headerMatch) {
        const level = Math.min(6, headerMatch[1].length + 1); // # -> h2, ## -> h3, ### -> h4, etc.
        const titleText = escapeHTML(headerMatch[2]);
        return `<h${level}>${titleText}</h${level}>`;
    }
    
    // 2. Detect Blockquotes: lines starting with >
    if (text.startsWith('>')) {
        const lines = text.split('\n');
        const quoteContent = lines.map(line => line.replace(/^>\s*/, '')).join('\n');
        const escaped = escapeHTML(quoteContent);
        const formatted = applyInlineMarkdown(escaped).replace(/\n/g, '<br />');
        return `<blockquote>${formatted}</blockquote>`;
    }
    
    // 3. Detect Lists (ul / ol)
    const lines = text.split('\n');
    const isBulletList = lines.every(line => /^\s*([*\-+]\s+)/.test(line));
    const isOrderedList = lines.every(line => /^\s*(\d+\.\s+)/.test(line));
    
    if (isBulletList) {
        const listItems = lines.map(line => {
            const itemText = line.replace(/^\s*([*\-+]\s+)/, '');
            return `<li>${applyInlineMarkdown(escapeHTML(itemText))}</li>`;
        }).join('');
        return `<ul>${listItems}</ul>`;
    }
    
    if (isOrderedList) {
        const listItems = lines.map(line => {
            const itemText = line.replace(/^\s*(\d+\.\s+)/, '');
            return `<li>${applyInlineMarkdown(escapeHTML(itemText))}</li>`;
        }).join('');
        return `<ol>${listItems}</ol>`;
    }
    
    // 4. Normal Paragraph
    let htmlParagraph = escapeHTML(text);
    htmlParagraph = applyInlineMarkdown(htmlParagraph);
    
    // Preserve single newlines with br (if any exist within a paragraph block)
    htmlParagraph = htmlParagraph.replace(/\n/g, '<br />');
    
    return `<p>${htmlParagraph}</p>`;
}

function renderArticleContent(content) {
    if (!content) return "";
    
    // Split into paragraphs and render
    const paragraphs = content.split(/\n\s*\n/);
    return paragraphs.map(p => renderSingleParagraph(p.trim())).filter(x => x).join('\n');
}

async function loadFulltextText(entryId) {
    elements.fulltextContentArea.innerHTML = '<p class="loading-placeholder">正在抓取清洗原文正文...</p>';
    try {
        const response = await fetch(`/entries/${entryId}/fulltext`);
        const data = await response.json();
        
        if (data.content) {
            elements.fulltextContentArea.innerHTML = renderArticleContent(data.content);
            elements.fulltextContentArea.dataset.loaded = 'true';
        } else {
            elements.fulltextContentArea.innerHTML = `<p class="loading-placeholder">无法提取正文。点击上方"访问原文"查看完整页面。</p>`;
        }
    } catch (e) {
        elements.fulltextContentArea.innerHTML = `<p class="loading-placeholder">正文抓取失败</p>`;
    }
}

async function reloadChatHistory(entryId) {
    if (!state.currentOpenEntry || state.currentOpenEntry.id !== entryId) return;
    try {
        const res = await fetch(`/entries/${entryId}/chat`);
        if (!res.ok) throw new Error("Failed to fetch chat history");
        const history = await res.json();
        
        // Check if current open entry has changed during network request
        if (!state.currentOpenEntry || state.currentOpenEntry.id !== entryId) return;
        
        if (history && history.length > 0) {
            if (elements.clearChatBtn) elements.clearChatBtn.style.display = 'inline-block';
            elements.chatHistory.innerHTML = ''; // Clear default prompt
            history.forEach(msg => {
                appendChatBubble(msg.role, msg.content, msg.id, msg.created_at);
            });
        } else {
            if (elements.clearChatBtn) elements.clearChatBtn.style.display = 'none';
            elements.chatHistory.innerHTML = `
                <div class="system-message">
                    您可以针对正文或摘要内容，向 AI 提出任何疑问或进行深度拓展探讨。
                </div>
            `;
        }
        elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
        loadNotesCount();
    } catch (err) {
        console.error("Failed to load chat history:", err);
    }
}

// ----------------------------------------------------
// AI SUMMARY AND SSE STREAMING PARSING
// ----------------------------------------------------
async function loadArticleDetails(entry) {
    const lang = state.systemLang || 'zh';
    
    // Close any active event source immediately to prevent race conditions
    if (window.summaryEventSource) {
        window.summaryEventSource.close();
        window.summaryEventSource = null;
    }
    
    state.currentOpenEntryFulltext = "";
    state.isBilingualMode = false;
    state.isTranslating = false;
    state.translatedContentCache = null;
    
    // Reset translation button text to default
    if (elements.artTranslateBtn) {
        const btnText = elements.artTranslateBtn.querySelector('.btn-text');
        if (btnText) {
            btnText.textContent = TRANSLATIONS[lang]["translate_btn"];
        }
    }
    
    // 1. Reset Clickbait Warning Banner
    elements.clickbaitBanner.classList.add('hidden');
    elements.clickbaitText.textContent = '';
    
    // Reset Summary visibility and metadata
    elements.aiSummaryBlock.classList.remove('hidden');
    elements.summaryMetaInfo.textContent = '';
    elements.summaryMetaInfo.classList.add('hidden');
    
    if (elements.regenerateSummaryBtn) {
        elements.regenerateSummaryBtn.disabled = false;
        elements.regenerateSummaryBtn.classList.remove('hidden');
    }
    
    // 2. Reset Chat History & load previous chat history
    elements.chatHistory.innerHTML = `
        <div class="system-message">
            ${TRANSLATIONS[lang]["ask_ai_first_msg"]}
        </div>
    `;
    reloadChatHistory(entry.id);
    
    // Reset Scroll Position & Back to Top Button
    if (elements.articleScrollView) {
        elements.articleScrollView.scrollTop = 0;
    }
    if (elements.backToTopBtn) {
        elements.backToTopBtn.classList.remove('visible');
    }
    
    // 3. Reset Fulltext Expander Block
    elements.fulltextContentArea.classList.add('hidden');
    elements.fulltextContentArea.innerHTML = '';
    elements.fulltextContentArea.dataset.loaded = 'false';
    elements.expanderText.textContent = TRANSLATIONS[lang]["expand_fulltext"];
    elements.expanderIcon.style.transform = "rotate(0deg)";
    elements.toggleFulltextBtn.style.display = 'inline-flex';
    if (elements.artTranslateBtn) {
        elements.artTranslateBtn.classList.add('hidden');
    }
    
    // 4. Fetch Fulltext in advance to decide summary strategy
    elements.summaryContent.innerHTML = lang === 'en' ? 'Loading & extracting word count...' : '正在加载并提取正文字数...';
    elements.summaryStatusBadge.textContent = lang === 'en' ? 'Loading' : '读取中';
    elements.summaryStatusBadge.className = 'status-indicator loading';
    
    try {
        const response = await fetch(`/entries/${entry.id}/fulltext`);
        const data = await response.json();
        const content = data.content || "";
        const cleanCharCount = data.clean_char_count !== undefined ? data.clean_char_count : content.length;
        const hasSummary = data.has_summary || false;
        
        // Fill fulltext area
        if (content) {
            state.currentOpenEntryFulltext = content;
            elements.fulltextContentArea.innerHTML = renderArticleContent(content);
            elements.fulltextContentArea.dataset.loaded = 'true';
        } else {
            elements.fulltextContentArea.innerHTML = `<p class="loading-placeholder">${lang === 'en' ? 'Could not extract full-text. Click "Visit Original" above to read.' : '无法提取正文。点击上方"访问原文"查看完整页面。'}</p>`;
        }
        
        // Display reading time and character count using clean text length
        const readTime = Math.ceil(cleanCharCount / 500);
        if (cleanCharCount > 0) {
            elements.summaryMetaInfo.textContent = lang === 'en' 
                ? `Full-text: ${cleanCharCount} chars | Est. read time: ${readTime} min` 
                : `全文字数: ${cleanCharCount} 字 | 预计阅读: ${readTime} 分钟`;
            elements.summaryMetaInfo.classList.remove('hidden');
        } else {
            elements.summaryMetaInfo.textContent = '';
            elements.summaryMetaInfo.classList.add('hidden');
        }
        
        // 5. Decide strategy based on clean character count and cache
        if (hasSummary) {
            streamSummary(entry.id);
        } else if (cleanCharCount > 0 && cleanCharCount < 1000) {
            // Short article: Expand fulltext automatically
            elements.fulltextContentArea.classList.remove('hidden');
            if (elements.artTranslateBtn) {
                elements.artTranslateBtn.classList.remove('hidden');
            }
            elements.expanderText.textContent = TRANSLATIONS[lang]["collapse_fulltext"];
            elements.expanderIcon.style.transform = "rotate(180deg)";
            
            elements.summaryStatusBadge.textContent = lang === 'en' ? 'No Summary' : '无需摘要';
            elements.summaryStatusBadge.className = 'status-indicator ready';
            elements.summaryContent.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--text-muted);">
                    <span>${lang === 'en' ? '💡 Short article. Full-text expanded below.' : '💡 本文较短，已自动展开下方全文。'}</span>
                    <button id="trigger-summary-btn" class="btn-compact">✨ ${lang === 'en' ? 'Generate AI Summary' : '生成 AI 摘要'}</button>
                </div>
            `;
            
            const triggerBtn = document.getElementById('trigger-summary-btn');
            if (triggerBtn) {
                triggerBtn.addEventListener('click', () => {
                    streamSummary(entry.id);
                });
            }
        } else if (cleanCharCount === 0) {
            elements.summaryStatusBadge.textContent = lang === 'en' ? 'Empty Text' : '无正文';
            elements.summaryStatusBadge.className = 'status-indicator ready';
            elements.summaryContent.innerHTML = lang === 'en' ? 'This article contains no extractable text, cannot generate summary.' : '此文章不含可清洗正文，无法生成摘要。';
            if (elements.regenerateSummaryBtn) {
                elements.regenerateSummaryBtn.classList.add('hidden');
            }
        } else {
            // Long article (>1000 characters)
            if (state.autoSummary) {
                streamSummary(entry.id);
            } else {
                elements.fulltextContentArea.classList.remove('hidden');
                if (elements.artTranslateBtn) {
                    elements.artTranslateBtn.classList.remove('hidden');
                }
                elements.expanderText.textContent = TRANSLATIONS[lang]["collapse_fulltext"];
                elements.expanderIcon.style.transform = "rotate(180deg)";
                
                elements.summaryStatusBadge.textContent = lang === 'en' ? 'Not Summarized' : '未生成摘要';
                elements.summaryStatusBadge.className = 'status-indicator ready';
                elements.summaryContent.innerHTML = `
                    <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--text-muted);">
                        <span>${lang === 'en' ? '💡 Auto-summary is disabled.' : '💡 已关闭自动摘要设置。'}</span>
                        <button id="trigger-summary-btn" class="btn-compact">✨ ${lang === 'en' ? 'Generate AI Summary' : '生成 AI 摘要'}</button>
                    </div>
                `;
                
                const triggerBtn = document.getElementById('trigger-summary-btn');
                if (triggerBtn) {
                    triggerBtn.addEventListener('click', () => {
                        streamSummary(entry.id);
                    });
                }
            }
        }
        
    } catch (e) {
        console.error("Failed to load article details:", e);
        elements.summaryContent.innerHTML = lang === 'en' ? 'Failed to fetch full-text, cannot decide summary strategy.' : '正文获取失败，无法决定摘要策略。';
        elements.summaryStatusBadge.textContent = lang === 'en' ? 'Failed' : '失败';
        elements.summaryStatusBadge.className = 'status-indicator ready';
    }
}

function streamSummary(entryId, force = false) {
    const lang = state.systemLang || 'zh';
    elements.aiSummaryBlock.classList.remove('hidden');
    
    // Disable regenerate button while loading/streaming
    if (elements.regenerateSummaryBtn) {
        elements.regenerateSummaryBtn.disabled = true;
    }
    
    // Clear clickbait banner on start/restart
    elements.clickbaitBanner.classList.add('hidden');
    elements.clickbaitText.textContent = '';
    
    elements.summaryContent.innerHTML = lang === 'en' ? 'Generating AI Summary...' : '正在加载 AI 智能总结...';
    elements.summaryStatusBadge.textContent = lang === 'en' ? 'Generating...' : '生成中...';
    elements.summaryStatusBadge.className = 'status-indicator loading';
    
    // Close existing event source if open
    if (window.summaryEventSource) {
        window.summaryEventSource.close();
    }
    
    let summaryText = "";
    let clickbaitNote = null;
    
    // Call summary stream endpoint using browser native EventSource
    const url = `/entries/${entryId}/summary?stream=true` + (force ? '&force=true' : '');
    const es = new EventSource(url);
    window.summaryEventSource = es;
    
    es.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.status === 'streaming') {
                if (data.clickbait_note) {
                    clickbaitNote = data.clickbait_note;
                    elements.clickbaitText.textContent = clickbaitNote;
                    elements.clickbaitBanner.classList.remove('hidden');
                }
                if (data.summary) {
                    summaryText += data.summary;
                    // Format summary bullet points in real-time
                    elements.summaryContent.innerHTML = renderSummaryMarkdown(summaryText);
                }
            } else if (data.status === 'done') {
                es.close();
                elements.summaryStatusBadge.textContent = lang === 'en' ? 'Ready' : '就绪';
                elements.summaryStatusBadge.className = 'status-indicator ready';
                if (elements.regenerateSummaryBtn) {
                    elements.regenerateSummaryBtn.disabled = false;
                }
                // Final render
                if (summaryText.trim() === '') {
                    elements.summaryContent.innerHTML = lang === 'en' ? 'AI Summary generation finished.' : '文章摘要生成完毕。';
                }
            } else if (data.status === 'no_text') {
                es.close();
                elements.summaryStatusBadge.textContent = lang === 'en' ? 'Media content' : '媒体内容';
                elements.summaryStatusBadge.className = 'status-indicator ready';
                if (elements.regenerateSummaryBtn) {
                    elements.regenerateSummaryBtn.disabled = false;
                }
                elements.summaryContent.innerHTML = data.summary || (lang === 'en' ? 'This article contains no text, cannot generate summary.' : '此文章不含正文，无法生成摘要。');
            } else if (data.status === 'error') {
                es.close();
                elements.summaryStatusBadge.textContent = lang === 'en' ? 'Failed' : '失败';
                elements.summaryStatusBadge.className = 'status-indicator ready';
                if (elements.regenerateSummaryBtn) {
                    elements.regenerateSummaryBtn.disabled = false;
                }
                elements.summaryContent.innerHTML = (lang === 'en' ? 'AI summary service temporarily unavailable: ' : 'AI 摘要服务暂时不可用：') + (data.detail || (lang === 'en' ? 'API Error' : '接口报错'));
            }
        } catch (e) {
            console.error("Error parsing summary stream data:", e);
        }
    };
    
    es.onerror = (err) => {
        es.close();
        elements.summaryStatusBadge.textContent = lang === 'en' ? 'Ready' : '就绪';
        elements.summaryStatusBadge.className = 'status-indicator ready';
        if (elements.regenerateSummaryBtn) {
            elements.regenerateSummaryBtn.disabled = false;
        }
    };
}

function renderSummaryMarkdown(text) {
    if (!text) return "";
    
    const lines = text.split('\n');
    let html = "";
    let inList = null; // 'ul', 'ol', or null
    
    for (let i = 0; i < lines.length; i++) {
        let line = lines[i].trim();
        if (!line) {
            if (inList) {
                html += `</${inList}>`;
                inList = null;
            }
            continue;
        }
        
        let escapedLine = escapeHTML(line);
        
        // 1. Check for bullet list item: starts with -, *, •, or standard bullet
        const bulletMatch = escapedLine.match(/^([-*•])\s+(.+)$/);
        // 2. Check for ordered list item: starts with 1. (needs space) or 1、 (space optional)
        const orderedMatch = escapedLine.match(/^(\d+\.)\s+(.+)$/) || escapedLine.match(/^(\d+、)\s*(.+)$/);
        
        if (bulletMatch) {
            if (inList !== 'ul') {
                if (inList) {
                    html += `</${inList}>`;
                }
                html += '<ul>';
                inList = 'ul';
            }
            html += `<li>${applyInlineMarkdown(bulletMatch[2].trim())}</li>`;
        } else if (orderedMatch) {
            if (inList !== 'ol') {
                if (inList) {
                    html += `</${inList}>`;
                }
                html += '<ol>';
                inList = 'ol';
            }
            html += `<li>${applyInlineMarkdown(orderedMatch[2].trim())}</li>`;
        } else {
            if (inList) {
                html += `</${inList}>`;
                inList = null;
            }
            html += `<p>${applyInlineMarkdown(escapedLine)}</p>`;
        }
    }
    
    if (inList) {
        html += `</${inList}>`;
    }
    
    return html;
}

// ----------------------------------------------------
// CHAT CONVERSATION AGENT (STREAMING POST RESPONSE)
// ----------------------------------------------------
async function handleChatSubmit(e) {
    e.preventDefault();
    if (!state.currentOpenEntry) return;
    
    const messageText = elements.chatInputField.value.trim();
    if (!messageText) return;
    
    elements.chatInputField.value = '';
    elements.chatInputField.disabled = true;
    elements.chatSendBtn.disabled = true;
    
    // Render user message bubble
    appendChatBubble('user', messageText);
    
    // Render assistant placeholder bubble
    const aiBubble = appendChatBubble('assistant', '正在思考...');
    
    const entryId = state.currentOpenEntry.id;
    
    try {
        // We use fetch with reader stream to POST and receive Server-Sent Events chunks
        const response = await fetch(`/entries/${entryId}/chat?stream=true`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: messageText })
        });
        
        if (!response.ok) throw new Error("HTTP error " + response.status);
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullReplyText = "";
        
        aiBubble.textContent = ""; // clear thinking placeholder
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            // Split lines in buffer
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep partial line in buffer
            
            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.startsWith('data:')) {
                    const dataStr = trimmed.slice(5).trim();
                    try {
                        const data = JSON.parse(dataStr);
                        if (data.status === 'streaming' && data.reply) {
                            fullReplyText += data.reply;
                            aiBubble.innerHTML = formatChatReply(fullReplyText);
                            // Scroll chat history to bottom
                            elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
                        } else if (data.status === 'done') {
                            // Stream complete
                            break;
                        }
                    } catch (parseErr) {
                        // ignore malformed lines
                    }
                }
            }
        }
        
        // Reload chat history to get the saved IDs and assign them to delete buttons
        setTimeout(() => {
            reloadChatHistory(entryId);
        }, 100);
        
    } catch (e) {
        console.error("Chat failure:", e);
        aiBubble.textContent = "发送提问失败，请重试。";
    } finally {
        elements.chatInputField.disabled = false;
        elements.chatSendBtn.disabled = false;
        elements.chatInputField.focus();
    }
}

function appendChatBubble(role, text, id, createdAt) {
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role}`;
    if (id) {
        bubble.dataset.messageId = id;
    }
    
    let timeStr = "";
    if (createdAt) {
        try {
            const date = new Date(createdAt);
            timeStr = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
        } catch (e) {
            timeStr = "";
        }
    }
    if (!timeStr) {
        const now = new Date();
        timeStr = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    
    const deleteBtnHtml = id ? `<button class="delete-msg-btn" title="删除此条消息">删除</button>` : "";
    
    bubble.innerHTML = `
        <div class="bubble-content">${formatChatReply(text)}</div>
        <div class="bubble-meta">
            <span>${timeStr}</span>
            ${deleteBtnHtml}
        </div>
    `;
    
    // Add to history list before input form
    elements.chatHistory.appendChild(bubble);
    elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
    
    // Return the content container so we can update it in real-time
    return bubble.querySelector('.bubble-content');
}

function formatChatReply(text) {
    if (!text) return "";
    let formatted = escapeHTML(text);
    formatted = applyInlineMarkdown(formatted);
    formatted = formatted.replace(/\n/g, '<br>');
    return formatted;
}

// ----------------------------------------------------
// ADD SUBSCRIPTION SOURCE (MODAL FORM)
// ----------------------------------------------------
async function addFeedSubmit() {
    const url = elements.feedUrlInput.value.trim();
    if (!url) return;
    
    elements.submitFeedBtn.disabled = true;
    elements.submitFeedBtn.textContent = "正在解析并播种...";
    
    try {
        const response = await fetch('/feeds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        
        if (response.ok) {
            const feed = await response.json();
            elements.feedUrlInput.value = '';
            hideAllModals();
            
            // Reload feeds list
            await loadFeeds();
            // Select the newly added feed
            selectFeed(feed.id);
        } else {
            const err = await response.json();
            alert("添加订阅失败: " + (err.detail || "服务器错误"));
        }
    } catch (e) {
        alert("添加订阅源出错，请检查网络连接");
    } finally {
        elements.submitFeedBtn.disabled = false;
        elements.submitFeedBtn.textContent = "确定添加";
    }
}

// ----------------------------------------------------
// OPML FILE IMPORT (MODAL FORM)
// ----------------------------------------------------
function handleOpmlFileSelect() {
    const file = elements.opmlFileInput.files[0];
    if (file) {
        elements.fileUploadLabel.textContent = `选择文件: ${file.name}`;
        elements.submitOpmlBtn.disabled = false;
    }
}

async function importOpmlSubmit() {
    const file = elements.opmlFileInput.files[0];
    if (!file) return;
    
    elements.submitOpmlBtn.disabled = true;
    elements.submitOpmlBtn.textContent = "导入并生成中...";
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
        const response = await fetch('/import/opml', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const data = await response.json();
            alert(`成功导入 ${data.added} 个新订阅源！后台正在加载播种分类，稍后可手动刷新查看。`);
            elements.opmlFileInput.value = '';
            elements.fileUploadLabel.textContent = "点击或拖拽 OPML 文件到这里";
            hideAllModals();
            loadFeeds();
        } else {
            alert("OPML 导入失败");
        }
    } catch (e) {
        alert("导入文件时发生错误");
    } finally {
        elements.submitOpmlBtn.disabled = false;
        elements.submitOpmlBtn.textContent = "开始导入";
    }
}

// ----------------------------------------------------
// GENERAL SYSTEM REFRESH ACTIONS
// ----------------------------------------------------
async function forceRefresh() {
    if (state.isRefreshing) return;
    
    state.isRefreshing = true;
    elements.refreshIcon.classList.add('spinning');
    elements.refreshAllBtn.disabled = true;
    
    try {
        const response = await fetch('/refresh', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            console.log(`Forced refresh complete: fetched ${data.fetched} feeds, found ${data.new_entries} new entries.`);
            
            // Reload sidebar and entry list
            await loadFeeds();
            await refreshCurrentListView();
        }
    } catch (e) {
        console.error("Refresh failed:", e);
    } finally {
        state.isRefreshing = false;
        elements.refreshIcon.classList.remove('spinning');
        elements.refreshAllBtn.disabled = false;
    }
}

async function simpleRefresh() {
    if (state.isRefreshing) return;
    
    state.isRefreshing = true;
    try {
        await Promise.all([loadFeeds(), refreshCurrentListView()]);
    } catch (e) {
        console.error("Simple refresh failed:", e);
    } finally {
        state.isRefreshing = false;
    }
}

// ----------------------------------------------------
// UI HELPERS & MODALS
// ----------------------------------------------------
function showModal(modalNode) {
    modalNode.classList.remove('hidden');
}

function hideAllModals() {
    elements.addFeedModal.classList.add('hidden');
    elements.opmlModal.classList.add('hidden');
    elements.manageFeedsModal.classList.add('hidden');
    if (elements.profileModal) {
        elements.profileModal.classList.add('hidden');
    }
    elements.feedUrlInput.value = '';
    elements.opmlFileInput.value = '';
    elements.submitOpmlBtn.disabled = true;
    elements.fileUploadLabel.textContent = "点击或拖拽 OPML 文件到这里";
}

function escapeHTML(str) {
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function parseEntryDate(dateInput) {
    if (!dateInput) return new Date(0);
    if (dateInput instanceof Date) return dateInput;
    let dateStr = dateInput;
    if (typeof dateStr === 'string' && dateStr.includes('T') && !dateStr.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(dateStr)) {
        dateStr += 'Z';
    }
    return new Date(dateStr);
}

function formatRelativeTime(dateInput) {
    if (!dateInput) return "";
    const date = parseEntryDate(dateInput);
    if (isNaN(date.getTime())) return dateInput;
    
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);
    const diffMinutes = Math.floor(diffSeconds / 60);
    const diffHours = Math.floor(diffMinutes / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffSeconds < 0) {
        return "刚刚";
    }
    if (diffSeconds < 60) {
        return "刚刚";
    } else if (diffMinutes < 60) {
        return `${diffMinutes} 分钟前`;
    } else if (diffHours < 24) {
        return `${diffHours} 小时前`;
    } else if (diffDays < 30) {
        return `${diffDays} 天前`;
    } else {
        return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + " " + 
               date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
}

// ----------------------------------------------------
// RESIZABLE COLUMNS (DESKTOP) & MOBILE TABS
// ----------------------------------------------------
function initResizers() {
    const resizerLeft = document.getElementById('resizer-left');
    const resizerRight = document.getElementById('resizer-right');
    const feedsCol = document.getElementById('feeds-column');
    const entriesCol = document.getElementById('entries-column');
    
    if (resizerLeft && feedsCol) {
        resizerLeft.addEventListener('mousedown', (e) => {
            e.preventDefault();
            document.body.classList.add('resizing');
            resizerLeft.classList.add('dragging');
            
            const startX = e.clientX;
            const startWidth = feedsCol.getBoundingClientRect().width;
            
            function onMouseMove(e) {
                const newWidth = Math.max(180, Math.min(500, startWidth + (e.clientX - startX)));
                document.documentElement.style.setProperty('--sidebar-width', `${newWidth}px`);
            }
            
            function onMouseUp() {
                document.body.classList.remove('resizing');
                resizerLeft.classList.remove('dragging');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                localStorage.setItem('sidebar-width', `${feedsCol.getBoundingClientRect().width}px`);
            }
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }
    
    if (resizerRight && entriesCol) {
        resizerRight.addEventListener('mousedown', (e) => {
            e.preventDefault();
            document.body.classList.add('resizing');
            resizerRight.classList.add('dragging');
            
            const startX = e.clientX;
            const startWidth = entriesCol.getBoundingClientRect().width;
            
            function onMouseMove(e) {
                const newWidth = Math.max(250, Math.min(800, startWidth + (e.clientX - startX)));
                document.documentElement.style.setProperty('--list-width', `${newWidth}px`);
            }
            
            function onMouseUp() {
                document.body.classList.remove('resizing');
                resizerRight.classList.remove('dragging');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                localStorage.setItem('list-width', `${entriesCol.getBoundingClientRect().width}px`);
            }
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }
    
    // Load saved widths
    const savedSidebar = localStorage.getItem('sidebar-width');
    if (savedSidebar) {
        document.documentElement.style.setProperty('--sidebar-width', savedSidebar);
    }
    const savedList = localStorage.getItem('list-width');
    if (savedList) {
        document.documentElement.style.setProperty('--list-width', savedList);
    }
}

function initChatDrawer() {
    const toggleBtn = document.getElementById('toggle-chat-drawer-btn');
    const closeBtn = document.getElementById('close-chat-drawer-btn');
    const chatSection = document.getElementById('chat-section');
    const detailCol = document.getElementById('detail-column');
    const articleScrollView = document.querySelector('.article-scroll-view');
    
    if (toggleBtn && chatSection && detailCol) {
        toggleBtn.addEventListener('click', async (e) => {
            if (window.preventChatBtnClick) return;
            e.stopPropagation();
            chatSection.classList.add('open');
            detailCol.classList.add('chat-open');
        });
    }
    
    if (closeBtn && chatSection && detailCol) {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            chatSection.classList.remove('open');
            detailCol.classList.remove('chat-open');
        });
    }
    
    // Close drawer when clicking outside (on the article content area)
    if (articleScrollView && chatSection && detailCol) {
        articleScrollView.addEventListener('click', () => {
            if (chatSection.classList.contains('open')) {
                chatSection.classList.remove('open');
                detailCol.classList.remove('chat-open');
            }
        });
    }
    initDraggableAiButton();
}


async function loadAndRenderManageFeeds() {
    elements.manageFeedsList.innerHTML = '<div class="loading-placeholder">正在加载订阅源列表...</div>';
    try {
        const response = await fetch('/feeds');
        const feeds = await response.json();
        
        elements.manageFeedsList.innerHTML = '';
        if (feeds.length === 0) {
            elements.manageFeedsList.innerHTML = '<div class="loading-placeholder"><p>暂无订阅源</p></div>';
            return;
        }
        
        feeds.forEach(feed => {
            const item = document.createElement('div');
            item.className = `manage-item ${feed.enabled ? '' : 'disabled'}`;
            item.dataset.id = feed.id;
            
            item.innerHTML = `
                <input type="text" class="manage-item-title-input" value="${escapeHTML(feed.title)}" title="${escapeHTML(feed.url)}" placeholder="订阅源名称">
                <div class="manage-item-actions">
                    <label class="feed-switch" title="${feed.enabled ? '已启用抓取' : '已禁用抓取'}">
                        <input type="checkbox" class="feed-enabled-toggle" ${feed.enabled ? 'checked' : ''}>
                        <span class="feed-slider enabled-slider"></span>
                    </label>
                    <label class="feed-switch" title="${feed.need_classification !== 0 ? 'AI 智能分类：开启' : 'AI 智能分类：关闭'}">
                        <input type="checkbox" class="feed-classify-toggle" ${feed.need_classification !== 0 ? 'checked' : ''}>
                        <span class="feed-slider classify-slider"></span>
                    </label>
                    <button class="reset-feed-categories-btn" title="重置该订阅源的分类抽屉">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                        </svg>
                    </button>
                    <button class="delete-feed-btn" title="删除该订阅源 (双击确认)" data-clicks="0">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                    </button>
                </div>
            `;
            
            const titleInput = item.querySelector('.manage-item-title-input');
            const enabledToggle = item.querySelector('.feed-enabled-toggle');
            const classifyToggle = item.querySelector('.feed-classify-toggle');
            const resetBtn = item.querySelector('.reset-feed-categories-btn');
            const deleteBtn = item.querySelector('.delete-feed-btn');
            
            const updateResetBtnState = () => {
                if (classifyToggle.checked) {
                    resetBtn.disabled = false;
                    resetBtn.style.opacity = '1';
                    resetBtn.style.pointerEvents = 'auto';
                } else {
                    resetBtn.disabled = true;
                    resetBtn.style.opacity = '0.3';
                    resetBtn.style.pointerEvents = 'none';
                }
            };
            
            // Initialize reset button state
            updateResetBtnState();
            
            classifyToggle.addEventListener('change', async (e) => {
                const needClassify = e.target.checked;
                updateResetBtnState();
                try {
                    const res = await fetch(`/feeds/${feed.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ need_classification: needClassify })
                    });
                    if (res.ok) {
                        feed.need_classification = needClassify ? 1 : 0;
                        classifyToggle.parentElement.title = needClassify ? 'AI 智能分类：开启' : 'AI 智能分类：关闭';
                        await loadFeeds();
                        if (state.selectedFeedId === feed.id) {
                            selectFeed(feed.id);
                        }
                        
                        // If enabled, offer immediate classification
                        if (needClassify) {
                            if (confirm(`已开启订阅源「${feed.title}」的 AI 分类！\n是否要立刻为已有文章运行一次 AI 抽屉生成和归类整理？`)) {
                                // Execute reset categories synchronously 
                                resetBtn.disabled = true;
                                const originalSvg = resetBtn.innerHTML;
                                resetBtn.innerHTML = `<span style="font-size:10px; color:var(--accent-color);">...</span>`;
                                try {
                                    const resetRes = await fetch(`/feeds/${feed.id}/reset-categories`, { method: 'POST' });
                                    if (resetRes.ok) {
                                        alert("分类抽屉生成已完成！文章正在后台自动进行归类分桶，分类抽屉将在几秒内填充。");
                                        hideAllModals();
                                        await loadFeeds();
                                        selectGlobalUnread();
                                    } else {
                                        alert("自动生成分类失败，您可以稍后手动点击重置按钮。");
                                    }
                                } catch (resetErr) {
                                    console.error(resetErr);
                                } finally {
                                    resetBtn.disabled = false;
                                    resetBtn.innerHTML = originalSvg;
                                }
                            }
                        }
                    } else {
                        classifyToggle.checked = !needClassify;
                        updateResetBtnState();
                        alert('更新分类设置失败');
                    }
                } catch (err) {
                    classifyToggle.checked = !needClassify;
                    updateResetBtnState();
                    console.error(err);
                    alert('网络连接错误');
                }
            });
            
            resetBtn.addEventListener('click', async () => {
                if (!confirm(`确定要重置订阅源「${feed.title}」的分类抽屉吗？\n此操作将删除该订阅源下所有AI生成的自定义抽屉，将文章归入'未归类'，并利用 AI 重新生成分类。`)) {
                    return;
                }
                
                resetBtn.disabled = true;
                const originalSvg = resetBtn.innerHTML;
                resetBtn.innerHTML = `<span style="font-size:10px; color:var(--accent-color);">...</span>`;
                
                try {
                    const res = await fetch(`/feeds/${feed.id}/reset-categories`, {
                        method: 'POST'
                    });
                    if (res.ok) {
                        alert("分类抽屉重置与种子生成已完成！文章正在后台自动进行归类分桶，分类抽屉将在几秒内填充。");
                        hideAllModals();
                        await loadFeeds();
                        selectGlobalUnread();
                    } else {
                        const errData = await res.json();
                        alert('重置分类失败: ' + (errData.detail || '服务器错误'));
                    }
                } catch (e) {
                    console.error(e);
                    alert('网络连接错误，重置分类失败');
                } finally {
                    resetBtn.disabled = false;
                    resetBtn.innerHTML = originalSvg;
                }
            });
            
            let oldTitle = feed.title;
            const handleRename = async () => {
                const newTitle = titleInput.value.trim();
                if (newTitle && newTitle !== oldTitle) {
                    try {
                        const res = await fetch(`/feeds/${feed.id}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ title: newTitle })
                        });
                        if (res.ok) {
                            oldTitle = newTitle;
                            loadFeeds();
                        } else {
                            titleInput.value = oldTitle;
                            alert('重命名失败');
                        }
                    } catch (e) {
                        titleInput.value = oldTitle;
                        console.error(e);
                    }
                } else if (!newTitle) {
                    titleInput.value = oldTitle;
                }
            };
            titleInput.addEventListener('change', handleRename);
            titleInput.addEventListener('blur', handleRename);
            titleInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    titleInput.blur();
                }
            });
            
            enabledToggle.addEventListener('change', async () => {
                const enabled = enabledToggle.checked;
                try {
                    const res = await fetch(`/feeds/${feed.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: enabled })
                    });
                    if (res.ok) {
                        item.classList.toggle('disabled', !enabled);
                        enabledToggle.parentElement.title = enabled ? '已启用（抓取中）' : '已禁用（不抓取）';
                        loadFeeds();
                    } else {
                        enabledToggle.checked = !enabled;
                        alert('修改启用状态失败');
                    }
                } catch (e) {
                    enabledToggle.checked = !enabled;
                    console.error(e);
                }
            });
            
            deleteBtn.addEventListener('click', async () => {
                const clicks = parseInt(deleteBtn.dataset.clicks);
                if (clicks === 0) {
                    deleteBtn.dataset.clicks = "1";
                    deleteBtn.style.color = "#ef4444";
                    deleteBtn.style.background = "rgba(239, 68, 68, 0.15)";
                    deleteBtn.title = "再次点击确认删除！";
                    setTimeout(() => {
                        deleteBtn.dataset.clicks = "0";
                        deleteBtn.style.color = "";
                        deleteBtn.style.background = "";
                        deleteBtn.title = "删除该订阅源 (双击确认)";
                    }, 3000);
                } else {
                    try {
                        const res = await fetch(`/feeds/${feed.id}`, {
                            method: 'DELETE'
                        });
                        if (res.ok) {
                            alert('订阅源删除成功');
                            item.remove();
                            if (state.selectedFeedId === feed.id) {
                                state.selectedFeedId = null;
                                state.selectedCategoryId = null;
                                // If the active selectAllUnread function is available, call it
                                if (typeof selectGlobalUnread === 'function') {
                                    selectGlobalUnread();
                                }
                            }
                            loadFeeds();
                        } else {
                            alert('删除失败');
                        }
                    } catch (e) {
                        console.error(e);
                        alert('删除出错');
                    }
                }
            });
            
            elements.manageFeedsList.appendChild(item);
        });
    } catch (e) {
        console.error(e);
        elements.manageFeedsList.innerHTML = '<div class="loading-placeholder"><p style="color:#ef4444;">加载失败，请重试</p></div>';
    }
}

async function exportOpml() {
    try {
        const response = await fetch('/export/opml');
        if (!response.ok) throw new Error('Failed to export OPML');
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'subscriptions.opml';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (err) {
        console.error('Export failed:', err);
        alert('导出失败，请重试');
    }
}

async function exportReadingNotes() {
    if (!state.currentOpenEntry) {
        alert('当前没有打开的文章');
        return;
    }
    
    const entry = state.currentOpenEntry;
    const entryId = entry.id;
    
    try {
        // Fetch chat history
        const res = await fetch(`/entries/${entryId}/chat`);
        if (!res.ok) throw new Error("Failed to fetch chat history");
        const history = await res.json();
        
        // Fetch summary if any
        let summaryContent = '';
        let clickbaitNote = '';
        
        try {
            const sumRes = await fetch(`/entries/${entryId}/summary?stream=false`);
            if (sumRes.ok) {
                const sumData = await sumRes.json();
                summaryContent = sumData.summary || '';
                clickbaitNote = sumData.clickbait_note || '';
            }
        } catch (sumErr) {
            console.warn("Failed to fetch summary for export:", sumErr);
        }
        
        // Format as Markdown
        let md = `# 阅读笔记: ${entry.title}\n\n`;
        md += `- **原文链接**: ${entry.url || '无'}\n`;
        md += `- **导出时间**: ${new Date().toLocaleString()}\n\n`;
        
        if (summaryContent && summaryContent.trim() !== '') {
            md += `## ✨ AI 智能总结\n\n${summaryContent}\n\n`;
        }
        
        if (clickbaitNote && clickbaitNote.trim() !== '') {
            md += `> [!WARNING] 【标题警告】\n> ${clickbaitNote}\n\n`;
        }
        
        if (history && history.length > 0) {
            md += `## 💬 AI 追问对话记录\n\n`;
            history.forEach(msg => {
                const roleName = msg.role === 'user' ? '👤 我' : '🤖 AI';
                md += `### ${roleName}\n${msg.content}\n\n`;
            });
        } else {
            md += `*(暂无 AI 对话记录)*\n`;
        }
        
        // Create Blob and trigger download
        const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const safeTitle = entry.title.replace(/[\\/:*?"<>|]/g, '_').substring(0, 50);
        a.download = `阅读笔记_${safeTitle}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        
    } catch (err) {
        console.error("Failed to export reading notes:", err);
        alert('导出阅读笔记失败，请重试');
    }
}

async function loadNotesCount() {
    try {
        const response = await fetch('/entries/notes/count?t=' + Date.now());
        if (response.ok) {
            const data = await response.json();
            if (elements.notesCount) elements.notesCount.textContent = data.total_count;
        }
    } catch (e) {
        console.error("Failed to load notes count:", e);
    }
}

function toggleNotesHeaderControls(isNotesView) {
    const toggleContainer = document.querySelector('#entries-column .toggle-container');
    if (isNotesView) {
        if (elements.btnSelectAllNotes) elements.btnSelectAllNotes.style.display = 'inline-block';
        if (elements.btnBatchExportNotes) elements.btnBatchExportNotes.style.display = 'inline-block';
        if (elements.markAllReadBtn) elements.markAllReadBtn.style.display = 'none';
        if (toggleContainer) toggleContainer.style.display = 'none';
    } else {
        if (elements.btnSelectAllNotes) elements.btnSelectAllNotes.style.display = 'none';
        if (elements.btnBatchExportNotes) elements.btnBatchExportNotes.style.display = 'none';
        if (toggleContainer) toggleContainer.style.display = 'flex';
    }
}

function toggleSelectAllNotes() {
    const checkboxes = elements.entriesList.querySelectorAll('.note-selector-checkbox');
    if (checkboxes.length === 0) return;
    
    let allChecked = true;
    checkboxes.forEach(chk => {
        if (!chk.checked) allChecked = false;
    });
    
    checkboxes.forEach(chk => {
        const id = parseInt(chk.dataset.id);
        chk.checked = !allChecked;
        if (chk.checked) {
            state.selectedNotesIds.add(id);
        } else {
            state.selectedNotesIds.delete(id);
        }
    });
    
    updateBatchNotesButtonsUI();
}

async function exportSelectedNotes() {
    if (!state.selectedNotesIds || state.selectedNotesIds.size === 0) {
        alert('请先勾选需要导出的笔记文章');
        return;
    }
    
    const ids = Array.from(state.selectedNotesIds);
    const originalText = elements.btnBatchExportNotes.textContent;
    elements.btnBatchExportNotes.textContent = '⏳ 正在导出...';
    elements.btnBatchExportNotes.disabled = true;
    
    try {
        let compiledMd = `# KickRSS AI 智能阅读笔记合集\n\n`;
        compiledMd += `- **导出数量**: ${ids.length} 篇\n`;
        compiledMd += `- **导出时间**: ${new Date().toLocaleString()}\n\n`;
        compiledMd += `\n---\n\n`;
        
        const fetchPromises = ids.map(async (id) => {
            const entry = state.entries.find(e => e.id === id) || { id, title: `文章 #${id}` };
            
            let chatHistory = [];
            let summaryContent = '';
            let clickbaitNote = '';
            
            try {
                const chatRes = await fetch(`/entries/${id}/chat`);
                if (chatRes.ok) {
                    chatHistory = await chatRes.json();
                }
            } catch (err) {
                console.error(`Failed to fetch chat history for entry ${id}:`, err);
            }
            
            try {
                const sumRes = await fetch(`/entries/${id}/summary?stream=false&cache_only=true`);
                if (sumRes.ok) {
                    const sumData = await sumRes.json();
                    summaryContent = sumData.summary || '';
                    clickbaitNote = sumData.clickbait_note || '';
                }
            } catch (err) {
                console.error(`Failed to fetch summary for entry ${id}:`, err);
            }
            
            return {
                entry,
                chatHistory,
                summaryContent,
                clickbaitNote
            };
        });
        
        const results = await Promise.all(fetchPromises);
        
        results.forEach(({ entry, chatHistory, summaryContent, clickbaitNote }) => {
            compiledMd += `## 📝 ${entry.title}\n\n`;
            compiledMd += `- **原文链接**: ${entry.url || '无'}\n`;
            if (entry.feed_title) {
                compiledMd += `- **订阅源**: ${entry.feed_title}\n`;
            }
            compiledMd += '\n';
            
            if (summaryContent && summaryContent.trim() !== '') {
                compiledMd += `### ✨ AI 智能总结\n\n${summaryContent}\n\n`;
            }
            
            if (clickbaitNote && clickbaitNote.trim() !== '') {
                compiledMd += `> [!WARNING] 【标题警告】\n> ${clickbaitNote}\n\n`;
            }
            
            if (chatHistory && chatHistory.length > 0) {
                compiledMd += `### 💬 AI 追问对话记录\n\n`;
                chatHistory.forEach(msg => {
                    const roleName = msg.role === 'user' ? '👤 我' : '🤖 AI';
                    compiledMd += `#### ${roleName}\n${msg.content}\n\n`;
                });
            } else {
                compiledMd += `*(暂无 AI 对话记录)*\n\n`;
            }
            
            compiledMd += `\n---\n\n`;
        });
        
        const blob = new Blob([compiledMd], { type: 'text/markdown;charset=utf-8' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        a.download = `KickRSS_AI笔记合集_${dateStr}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        
    } catch (err) {
        console.error("Failed to batch export notes:", err);
        alert('批量导出笔记失败，请重试');
    } finally {
        elements.btnBatchExportNotes.textContent = originalText;
        elements.btnBatchExportNotes.disabled = false;
    }
}

function updateBatchNotesButtonsUI() {
    if (!state.selectedNotesIds) return;
    
    const totalSelected = state.selectedNotesIds.size;
    if (elements.btnBatchExportNotes) {
        if (totalSelected > 0) {
            elements.btnBatchExportNotes.textContent = `📥 批量导出 (${totalSelected})`;
            elements.btnBatchExportNotes.style.opacity = '1';
            elements.btnBatchExportNotes.style.pointerEvents = 'auto';
        } else {
            elements.btnBatchExportNotes.textContent = `📥 批量导出`;
            elements.btnBatchExportNotes.style.opacity = '0.5';
            elements.btnBatchExportNotes.style.pointerEvents = 'none';
        }
    }
    
    if (elements.btnSelectAllNotes) {
        const checkboxes = elements.entriesList.querySelectorAll('.note-selector-checkbox');
        let allChecked = checkboxes.length > 0;
        checkboxes.forEach(chk => {
            if (!chk.checked) allChecked = false;
        });
        
        if (checkboxes.length > 0 && allChecked) {
            elements.btnSelectAllNotes.textContent = '取消全选';
        } else {
            elements.btnSelectAllNotes.textContent = '全选';
        }
    }
}

function selectNotesView(isStartup = false) {
    state.activeView = 'notes';
    state.selectedFeedId = null;
    state.selectedCategoryId = null;
    state.selectedNotesIds = new Set();
    
    document.querySelectorAll('.feed-row').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.category-row').forEach(node => node.classList.remove('active'));
    elements.btnAllUnread.classList.remove('active');
    elements.btnStarred.classList.remove('active');
    if (elements.btnNotes) elements.btnNotes.classList.add('active');
    
    elements.currentCategoryName.textContent = "我的笔记";
    loadNotesEntries();
    updateBatchNotesButtonsUI();
    
    if (isStartup !== true) {
        document.body.classList.add('show-entries');
    }
}

async function loadNotesEntries(appendMode = false) {
    if (!appendMode) {
        state.entriesOffset = 0;
        state.hasMoreEntries = true;
        elements.entriesList.innerHTML = '<div class="loading-placeholder">正在加载笔记文章...</div>';
    }
    try {
        const offset = state.entriesOffset;
        const limit = state.entriesLimit;
        const response = await fetch(`/entries/notes?limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        if (data.length < limit) {
            state.hasMoreEntries = false;
        }
        
        if (appendMode) {
            state.entries = [...state.entries, ...data];
        } else {
            state.entries = data;
        }
        state.entriesOffset += data.length;
        refreshEntriesList(appendMode, data);
    } catch (e) {
        console.error("Failed to load notes entries:", e);
        if (!appendMode) {
            elements.entriesList.innerHTML = '<div class="loading-placeholder">加载笔记文章失败</div>';
        }
    }
}

function switchManageModalTab(tab) {
    if (tab === 'feeds') {
        elements.tabBtnFeeds.classList.add('active');
        elements.tabBtnSettings.classList.remove('active');
        
        elements.tabContentFeeds.classList.remove('hidden');
        elements.tabContentSettings.classList.add('hidden');
        
        elements.settingsSaveBtn.classList.add('hidden');
    } else {
        elements.tabBtnFeeds.classList.remove('active');
        elements.tabBtnSettings.classList.add('active');
        
        elements.tabContentFeeds.classList.add('hidden');
        elements.tabContentSettings.classList.remove('hidden');
        
        elements.settingsSaveBtn.classList.remove('hidden');
    }
}

async function loadAndRenderSystemSettings() {
    try {
        const response = await fetch('/settings');
        const settingsData = await response.json();
        
        // Load token stats
        try {
            const tokenResponse = await fetch('/settings/token-stats');
            if (tokenResponse.ok) {
                const tokenData = await tokenResponse.json();
                const formatNum = (num) => Number(num || 0).toLocaleString();
                document.getElementById('token-prompt-count').textContent = formatNum(tokenData.prompt_tokens);
                document.getElementById('token-completion-count').textContent = formatNum(tokenData.completion_tokens);
                document.getElementById('token-total-count').textContent = formatNum(tokenData.total_tokens);
            }
        } catch (tokenErr) {
            console.error("Failed to load token stats:", tokenErr);
        }
        
        if (elements.settingApiBase) elements.settingApiBase.value = localStorage.getItem('KICKRSS_API_BASE') || '';
        if (elements.settingFetchInterval) elements.settingFetchInterval.value = settingsData.fetch_interval_minutes;
        if (elements.settingMinTextChars) elements.settingMinTextChars.value = settingsData.min_text_chars;
        if (elements.settingPromoteThreshold) elements.settingPromoteThreshold.value = settingsData.promote_threshold;
        
        if (elements.settingAiUrl) elements.settingAiUrl.value = settingsData.ai_base_url;
        if (elements.settingAiKey) elements.settingAiKey.value = settingsData.ai_api_key;
        if (elements.settingAiModel) elements.settingAiModel.value = settingsData.ai_model;
        
        if (elements.settingAiPregenerate) elements.settingAiPregenerate.checked = settingsData.ai_pregenerate;
        if (elements.settingAiStream) elements.settingAiStream.checked = settingsData.ai_stream;
        if (elements.settingAiAutoSummary) elements.settingAiAutoSummary.checked = settingsData.ai_auto_summary !== false;
        
        if (elements.settingAiSummaryLang) elements.settingAiSummaryLang.value = settingsData.ai_summary_lang || 'auto';
        if (elements.settingSystemLang) elements.settingSystemLang.value = settingsData.system_lang || 'zh';
        
        if (elements.settingChatUrl) elements.settingChatUrl.value = settingsData.chat_base_url;
        if (elements.settingChatKey) elements.settingChatKey.value = settingsData.chat_api_key || '';
        if (elements.settingChatModel) elements.settingChatModel.value = settingsData.chat_model;
        if (elements.settingChatTokens) elements.settingChatTokens.value = settingsData.chat_max_tokens || '';
        if (elements.settingInterestProfileEnabled) {
            elements.settingInterestProfileEnabled.checked = settingsData.interest_profile_enabled === true;
        }
    } catch (e) {
        console.error("Failed to load settings:", e);
        const lang = state.systemLang || 'zh';
        alert((TRANSLATIONS[lang] && TRANSLATIONS[lang]["load_failed"]) || "获取系统设置参数失败！");
    }
}

async function saveSystemSettings(e) {
    e.preventDefault();
    
    if (elements.systemSettingsForm && !elements.systemSettingsForm.reportValidity()) {
        return;
    }
    
    if (elements.settingApiBase) {
        const apiBase = elements.settingApiBase.value.trim();
        if (apiBase) {
            const cleanApiBase = apiBase.replace(/\/+$/, '');
            localStorage.setItem('KICKRSS_API_BASE', cleanApiBase);
        } else {
            localStorage.removeItem('KICKRSS_API_BASE');
        }
    }
    
    const payload = {
        fetch_interval_minutes: elements.settingFetchInterval ? parseInt(elements.settingFetchInterval.value) : 15,
        min_text_chars: elements.settingMinTextChars ? parseInt(elements.settingMinTextChars.value) : 100,
        promote_threshold: elements.settingPromoteThreshold ? parseInt(elements.settingPromoteThreshold.value) : 5,
        
        ai_base_url: elements.settingAiUrl ? elements.settingAiUrl.value.trim() : "",
        ai_api_key: elements.settingAiKey ? elements.settingAiKey.value.trim() : "",
        ai_model: elements.settingAiModel ? elements.settingAiModel.value.trim() : "",
        
        ai_pregenerate: elements.settingAiPregenerate ? elements.settingAiPregenerate.checked : false,
        ai_stream: elements.settingAiStream ? elements.settingAiStream.checked : false,
        ai_auto_summary: elements.settingAiAutoSummary ? elements.settingAiAutoSummary.checked : false,
        
        ai_summary_lang: elements.settingAiSummaryLang ? elements.settingAiSummaryLang.value : "auto",
        system_lang: elements.settingSystemLang ? elements.settingSystemLang.value : "zh",
        
        chat_base_url: elements.settingChatUrl ? elements.settingChatUrl.value.trim() : "",
        chat_api_key: elements.settingChatKey ? elements.settingChatKey.value.trim() : "",
        chat_model: elements.settingChatModel ? elements.settingChatModel.value.trim() : "",
        chat_max_tokens: (elements.settingChatTokens && elements.settingChatTokens.value) ? parseInt(elements.settingChatTokens.value) : null,
        interest_profile_enabled: elements.settingInterestProfileEnabled ? elements.settingInterestProfileEnabled.checked : false
    };
    
    try {
        const response = await fetch('/settings', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        
        const lang = payload.system_lang || 'zh';
        if (response.ok) {
            state.autoSummary = payload.ai_auto_summary;
            state.systemLang = payload.system_lang;
            state.interestProfileEnabled = payload.interest_profile_enabled;
            updateUILanguage(state.systemLang);
            alert((TRANSLATIONS[lang] && TRANSLATIONS[lang]["save_success"]) || "系统设置参数保存成功！");
            hideAllModals();
        } else {
            const errData = await response.json();
            const failPrefix = (TRANSLATIONS[lang] && TRANSLATIONS[lang]["save_failed"]) || "保存设置失败: ";
            alert(failPrefix + (errData.detail || "Server error"));
        }
    } catch (e) {
        console.error("Failed to save settings:", e);
        const lang = payload.system_lang || 'zh';
        alert((TRANSLATIONS[lang] && TRANSLATIONS[lang]["network_error"]) || "保存参数设置出错，请检查网络连接");
    }
}



async function triggerManualMaintenance(e) {
    if (e) e.preventDefault();
    if (!confirm("确定要立即运行系统维护任务吗？\n这将会进行抽屉合并、清理无用分类，并对未归类文章重新分类。此操作为同步执行，可能需要几秒钟。")) {
        return;
    }
    
    const originalText = elements.btnManualMaintenance.innerText;
    elements.btnManualMaintenance.disabled = true;
    elements.btnManualMaintenance.innerText = "执行中...";
    
    try {
        const response = await fetch('/maintenance', {
            method: 'POST'
        });
        
        if (response.ok) {
            alert("系统维护与抽屉合并/清理任务执行完毕！");
            hideAllModals();
            await loadFeeds();
            selectGlobalUnread();
        } else {
            const errData = await response.json();
            alert("执行维护失败: " + (errData.detail || "服务器错误"));
        }
    } catch (err) {
        console.error("Failed to run maintenance:", err);
        alert("执行维护失败，请检查网络连接");
    } finally {
        elements.btnManualMaintenance.disabled = false;
        elements.btnManualMaintenance.innerText = originalText;
    }
}

// Theme Operations
function getAutomaticTheme() {
    const hour = new Date().getHours();
    return (hour >= 6 && hour < 18) ? 'light' : 'dark';
}

function initTheme() {
    const themePref = localStorage.getItem('theme_pref') || 'auto';
    let theme = 'dark';
    
    if (themePref === 'light') {
        theme = 'light';
    } else if (themePref === 'dark') {
        theme = 'dark';
    } else { // auto
        theme = getAutomaticTheme();
    }
    
    if (theme === 'light') {
        document.body.classList.remove('dark-theme');
        document.body.classList.add('light-theme');
    } else {
        document.body.classList.remove('light-theme');
        document.body.classList.add('dark-theme');
    }
    
    updateThemeIcons(themePref);
    
    // Automatically update theme in auto mode every minute
    if (window.themeTimer) clearInterval(window.themeTimer);
    window.themeTimer = setInterval(() => {
        if (localStorage.getItem('theme_pref') === 'auto' || !localStorage.getItem('theme_pref')) {
            initTheme();
        }
    }, 60000);
}

function toggleTheme() {
    const themePref = localStorage.getItem('theme_pref') || 'auto';
    let nextTheme = 'auto';
    
    if (themePref === 'auto') {
        nextTheme = 'light';
    } else if (themePref === 'light') {
        nextTheme = 'dark';
    } else {
        nextTheme = 'auto';
    }
    
    localStorage.setItem('theme_pref', nextTheme);
    initTheme();
}

function updateThemeIcons(themePref) {
    if (!elements.themeToggleBtn) return;
    const lightIcon = elements.themeToggleBtn.querySelector('.light-icon');
    const darkIcon = elements.themeToggleBtn.querySelector('.dark-icon');
    const autoIcon = elements.themeToggleBtn.querySelector('.auto-icon');
    
    if (lightIcon) lightIcon.classList.add('hidden');
    if (darkIcon) darkIcon.classList.add('hidden');
    if (autoIcon) autoIcon.classList.add('hidden');
    
    const lang = state.systemLang || 'zh';
    
    if (themePref === 'light') {
        if (lightIcon) lightIcon.classList.remove('hidden');
        elements.themeToggleBtn.title = (TRANSLATIONS[lang] && TRANSLATIONS[lang]["theme_light"]) || "亮色模式";
    } else if (themePref === 'dark') {
        if (darkIcon) darkIcon.classList.remove('hidden');
        elements.themeToggleBtn.title = (TRANSLATIONS[lang] && TRANSLATIONS[lang]["theme_dark"]) || "暗色模式";
    } else { // auto
        if (autoIcon) autoIcon.classList.remove('hidden');
        elements.themeToggleBtn.title = (TRANSLATIONS[lang] && TRANSLATIONS[lang]["theme_auto"]) || "自动模式 (随时间自动切换)";
    }
}

// Make sure icons are synchronized as soon as the DOMContentLoaded hook runs
document.addEventListener('DOMContentLoaded', () => {
    const themePref = localStorage.getItem('theme_pref') || 'auto';
    updateThemeIcons(themePref);
});

// Translation resources for UI localization
const TRANSLATIONS = {
    zh: {
        "unread_articles": "未读文章",
        "my_starred": "我的收藏",
        "feeds_title": "订阅源",
        "refresh_all": "刷新所有订阅",
        "current_category_unread": "所有未读",
        "mark_all_read": "一键已读",
        "only_unread": "仅未读",
        "original_article": "原文",
        "mark_read": "已读",
        "mark_unread": "未读",
        "star": "收藏",
        "unstar": "收藏",
        "ai_summary_title": "AI 智能摘要",
        "regenerate": "🔄 重新生成",
        "expand_fulltext": "展开阅读全文",
        "collapse_fulltext": "折叠全文正文",
        "ask_ai": "💬 AI 追问对话",
        "ask_ai_desc": "围绕本文内容进行自由追问",
        "ask_ai_placeholder": "输入关于本文的追问...",
        "ask_ai_first_msg": "您可以针对正文或摘要内容，向 AI 提出任何疑问或进行深度拓展探讨。",
        "system_management_center": "系统管理中心",
        "feed_management": "订阅源管理",
        "system_settings": "系统参数设置",
        "save_settings": "保存设置",
        "close": "关闭",
        "glance": "掠读",
        "skim": "扫读",
        "read": "精读",
        "attention_label": "注意力:",
        "search_placeholder": "搜索文章标题或正文...",
        "clickbait_warn": "标题党警告：",
        "save_success": "系统设置参数保存成功！",
        "save_failed": "保存设置失败: ",
        "load_failed": "获取系统设置参数失败！",
        "network_error": "保存参数设置出错，请检查网络连接",
        "theme_light": "亮色模式",
        "theme_dark": "暗色模式",
        "theme_auto": "自动模式 (随时间自动切换)",
        "translate_btn": "对照翻译",
        "translating": "正在对照翻译...",
        "show_original": "只看原文",
        "target_lang_label": "目标语言（摘要、翻译、问答）",
        "ui_lang_label": "系统界面语言"
    },
    "zh-hant": {
        "unread_articles": "未讀文章",
        "my_starred": "我的收藏",
        "feeds_title": "訂閱源",
        "refresh_all": "刷新所有訂閱",
        "current_category_unread": "所有未讀",
        "mark_all_read": "一鍵已讀",
        "only_unread": "僅未讀",
        "original_article": "原文",
        "mark_read": "已讀",
        "mark_unread": "未讀",
        "star": "收藏",
        "unstar": "收藏",
        "ai_summary_title": "AI 智能摘要",
        "regenerate": "🔄 重新生成",
        "expand_fulltext": "展開閱讀全文",
        "collapse_fulltext": "折疊全文正文",
        "ask_ai": "💬 AI 追問對話",
        "ask_ai_desc": "圍繞本文內容進行自由追問",
        "ask_ai_placeholder": "輸入關於本文的追問...",
        "ask_ai_first_msg": "您可以針對正文或摘要內容，向 AI 提出任何疑問或進行深度拓展探討。",
        "system_management_center": "系統管理中心",
        "feed_management": "訂閱源管理",
        "system_settings": "系統參數設置",
        "save_settings": "保存設置",
        "close": "關閉",
        "glance": "掠讀",
        "skim": "掃讀",
        "read": "精讀",
        "attention_label": "注意力:",
        "search_placeholder": "搜索文章標題或正文...",
        "clickbait_warn": "標題黨警告：",
        "save_success": "系統參數設置保存成功！",
        "save_failed": "保存設置失敗: ",
        "load_failed": "獲取系統設置參數失敗！",
        "network_error": "保存參數設置出錯，請檢查網絡連接",
        "theme_light": "亮色模式",
        "theme_dark": "暗色模式",
        "theme_auto": "自動模式 (隨時間自動切換)",
        "translate_btn": "對照翻譯",
        "translating": "正在對照翻譯...",
        "show_original": "只看原文",
        "target_lang_label": "目標語言（摘要、翻譯、問答）",
        "ui_lang_label": "系統界面語言"
    },
    en: {
        "unread_articles": "Unread Articles",
        "my_starred": "My Favorites",
        "feeds_title": "Feeds",
        "refresh_all": "Refresh Feeds",
        "current_category_unread": "All Unread",
        "mark_all_read": "Mark All Read",
        "only_unread": "Unread Only",
        "original_article": "Original",
        "mark_read": "Read",
        "mark_unread": "Unread",
        "star": "Star",
        "unstar": "Star",
        "ai_summary_title": "AI Summary",
        "regenerate": "🔄 Regenerate",
        "expand_fulltext": "Expand Fulltext",
        "collapse_fulltext": "Collapse Fulltext",
        "ask_ai": "💬 Ask AI Assistant",
        "ask_ai_desc": "Ask follow-up questions about this article",
        "ask_ai_placeholder": "Ask a follow-up question...",
        "ask_ai_first_msg": "You can ask AI any questions or explore details about the article body or summary.",
        "system_management_center": "System Management Center",
        "feed_management": "Feed Management",
        "system_settings": "Settings Configuration",
        "save_settings": "Save Settings",
        "close": "Close",
        "glance": "Glance",
        "skim": "Skim",
        "read": "Read",
        "attention_label": "Attention:",
        "search_placeholder": "Search title or content...",
        "clickbait_warn": "Clickbait Alert:",
        "save_success": "System settings saved successfully!",
        "save_failed": "Failed to save settings: ",
        "load_failed": "Failed to get system settings!",
        "network_error": "Error saving settings, please check network connection.",
        "theme_light": "Light Mode",
        "theme_dark": "Dark Mode",
        "theme_auto": "Auto Mode",
        "translate_btn": "Bilingual Translation",
        "translating": "Translating...",
        "show_original": "Show Original Only",
        "target_lang_label": "Target Language (Summary, Translation, Q&A)",
        "ui_lang_label": "UI Language"
    },
    ja: {
        "unread_articles": "未読記事",
        "my_starred": "お気に入り",
        "feeds_title": "購読フィード",
        "refresh_all": "すべてのフィードを更新",
        "current_category_unread": "すべての未読",
        "mark_all_read": "すべて既読にする",
        "only_unread": "未読のみ",
        "original_article": "原文を読む",
        "mark_read": "既読にする",
        "mark_unread": "未読にする",
        "star": "お気に入りに追加",
        "unstar": "お気に入りから削除",
        "ai_summary_title": "AI要約",
        "regenerate": "🔄 再生成",
        "expand_fulltext": "全文を展開",
        "collapse_fulltext": "本文を折りたたむ",
        "ask_ai": "💬 AIチャット",
        "ask_ai_desc": "この記事についてAIと対話する",
        "ask_ai_placeholder": "質問を入力してください...",
        "ask_ai_first_msg": "記事の本文や要約について、AIに自由に質問することができます。",
        "system_management_center": "システム管理センター",
        "feed_management": "フィード管理",
        "system_settings": "システム設定",
        "save_settings": "設定を保存",
        "close": "閉じる",
        "glance": "流し読み",
        "skim": "ざっと読む",
        "read": "精読",
        "attention_label": "注目度:",
        "search_placeholder": "タイトルや本文を検索...",
        "clickbait_warn": "クリックベイト警告：",
        "save_success": "システム設定が正常に保存されました！",
        "save_failed": "設定の保存に失敗しました: ",
        "load_failed": "システム設定의取得に失敗しました！",
        "network_error": "設定の保存エラー、ネットワーク接続を確認してください。",
        "theme_light": "ライトモード",
        "theme_dark": "ダークモード",
        "theme_auto": "自動モード",
        "translate_btn": "対訳を表示",
        "translating": "翻訳中...",
        "show_original": "原文のみ表示",
        "target_lang_label": "対象言語（要約、翻訳、Q&A）",
        "ui_lang_label": "UI言語"
    },
    ko: {
        "unread_articles": "읽지 않은 글",
        "my_starred": "내 보관함",
        "feeds_title": "구독 피드",
        "refresh_all": "모든 피드 새로고침",
        "current_category_unread": "읽지 않은 모든 글",
        "mark_all_read": "모두 읽음으로 표시",
        "only_unread": "읽지 않은 글만",
        "original_article": "원본 기사 보기",
        "mark_read": "읽음으로 표시",
        "mark_unread": "읽지 않음으로 표시",
        "star": "즐겨찾기 추가",
        "unstar": "즐겨찾기 해제",
        "ai_summary_title": "AI 요약",
        "regenerate": "🔄 다시 생성",
        "expand_fulltext": "본문 펼치기",
        "collapse_fulltext": "본문 접기",
        "ask_ai": "💬 AI 대화",
        "ask_ai_desc": "이 기사에 대해 AI에게 질문하기",
        "ask_ai_placeholder": "질문을 입력하세요...",
        "ask_ai_first_msg": "본문이나 요약 내용에 대해 AI에게 자유롭게 질문할 수 있습니다.",
        "system_management_center": "시스템 관리 센터",
        "feed_management": "피드 관리",
        "system_settings": "시스템 설정",
        "save_settings": "설정 저장",
        "close": "닫기",
        "glance": "속독",
        "skim": "훑어보기",
        "read": "정독",
        "attention_label": "주목도:",
        "search_placeholder": "제목 또는 본문 검색...",
        "clickbait_warn": "클릭베이트 경고:",
        "save_success": "시스템 설정이 성공적으로 저장되었습니다!",
        "save_failed": "설정 저장 실패: ",
        "load_failed": "시스템 설정을 가져오는데 실패했습니다!",
        "network_error": "설정 저장 오류, 네트워크 연결을 확인하십시오.",
        "theme_light": "라이트 모드",
        "theme_dark": "다크 모드",
        "theme_auto": "자동 모드",
        "translate_btn": "대역 번역",
        "translating": "번역 중...",
        "show_original": "원본만 보기",
        "target_lang_label": "대상 언어 (요약, 번역, Q&A)",
        "ui_lang_label": "UI 언어"
    },
    fr: {
        "unread_articles": "Articles non lus",
        "my_starred": "Mes favoris",
        "feeds_title": "Flux",
        "refresh_all": "Actualiser les flux",
        "current_category_unread": "Tout non lu",
        "mark_all_read": "Tout marquer comme lu",
        "only_unread": "Non lus seulement",
        "original_article": "Visiter l'original",
        "mark_read": "Marquer comme lu",
        "mark_unread": "Marquer comme non lu",
        "star": "Favoris",
        "unstar": "Retirer des favoris",
        "ai_summary_title": "Résumé IA",
        "regenerate": "🔄 Régénérer",
        "expand_fulltext": "Déplier le texte complet",
        "collapse_fulltext": "Plier le texte complet",
        "ask_ai": "💬 Chat avec l'IA",
        "ask_ai_desc": "Poser des questions sur cet article",
        "ask_ai_placeholder": "Poser une question...",
        "ask_ai_first_msg": "Vous pouvez poser des questions à l'IA sur le texte ou le résumé de cet article.",
        "system_management_center": "Centre de gestion",
        "feed_management": "Gestion des flux",
        "system_settings": "Paramètres système",
        "save_settings": "Enregistrer",
        "close": "Fermer",
        "glance": "Parcourir",
        "skim": "Survoler",
        "read": "Lire attentivement",
        "attention_label": "Attention :",
        "search_placeholder": "Rechercher titre ou contenu...",
        "clickbait_warn": "Alerte Clickbait :",
        "save_success": "Paramètres système enregistrés avec succès !",
        "save_failed": "Échec de l'enregistrement : ",
        "load_failed": "Échec du chargement des paramètres !",
        "network_error": "Erreur de réseau, veuillez vérifier votre connexion.",
        "theme_light": "Mode clair",
        "theme_dark": "Mode sombre",
        "theme_auto": "Mode automatique",
        "translate_btn": "Traduction bilingue",
        "translating": "Traduction en cours...",
        "show_original": "Afficher l'original",
        "target_lang_label": "Langue cible (Résumé, Traduction, Q&R)",
        "ui_lang_label": "Langue de l'interface"
    },
    es: {
        "unread_articles": "Artículos no leídos",
        "my_starred": "Mis favoritos",
        "feeds_title": "Canales",
        "refresh_all": "Actualizar canales",
        "current_category_unread": "Todos los no leídos",
        "mark_all_read": "Marcar todo como leído",
        "only_unread": "Solo no leídos",
        "original_article": "Visitar original",
        "mark_read": "Marcar como leído",
        "mark_unread": "Marcar como no leído",
        "star": "Favorito",
        "unstar": "Quitar favorito",
        "ai_summary_title": "Resumen IA",
        "regenerate": "🔄 Regenerar",
        "expand_fulltext": "Expandir texto completo",
        "collapse_fulltext": "Contraer texto completo",
        "ask_ai": "💬 Preguntar a la IA",
        "ask_ai_desc": "Hacer preguntas sobre este artículo",
        "ask_ai_placeholder": "Hacer una pregunta...",
        "ask_ai_first_msg": "Puedes hacer preguntas a la IA sobre el contenido del artículo o el resumen.",
        "system_management_center": "Centro de gestión",
        "feed_management": "Gestión de canales",
        "system_settings": "Configuración del sistema",
        "save_settings": "Guardar",
        "close": "Cerrar",
        "glance": "Ojear",
        "skim": "Escanear",
        "read": "Leer",
        "attention_label": "Atención:",
        "search_placeholder": "Buscar título o contenido...",
        "clickbait_warn": "Alerta Clickbait:",
        "save_success": "¡Configuración del sistema guardada con éxito!",
        "save_failed": "Error al guardar la configuración: ",
        "load_failed": "¡Error al obtener la configuración del sistema!",
        "network_error": "Error de red, por favor verifique la conexión.",
        "theme_light": "Modo claro",
        "theme_dark": "Modo oscuro",
        "theme_auto": "Modo automático",
        "translate_btn": "Traducción bilingüe",
        "translating": "Traduciendo...",
        "show_original": "Mostrar solo original",
        "target_lang_label": "Idioma objetivo (Resumen, Traducción, Preguntas)",
        "ui_lang_label": "Idioma de la interfaz"
    },
    de: {
        "unread_articles": "Ungelesene Artikel",
        "my_starred": "Meine Favoriten",
        "feeds_title": "Feeds",
        "refresh_all": "Feeds aktualisieren",
        "current_category_unread": "Alle ungelesenen",
        "mark_all_read": "Alle als gelesen markieren",
        "only_unread": "Nur ungelesene",
        "original_article": "Original anzeigen",
        "mark_read": "Als gelesen markieren",
        "mark_unread": "Als ungelesen markieren",
        "star": "Favorit hinzufügen",
        "unstar": "Favorit entfernen",
        "ai_summary_title": "AI-Zusammenfassung",
        "regenerate": "🔄 Regenerieren",
        "expand_fulltext": "Volltext anzeigen",
        "collapse_fulltext": "Volltext ausblenden",
        "ask_ai": "💬 AI Chatbot",
        "ask_ai_desc": "Fragen zu diesem Artikel stellen",
        "ask_ai_placeholder": "Frage eingeben...",
        "ask_ai_first_msg": "Sie können der KI Fragen zum Inhalt oder zur Zusammenfassung des Artikels stellen.",
        "system_management_center": "Verwaltungscenter",
        "feed_management": "Feed-Verwaltung",
        "system_settings": "Systemeinstellungen",
        "save_settings": "Einstellungen speichern",
        "close": "Schließen",
        "glance": "Überfliegen",
        "skim": "Querlesen",
        "read": "Lesen",
        "attention_label": "Aufmerksamkeit:",
        "search_placeholder": "Titel oder Inhalt suchen...",
        "clickbait_warn": "Clickbait-Warnung:",
        "save_success": "Systemeinstellungen erfolgreich gespeichert!",
        "save_failed": "Speichern fehlgeschlagen: ",
        "load_failed": "Laden der Systemeinstellungen fehlgeschlagen!",
        "network_error": "Netzwerkfehler, bitte Verbindung prüfen.",
        "theme_light": "Heller Modus",
        "theme_dark": "Dunkler Modus",
        "theme_auto": "Automatischer Modus",
        "translate_btn": "Zweisprachige Übersetzung",
        "translating": "Übersetzung...",
        "show_original": "Nur Original anzeigen",
        "target_lang_label": "Zielsprache (Zusammenfassung, Übersetzung, F&A)",
        "ui_lang_label": "Systemsprache"
    }
};

function updateUILanguage(lang) {
    if (!TRANSLATIONS[lang]) lang = 'zh';
    
    // 1. Sidebar Links
    const unreadText = elements.btnAllUnread.querySelector('.item-text');
    if (unreadText) unreadText.textContent = TRANSLATIONS[lang]["unread_articles"];
    
    const starredText = elements.btnStarred.querySelector('.item-text');
    if (starredText) starredText.textContent = TRANSLATIONS[lang]["my_starred"];
    
    const feedsTitle = document.querySelector('.section-title');
    if (feedsTitle) feedsTitle.textContent = TRANSLATIONS[lang]["feeds_title"];
    
    // 2. Refresh Button
    if (elements.refreshAllBtn) {
        const refreshIcon = document.getElementById('refresh-icon');
        elements.refreshAllBtn.innerHTML = '';
        if (refreshIcon) {
            elements.refreshAllBtn.appendChild(refreshIcon);
        }
        elements.refreshAllBtn.appendChild(document.createTextNode(' ' + TRANSLATIONS[lang]["refresh_all"]));
    }
    
    // 3. Middle Column Filters
    if (elements.markAllReadBtn) {
        elements.markAllReadBtn.textContent = TRANSLATIONS[lang]["mark_all_read"];
    }
    
    const toggleLabel = document.querySelector('.toggle-label');
    if (toggleLabel) toggleLabel.textContent = TRANSLATIONS[lang]["only_unread"];
    
    if (state.activeView === 'unread') {
        elements.currentCategoryName.textContent = TRANSLATIONS[lang]["current_category_unread"];
    }
    
    // 4. Search Bar
    if (elements.searchInput) {
        elements.searchInput.placeholder = TRANSLATIONS[lang]["search_placeholder"];
    }
    
    // 5. Article Detail Views (if an article is loaded)
    if (state.currentOpenEntry) {
        // Visit Original Link
        const originalTextSpan = elements.artOriginalLink;
        if (originalTextSpan) {
            const btnText = originalTextSpan.querySelector('.btn-text');
            if (btnText) {
                btnText.textContent = TRANSLATIONS[lang]["original_article"];
            } else {
                const linkSvg = originalTextSpan.querySelector('svg');
                originalTextSpan.innerHTML = TRANSLATIONS[lang]["original_article"] + ' ';
                if (linkSvg) originalTextSpan.appendChild(linkSvg);
            }
        }
        
        // Mark Read/Unread
        if (elements.artToggleReadBtn) {
            const btnText = elements.artToggleReadBtn.querySelector('.btn-text');
            const textVal = state.currentOpenEntry.is_read ? TRANSLATIONS[lang]["mark_unread"] : TRANSLATIONS[lang]["mark_read"];
            if (btnText) btnText.textContent = textVal;
            else elements.artToggleReadBtn.textContent = textVal;
        }
        
        // Star/Unstar
        if (elements.artToggleStarBtn) {
            const btnText = elements.artToggleStarBtn.querySelector('.btn-text');
            const textVal = state.currentOpenEntry.is_starred ? TRANSLATIONS[lang]["unstar"] : TRANSLATIONS[lang]["star"];
            if (btnText) btnText.textContent = textVal;
            else elements.artToggleStarBtn.textContent = textVal;
        }

        // Bilingual Translation Button
        const transBtn = elements.artTranslateBtn;
        if (transBtn) {
            const btnText = transBtn.querySelector('.btn-text');
            if (btnText) {
                if (state.isTranslating) {
                    btnText.textContent = TRANSLATIONS[lang]["translating"];
                } else if (state.isBilingualMode) {
                    btnText.textContent = TRANSLATIONS[lang]["show_original"];
                } else {
                    btnText.textContent = TRANSLATIONS[lang]["translate_btn"];
                }
            }
        }
    }
    
    // 6. Attention levels
    const attentionLabel = document.querySelector('.attention-selector-wrapper .actions-label');
    if (attentionLabel) attentionLabel.textContent = TRANSLATIONS[lang]["attention_label"];
    
    if (elements.attnBtnGlance) elements.attnBtnGlance.textContent = TRANSLATIONS[lang]["glance"];
    if (elements.attnBtnSkim) elements.attnBtnSkim.textContent = TRANSLATIONS[lang]["skim"];
    if (elements.attnBtnRead) elements.attnBtnRead.textContent = TRANSLATIONS[lang]["read"];
    
    // 7. AI Summary Block
    if (elements.aiSummaryBlock) {
        const titleTag = elements.aiSummaryBlock.querySelector('.ai-title-tag');
        if (titleTag) {
            titleTag.innerHTML = `<span class="sparkle-icon">✨</span> ` + TRANSLATIONS[lang]["ai_summary_title"];
        }
        if (elements.regenerateSummaryBtn) {
            elements.regenerateSummaryBtn.textContent = TRANSLATIONS[lang]["regenerate"];
        }
        const isHidden = elements.fulltextContentArea.classList.contains('hidden');
        if (elements.expanderText) {
            elements.expanderText.textContent = isHidden ? TRANSLATIONS[lang]["expand_fulltext"] : TRANSLATIONS[lang]["collapse_fulltext"];
        }
    }
    
    // 8. Chat block
    const chatTitle = document.querySelector('#chat-section h3');
    if (chatTitle) chatTitle.textContent = TRANSLATIONS[lang]["ask_ai"];
    
    const chatDesc = document.querySelector('.chat-desc');
    if (chatDesc) chatDesc.textContent = TRANSLATIONS[lang]["ask_ai_desc"];
    
    if (elements.chatInputField) {
        elements.chatInputField.placeholder = TRANSLATIONS[lang]["ask_ai_placeholder"];
    }
    
    // Do NOT overwrite elements.chatSendBtn's textContent to preserve the SVG icon inside. Update its title instead.
    if (elements.chatSendBtn) {
        const sendTitles = {
            'zh': '发送',
            'zh-hant': '發送',
            'en': 'Send',
            'ja': '送信',
            'ko': '전송',
            'fr': 'Envoyer',
            'es': 'Enviar',
            'de': 'Senden'
        };
        elements.chatSendBtn.title = sendTitles[lang] || '发送';
    }
    
    // 9. Modal UI Labels
    const addFeedTitle = document.querySelector('#add-feed-modal h2');
    if (addFeedTitle) addFeedTitle.textContent = TRANSLATIONS[lang]["add_feed"];
    
    const inputFeedLabel = document.querySelector('#add-feed-modal label');
    if (inputFeedLabel) inputFeedLabel.textContent = TRANSLATIONS[lang]["feed_url_label"];
    
    const addBtn = document.getElementById('feed-add-submit-btn');
    if (addBtn) addBtn.textContent = TRANSLATIONS[lang]["add_button"];
    
    const opmlTitle = document.querySelector('#opml-modal h2');
    if (opmlTitle) opmlTitle.textContent = TRANSLATIONS[lang]["import_opml"];
    
    const opmlLabel = document.querySelector('#opml-modal label');
    if (opmlLabel) opmlLabel.textContent = TRANSLATIONS[lang]["select_opml_file"];
    
    const importSubmitBtn = document.getElementById('opml-import-submit-btn');
    if (importSubmitBtn) importSubmitBtn.textContent = TRANSLATIONS[lang]["import_button"];
    
    const manageTitle = document.querySelector('#manage-feeds-modal h2');
    if (manageTitle) manageTitle.textContent = TRANSLATIONS[lang]["manage_feeds"];
    
    if (elements.settingsSaveBtn) elements.settingsSaveBtn.textContent = TRANSLATIONS[lang]["save_settings"];
    
    const closeBtn = document.getElementById('modal-cancel-btn');
    if (closeBtn) closeBtn.textContent = TRANSLATIONS[lang]["close"];

    // 10. Settings labels
    const targetLangLabel = document.getElementById('label-target-lang');
    if (targetLangLabel) targetLangLabel.textContent = TRANSLATIONS[lang]["target_lang_label"];
    
    const uiLangLabel = document.getElementById('label-ui-lang');
    if (uiLangLabel) uiLangLabel.textContent = TRANSLATIONS[lang]["ui_lang_label"];
}

function renderBilingualContainer(content) {
    if (!content) return "";
    const paragraphs = content.split(/\n\s*\n/);
    let html = "";
    
    paragraphs.forEach((p, index) => {
        const text = p.trim();
        if (!text) return;
        
        const origHtml = renderSingleParagraph(text);
        
        // Check if paragraph has letters/symbols that need translation
        // Avoid translating pure HTML-like image tag strings if any (e.g. <img>) or pure markdown image
        const isTranslatable = /[a-zA-Z\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]/.test(text) && 
                              !text.startsWith('<img') && 
                              !/^\s*!\[.*\]\(.*\)\s*$/.test(text); // Skip markdown pure image
                              
        html += `
        <div class="bilingual-paragraph-pair" 
             data-para-index="${index}" 
             data-translatable="${isTranslatable}"
             data-translated="false" 
             data-raw-text="${encodeURIComponent(text)}" 
             style="margin-bottom: 1.6em; border-left: 2px solid rgba(99, 102, 241, 0.15); padding-left: 10px; position: relative;">
            <div class="original-text" style="color: var(--text-primary); font-size: 1em; line-height: 1.6;">
                ${origHtml}
            </div>
            <div class="translated-text-container" style="margin-top: 6px;"></div>
        </div>`;
    });
    return html;
}

function startBilingualObserver() {
    if (window.bilingualObserver) {
        window.bilingualObserver.disconnect();
    }
    
    const options = {
        root: null, // viewport
        rootMargin: '0px 0px 300px 0px', // Pre-load 300px before scrolling into view
        threshold: 0.1
    };
    
    const observer = new IntersectionObserver((entries, obs) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const container = entry.target;
                const paraIndex = container.dataset.paraIndex;
                const isTranslatable = container.dataset.translatable === 'true';
                const translated = container.dataset.translated;
                
                if (translated === 'false') {
                    translateParagraph(container, paraIndex, isTranslatable);
                }
                obs.unobserve(container);
            }
        });
    }, options);
    
    window.bilingualObserver = observer;
    
    const pairs = document.querySelectorAll('.bilingual-paragraph-pair');
    pairs.forEach(pair => {
        const isTranslatable = pair.dataset.translatable === 'true';
        if (isTranslatable) {
            observer.observe(pair);
        } else {
            pair.dataset.translated = 'true';
        }
    });
}

async function translateParagraph(container, paraIndex, isTranslatable) {
    if (!isTranslatable) {
        container.dataset.translated = 'true';
        return;
    }
    
    container.dataset.translated = 'translating';
    const transContainer = container.querySelector('.translated-text-container');
    
    // Render elegant loading indicator with standard spin/pulse animations from style.css
    transContainer.innerHTML = `
        <div class="para-translating-indicator" style="font-size: 13px; color: var(--text-muted); display: inline-flex; align-items: center; gap: 6px; animation: pulse 1.5s infinite;">
            <span class="spinner" style="display: inline-block; width: 12px; height: 12px; border: 2px solid var(--accent-color, #6366f1); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite;"></span>
            <span>翻译中...</span>
        </div>
    `;
    
    const rawText = decodeURIComponent(container.dataset.rawText);
    const entryId = state.currentOpenEntry.id;
    
    try {
        const response = await fetch(`/entries/${entryId}/translate_paragraph`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                para_index: parseInt(paraIndex),
                text: rawText
            })
        });
        
        if (!response.ok) throw new Error("Translation failed");
        
        const data = await response.json();
        const translatedText = data.translated_text || "";
        
        if (translatedText && translatedText.trim() !== rawText.trim()) {
            const translatedHtml = renderSingleParagraph(translatedText);
            transContainer.innerHTML = `
                <div class="translated-text" style="color: var(--accent-color, #6366f1); font-size: 0.95em; line-height: 1.6; opacity: 0.85;">
                    ${translatedHtml}
                </div>
            `;
        } else {
            transContainer.innerHTML = '';
        }
        container.dataset.translated = 'true';
    } catch (err) {
        console.error("Failed to translate paragraph:", err);
        transContainer.innerHTML = '';
        container.dataset.translated = 'error';
    }
}

async function toggleBilingualTranslation() {
    if (!state.currentOpenEntry) return;
    const lang = state.systemLang || 'zh';
    
    if (state.isBilingualMode) {
        state.isBilingualMode = false;
        if (window.bilingualObserver) {
            window.bilingualObserver.disconnect();
        }
        elements.fulltextContentArea.innerHTML = renderArticleContent(state.currentOpenEntryFulltext);
        updateUILanguage(lang);
    } else {
        state.isBilingualMode = true;
        elements.fulltextContentArea.innerHTML = renderBilingualContainer(state.currentOpenEntryFulltext);
        updateUILanguage(lang);
        startBilingualObserver();
    }
}

// ====================================================
// PWA GESTURES & INTERACTIONS
// ====================================================
// PWA GESTURES & INTERACTIONS
// ====================================================
function initPwaGestures() {
    let touchStartX = 0;
    let touchStartY = 0;
    let touchStartTime = 0;
    let isSwipingY = false;
    let isSwipingCard = false;
    let activeSwipeCard = null;
    let cardSwipeDistance = 0;

    // Pull to Refresh state
    let ptrStartY = 0;
    let isPullingPtr = false;
    let ptrPullDistance = 0;
    
    // Active PTR tracking targets
    let activePtrContainer = null;
    let activeScrollContent = null;

    // Create PTR container in middle column (entries) scroll content
    const entriesColumn = document.getElementById('entries-column');
    const scrollContent = entriesColumn ? entriesColumn.querySelector('.panel-scroll-content') : null;
    let entriesPtrContainer = null;
    
    if (scrollContent) {
        entriesPtrContainer = document.createElement('div');
        entriesPtrContainer.className = 'ptr-container';
        entriesPtrContainer.innerHTML = `
            <div class="ptr-icon">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M23 4v6h-6"></path>
                    <path d="M1 20v-6h6"></path>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                </svg>
            </div>
            <div class="ptr-text">下拉刷新当前列表...</div>
        `;
        scrollContent.insertBefore(entriesPtrContainer, scrollContent.firstChild);
    }

    // Create PTR container in left column (feeds) scroll content
    const feedsColumn = document.getElementById('feeds-column');
    const feedsScrollContent = feedsColumn ? feedsColumn.querySelector('.panel-scroll-content') : null;
    let feedsPtrContainer = null;

    if (feedsScrollContent) {
        feedsPtrContainer = document.createElement('div');
        feedsPtrContainer.className = 'ptr-container';
        feedsPtrContainer.innerHTML = `
            <div class="ptr-icon">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M23 4v6h-6"></path>
                    <path d="M1 20v-6h6"></path>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                </svg>
            </div>
            <div class="ptr-text">下拉刷新订阅列表...</div>
        `;
        feedsScrollContent.insertBefore(feedsPtrContainer, feedsScrollContent.firstChild);
    }

    // Handle touch start
    document.addEventListener('touchstart', (e) => {
        // Disable on desktop
        if (window.innerWidth > 900) return;

        const touch = e.touches[0];
        const clientX = touch.clientX;
        const clientY = touch.clientY;

        // Skip edge touches to allow browser native swipe-back (20px edge buffer)
        if (clientX < 20 || clientX > window.innerWidth - 20) {
            return;
        }

        touchStartX = clientX;
        touchStartY = clientY;
        touchStartTime = Date.now();
        isSwipingY = false;
        isSwipingCard = false;
        activeSwipeCard = null;
        cardSwipeDistance = 0;
        window.preventClickFlag = false;
        
        // PTR detection: check which scroll panel is active and scrolled to the top
        isPullingPtr = false;
        activePtrContainer = null;
        activeScrollContent = null;
        
        if (scrollContent && scrollContent.contains(e.target) && scrollContent.scrollTop <= 0) {
            ptrStartY = clientY;
            activePtrContainer = entriesPtrContainer;
            activeScrollContent = scrollContent;
        } else if (feedsScrollContent && feedsScrollContent.contains(e.target) && feedsScrollContent.scrollTop <= 0) {
            ptrStartY = clientY;
            activePtrContainer = feedsPtrContainer;
            activeScrollContent = feedsScrollContent;
        }

        // Card swipe detection: touch starts on an unread entry card
        const card = e.target.closest('.entry-card.unread');
        const isViewingEntries = document.body.classList.contains('show-entries') && !document.body.classList.contains('show-detail');
        if (card && isViewingEntries) {
            activeSwipeCard = card;
        }
    }, { passive: true });

    // Handle touch move
    document.addEventListener('touchmove', (e) => {
        if (window.innerWidth > 900) return;
        if (!touchStartX || !touchStartY) return;

        const touch = e.touches[0];
        const clientX = touch.clientX;
        const clientY = touch.clientY;

        const diffX = clientX - touchStartX;
        const diffY = clientY - touchStartY;

        // Lock swipe type
        if (!isSwipingY && !isSwipingCard && !isPullingPtr) {
            const absX = Math.abs(diffX);
            const absY = Math.abs(diffY);
            
            if (absX > 10 || absY > 10) {
                // Mark gesture movement to prevent accidental click on release
                window.preventClickFlag = true;

                if (absY > absX) {
                    // Vertical Swipe
                    if (activeScrollContent && activeScrollContent.scrollTop <= 0 && diffY > 0 && ptrStartY > 0) {
                        isPullingPtr = true;
                    } else {
                        isSwipingY = true;
                    }
                } else {
                    // Horizontal Swipe
                    if (diffX < 0 && activeSwipeCard) {
                        isSwipingCard = true;
                    }
                }
            }
        }

        if (isSwipingY) return;

        // A. Card Swipe (Left swipe to read)
        if (isSwipingCard && activeSwipeCard) {
            if (e.cancelable) e.preventDefault();

            const cardContent = activeSwipeCard.querySelector('.entry-card-content');
            const bgAction = activeSwipeCard.querySelector('.entry-card-bg-action');
            if (cardContent) {
                let distance = diffX;
                if (distance < -100) {
                    distance = -100 + (distance + 100) * 0.4; // Dampened elastic feel
                }
                cardSwipeDistance = Math.min(0, distance);
                cardContent.style.transform = `translateX(${cardSwipeDistance}px)`;
                cardContent.style.transition = 'none';

                if (bgAction) {
                    bgAction.style.opacity = Math.min(1, Math.abs(cardSwipeDistance) / 70);
                }
            }
            return;
        }

        // B. Pull to Refresh
        if (isPullingPtr && activePtrContainer) {
            if (e.cancelable) e.preventDefault();

            const pullDist = clientY - ptrStartY;
            if (pullDist > 0) {
                ptrPullDistance = Math.min(75, pullDist * 0.5); // Friction coeff
                activePtrContainer.style.height = `${ptrPullDistance}px`;
                activePtrContainer.classList.add('visible');
                
                const ptrText = activePtrContainer.querySelector('.ptr-text');
                const ptrIcon = activePtrContainer.querySelector('.ptr-icon');
                if (ptrPullDistance >= 50) {
                    if (ptrText) {
                        ptrText.textContent = '释放立即刷新...';
                    }
                    if (ptrIcon) ptrIcon.style.transform = 'rotate(180deg)';
                } else {
                    if (ptrText) {
                        ptrText.textContent = activePtrContainer === feedsPtrContainer ? '下拉刷新订阅列表...' : '下拉刷新当前列表...';
                    }
                    if (ptrIcon) ptrIcon.style.transform = 'rotate(0deg)';
                }
            }
        }
    }, { passive: false });

    // Handle touch end
    document.addEventListener('touchend', (e) => {
        if (window.innerWidth > 900) return;

        const duration = Date.now() - touchStartTime;
        const touch = e.changedTouches[0];
        const clientX = touch.clientX;
        const diffX = clientX - touchStartX;

        const cleanUp = () => {
            touchStartX = 0;
            touchStartY = 0;
            ptrStartY = 0;
            activeSwipeCard = null;
            isSwipingCard = false;
            isSwipingY = false;
            isPullingPtr = false;
            activePtrContainer = null;
            activeScrollContent = null;
            
            // Retain preventClickFlag briefly to block the trailing click event
            setTimeout(() => {
                window.preventClickFlag = false;
            }, 100);
        };

        // 1. Commit Card Swipe
        if (isSwipingCard && activeSwipeCard) {
            const cardContent = activeSwipeCard.querySelector('.entry-card-content');
            const bgAction = activeSwipeCard.querySelector('.entry-card-bg-action');
            const entryId = parseInt(activeSwipeCard.dataset.id);

            if (cardSwipeDistance < -70) {
                // Swipe out completely
                if (cardContent) {
                    cardContent.classList.add('swiped-out');
                }
                
                setTimeout(async () => {
                    await markSingleEntryAsRead(entryId);
                    
                    if (state.filterUnreadOnly && state.activeView !== 'search' && state.activeView !== 'starred' && state.activeView !== 'notes') {
                        activeSwipeCard.classList.add('collapsed');
                        setTimeout(() => {
                            activeSwipeCard.remove();
                            // Update count label
                            updateEntriesCountLabel();
                            if (elements.entriesList.querySelectorAll('.entry-card').length === 0) {
                                elements.entriesList.innerHTML = `
                                    <div class="empty-state">
                                        <span class="empty-icon">☕</span>
                                        <h3>所有文章已读完</h3>
                                        <p>真棒！已清理完当前订阅源的全部未读。</p>
                                    </div>`;
                             }
                        }, 300);
                    } else {
                        // Keep visible but mark as read style
                        activeSwipeCard.classList.remove('unread');
                        const light = activeSwipeCard.querySelector('.unread-indicator-light');
                        if (light) {
                            light.classList.remove('lit');
                        }
                        if (cardContent) {
                            cardContent.classList.remove('swiped-out');
                            cardContent.style.transition = 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)';
                            cardContent.style.transform = 'translateX(0)';
                        }
                        updateEntriesCountLabel();
                    }
                }, 200);
            } else {
                // Bounce back
                if (cardContent) {
                    cardContent.style.transition = 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)';
                    cardContent.style.transform = 'translateX(0)';
                }
                if (bgAction) {
                    bgAction.style.opacity = '0';
                }
            }
            cleanUp();
            return;
        }

        // 2. Commit Pull to Refresh
        if (isPullingPtr && activePtrContainer) {
            if (ptrPullDistance >= 50) {
                activePtrContainer.style.height = '50px';
                activePtrContainer.classList.add('loading');
                const ptrText = activePtrContainer.querySelector('.ptr-text');
                if (ptrText) ptrText.textContent = '正在刷新...';

                simpleRefresh().finally(() => {
                    activePtrContainer.style.height = '0';
                    activePtrContainer.classList.remove('loading');
                    activePtrContainer.classList.remove('visible');
                    ptrPullDistance = 0;
                    cleanUp();
                });
            } else {
                activePtrContainer.style.height = '0';
                activePtrContainer.classList.remove('visible');
                ptrPullDistance = 0;
                cleanUp();
            }
            return;
        }

        // 3. Commit Global Horizontal Panel Swipe
        if (!isSwipingY && Math.abs(diffX) > 60 && duration < 300) {
            const body = document.body;
            if (diffX > 0) {
                // Swipe Right (Go Back)
                if (body.classList.contains('show-detail')) {
                    elements.mobileBackToEntries.click();
                } else if (body.classList.contains('show-entries')) {
                    elements.mobileBackToFeeds.click();
                }
            } else {
                // Swipe Left (Go Forward)
                if (!body.classList.contains('show-entries')) {
                    body.classList.add('show-entries');
                } else if (!body.classList.contains('show-detail')) {
                    if (state.selectedEntryId) {
                        body.classList.add('show-detail');
                    }
                }
            }
        }

        cleanUp();
    }, { passive: true });
}

async function markSingleEntryAsRead(entryId) {
    try {
        const response = await fetch(`/entries/${entryId}/read`, { method: 'POST' });
        if (response.ok) {
            const entry = state.entries.find(e => e.id === entryId);
            if (entry) {
                entry.is_read = 1;
            }
            if (state.currentOpenEntry && state.currentOpenEntry.id === entryId) {
                state.currentOpenEntry.is_read = 1;
                updateReadButtonUI(1);
            }
            await loadFeeds();
        }
    } catch (e) {
        console.error("Failed to mark entry read during swipe:", e);
    }
}

async function refreshCurrentListView() {
    try {
        if (state.activeView === 'feed') {
            await loadFeedEntries(state.selectedFeedId, false);
        } else if (state.activeView === 'category') {
            await loadCategoryEntries(state.selectedCategoryId, false);
        } else if (state.activeView === 'starred') {
            await loadStarredEntries(false);
        } else if (state.activeView === 'notes') {
            await loadNotesEntries(false);
        } else if (state.activeView === 'search') {
            const query = document.getElementById('search-input').value;
            await loadSearchEntries(query, false);
        } else {
            await loadUnreadEntries(false);
        }
    } catch (e) {
        console.error("Failed to refresh active view:", e);
    }
}

// Draggable Floating AI Assistant Button (for mobile layout safety)
function initDraggableAiButton() {
    // Disabled draggable feature per request - using fixed CSS positioning instead.
}

// ----------------------------------------------------
// ATTENTION PERSONALIZATION & ENGAGEMENT TRACKING
// ----------------------------------------------------
let lastActivityTimeProcessed = 0;

function initEngagementTracking() {
    if (elements.articleScrollView) {
        elements.articleScrollView.addEventListener('scroll', () => {
            if (!currentEngagement) return;
            const scrollTop = elements.articleScrollView.scrollTop;
            const clientHeight = elements.articleScrollView.clientHeight;
            const scrollHeight = elements.articleScrollView.scrollHeight;
            const scrollPct = scrollHeight > clientHeight ? (scrollTop / (scrollHeight - clientHeight)) : 0;
            currentEngagement.maxScrollPct = Math.max(currentEngagement.maxScrollPct, scrollPct);
            
            handleUserActivity();
        });
    }

    if (elements.artOriginalLink) {
        elements.artOriginalLink.addEventListener('click', () => {
            if (currentEngagement) {
                currentEngagement.openedOriginal = true;
            }
        });
    }

    document.addEventListener('mousemove', handleUserActivity);
    document.addEventListener('touchstart', handleUserActivity);
    document.addEventListener('keydown', handleUserActivity);

    document.addEventListener('visibilitychange', () => {
        if (!currentEngagement) return;
        if (document.hidden) {
            stopActiveTimer();
        } else {
            currentEngagement.isActive = true;
            currentEngagement.lastActiveTime = Date.now();
        }
    });

    window.addEventListener('beforeunload', () => {
        submitCurrentEngagement(true);
    });
}

function handleUserActivity() {
    if (!currentEngagement) return;
    const now = Date.now();
    if (now - lastActivityTimeProcessed < 2000) {
        return;
    }
    lastActivityTimeProcessed = now;
    
    clearTimeout(currentEngagement.idleTimer);
    if (!currentEngagement.isActive) {
        currentEngagement.isActive = true;
        currentEngagement.lastActiveTime = now;
    } else {
        currentEngagement.activeDwellMs += (now - currentEngagement.lastActiveTime);
        currentEngagement.lastActiveTime = now;
    }
    
    currentEngagement.idleTimer = setTimeout(stopActiveTimer, 30000);
}

function stopActiveTimer() {
    if (currentEngagement && currentEngagement.isActive) {
        const now = Date.now();
        currentEngagement.activeDwellMs += (now - currentEngagement.lastActiveTime);
        currentEngagement.isActive = false;
    }
}

function submitCurrentEngagement(isBeacon = false) {
    if (!currentEngagement) return;
    
    stopActiveTimer();
    
    const dwell = currentEngagement.activeDwellMs;
    const scrollPct = currentEngagement.maxScrollPct;
    const openedOriginal = currentEngagement.openedOriginal;
    const entryId = currentEngagement.entryId;
    
    clearTimeout(currentEngagement.idleTimer);
    currentEngagement = null;
    
    if (dwell < 2000) {
        return;
    }
    
    const payload = {
        active_dwell_ms: Math.round(dwell),
        scrolled_pct: parseFloat(scrollPct.toFixed(4)),
        opened_original: openedOriginal
    };
    
    const url = `/entries/${entryId}/engagement`;
    
    if (isBeacon && navigator.sendBeacon) {
        navigator.sendBeacon(url, new Blob([JSON.stringify(payload)], { type: 'application/json' }));
    } else {
        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).catch(err => console.warn("Failed to submit engagement data:", err));
    }
}

// ----------------------------------------------------
// READING PROFILE VISUALIZATION
// ----------------------------------------------------
async function showProfileModal() {
    showModal(elements.profileModal);
    
    elements.profileStatusView.classList.remove('hidden');
    elements.profileMainContent.classList.add('hidden');
    elements.profileStatusTitle.textContent = "正在加载...";
    elements.profileStatusDesc.textContent = "正在计算阅读偏好，提炼画像数据...";
    
    try {
        const response = await fetch('/profile/interests');
        if (!response.ok) {
            throw new Error("Failed to fetch profile");
        }
        const data = await response.json();
        state.interestProfileData = data;
        
        if (data.status === 'disabled') {
            elements.profileStatusView.classList.remove('hidden');
            elements.profileMainContent.classList.add('hidden');
            elements.profileStatusTitle.textContent = "智能画像功能已关闭";
            elements.profileStatusDesc.innerHTML = "请在设置中开启「阅读画像与智能分级」以启用本功能。行为数据仅在本地采集，开启偏好分析会每日自动执行一次AI归纳。";
            return;
        }
        
        if (data.status === 'cold_start') {
            elements.profileStatusView.classList.remove('hidden');
            elements.profileMainContent.classList.add('hidden');
            elements.profileStatusTitle.textContent = "智能画像积累中";
            elements.profileStatusDesc.textContent = data.message || "阅读数据积累中，需至少15篇文章的阅读行为。";
            return;
        }
        
        elements.profileStatusView.classList.add('hidden');
        elements.profileMainContent.classList.remove('hidden');
        
        elements.profileStatTotal.textContent = data.total_articles || 0;
        elements.profileStatHigh.textContent = data.high_engagement || 0;
        elements.profileStatLow.textContent = data.low_engagement || 0;
        
        // Reset tabs to Monthly View by default
        state.profileTrendView = 'month';
        if (elements.profileToggleMonth) {
            elements.profileToggleMonth.classList.add('active');
            elements.profileToggleMonth.style.background = 'var(--accent-indigo, #6366f1)';
            elements.profileToggleMonth.style.color = '#fff';
        }
        if (elements.profileToggleWeek) {
            elements.profileToggleWeek.classList.remove('active');
            elements.profileToggleWeek.style.background = 'transparent';
            elements.profileToggleWeek.style.color = 'var(--text-muted)';
        }
        if (elements.profileTabMonthContent) elements.profileTabMonthContent.classList.remove('hidden');
        if (elements.profileTabWeekContent) elements.profileTabWeekContent.classList.add('hidden');
        
        renderProfileTokenStats(data.token_stats || []);
        renderProfileTagCloud(data.topics || { high_interest: [], low_interest: [] });
        if (data.topics) {
            renderProfileHeatmap(data.topics);
            renderProfileCategoryDistribution(data.category_distribution);
        }
        
        if (data.topics && data.topics.concentration_note) {
            elements.profileInsightText.textContent = data.topics.concentration_note;
        } else {
            elements.profileInsightText.textContent = "这是 AI 默默窥探你 30 天后的铁证。如果有些字小到要拿放大镜看，别怀疑，那就是你嘴上高喊‘热爱’却连点都没点过的叶公好龙型兴趣。下次跟人假装博学之前，建议先来这里‘雨露均沾’一下，免得你的信息茧房厚到能防弹。";
        }
        
        // Hide detail panel initially
        elements.profileDetailPanel.classList.add('hidden');
        
    } catch (err) {
        console.error("Failed to load profile modal:", err);
        elements.profileStatusView.classList.remove('hidden');
        elements.profileMainContent.classList.add('hidden');
        elements.profileStatusTitle.textContent = "加载失败";
        elements.profileStatusDesc.textContent = "无法获取阅读画像数据，请稍后重试。";
    }
}

function renderProfileTagCloud(topics) {
    const allTopics = [];
    if (topics.high_interest) {
        topics.high_interest.forEach(t => allTopics.push({ ...t, type: 'high' }));
    }
    if (topics.low_interest) {
        topics.low_interest.forEach(t => allTopics.push({ ...t, type: 'low' }));
    }
    
    // Shuffle
    for (let i = allTopics.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [allTopics[i], allTopics[j]] = [allTopics[j], allTopics[i]];
    }
    
    elements.profileTagCloud.innerHTML = '';
    
    if (allTopics.length === 0) {
        elements.profileTagCloud.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">暂无兴趣标签，阅读更多文章后再来看看吧。</div>';
        return;
    }
    
    allTopics.forEach(tag => {
        const tagEl = document.createElement('span');
        tagEl.textContent = tag.topic;
        tagEl.className = 'profile-tag';
        tagEl.style.cursor = 'pointer';
        tagEl.style.padding = '4px 10px';
        tagEl.style.borderRadius = '20px';
        tagEl.style.border = '1px solid transparent';
        tagEl.style.transition = 'all 0.2s ease';
        tagEl.style.display = 'inline-block';
        tagEl.style.margin = '2px';
        
        if (tag.type === 'high') {
            tagEl.style.fontWeight = '600';
            if (tag.strength === 'high') {
                tagEl.style.fontSize = '16px';
                tagEl.style.color = 'var(--text-inverse, #fff)';
                tagEl.style.background = 'rgba(99, 102, 241, 0.2)';
                tagEl.style.borderColor = 'rgba(99, 102, 241, 0.4)';
            } else {
                tagEl.style.fontSize = '14px';
                tagEl.style.color = 'var(--text-primary, #e2e8f0)';
                tagEl.style.background = 'rgba(16, 185, 129, 0.15)';
                tagEl.style.borderColor = 'rgba(16, 185, 129, 0.3)';
            }
        } else {
            tagEl.style.fontWeight = '400';
            tagEl.style.fontSize = '12px';
            tagEl.style.color = 'var(--text-muted, #64748b)';
            tagEl.style.background = 'rgba(255, 255, 255, 0.02)';
            tagEl.style.borderColor = 'var(--border-color)';
        }
        
        tagEl.addEventListener('mouseenter', () => {
            tagEl.style.transform = 'scale(1.05)';
            if (tag.type === 'high') {
                tagEl.style.boxShadow = '0 0 10px rgba(99, 102, 241, 0.2)';
            } else {
                tagEl.style.background = 'rgba(255, 255, 255, 0.05)';
            }
        });
        tagEl.addEventListener('mouseleave', () => {
            tagEl.style.transform = 'scale(1)';
            tagEl.style.boxShadow = 'none';
            if (tag.type === 'low') {
                tagEl.style.background = 'rgba(255, 255, 255, 0.02)';
            }
        });
        
        tagEl.addEventListener('click', () => {
            elements.profileTagCloud.querySelectorAll('.profile-tag').forEach(el => {
                el.style.outline = 'none';
            });
            tagEl.style.outline = '2px solid var(--accent-indigo, #6366f1)';
            tagEl.style.outlineOffset = '2px';
            
            showTopicDetail(tag.topic);
        });
        
        elements.profileTagCloud.appendChild(tagEl);
    });
}

async function showTopicDetail(topicName) {
    elements.profileDetailPanel.classList.remove('hidden');
    elements.profileDetailTitle.textContent = topicName;
    elements.profileDetailCount.textContent = '-';
    elements.profileDetailStarred.textContent = '-';
    elements.profileDetailOriginal.textContent = '-';
    elements.profileDetailTrend.innerHTML = '<div style="color:var(--text-muted); font-size:11px; margin: auto;">加载中...</div>';
    elements.profileDetailArticles.innerHTML = '<div style="color:var(--text-muted); font-size:11px; text-align:center; padding:20px;">正在加载相关文章...</div>';
    
    try {
        const response = await fetch(`/profile/topic-detail?topic=${encodeURIComponent(topicName)}`);
        if (!response.ok) {
            throw new Error("Failed to fetch topic details");
        }
        const data = await response.json();
        
        elements.profileDetailCount.textContent = data.stats.article_count;
        elements.profileDetailStarred.textContent = data.stats.favorite_count;
        elements.profileDetailOriginal.textContent = data.stats.original_count;
        
        // Render Trend Chart
        elements.profileDetailTrend.innerHTML = '';
        if (elements.profileDetailTrendTitle) elements.profileDetailTrendTitle.textContent = '近4周阅读活跃度趋势';
        const trendToShow = data.weekly_trend.slice(8); // show last 4 weeks (indices 8, 9, 10, 11)
        const maxVal = Math.max(...trendToShow, 1);
        const colLabels = ['4周前', '3周前', '2周前', '本周'];
        trendToShow.forEach((count, i) => {
            const barHeightPct = (count / maxVal) * 100;
            const bar = document.createElement('div');
            bar.style.width = '20%';
            bar.style.height = `${Math.max(barHeightPct, 5)}%`;
            bar.style.backgroundColor = 'var(--accent-indigo, #6366f1)';
            bar.style.borderRadius = '3px 3px 0 0';
            bar.style.opacity = count > 0 ? (0.3 + (count / maxVal) * 0.7) : 0.1;
            bar.title = `${colLabels[i]}: ${count} 篇`;
            elements.profileDetailTrend.appendChild(bar);
        });
        
        // Render Articles List
        elements.profileDetailArticles.innerHTML = '';
        if (!data.articles || data.articles.length === 0) {
            elements.profileDetailArticles.innerHTML = '<div style="color:var(--text-muted); font-size:12px; text-align:center; padding: 20px;">该话题的深度阅读文章较少，暂无记录</div>';
            return;
        }
        
        data.articles.forEach(art => {
            const artEl = document.createElement('div');
            artEl.className = 'profile-detail-article-item';
            artEl.style.display = 'flex';
            artEl.style.justifyContent = 'space-between';
            artEl.style.alignItems = 'center';
            artEl.style.padding = '6px 8px';
            artEl.style.borderRadius = '4px';
            artEl.style.background = 'rgba(255, 255, 255, 0.01)';
            artEl.style.border = '1px solid transparent';
            artEl.style.cursor = 'pointer';
            artEl.style.transition = 'all 0.2s';
            
            artEl.addEventListener('mouseenter', () => {
                artEl.style.background = 'rgba(255, 255, 255, 0.04)';
                artEl.style.borderColor = 'var(--border-color)';
            });
            artEl.addEventListener('mouseleave', () => {
                artEl.style.background = 'rgba(255, 255, 255, 0.01)';
                artEl.style.borderColor = 'transparent';
            });
            
            const leftEl = document.createElement('div');
            leftEl.style.display = 'flex';
            leftEl.style.flexDirection = 'column';
            leftEl.style.gap = '2px';
            leftEl.style.maxWidth = '75%';
            
            const titleSpan = document.createElement('span');
            titleSpan.textContent = art.title;
            titleSpan.style.fontSize = '12px';
            titleSpan.style.fontWeight = '500';
            titleSpan.style.color = 'var(--text-primary)';
            titleSpan.style.whiteSpace = 'nowrap';
            titleSpan.style.overflow = 'hidden';
            titleSpan.style.textOverflow = 'ellipsis';
            
            const sourceSpan = document.createElement('span');
            sourceSpan.textContent = art.source;
            sourceSpan.style.fontSize = '10px';
            sourceSpan.style.color = 'var(--text-muted)';
            
            leftEl.appendChild(titleSpan);
            leftEl.appendChild(sourceSpan);
            
            const rightEl = document.createElement('div');
            rightEl.style.display = 'flex';
            rightEl.style.gap = '6px';
            
            if (art.badges && art.badges.includes('favorited')) {
                const starBadge = document.createElement('span');
                starBadge.textContent = '⭐';
                starBadge.title = '已收藏';
                starBadge.style.fontSize = '11px';
                rightEl.appendChild(starBadge);
            }
            if (art.badges && art.badges.includes('opened_original')) {
                const linkBadge = document.createElement('span');
                linkBadge.textContent = '🔗';
                linkBadge.title = '已访问原文';
                linkBadge.style.fontSize = '11px';
                rightEl.appendChild(linkBadge);
            }
            
            artEl.appendChild(leftEl);
            artEl.appendChild(rightEl);
            
            artEl.addEventListener('click', () => {
                hideAllModals();
                selectEntry(art.entry_id);
            });
            
            elements.profileDetailArticles.appendChild(artEl);
        });
        
    } catch (err) {
        console.error("Failed to load topic details:", err);
        elements.profileDetailArticles.innerHTML = '<div style="color:var(--text-muted); font-size:12px; text-align:center; padding: 20px;">加载详情失败</div>';
    }
}

function renderProfileTokenStats(tokenStats) {
    if (!elements.profileActivityHeatmap) return;
    elements.profileActivityHeatmap.innerHTML = '';
    
    if (elements.profileHeatmapLegend) {
        elements.profileHeatmapLegend.classList.add('hidden');
    }
    
    const container = elements.profileActivityHeatmap;
    container.style.display = 'flex';
    container.style.flexDirection = 'row';
    container.style.alignItems = 'flex-end';
    container.style.justifyContent = 'space-between';
    container.style.height = '160px';
    container.style.padding = '20px 10px 10px 10px';
    container.style.gap = '15px';
    container.style.minWidth = 'unset';
    
    // Find max token count to scale the bars
    const maxTokens = Math.max(...tokenStats.map(d => d.total_tokens), 1);
    
    tokenStats.forEach(day => {
        const col = document.createElement('div');
        col.style.display = 'flex';
        col.style.flexDirection = 'column';
        col.style.alignItems = 'center';
        col.style.flex = '1';
        col.style.height = '100%';
        col.style.justifyContent = 'flex-end';
        
        // Bar wrapper to align bar at bottom
        const barWrapper = document.createElement('div');
        barWrapper.style.width = '100%';
        barWrapper.style.flex = '1';
        barWrapper.style.display = 'flex';
        barWrapper.style.flexDirection = 'column';
        barWrapper.style.justifyContent = 'flex-end';
        barWrapper.style.alignItems = 'center';
        barWrapper.style.position = 'relative';
        
        // The bar itself
        const ratio = day.total_tokens / maxTokens;
        const bar = document.createElement('div');
        bar.style.width = '70%';
        bar.style.maxWidth = '30px';
        bar.style.height = `${Math.max(ratio * 100, 2)}%`;
        bar.style.background = 'linear-gradient(180deg, var(--accent-indigo, #6366f1) 0%, rgba(99, 102, 241, 0.4) 100%)';
        bar.style.borderRadius = '4px 4px 0 0';
        bar.style.transition = 'all 0.3s ease';
        bar.style.cursor = 'pointer';
        
        // Tooltip or text bubble on hover
        const tokenLabel = document.createElement('div');
        tokenLabel.style.position = 'absolute';
        tokenLabel.style.bottom = `${ratio * 100 + 4}%`;
        tokenLabel.style.fontSize = '9px';
        tokenLabel.style.color = 'var(--text-primary)';
        tokenLabel.style.fontWeight = '600';
        tokenLabel.style.opacity = '0';
        tokenLabel.style.transition = 'opacity 0.2s';
        tokenLabel.style.whiteSpace = 'nowrap';
        tokenLabel.textContent = day.total_tokens;
        barWrapper.appendChild(tokenLabel);
        
        // Show label on hover
        bar.addEventListener('mouseenter', () => {
            bar.style.filter = 'brightness(1.2)';
            tokenLabel.style.opacity = '1';
        });
        bar.addEventListener('mouseleave', () => {
            bar.style.filter = 'none';
            tokenLabel.style.opacity = '0';
        });
        
        barWrapper.appendChild(bar);
        col.appendChild(barWrapper);
        
        // Date label
        const dateLabel = document.createElement('div');
        dateLabel.style.fontSize = '10px';
        dateLabel.style.color = 'var(--text-secondary)';
        dateLabel.style.marginTop = '6px';
        const shortDate = day.date.slice(5);
        dateLabel.textContent = shortDate;
        col.appendChild(dateLabel);
        
        container.appendChild(col);
    });

    // Generate insights in the insight box
    if (elements.profileHabitInsightText) {
        const totalTokensUsed = tokenStats.reduce((sum, d) => sum + d.total_tokens, 0);
        const avgTokens = Math.round(totalTokensUsed / (tokenStats.length || 1));
        elements.profileHabitInsightText.innerHTML = `过去 7 天您共消耗了 <strong>${totalTokensUsed}</strong> 个 Token（平均每日 <strong>${avgTokens}</strong> 个），主要用于文章注意力评估与大模型摘要服务。`;
    }
}
    
    let peakPeriod = 0;
    let maxPeriodVal = 0;
    for (let r = 0; r < 4; r++) {
        if (periodSums[r] > maxPeriodVal) {
            maxPeriodVal = periodSums[r];
            peakPeriod = r;
        }
    }
    
    let habitText = '';
    if (timestamps.length === 0) {
        habitText = '暂无足够阅读活动记录。多看几篇新闻，你的每日阅读习惯就会出现在这里哦！';
    } else {
        if (peakPeriod === 3) {
            habitText = '仙风道骨！统计发现你最常在【深夜/凌晨】看新闻。熬最深的夜，吃最烫的信息瓜，你是名副其实的“修仙党”——注意护肝哦！';
        } else if (peakPeriod === 0) {
            habitText = '晨光熹微，元气满满！你最习惯在【清晨/上午】开启阅读。用天下大事唤醒沉睡的细胞，自律程度拉满，今天也是充实的一天！';
        } else if (peakPeriod === 1) {
            habitText = '咖啡续命，摸鱼大师！你爱在【中午/下午】工作间隙刷新闻。这叫劳逸结合、科学放松，我们懂的（主编暗示：在偷偷偷懒吧？）。';
        } else if (peakPeriod === 2) {
            habitText = '日落西山，静享时光。你最钟爱在【傍晚/晚上】静心阅读。洗净一天的喧嚣与疲惫，慢慢品读这个世界，阅读体验极佳。';
        } else {
            habitText = '规律得像个机器人！你的阅读分布非常均匀，成功避开了所有极端的摸鱼或修仙时段。佩服佩服！';
        }
    }
    
    if (elements.profileHabitInsightText) {
        elements.profileHabitInsightText.textContent = habitText;
    }
}

function renderProfileCategoryDistribution(categoryDistribution) {
    if (!elements.profileCategoryDistributionList) return;
    elements.profileCategoryDistributionList.innerHTML = '';
    
    if (!categoryDistribution || categoryDistribution.length === 0) {
        elements.profileCategoryDistributionList.innerHTML = '<div style="color:var(--text-muted); font-size:12px; text-align:center;">暂无分类阅读统计</div>';
        return;
    }
    
    const totalCount = categoryDistribution.reduce((acc, c) => acc + c.count, 0) || 1;
    
    categoryDistribution.forEach(cat => {
        const pct = Math.round((cat.count / totalCount) * 100);
        
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.flexDirection = 'column';
        row.style.gap = '4px';
        
        const labelRow = document.createElement('div');
        labelRow.style.display = 'flex';
        labelRow.style.justifyContent = 'space-between';
        labelRow.style.fontSize = '11px';
        labelRow.style.fontWeight = '500';
        labelRow.style.color = 'var(--text-secondary)';
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = cat.name;
        
        const countSpan = document.createElement('span');
        countSpan.textContent = `${cat.count} 篇 (${pct}%)`;
        countSpan.style.color = 'var(--text-muted)';
        
        labelRow.appendChild(nameSpan);
        labelRow.appendChild(countSpan);
        
        const barContainer = document.createElement('div');
        barContainer.style.width = '100%';
        barContainer.style.height = '6px';
        barContainer.style.background = 'rgba(255, 255, 255, 0.03)';
        barContainer.style.borderRadius = '3px';
        barContainer.style.overflow = 'hidden';
        
        const fillBar = document.createElement('div');
        fillBar.style.width = `${pct}%`;
        fillBar.style.height = '100%';
        fillBar.style.background = 'var(--accent-indigo, #6366f1)';
        fillBar.style.borderRadius = '3px';
        
        barContainer.appendChild(fillBar);
        row.appendChild(labelRow);
        row.appendChild(barContainer);
        
        elements.profileCategoryDistributionList.appendChild(row);
    });
}

async function renderProfileHeatmap(topics) {
    const high = topics.high_interest || [];
    const low = topics.low_interest || [];
    const coreTopics = [...high.map(t => t.topic), ...low.slice(0, 2).map(t => t.topic)].slice(0, 8);
    
    elements.profileHeatmapContainer.innerHTML = '<div style="color:var(--text-muted); font-size:11px; text-align:center; padding: 10px;">正在加载趋势热力图...</div>';
    
    try {
        const detailPromises = coreTopics.map(topic => 
            fetch(`/profile/topic-detail?topic=${encodeURIComponent(topic)}`)
                .then(res => {
                    if (!res.ok) throw new Error("Fetch failed");
                    return res.json();
                })
                .catch(() => null)
        );
        
        const details = await Promise.all(detailPromises);
        
        elements.profileHeatmapContainer.innerHTML = '';
        
        const validDetails = details.filter(d => d !== null);
        if (validDetails.length === 0) {
            elements.profileHeatmapContainer.innerHTML = '<div style="color:var(--text-muted); font-size:11px; text-align:center; padding: 10px;">暂无趋势数据</div>';
            return;
        }
        
        // Find global max value to scale the heatmap opacity relatively across all topics
        const globalMaxVal = Math.max(...validDetails.flatMap(d => d.weekly_trend.slice(8)), 1);
        
        const headerRow = document.createElement('div');
        headerRow.style.display = 'flex';
        headerRow.style.alignItems = 'center';
        headerRow.style.gap = '4px';
        headerRow.style.fontSize = '9px';
        headerRow.style.color = 'var(--text-muted)';
        headerRow.style.fontWeight = '600';
        headerRow.style.paddingBottom = '4px';
        headerRow.style.borderBottom = '1px solid var(--border-color)';
        
        const topicColHeader = document.createElement('div');
        topicColHeader.style.width = '120px';
        topicColHeader.textContent = '话题';
        headerRow.appendChild(topicColHeader);
        
        const weeksContainerHeader = document.createElement('div');
        weeksContainerHeader.style.display = 'flex';
        weeksContainerHeader.style.gap = '4px';
        weeksContainerHeader.style.flex = '1';
        weeksContainerHeader.style.justifyContent = 'space-between';
        
        const colLabels = ['4周前', '3周前', '2周前', '本周'];
        colLabels.forEach(label => {
            const wLabel = document.createElement('div');
            wLabel.style.width = '45px';
            wLabel.style.textAlign = 'center';
            wLabel.textContent = label;
            weeksContainerHeader.appendChild(wLabel);
        });
        headerRow.appendChild(weeksContainerHeader);
        elements.profileHeatmapContainer.appendChild(headerRow);
        
        validDetails.forEach(detail => {
            const row = document.createElement('div');
            row.style.display = 'flex';
            row.style.alignItems = 'center';
            row.style.gap = '4px';
            row.style.padding = '4px 0';
            row.style.borderBottom = '1px solid rgba(255, 255, 255, 0.02)';
            
            const topicLabel = document.createElement('div');
            topicLabel.style.width = '120px';
            topicLabel.style.fontSize = '11px';
            topicLabel.style.fontWeight = '500';
            topicLabel.style.color = 'var(--text-secondary)';
            topicLabel.style.whiteSpace = 'nowrap';
            topicLabel.style.overflow = 'hidden';
            topicLabel.style.textOverflow = 'ellipsis';
            topicLabel.textContent = detail.topic;
            topicLabel.title = detail.topic;
            row.appendChild(topicLabel);
            
            const weeksContainer = document.createElement('div');
            weeksContainer.style.display = 'flex';
            weeksContainer.style.gap = '4px';
            weeksContainer.style.flex = '1';
            weeksContainer.style.justifyContent = 'space-between';
            
            const trendToShow = detail.weekly_trend.slice(8); // show last 4 weeks (indices 8, 9, 10, 11)
            trendToShow.forEach((count, i) => {
                const cell = document.createElement('div');
                cell.style.width = '45px';
                cell.style.height = '20px';
                cell.style.borderRadius = '3px';
                
                if (count === 0) {
                    cell.style.backgroundColor = 'rgba(255, 255, 255, 0.02)';
                    cell.style.border = '1px solid rgba(255, 255, 255, 0.03)';
                } else {
                    const ratio = count / globalMaxVal;
                    cell.style.backgroundColor = 'var(--accent-indigo, #6366f1)';
                    cell.style.opacity = 0.15 + ratio * 0.85;
                }
                
                cell.style.cursor = 'pointer';
                cell.title = `${detail.topic}\n${colLabels[i]}: ${count}篇`;
                
                weeksContainer.appendChild(cell);
            });
            row.appendChild(weeksContainer);
            
            elements.profileHeatmapContainer.appendChild(row);
        });
        
        const legendRow = document.createElement('div');
        legendRow.style.display = 'flex';
        legendRow.style.justifyContent = 'flex-end';
        legendRow.style.alignItems = 'center';
        legendRow.style.gap = '6px';
        legendRow.style.marginTop = '10px';
        legendRow.style.fontSize = '9px';
        legendRow.style.color = 'var(--text-muted)';
        
        const lessLabel = document.createElement('span');
        lessLabel.textContent = '少';
        legendRow.appendChild(lessLabel);
        
        const legendLevels = [0, 0.25, 0.5, 0.75, 1];
        legendLevels.forEach(level => {
            const cell = document.createElement('div');
            cell.style.width = '10px';
            cell.style.height = '10px';
            cell.style.borderRadius = '2px';
            if (level === 0) {
                cell.style.backgroundColor = 'rgba(255, 255, 255, 0.02)';
                cell.style.border = '1px solid rgba(255, 255, 255, 0.03)';
            } else {
                cell.style.backgroundColor = 'var(--accent-indigo, #6366f1)';
                cell.style.opacity = 0.2 + level * 0.8;
            }
            legendRow.appendChild(cell);
        });
        
        const moreLabel = document.createElement('span');
        moreLabel.textContent = '多';
        legendRow.appendChild(moreLabel);
        
        elements.profileHeatmapContainer.appendChild(legendRow);
        
    } catch (err) {
        console.error("Failed to render profile heatmap:", err);
        elements.profileHeatmapContainer.innerHTML = '<div style="color:var(--text-muted); font-size:11px; text-align:center; padding: 10px;">趋势热力图加载失败</div>';
    }
}
