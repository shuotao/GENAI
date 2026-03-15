/**
 * 本地開發用配置文件
 *
 * 使用方式：
 * 1. 複製此文件為 config.local.js（與此檔同目錄）
 * 2. 填入你的 API Key
 * 3. 打開 studio.html，config.local.js 會自動加載並填入 API Key
 *
 * 注意：
 * - config.local.js 已加入 .gitignore，不會被上傳到 GitHub
 * - 生產環境（GitHub Pages）不會加載此文件，用戶需手動輸入 API Key
 */

// 本地開發用 API Keys
const LOCAL_CONFIG = {
    GROQ_API_KEY: 'your-groq-api-key-here',
    GEMINI_API_KEY: 'your-gemini-api-key-here'
};

// 頁面加載時自動填入輸入框
document.addEventListener('DOMContentLoaded', () => {
    if (LOCAL_CONFIG.GROQ_API_KEY && LOCAL_CONFIG.GROQ_API_KEY !== 'your-groq-api-key-here') {
        const groqEl = document.getElementById('groq-key');
        if (groqEl) groqEl.value = LOCAL_CONFIG.GROQ_API_KEY;
    }
    if (LOCAL_CONFIG.GEMINI_API_KEY && LOCAL_CONFIG.GEMINI_API_KEY !== 'your-gemini-api-key-here') {
        const geminiEl = document.getElementById('gemini-key-2');
        if (geminiEl) geminiEl.value = LOCAL_CONFIG.GEMINI_API_KEY;
    }
});
