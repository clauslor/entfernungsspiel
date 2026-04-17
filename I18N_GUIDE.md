# i18n Implementation Guide

## Overview
The game now supports both German (de) and English (en) languages with automatic browser language detection.

## How It Works

### 1. **Browser Language Detection**
- JavaScript detects the browser's language via `navigator.language` or `navigator.languages`
- If browser is set to German (de), German translations load
- If browser is set to English (en), English translations load
- Falls back to German (de) if neither is configured
- Detected language is logged to browser console: `[i18n] Detected language: de-DE, using: de`

### 2. **Translation Files**
Located in `static/i18n/`:
- `de.json` - German translations
- `en.json` - English translations

Both files contain identical key structures with language-specific values.

### 3. **Frontend Integration**

#### Static HTML Elements
Use `data-i18n` attributes on HTML elements:
```html
<h2 class="card-title" data-i18n="answer.title">📍 Your Answer</h2>
<input placeholder="Distance in km" data-i18n="question.placeholder">
```

The `updateUILanguage()` function updates all elements with `data-i18n` on page load and language change.

#### Dynamic JavaScript Text
Use the `t()` function with dot notation:
```javascript
appendMessage(t("messages.ready"));  // Returns "✅ Ready to play!" or equivalent
```

With template substitution:
```javascript
t("question.distanceTemplate", { city1: "Berlin", city2: "Dresden" })
// Returns: "How far is it from Berlin to Dresden? (in km)" or German equivalent
```

#### Dynamic HTML Content
Use `data-i18n-html` for HTML content that needs translation.

### 4. **Backend Integration**
- Backend sends language-neutral or English questions
- Frontend translates question text to current user's language
- Allows players with different languages in the same game

### 5. **Translation Keys Reference**

#### Common
- `common.title` - Game title
- `common.subtitle` - Game subtitle

#### Messages
- `messages.ready` - Connection established
- `messages.disconnected` - Connection lost
- `messages.connectionError` - Connection error
- `messages.gameCreated` - Game created notification
- `messages.gameJoined` - Game joined notification
- `messages.roundUpdate` - Round update prefix

#### Questions
- `question.distanceTemplate` - Distance question template with {city1}, {city2}

#### Countdown
- `countdown.startingIn` - Game starts in
- `countdown.answerTimeRemaining` - Answer time remaining
- `countdown.timesUp` - Time's up
- `countdown.waiting` - Waiting to start
- `countdown.paused` - Paused

## Testing

### Method 1: Browser Language Settings
1. Open browser DevTools (F12)
2. Settings → Language preferences
3. Change to German (de) or English (en)
4. Reload page
5. Verify UI text changes

### Method 2: Console Testing
```javascript
// Check current language
getLanguage()  // Returns "de" or "en"

// Switch language
await setLanguage("en")
// Or
await setLanguage("de")

// Get translated text
t("messages.ready")
t("question.distanceTemplate", { city1: "Berlin", city2: "Dresden" })
```

### Method 3: Check Network Tab
1. Open DevTools → Network tab
2. Look for requests to:
   - `static/i18n/de.json`
   - `static/i18n/en.json`
3. Verify the JSON loads correctly with 200 status

## Adding New Translations

1. **Edit both `de.json` and `en.json`**
2. **Add key in both files** (keys must be identical)
3. **Use in code**:
   ```javascript
   // In JavaScript
   t("new_category.new_key")
   
   // In HTML
   <element data-i18n="new_category.new_key">Default text</element>
   ```

## Known Limitations

1. **Multi-language Games**: If players have different browser languages in the same game, each sees text in their own language. Game text (cities, numbers) remains language-neutral.
2. **Backend Messages**: Some debug/logging messages are still in German. These are internal and not shown to players.
3. **Dynamic Content**: Player names, game IDs, and other user-generated content are not translated (correct behavior).

## Troubleshooting

### Translations not loading
- Check browser console for `[i18n]` log messages
- Verify `static/i18n/` directory exists and contains both JSON files
- Check network requests for failed JSON loads

### Wrong language loaded
- Check browser language settings
- Clear browser cache and reload
- Try explicit language switch: `await setLanguage("en")`

### Missing translation key
- Check console for warning: `[i18n] Missing translation key: category.key`
- Add missing key to both `de.json` and `en.json`
- Verify JSON syntax is valid (commas, quotes, etc.)
