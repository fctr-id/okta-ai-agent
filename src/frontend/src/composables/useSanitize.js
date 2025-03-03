import { ref } from "vue";

/**
 * Composable for input sanitization and validation
 *
 * @returns {Object} Sanitization utility functions
 */
export function useSanitize() {
    // Keep track of sanitization actions for debugging (optional)
    const sanitizationLog = ref([]);

    /**
     * Sanitize general text input
     * @param {string} input - Text to sanitize
     * @param {Object} options - Options
     * @returns {string} - Sanitized text
     */
    const text = (input, options = {}) => {
        const { maxLength = 2000, removeHtml = true, trim = true } = options;

        if (!input) return "";

        let result = String(input);

        // Limit length
        if (maxLength && result.length > maxLength) {
            result = result.substring(0, maxLength);
            logSanitization("text", "truncated", input, result);
        }

        // Remove HTML tags
        if (removeHtml) {
            const originalLength = result.length;
            result = result.replace(/<[^>]*>/g, "");
            if (result.length !== originalLength) {
                logSanitization("text", "removed HTML", input, result);
            }
        }

        // Remove control characters except newlines and tabs
        const originalLength = result.length;
        result = result.replace(/[\x00-\x09\x0B-\x1F\x7F]/g, "");
        if (result.length !== originalLength) {
            logSanitization("text", "removed control chars", input, result);
        }

        // Trim if requested
        if (trim) {
            result = result.trim();
        }

        return result;
    };

    /**
     * Sanitize username/identifier
     * @param {string} input - Username to sanitize
     * @param {Object} options - Options
     * @returns {string} - Sanitized username
     */
    const username = (input, options = {}) => {
        const { maxLength = 20, allowedPattern = /^[a-zA-Z0-9_-]+$/ } = options;

        if (!input) return "";

        let result = String(input);

        // Limit length
        if (result.length > maxLength) {
            result = result.substring(0, maxLength);
            logSanitization("username", "truncated", input, result);
        }

        // Only allow characters matching pattern
        if (allowedPattern) {
            const originalValue = result;
            result = result
                .split("")
                .filter((char) => allowedPattern.test(char))
                .join("");

            if (result !== originalValue) {
                logSanitization("username", "filtered chars", input, result);
            }
        }

        return result;
    };

    /**
     * Sanitize URL
     * @param {string} input - URL to sanitize
     * @returns {string} - Sanitized URL
     */
    const url = (input) => {
        if (!input) return "";

        let result = String(input).trim();

        // Force HTTPS or relative URL
        if (result.match(/^http:/i)) {
            const originalUrl = result;
            result = result.replace(/^http:/i, "https:");
            logSanitization("url", "forced HTTPS", input, result);
        }

        // Check for JavaScript URLs
        if (result.match(/^javascript:/i) || result.match(/^data:/i) || result.match(/^vbscript:/i)) {
            logSanitization("url", "blocked unsafe protocol", input, "");
            return "#"; // Return harmless link
        }

        return result;
    };

    /**
     * Sanitize natural language query
     * @param {string} input - Query to sanitize
     * @param {Object} options - Options
     * @returns {string} - Sanitized query
     */
    const query = (input, options = {}) => {
        const { maxLength = 2000 } = options;

        if (!input) return "";

        let result = String(input);

        // Limit length
        if (maxLength && result.length > maxLength) {
            result = result.substring(0, maxLength);
            logSanitization("query", "truncated", input, result);
        }

        // Remove HTML tags
        const originalLength = result.length;
        result = result.replace(/<[^>]*>/g, "");
        if (result.length !== originalLength) {
            logSanitization("query", "removed HTML", input, result);
        }

        // Remove control characters except newlines and tabs
        const newLength = result.length;
        result = result.replace(/[\x00-\x09\x0B-\x1F\x7F]/g, "");
        if (result.length !== newLength) {
            logSanitization("query", "removed control chars", input, result);
        }

        return result;
    };

    /**
     * Log sanitization action for debugging
     */
    const logSanitization = (type, action, original, result) => {
        sanitizationLog.value.push({
            timestamp: new Date(),
            type,
            action,
            original: typeof original === "string" ? original.substring(0, 30) : original,
            result: typeof result === "string" ? result.substring(0, 30) : result,
        });

        // Optional: Keep log limited to recent entries
        if (sanitizationLog.value.length > 100) {
            sanitizationLog.value.shift();
        }
    };

    // Clear the sanitization log
    const clearLog = () => {
        sanitizationLog.value = [];
    };

    return {
        text, // For general text inputs
        username, // For usernames and identifiers
        url, // For URL sanitization
        query, // For natural language queries
        sanitizationLog,
        clearLog,
    };
}
