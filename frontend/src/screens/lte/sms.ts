// Copies of the server's SMS rules (lte/sms.py GSM_7BIT_BASIC and GSM_RULE, lte/commands.py TARGET_RULE and
// TARGET_MESSAGE). tests/contract/test_frontend_copies.py keeps them the same; keep each on one line.

/** The characters whose GSM-7 code equals their ASCII code: the only ones uqmi can send as they are. */
export const GSM_CHARS = "\n !\"#%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
export const GSM_RULE = "An SMS is 1 to 160 characters of the GSM basic set (letters, digits, common punctuation)"
export const TARGET_RULE = "A number is digits with an optional + (3 to 15)"
export const TARGET = /^\+?[0-9]{3,15}$/
export const MAX_TEXT = 160

const GSM = new Set(GSM_CHARS)

/** True when the text is 1 to 160 characters, all of them sendable. */
export function isSendable(text: string): boolean {
  return text.length >= 1 && text.length <= MAX_TEXT && [...text].every((c) => GSM.has(c))
}
