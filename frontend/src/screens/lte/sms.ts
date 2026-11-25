// Copies of the server's SMS and USSD rules (lte/sms.py GSM_7BIT_BASIC and GSM_RULE, lte/commands.py
// TARGET_RULE, TARGET_MESSAGE, USSD_CODE and USSD_MESSAGE). tests/contract/test_frontend_copies.py keeps them
// the same; keep each on one line.

/** The characters whose GSM-7 code equals their ASCII code: the only ones uqmi can send as they are. */
export const GSM_CHARS = "\n !\"#%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
export const GSM_RULE = "An SMS is 1 to 160 characters of the GSM basic set (letters, digits, common punctuation)"
export const TARGET_RULE = "A number is digits with an optional + (3 to 15)"
export const TARGET = /^\+?[0-9]{3,15}$/
export const MAX_TEXT = 160

/** A USSD code: * or #, digits, * or #, ending in #; never a PIN, PUK, call barring or ** / ## string. */
export const USSD_CODE = /^(?!\*\*|##)(?![*#]{1,2}(?:0[3-5]2?|33[0-3]?|35[13]?)[*#])[*#][0-9*#]{1,30}#$/
export const USSD_RULE = "A USSD code looks like *100#: * or #, digits, * or #, ending in #. PIN, PUK and call barring codes, and codes starting with ** or ##, are refused"

const GSM = new Set(GSM_CHARS)

/** True when the text is 1 to 160 characters, all of them sendable. */
export function isSendable(text: string): boolean {
  return text.length >= 1 && text.length <= MAX_TEXT && [...text].every((c) => GSM.has(c))
}
