/**
 * i18n - Internationalization Module
 * Provides language detection and translation management
 */

let currentLanguage = "de";
let translations = {};

/**
 * Detect browser language and load appropriate translation file
 */
async function initializeI18n() {
  // Check if user has previously selected a language
  const storedLanguage = localStorage.getItem("entfernungsspiel.language");
  
  if (storedLanguage) {
    // Use stored language preference
    currentLanguage = storedLanguage;
    console.log(`[i18n] Using stored language preference: ${currentLanguage}`);
  } else {
    // Determine user language preference from browser
    const browserLanguage = navigator.language || navigator.userLanguage;
    
    // Extract language code (e.g., "de-DE" -> "de", "en-US" -> "en")
    const languageCode = browserLanguage.split("-")[0].toLowerCase();
    
    // Supported languages: "de" or "en"
    const supportedLanguages = ["de", "en"];
    currentLanguage = supportedLanguages.includes(languageCode) ? languageCode : "de";
    
    console.log(`[i18n] Detected language: ${browserLanguage}, using: ${currentLanguage}`);
  }
  
  // Load translation file
  try {
    const response = await fetch(`static/i18n/${currentLanguage}.json`);
    if (!response.ok) {
      throw new Error(`Failed to load ${currentLanguage}.json`);
    }
    translations = await response.json();
    console.log(`[i18n] Loaded translations for: ${currentLanguage}`);
  } catch (error) {
    console.error(`[i18n] Error loading translations:`, error);
    // Fallback to German
    currentLanguage = "de";
    try {
      const response = await fetch("static/i18n/de.json");
      translations = await response.json();
      console.log("[i18n] Loaded fallback German translations");
    } catch (fallbackError) {
      console.error("[i18n] Critical: Could not load fallback translations", fallbackError);
    }
  }
}

/**
 * Get translated string using dot notation path
 * Example: t("messages.gameCreated") -> returns translated string
 * Supports template substitution: t("messages.roundUpdate", { round: 1, max: 5 })
 */
function t(key, substitutions = {}) {
  const keys = key.split(".");
  let value = translations;
  
  for (const k of keys) {
    if (value && typeof value === "object" && k in value) {
      value = value[k];
    } else {
      console.warn(`[i18n] Missing translation key: ${key}`);
      return key; // Return key as fallback
    }
  }
  
  if (typeof value !== "string") {
    console.warn(`[i18n] Translation value is not a string: ${key}`);
    return key;
  }
  
  // Replace template variables: {variableName}
  let result = value;
  for (const [key, val] of Object.entries(substitutions)) {
    result = result.replace(new RegExp(`\\{${key}\\}`, "g"), val);
  }
  
  return result;
}

function normalizeI18nKey(rawKey) {
  if (typeof rawKey !== "string") return "";
  // Tolerate accidentally escaped/quoted attribute values like \"answer.shortcut\".
  let key = rawKey.trim();
  key = key.replace(/\\/g, "");
  key = key.replace(/^"+|"+$/g, "");
  return key;
}

/**
 * Get current language code
 */
function getLanguage() {
  return currentLanguage;
}

/**
 * Set language and reload translations
 */
async function setLanguage(langCode) {
  if (langCode !== currentLanguage) {
    currentLanguage = langCode;
    try {
      const response = await fetch(`static/i18n/${langCode}.json`);
      translations = await response.json();
      console.log(`[i18n] Switched to language: ${langCode}`);
      updateUILanguage(); // Update DOM with new translations
    } catch (error) {
      console.error(`[i18n] Error switching language:`, error);
    }
  }
}

/**
 * Update all UI elements with new language
 * This is called after language change
 */
function updateUILanguage() {
  // Update static content
  const titleEl = document.querySelector("h1.title");
  if (titleEl) titleEl.textContent = t("common.title");
  
  const subtitleEl = document.querySelector("p.subtitle");
  if (subtitleEl) subtitleEl.textContent = t("common.subtitle");
  
  // Update all data-i18n attributes
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = normalizeI18nKey(el.getAttribute("data-i18n"));
    if (!key) return;
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      el.placeholder = t(key);
    } else {
      el.textContent = t(key);
    }
  });
  
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    const key = normalizeI18nKey(el.getAttribute("data-i18n-html"));
    if (!key) return;
    el.innerHTML = t(key);
  });
  
  // Update language button states
  const langDE = document.getElementById("langDE");
  const langEN = document.getElementById("langEN");
  if (langDE && langEN) {
    langDE.classList.toggle("lang-btn-active", currentLanguage === "de");
    langEN.classList.toggle("lang-btn-active", currentLanguage === "en");
  }
}
