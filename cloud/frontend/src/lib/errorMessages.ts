/**
 * Maps API error messages (English) to i18n keys.
 *
 * The backend returns hardcoded English error strings.
 * This module matches them to translation keys so the frontend
 * can display localised messages via next-intl.
 */

interface ErrorPattern {
  /** Regex to match the English error detail from the API. */
  pattern: RegExp;
  /** i18n key under the "errors" namespace. */
  key: string;
  /** Extract dynamic params from the regex match. */
  params?: (match: RegExpMatchArray) => Record<string, string>;
}

const patterns: ErrorPattern[] = [
  {
    pattern: /^Concurrent test limit reached \((\d+)\)/,
    key: "concurrentLimit",
    params: (m) => ({ limit: m[1] }),
  },
  {
    pattern: /^Monthly test limit reached \((\d+)\)\. Upgrade/,
    key: "monthlyLimitFree",
    params: (m) => ({ limit: m[1] }),
  },
  {
    pattern: /^Monthly test limit reached \((\d+)\)/,
    key: "monthlyLimit",
    params: (m) => ({ limit: m[1] }),
  },
  { pattern: /^Test not found$/, key: "testNotFound" },
  { pattern: /^Not authenticated$/, key: "notAuthenticated" },
  { pattern: /^Token expired/, key: "tokenExpired" },
  { pattern: /^Invalid token/, key: "tokenExpired" },
  { pattern: /^Cannot edit scenarios in/, key: "cannotEditStatus" },
  { pattern: /^Cannot approve test in/, key: "cannotApproveStatus" },
  { pattern: /^Cannot cancel test in/, key: "cannotCancelStatus" },
  { pattern: /^Cannot upload documents in/, key: "cannotUploadStatus" },
  { pattern: /^No scenarios to approve$/, key: "noScenarios" },
  { pattern: /^Invalid YAML/, key: "invalidYaml" },
  { pattern: /^Empty scenario YAML$/, key: "emptyYaml" },
  { pattern: /^Unsupported file type/, key: "unsupportedFile" },
  { pattern: /^File too large/, key: "fileTooLarge" },
  { pattern: /^AAT core not installed/, key: "aiNotInstalled" },
  { pattern: /^Unknown AI provider/, key: "aiProviderUnknown" },
  { pattern: /^AI generation failed/, key: "aiGenerationFailed" },
  { pattern: /^AI generated no scenarios$/, key: "aiNoScenarios" },
  { pattern: /^API keys require a Pro/, key: "apiKeyProOnly" },
  { pattern: /^Cancelled by user$/, key: "cancelledByUser" },
  { pattern: /^Test timed out after/, key: "stuckTimeout" },
  { pattern: /^Test was interrupted by server restart$/, key: "serverRestart" },
];

/**
 * Translate an API error message using the provided `t()` function.
 *
 * @param message - raw English error string from the API
 * @param t - next-intl translator scoped to "errors" namespace
 * @returns translated message, or the original if no pattern matches
 */
export function translateApiError(
  message: string,
  t: (key: string, params?: Record<string, string>) => string,
): string {
  for (const { pattern, key, params } of patterns) {
    const match = message.match(pattern);
    if (match) {
      return t(key, params?.(match));
    }
  }
  return message;
}
